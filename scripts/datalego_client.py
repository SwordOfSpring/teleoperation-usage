#!/usr/bin/env python3
"""Small, local DataLego client used by the teleoperation usage jobs.

The implementation intentionally mirrors the DataLego flow used by the
reference project: read the cached HCIAuthToken, submit a Hive job, poll its
status, and convert the result payload to a UTF-8 BOM CSV.
"""

from __future__ import annotations

import base64
import csv
import http.client
import http.server
import json
import os
import secrets
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from pathlib import Path
from typing import Any


DATALEGO_BASE_URL = os.getenv("DATALEGO_BASE_URL", "https://datalego.agoralab.co")
TOKEN_FILE = Path(os.getenv(
    "DATALEGO_TOKEN_FILE",
    str(Path.home() / ".config" / "data-agent-tools" / ".hci-auth-token"),
))
POLL_INTERVAL_HIVE = int(os.getenv("DATALEGO_POLL_INTERVAL_HIVE", "30"))
POLL_INTERVAL_DORIS = int(os.getenv("DATALEGO_POLL_INTERVAL_DORIS", "5"))
MAX_POLL_DURATION = int(os.getenv("DATALEGO_MAX_POLL_SECONDS", str(40 * 60)))

OAUTH_CLIENT_ID = os.getenv("DATALEGO_OAUTH_CLIENT_ID", "i0SEAKhpH3WpfZNu671n202P4KG00nPq")
OAUTH_AUTHORIZE_URL = os.getenv("DATALEGO_OAUTH_AUTHORIZE_URL", "https://oauth.agoralab.co/oauth/authorize")
OAUTH_REDIRECT_URI = os.getenv("DATALEGO_OAUTH_REDIRECT_URI", "https://localhost/oauth2/callback")
OAUTH_REFRESH_HOST = os.getenv("DATALEGO_OAUTH_REFRESH_HOST", "grafana.bj2.agoralab.co")
OAUTH_CALLBACK_PROXY_HOST = os.getenv("DATALEGO_OAUTH_CALLBACK_PROXY_HOST", "110.43.210.221")
OAUTH_CODE_INPUT_PORT = int(os.getenv("DATALEGO_OAUTH_CODE_INPUT_PORT", "17823"))


class DataLegoError(RuntimeError):
    """Raised when DataLego authentication or query execution fails."""


def extract_access_context(hci_token: str) -> tuple[str, str]:
    """Read the access token and email embedded in an HCIAuthToken JWT."""
    parts = hci_token.split(".")
    if len(parts) < 2:
        raise DataLegoError("HCIAuthToken 格式无效")
    padded = parts[1] + "=" * ((4 - len(parts[1]) % 4) % 4)
    try:
        payload = json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DataLegoError("无法解析 HCIAuthToken") from exc
    access_token = payload.get("access_token", "")
    email = payload.get("user", {}).get("email", "")
    if not access_token:
        raise DataLegoError("HCIAuthToken 中缺少 access_token")
    return access_token, email


def read_hci_token(path: Path = TOKEN_FILE) -> str:
    if not path.exists():
        raise DataLegoError(f"Token 文件不存在：{path}。请先运行 python scripts/daily_usage.py --login")
    token = path.read_text(encoding="utf-8").strip()
    if not token:
        raise DataLegoError(f"Token 文件为空：{path}")
    return token


def save_hci_token(token: str, path: Path = TOKEN_FILE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(token, encoding="utf-8")


def refresh_hci_token(current_token: str) -> str | None:
    """Ask the existing Grafana endpoint to rotate the HCIAuthToken cookie."""
    ctx = ssl.create_default_context()
    conn = http.client.HTTPSConnection(OAUTH_REFRESH_HOST, context=ctx, timeout=60)
    try:
        conn.request("GET", "/", headers={"Cookie": f"HCIAuthToken={current_token}"})
        response = conn.getresponse()
        for name, value in response.getheaders():
            if name.lower() == "set-cookie" and "HCIAuthToken=" in value:
                return value.split("HCIAuthToken=", 1)[1].split(";", 1)[0] or None
        response.read()
    except Exception:
        return None
    finally:
        conn.close()
    return None


class AuthContext:
    def __init__(self, token_file: Path = TOKEN_FILE):
        self.token_file = token_file
        self.hci_token = ""
        self.access_token = ""
        self.email = ""

    def init(self) -> None:
        self.hci_token = read_hci_token(self.token_file)
        self.access_token, self.email = extract_access_context(self.hci_token)

    def refresh(self) -> bool:
        new_token = refresh_hci_token(self.hci_token)
        if not new_token or new_token == self.hci_token:
            return False
        self.hci_token = new_token
        save_hci_token(new_token, self.token_file)
        self.access_token, self.email = extract_access_context(new_token)
        return True


auth = AuthContext()


def datalego_request(
    method: str,
    path: str,
    body: dict[str, Any] | None = None,
    *,
    _retried: bool = False,
) -> dict[str, Any]:
    url = f"{DATALEGO_BASE_URL}{path}"
    headers = {"accessToken": auth.access_token, "Content-Type": "application/json"}
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        response_body = exc.read().decode("utf-8", errors="replace")
        if exc.code == 401 and not _retried and auth.refresh():
            return datalego_request(method, path, body, _retried=True)
        raise DataLegoError(
            f"DataLego API HTTP {exc.code}，路径 {path}，响应：{response_body[:300]}"
        ) from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise DataLegoError(f"DataLego API 请求失败：{exc}") from exc


def submit_query(sql: str, engine: str = "hive", queue: str = "share") -> tuple[str, str, dict[str, Any]]:
    if not auth.access_token:
        raise DataLegoError("尚未初始化 DataLego 认证")
    creator = urllib.parse.quote(auth.email or "", safe="")
    result = datalego_request(
        "POST",
        f"/api/v1/datainsight/job/trigger?creator={creator}",
        {"sql": sql, "engine": engine, "queue": queue, "download": False, "panelId": 0},
    )
    job_id = str(result.get("id", ""))
    if not job_id:
        raise DataLegoError(f"DataLego 未返回 job id：{json.dumps(result, ensure_ascii=False)[:300]}")
    return job_id, str(result.get("status", "unknown")), result


def get_job_status(job_id: str) -> dict[str, Any]:
    return datalego_request("GET", f"/api/v1/datainsight/jobs/{urllib.parse.quote(job_id)}/status")


def wait_for_job(job_id: str, label: str = "Query", engine: str = "hive") -> dict[str, Any] | None:
    interval = POLL_INTERVAL_HIVE if engine == "hive" else POLL_INTERVAL_DORIS
    start = time.monotonic()
    last_status = ""
    while True:
        elapsed = time.monotonic() - start
        if elapsed > MAX_POLL_DURATION:
            raise DataLegoError(f"{label} 超过 {MAX_POLL_DURATION // 60} 分钟仍未完成")
        result = get_job_status(job_id)
        status = str(result.get("status", "error"))
        if status != last_status:
            progress = result.get("progress", "")
            suffix = f" ({progress}%)" if progress else ""
            print(f"[{label}] {status}{suffix}")
            last_status = status
        if status == "success":
            return result
        if status in {"error", "cancelled", "cancel"}:
            print(f"[{label}] {result.get('error', 'Unknown error')}")
            return None
        time.sleep(interval)


def normalize_csv_encoding(output_path: Path) -> None:
    raw = output_path.read_bytes()
    if raw.startswith(b"\xef\xbb\xbf"):
        return
    with output_path.open("w", encoding="utf-8-sig", newline="") as handle:
        handle.write(raw.decode("utf-8"))


def result_to_csv(result: dict[str, Any], output_path: Path) -> int:
    schema = result.get("schema") or []
    rows = result.get("data") or []
    if not schema:
        raise DataLegoError("DataLego 返回结果缺少 schema")
    columns = [str(col.get("name", f"col_{i}")) for i, col in enumerate(schema)]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(columns)
        writer.writerows(rows)
    normalize_csv_encoding(output_path)
    return len(rows)


_CODE_CAPTURE_HTML = """<!doctype html><meta charset='utf-8'><title>DataLego 登录</title>
<style>body{font-family:system-ui;max-width:680px;margin:60px auto;padding:0 24px}input{width:100%;padding:12px;box-sizing:border-box}button{margin-top:12px;padding:10px 24px}</style>
<h2>粘贴 OAuth 回调链接</h2><p>完成声网 SSO 后复制 https://localhost/oauth2/callback?code=...，粘贴后提交。</p>
<input id='url' autofocus placeholder='https://localhost/oauth2/callback?code=...'><button onclick='send()'>提交</button><p id='msg'></p>
<script>async function send(){const v=document.querySelector('#url').value.trim();const r=await fetch('/code',{method:'POST',body:v});document.querySelector('#msg').textContent=await r.text()}</script>"""


class _CodeCaptureHandler(http.server.BaseHTTPRequestHandler):
    received_code: str | None = None

    def do_GET(self):  # noqa: N802
        if self.path != "/":
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(_CODE_CAPTURE_HTML.encode("utf-8"))

    def do_POST(self):  # noqa: N802
        if self.path != "/code":
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length", "0"))
        value = self.rfile.read(length).decode("utf-8").strip()
        parsed = urllib.parse.urlparse(value)
        code = urllib.parse.parse_qs(parsed.query).get("code", [value])[0]
        if not code:
            self.send_error(400, "没有找到 code")
            return
        _CodeCaptureHandler.received_code = code
        self.send_response(200)
        self.end_headers()
        self.wfile.write("收到，可以关闭页面。".encode("utf-8"))

    def log_message(self, *_args):
        return


def _exchange_code_for_token(code: str) -> str:
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    conn = http.client.HTTPSConnection(OAUTH_CALLBACK_PROXY_HOST, 443, context=ctx, timeout=60)
    try:
        conn.request("GET", f"/oauth2/callback?code={urllib.parse.quote(code)}", headers={"Host": "localhost"})
        response = conn.getresponse()
        for name, value in response.getheaders():
            if name.lower() == "set-cookie" and "HCIAuthToken=" in value:
                return value.split("HCIAuthToken=", 1)[1].split(";", 1)[0]
        body = response.read().decode("utf-8", errors="replace")
        raise DataLegoError(f"OAuth 换取 token 失败 HTTP {response.status}: {body[:200]}")
    finally:
        conn.close()


def interactive_login(token_file: Path = TOKEN_FILE) -> None:
    state = secrets.token_hex(16)
    auth_url = f"{OAUTH_AUTHORIZE_URL}?{urllib.parse.urlencode({'response_type': 'code', 'client_id': OAUTH_CLIENT_ID, 'redirect_uri': OAUTH_REDIRECT_URI, 'scope': 'email', 'state': state})}"
    try:
        webbrowser.open(auth_url)
    except Exception:
        print(f"请手动打开：{auth_url}")

    server = http.server.HTTPServer(("127.0.0.1", OAUTH_CODE_INPUT_PORT), _CodeCaptureHandler)
    server.timeout = 1
    page_url = f"http://localhost:{OAUTH_CODE_INPUT_PORT}"
    threading.Thread(target=lambda: webbrowser.open(page_url), daemon=True).start()
    print(f"请完成 SSO，并把回调 URL 粘贴到 {page_url}")
    started = time.monotonic()
    try:
        while _CodeCaptureHandler.received_code is None:
            if time.monotonic() - started > 300:
                raise DataLegoError("等待 OAuth 回调超时")
            server.handle_request()
        token = _exchange_code_for_token(_CodeCaptureHandler.received_code)
        save_hci_token(token, token_file)
        print(f"登录成功，Token 已保存到：{token_file}")
    finally:
        server.server_close()
        _CodeCaptureHandler.received_code = None
