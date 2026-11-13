#!/usr/bin/env python3
"""Customer mapping, SQL rendering, SKU aggregation, and dashboard outputs."""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import subprocess
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

try:  # noqa: E402
    from .datalego_client import (
        DataLegoError,
        auth,
        interactive_login,
        result_to_csv,
        submit_query,
        wait_for_job,
    )
except ImportError:  # direct execution through wrapper scripts
    from datalego_client import (
        DataLegoError,
        auth,
        interactive_login,
        result_to_csv,
        submit_query,
        wait_for_job,
    )


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CUSTOMER_PATH = PROJECT_ROOT / "customer" / "平行操控客户.xlsx"
USAGE_DIR = PROJECT_ROOT / "usage"
RAW_DIR = USAGE_DIR / "raw"
QUERY_STATE_PATH = USAGE_DIR / "query_state.json"
SKU_IDS = (1002, 1003, 2002, 2003, 2004, 2005, 2006, 2007)
RAW_COLUMNS = ["date", "vid", "sku", "value"]
DAILY_COLUMNS = [
    "date", "vid", "company_id", "company_name", "sale",
    "audio_host", "audio_viewer", "audio_total",
    "video_host", "video_viewer", "video_total",
    "host_total", "viewer_total", "total",
]
WEEKLY_COLUMNS = ["week", *DAILY_COLUMNS[1:]]
OVERVIEW_COLUMNS = [*DAILY_COLUMNS, "data_source"]
USAGE_METRICS = (
    "audio_host", "audio_viewer", "audio_total",
    "video_host", "video_viewer", "video_total",
    "host_total", "viewer_total", "total",
)
INDEX_PATH = PROJECT_ROOT / "index.html"


def _date_from_text(value: str) -> date:
    text = str(value).replace("-", "")
    return datetime.strptime(text, "%Y%m%d").date()


def date_text(value: date) -> str:
    return value.strftime("%Y%m%d")


def previous_complete_week(today: date | None = None) -> tuple[str, str]:
    today = today or date.today()
    this_monday = today - timedelta(days=today.weekday())
    start = this_monday - timedelta(days=7)
    return date_text(start), date_text(start + timedelta(days=6))


def week_label_range(label: str) -> tuple[str, str]:
    """Resolve an ISO week label such as 2026-W25 to its Monday-Sunday range."""
    match = re.fullmatch(r"(\d{4})-W(\d{2})", str(label or "").upper())
    if not match:
        raise ValueError("自然周必须使用 YYYY-Wxx 格式，例如 2026-W25")
    year, week = int(match.group(1)), int(match.group(2))
    try:
        monday = date.fromisocalendar(year, week, 1)
    except ValueError as exc:
        raise ValueError(f"无效的自然周：{label}") from exc
    return date_text(monday), date_text(monday + timedelta(days=6))


def normalize_week_argument(argv: list[str] | None) -> list[str] | None:
    """Convert the compact weekly flag --YYYY-Wxx to argparse's --week form."""
    if argv is None:
        return None
    normalized: list[str] = []
    for item in argv:
        match = re.fullmatch(r"--(\d{4}-W\d{2})", str(item).upper())
        if match:
            normalized.extend(["--week", match.group(1)])
        else:
            normalized.append(item)
    return normalized


def yesterday_range(today: date | None = None) -> tuple[str, str]:
    yesterday = (today or date.today()) - timedelta(days=1)
    return date_text(yesterday), date_text(yesterday)


def daily_query_range(today: date | None = None, last_end: str | None = None) -> tuple[str, str] | None:
    """Return the missing daily interval up to yesterday."""
    end = (today or date.today()) - timedelta(days=1)
    start = _date_from_text(last_end) + timedelta(days=1) if last_end else end
    if start > end:
        return None
    return date_text(start), date_text(end)


def weekly_query_range(today: date | None = None, last_end: str | None = None) -> tuple[str, str] | None:
    """Return missing dates through the latest complete Monday-Sunday week."""
    complete_start_text, complete_end_text = previous_complete_week(today)
    complete_end = _date_from_text(complete_end_text)
    start = _date_from_text(last_end) + timedelta(days=1) if last_end else _date_from_text(complete_start_text)
    if start > complete_end:
        return None
    return date_text(start), date_text(complete_end)


def _clean_vid(value: Any) -> str:
    if value is None or str(value).strip() == "":
        raise ValueError("客户表包含空 VID")
    text = str(value).strip()
    if text.endswith(".0") and text[:-2].isdigit():
        text = text[:-2]
    return text


def load_customers(path: Path = CUSTOMER_PATH) -> list[dict[str, str]]:
    try:
        import openpyxl
    except ImportError as exc:
        raise DataLegoError("读取 Excel 需要 openpyxl，请运行 pip install -r requirements.txt") from exc
    if not path.exists():
        raise DataLegoError(f"客户 Excel 不存在：{path}")
    workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
    sheet = workbook.active
    values = sheet.iter_rows(values_only=True)
    header = [str(v or "").strip().upper() for v in next(values, ())]
    required = {"NAME", "CID", "VID", "SALE"}
    missing = required - set(header)
    if missing:
        raise DataLegoError(f"客户 Excel 缺少列：{', '.join(sorted(missing))}")
    indexes = {name: header.index(name) for name in required}
    customers: list[dict[str, str]] = []
    seen: set[str] = set()
    for row in values:
        if not row or all(v is None for v in row):
            continue
        vid = _clean_vid(row[indexes["VID"]])
        if vid in seen:
            raise DataLegoError(f"客户 Excel 中 VID 重复：{vid}")
        seen.add(vid)
        customers.append({
            "vid": vid,
            "company_name": str(row[indexes["NAME"]] or "").strip(),
            "company_id": _clean_vid(row[indexes["CID"]]),
            "sale": str(row[indexes["SALE"]] or "").strip(),
        })
    workbook.close()
    if not customers:
        raise DataLegoError("客户 Excel 没有可用客户行")
    return customers


def customer_map(customers: Iterable[dict[str, str]]) -> dict[str, dict[str, str]]:
    return {row["vid"]: row for row in customers}


def _sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def build_usage_sql(start: str, end: str, vids: Iterable[str]) -> str:
    vid_values = [_clean_vid(vid) for vid in vids]
    if not vid_values:
        raise ValueError("至少需要一个 VID")
    vid_sql = ", ".join(_sql_literal(vid) for vid in sorted(set(vid_values)))
    sku_sql = ", ".join(str(sku) for sku in SKU_IDS)
    return f"""SELECT
    date,
    CAST(vid AS STRING) AS vid,
    CAST(sku AS INT) AS sku,
    SUM(value) AS value
FROM ods.sku
WHERE date BETWEEN {int(start)} AND {int(end)}
  AND CAST(vid AS STRING) IN ({vid_sql})
  AND sku IN ({sku_sql})
GROUP BY date, CAST(vid AS STRING), CAST(sku AS INT)
ORDER BY date ASC, vid ASC, sku ASC""".strip()


def _decimal(value: Any) -> Decimal:
    if value is None or value == "":
        return Decimal(0)
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"无法将 value 转为数字：{value!r}") from exc


def _json_number(value: Decimal) -> int | float:
    if value == value.to_integral_value():
        return int(value)
    return float(value)


def _week_label(date_value: str) -> str:
    parsed = _date_from_text(date_value)
    iso = parsed.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def normalize_result(result: dict[str, Any]) -> list[dict[str, str]]:
    schema = result.get("schema") or []
    data = result.get("data") or []
    columns = [str(item.get("name", "")).strip().lower() for item in schema]
    needed = {"date", "vid", "sku", "value"}
    if not needed.issubset(columns):
        raise DataLegoError(f"DataLego 返回字段不完整：{columns}")
    indexes = {name: columns.index(name) for name in needed}
    rows = []
    for raw in data:
        rows.append({
            "date": str(raw[indexes["date"]]),
            "vid": _clean_vid(raw[indexes["vid"]]),
            "sku": str(int(raw[indexes["sku"]])),
            "value": str(raw[indexes["value"]] if raw[indexes["value"]] is not None else 0),
        })
    return rows


def aggregate_rows(
    rows: Iterable[dict[str, Any]],
    customers: dict[str, dict[str, str]],
    period_key: str = "date",
) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        vid = _clean_vid(row["vid"])
        date_value = str(row["date"])
        period = date_value if period_key == "date" else _week_label(date_value)
        key = (period, vid)
        if key not in grouped:
            customer = customers.get(vid, {})
            grouped[key] = {
                period_key: period,
                "vid": vid,
                "company_id": customer.get("company_id", ""),
                "company_name": customer.get("company_name", "未登记客户"),
                "sale": customer.get("sale", ""),
                "audio_host": Decimal(0),
                "audio_viewer": Decimal(0),
                "audio_total": Decimal(0),
                "video_host": Decimal(0),
                "video_viewer": Decimal(0),
                "video_total": Decimal(0),
                "host_total": Decimal(0),
                "viewer_total": Decimal(0),
                "total": Decimal(0),
            }
        amount = _decimal(row.get("value"))
        sku = int(row["sku"])
        if sku == 1002:
            grouped[key]["audio_host"] += amount
        elif sku == 1003:
            grouped[key]["audio_viewer"] += amount
        elif sku in {2002, 2003, 2004}:
            grouped[key]["video_host"] += amount
        elif sku in {2005, 2006, 2007}:
            grouped[key]["video_viewer"] += amount

    result = []
    for item in grouped.values():
        item["audio_total"] = item["audio_host"] + item["audio_viewer"]
        item["video_total"] = item["video_host"] + item["video_viewer"]
        item["host_total"] = item["audio_host"] + item["video_host"]
        item["viewer_total"] = item["audio_viewer"] + item["video_viewer"]
        item["total"] = item["host_total"] + item["viewer_total"]
        for key in list(item):
            if isinstance(item[key], Decimal):
                item[key] = _json_number(item[key])
        result.append(item)
    return sorted(result, key=lambda item: (str(item[period_key]), str(item["vid"])))


def _amounts_match(left: dict[str, Any], right: dict[str, Any]) -> bool:
    """Compare usage values without losing decimal precision through float conversion."""
    return all(_decimal(left.get(key)) == _decimal(right.get(key)) for key in USAGE_METRICS)


def reconcile_overview(
    daily_rows: Iterable[dict[str, Any]],
    weekly_daily_rows: Iterable[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Prefer daily data, using completed-week data when the same day/VID disagrees."""
    daily_map = {(str(row["date"]), str(row["vid"])): dict(row) for row in daily_rows}
    weekly_map = {(str(row["date"]), str(row["vid"])): dict(row) for row in weekly_daily_rows}
    output: list[dict[str, Any]] = []
    fallback_count = 0
    checked_count = 0
    for key in sorted(set(daily_map) | set(weekly_map)):
        daily_row = daily_map.get(key)
        weekly_row = weekly_map.get(key)
        if weekly_row is not None:
            if daily_row is not None:
                checked_count += 1
            selected = weekly_row if daily_row is None or not _amounts_match(daily_row, weekly_row) else daily_row
            source = "weekly_fallback" if selected is weekly_row else "daily"
            if source == "weekly_fallback":
                fallback_count += 1
        else:
            selected = daily_row
            source = "daily"
        if selected is None:
            continue
        selected["data_source"] = source
        output.append(selected)
    return output, {"checked": checked_count, "fallback": fallback_count}


def _read_raw_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _read_query_state(path: Path = QUERY_STATE_PATH) -> dict[str, str]:
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _latest_raw_date(path: Path) -> str | None:
    dates = [str(row.get("date", "")) for row in _read_raw_csv(path) if row.get("date")]
    return max(dates) if dates else None


def last_query_end(mode: str, *, state_path: Path = QUERY_STATE_PATH, raw_path: Path | None = None) -> str | None:
    """Use explicit query metadata, falling back to the latest raw date."""
    state = _read_query_state(state_path)
    state_end = state.get(f"{mode}_end")
    if state_end:
        return str(state_end)
    return _latest_raw_date(raw_path or (USAGE_DIR / f"{mode}_raw.csv"))


def record_query_end(mode: str, end: str, path: Path = QUERY_STATE_PATH) -> None:
    state = _read_query_state(path)
    current = state.get(f"{mode}_end")
    if not current or str(end) > str(current):
        state[f"{mode}_end"] = str(end)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _merge_raw_csv(path: Path, rows: Iterable[dict[str, Any]]) -> list[dict[str, str]]:
    merged = {(str(row["date"]), _clean_vid(row["vid"]), str(row["sku"])): {
        "date": str(row["date"]), "vid": _clean_vid(row["vid"]), "sku": str(int(row["sku"])), "value": str(row["value"])
    } for row in _read_raw_csv(path)}
    for row in rows:
        merged[(str(row["date"]), _clean_vid(row["vid"]), str(row["sku"]))] = {
            "date": str(row["date"]), "vid": _clean_vid(row["vid"]), "sku": str(int(row["sku"])), "value": str(row["value"])
        }
    result = sorted(merged.values(), key=lambda row: (row["date"], row["vid"], int(row["sku"])))
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=RAW_COLUMNS)
        writer.writeheader()
        writer.writerows(result)
    return result


def reconcile_daily_raw(
    daily_rows: Iterable[dict[str, Any]],
    weekly_rows: Iterable[dict[str, Any]],
) -> tuple[list[dict[str, str]], dict[str, int]]:
    """Replace daily raw values when the completed-week query disagrees."""
    daily_map = {
        (str(row["date"]), _clean_vid(row["vid"]), str(int(row["sku"]))): {
            "date": str(row["date"]),
            "vid": _clean_vid(row["vid"]),
            "sku": str(int(row["sku"])),
            "value": str(row["value"]),
        }
        for row in daily_rows
    }
    weekly_map = {
        (str(row["date"]), _clean_vid(row["vid"]), str(int(row["sku"]))): {
            "date": str(row["date"]),
            "vid": _clean_vid(row["vid"]),
            "sku": str(int(row["sku"])),
            "value": str(row["value"]),
        }
        for row in weekly_rows
    }
    overwritten = 0
    checked = 0
    added = len(set(weekly_map) - set(daily_map))
    for key, weekly_row in weekly_map.items():
        daily_row = daily_map.get(key)
        if daily_row is None:
            daily_map[key] = weekly_row
            continue
        checked += 1
        if _decimal(daily_row["value"]) != _decimal(weekly_row["value"]):
            daily_map[key] = weekly_row
            overwritten += 1
    result = sorted(daily_map.values(), key=lambda row: (row["date"], row["vid"], int(row["sku"])))
    return result, {"checked": checked, "overwritten": overwritten, "added": added}


def should_update_index(mode: str, reconciliation: dict[str, int] | None = None) -> bool:
    """Return whether this query should refresh the embedded dashboard page."""
    if mode == "daily":
        return True
    if mode == "weekly":
        reconciliation = reconciliation or {}
        return bool(
            int(reconciliation.get("overwritten", 0))
            or int(reconciliation.get("added", 0))
        )
    raise ValueError(f"不支持的查询模式：{mode}")


def github_commit_message(mode: str, start: str, end: str, reconciliation: dict[str, int] | None = None) -> str:
    """Build a concise Chinese commit message for generated dashboard data."""
    reconciliation = reconciliation or {}
    period = "周" if mode == "weekly" else "日"
    overwritten = int(reconciliation.get("overwritten", 0))
    detail = f"；覆盖 {overwritten} 条 daily 数据" if mode == "weekly" else ""
    return f"用量数据更新：{period}查询 {start} ~ {end}{detail}"


def push_dashboard_updates(message: str) -> bool:
    """Commit the embedded dashboard and push it to the configured GitHub remote."""
    status = subprocess.run(
        ["git", "status", "--porcelain", "--", "index.html"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    if not status.stdout.strip():
        print("看板文件没有变化，跳过 GitHub 提交和推送。")
        return False
    subprocess.run(["git", "add", "--", "index.html"], cwd=PROJECT_ROOT, check=True)
    commit = subprocess.run(
        ["git", "commit", "-m", message],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
    )
    if commit.returncode != 0:
        detail = (commit.stderr or commit.stdout).strip()
        raise DataLegoError(f"Git 提交失败：{detail}")
    push = subprocess.run(
        ["git", "push", "origin", "HEAD"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
    )
    if push.returncode != 0:
        detail = (push.stderr or push.stdout).strip()
        raise DataLegoError(f"GitHub 推送失败：{detail}")
    print(f"已提交并推送 GitHub：{message}")
    return True


def _write_rows(path: Path, rows: Iterable[dict[str, Any]], columns: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows({column: row.get(column, "") for column in columns} for row in rows)


def write_dashboard_data(
    customers: list[dict[str, str]],
    daily_rows: list[dict[str, Any]],
    weekly_rows: list[dict[str, Any]],
    *,
    generated_at: str,
    overview_rows: list[dict[str, Any]] | None = None,
    weekly_daily_rows: list[dict[str, Any]] | None = None,
    reconciliation: dict[str, int] | None = None,
    update_index: bool = True,
) -> Path:
    overview_rows = overview_rows if overview_rows is not None else daily_rows
    weekly_daily_rows = weekly_daily_rows if weekly_daily_rows is not None else []
    reconciliation = reconciliation or {"checked": 0, "fallback": 0}
    _write_rows(USAGE_DIR / "daily_usage.csv", daily_rows, DAILY_COLUMNS)
    _write_rows(USAGE_DIR / "weekly_usage.csv", weekly_rows, WEEKLY_COLUMNS)
    _write_rows(USAGE_DIR / "overview_usage.csv", overview_rows, OVERVIEW_COLUMNS)
    payload = {
        "generatedAt": generated_at,
        "valueUnit": "passthrough",
        "customers": customers,
        "overview": overview_rows,
        "daily": daily_rows,
        "weekly": weekly_rows,
        "weeklyDaily": weekly_daily_rows,
        "reconciliation": reconciliation,
    }
    output = USAGE_DIR / "dashboard.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    if update_index:
        embed_dashboard_data(payload)
    return output


def embed_dashboard_data(payload: dict[str, Any], path: Path | None = None) -> None:
    """Write the latest dashboard payload into index.html for file:// and static hosting."""
    path = path or INDEX_PATH
    if not path.exists():
        return
    marker_start = '<script id="teleoperation-data" type="application/json">'
    marker_end = "</script>"
    source = path.read_text(encoding="utf-8")
    start = source.find(marker_start)
    if start < 0:
        return
    content_start = start + len(marker_start)
    end = source.find(marker_end, content_start)
    if end < 0:
        raise DataLegoError(f"index.html 缺少 teleoperation-data 结束标记：{path}")
    encoded = json.dumps(payload, ensure_ascii=False, indent=2).replace("</", "<\\/")
    updated = source[:content_start] + "\n" + encoded + "\n" + source[end:]
    path.write_text(updated, encoding="utf-8")


def update_dashboard(customers: list[dict[str, str]], *, update_index: bool = True) -> Path:
    mapping = customer_map(customers)
    daily_raw = _read_raw_csv(USAGE_DIR / "daily_raw.csv")
    weekly_raw = _read_raw_csv(USAGE_DIR / "weekly_raw.csv")
    daily_rows = aggregate_rows(daily_raw, mapping, "date")
    weekly_daily_rows = aggregate_rows(weekly_raw, mapping, "date")
    for row in weekly_daily_rows:
        row["week"] = _week_label(str(row["date"]))
    overview_rows, reconciliation = reconcile_overview(daily_rows, weekly_daily_rows)
    return write_dashboard_data(
        customers,
        daily_rows,
        aggregate_rows(weekly_raw, mapping, "week"),
        generated_at=datetime.now().astimezone().isoformat(timespec="seconds"),
        overview_rows=overview_rows,
        weekly_daily_rows=weekly_daily_rows,
        reconciliation=reconciliation,
        update_index=update_index,
    )


def run_query(start: str, end: str, mode: str, engine: str = "hive") -> Path:
    customers = load_customers()
    mapping = customer_map(customers)
    sql = build_usage_sql(start, end, mapping)
    print(f"[{mode}] 1/6 查询范围：{start} ~ {end}，客户 VID：{len(mapping)} 个")
    auth.init()
    job_id, status, _ = submit_query(sql, engine=engine)
    print(f"[{mode}] 2/6 DataLego job={job_id}，初始状态：{status}")
    result = wait_for_job(job_id, label=f"{mode} 查询", engine=engine)
    if result is None:
        raise DataLegoError("DataLego 查询失败")
    raw_rows = normalize_result(result)
    raw_path = RAW_DIR / f"{mode}-{start}-{end}.csv"
    result_to_csv(result, raw_path)
    merged_path = USAGE_DIR / f"{mode}_raw.csv"
    _merge_raw_csv(merged_path, raw_rows)
    print(f"[{mode}] 3/6 查询结果：{len(raw_rows)} 条，已写入 {raw_path}")
    reconciliation: dict[str, int] = {}
    if mode == "weekly":
        daily_path = USAGE_DIR / "daily_raw.csv"
        daily_rows = _read_raw_csv(daily_path)
        reconciled_daily, reconciliation = reconcile_daily_raw(daily_rows, raw_rows)
        if reconciliation["overwritten"] or reconciliation["added"]:
            _merge_raw_csv(daily_path, reconciled_daily)
        print(
            "[weekly] 4/6 daily 对账："
            f"检查 {reconciliation['checked']} 条，"
            f"覆盖 {reconciliation['overwritten']} 条，"
            f"补充 {reconciliation['added']} 条。"
        )
    update_index = should_update_index(mode, reconciliation)
    update_dashboard(customers, update_index=update_index)
    record_query_end(mode, end)
    print(f"[{mode}] 5/6 本地看板数据已更新：{USAGE_DIR / 'dashboard.json'}")
    if update_index:
        pushed = push_dashboard_updates(github_commit_message(mode, start, end, reconciliation))
        if pushed:
            print(f"[{mode}] 6/6 index.html 已更新并推送 GitHub。")
        else:
            print(f"[{mode}] 6/6 index.html 无变化，跳过 GitHub 推送。")
    else:
        print(f"[{mode}] 6/6 daily 与 weekly 数据一致，跳过 index.html 更新和 GitHub 推送。")
    return raw_path


def build_parser(mode: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=f"Run {mode} teleoperation usage query")
    parser.add_argument("--start", help="开始日期 YYYYMMDD")
    parser.add_argument("--end", help="结束日期 YYYYMMDD")
    if mode == "weekly":
        parser.add_argument("--week", help="指定 ISO 自然周 YYYY-Wxx")
    parser.add_argument("--engine", default="hive", help="DataLego query engine")
    parser.add_argument("--dry-run", action="store_true", help="只输出 SQL，不执行查询")
    parser.add_argument("--login", action="store_true", help="执行一次 Agora OAuth 登录")
    parser.set_defaults(mode=mode)
    return parser


def main(mode: str, argv: list[str] | None = None) -> int:
    parser = build_parser(mode)
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    args = parser.parse_args(normalize_week_argument(raw_argv) if mode == "weekly" else raw_argv)
    if args.login:
        interactive_login()
        return 0
    if mode == "weekly" and getattr(args, "week", None) and (args.start or args.end):
        parser.error("--week 不能与 --start/--end 同时使用")
    if bool(args.start) != bool(args.end):
        parser.error("--start 和 --end 必须同时提供")
    if mode == "weekly" and getattr(args, "week", None):
        try:
            start, end = week_label_range(args.week)
        except ValueError as exc:
            parser.error(str(exc))
    customers = load_customers()
    if not (mode == "weekly" and getattr(args, "week", None)) and args.start and args.end:
        start, end = args.start, args.end
    elif not (mode == "weekly" and getattr(args, "week", None)):
        last_end = last_query_end(mode)
        query_range = (
            weekly_query_range(last_end=last_end)
            if mode == "weekly"
            else daily_query_range(last_end=last_end)
        )
        if query_range is None:
            print(f"{mode} 查询已是最新，无需补数。")
            return 0
        start, end = query_range
    sql = build_usage_sql(start, end, [row["vid"] for row in customers])
    if args.dry_run:
        print(sql)
        return 0
    run_query(start, end, mode, args.engine)
    return 0
