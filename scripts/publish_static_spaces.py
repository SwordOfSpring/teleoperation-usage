#!/usr/bin/env python3
"""Publish the teleoperation dashboard to its StaticSpaces shared space."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PUBLISH_API_BASE = "https://publish-static-spaces.sh3.agoralab.co/v1"
SPACE_SLUG = "teleoperation-usage"
SPACE_KIND = "shared"
TOKEN_ENV = "AUTHENTIK_USER_API_TOKEN"
ASSET_NAMES = ("index.html", "styles.css", "app.js", "customer-metrics.js")


class StaticSpacesPublishError(RuntimeError):
    """Raised when StaticSpaces cannot publish or verify the dashboard."""


def _error_text(payload: Any) -> str:
    if isinstance(payload, dict) and isinstance(payload.get("error"), dict):
        error = payload["error"]
        code = str(error.get("code") or "API_ERROR")
        message = str(error.get("message") or "StaticSpaces API request failed")
        return f"{code}: {message}"
    return str(payload)


def _request_json(
    method: str,
    path: str,
    token: str,
    body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    data = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
    headers = {"Authorization": f"Bearer {token}"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    request = Request(f"{PUBLISH_API_BASE}{path}", data=data, method=method, headers=headers)
    try:
        with urlopen(request, timeout=60) as response:
            raw = response.read()
    except HTTPError as exc:
        try:
            payload = json.loads(exc.read().decode("utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            payload = exc.reason or str(exc)
        raise StaticSpacesPublishError(_error_text(payload)) from exc
    except (OSError, URLError) as exc:
        raise StaticSpacesPublishError(f"StaticSpaces API unavailable: {exc}") from exc
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise StaticSpacesPublishError("StaticSpaces API returned invalid JSON") from exc
    if not isinstance(payload, dict):
        raise StaticSpacesPublishError("StaticSpaces API returned an unexpected response")
    if payload.get("error"):
        raise StaticSpacesPublishError(_error_text(payload))
    return payload


def _read_assets(project_root: Path) -> tuple[list[dict[str, str]], dict[str, str]]:
    files: list[dict[str, str]] = []
    hashes: dict[str, str] = {}
    for name in ASSET_NAMES:
        path = project_root / name
        if not path.is_file():
            raise StaticSpacesPublishError(f"StaticSpaces asset not found: {path}")
        content = path.read_text(encoding="utf-8")
        encoded = content.encode("utf-8")
        files.append({"relative_path": name, "content": content})
        hashes[name] = hashlib.sha256(encoded).hexdigest()
    return files, hashes


def _verify_publish_response(response: dict[str, Any], hashes: dict[str, str]) -> None:
    warnings: list[Any] = []
    top_level_warnings = response.get("subscription_warnings")
    if top_level_warnings:
        warnings.extend(top_level_warnings if isinstance(top_level_warnings, list) else [top_level_warnings])
    written = response.get("files_written")
    if not isinstance(written, list):
        raise StaticSpacesPublishError("StaticSpaces publish response omitted files_written")
    by_name: dict[str, dict[str, Any]] = {}
    for item in written:
        if not isinstance(item, dict):
            continue
        path = str(item.get("path") or "")
        for name in hashes:
            if path in {name, f"/spaces/{SPACE_KIND}/{SPACE_SLUG}/{name}"}:
                by_name[name] = item
                break
        item_warnings = item.get("subscription_warnings")
        if item_warnings:
            warnings.extend(item_warnings if isinstance(item_warnings, list) else [item_warnings])
    missing = sorted(set(hashes) - set(by_name))
    if missing:
        raise StaticSpacesPublishError(f"StaticSpaces publish response omitted files: {', '.join(missing)}")
    mismatched = [name for name, expected in hashes.items() if str(by_name[name].get("sha256", "")).lower() != expected]
    if mismatched:
        raise StaticSpacesPublishError(f"StaticSpaces SHA-256 mismatch: {', '.join(mismatched)}")
    if warnings:
        detail = json.dumps(warnings, ensure_ascii=False)
        raise StaticSpacesPublishError(f"StaticSpaces subscription_warnings: {detail}")


def _verify_file_listing(listing: dict[str, Any]) -> None:
    files = listing.get("files")
    if not isinstance(files, list):
        raise StaticSpacesPublishError("StaticSpaces file listing omitted files")
    paths = {str(item.get("path")) for item in files if isinstance(item, dict)}
    missing = sorted(set(ASSET_NAMES) - paths)
    if missing:
        raise StaticSpacesPublishError(f"StaticSpaces file listing omitted files: {', '.join(missing)}")


def publish_static_space(project_root: Path = PROJECT_ROOT) -> dict[str, Any]:
    """Publish and verify the dashboard assets in the shared StaticSpaces space."""
    token = os.environ.get(TOKEN_ENV, "").strip()
    if not token:
        raise StaticSpacesPublishError(
            f"Missing {TOKEN_ENV}; set a fresh Authentik user API token before publishing"
        )
    files, hashes = _read_assets(project_root)
    payload = {
        "kind": SPACE_KIND,
        "slug": SPACE_SLUG,
        "overwrite": True,
        "files": files,
    }
    response = _request_json("POST", "/publish-space", token, payload)
    _verify_publish_response(response, hashes)
    listing_path = "/files?" + urlencode({"kind": SPACE_KIND, "slug": SPACE_SLUG})
    _verify_file_listing(_request_json("GET", listing_path, token))
    return response


def main() -> int:
    try:
        response = publish_static_space()
    except StaticSpacesPublishError as exc:
        print(f"[StaticSpaces] 发布未完成：{exc}")
        return 1
    print(
        "[StaticSpaces] 已更新 "
        f"{len(response.get('files_written', []))} 个文件："
        f"https://static-spaces.sh3.agoralab.co/spaces/{SPACE_KIND}/{SPACE_SLUG}/"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
