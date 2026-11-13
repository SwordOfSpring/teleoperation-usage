#!/usr/bin/env python3
"""Customer mapping, SQL rendering, SKU aggregation, and dashboard outputs."""

from __future__ import annotations

import argparse
import csv
import json
import os
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
) -> Path:
    _write_rows(USAGE_DIR / "daily_usage.csv", daily_rows, DAILY_COLUMNS)
    _write_rows(USAGE_DIR / "weekly_usage.csv", weekly_rows, WEEKLY_COLUMNS)
    payload = {
        "generatedAt": generated_at,
        "valueUnit": "passthrough",
        "customers": customers,
        "daily": daily_rows,
        "weekly": weekly_rows,
    }
    output = USAGE_DIR / "dashboard.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return output


def update_dashboard(customers: list[dict[str, str]]) -> Path:
    mapping = customer_map(customers)
    daily_raw = _read_raw_csv(USAGE_DIR / "daily_raw.csv")
    weekly_raw = _read_raw_csv(USAGE_DIR / "weekly_raw.csv")
    return write_dashboard_data(
        customers,
        aggregate_rows(daily_raw, mapping, "date"),
        aggregate_rows(weekly_raw, mapping, "week"),
        generated_at=datetime.now().astimezone().isoformat(timespec="seconds"),
    )


def run_query(start: str, end: str, mode: str, engine: str = "hive") -> Path:
    customers = load_customers()
    mapping = customer_map(customers)
    sql = build_usage_sql(start, end, mapping)
    print(f"查询范围：{start} ~ {end}，VID：{len(mapping)} 个")
    auth.init()
    job_id, status, _ = submit_query(sql, engine=engine)
    print(f"DataLego job={job_id}，初始状态={status}")
    result = wait_for_job(job_id, label=f"{mode} usage", engine=engine)
    if result is None:
        raise DataLegoError("DataLego 查询失败")
    raw_rows = normalize_result(result)
    raw_path = RAW_DIR / f"{mode}-{start}-{end}.csv"
    result_to_csv(result, raw_path)
    merged_path = USAGE_DIR / f"{mode}_raw.csv"
    _merge_raw_csv(merged_path, raw_rows)
    update_dashboard(customers)
    record_query_end(mode, end)
    print(f"写入 {len(raw_rows)} 条原始行：{raw_path}")
    print(f"看板数据已更新：{USAGE_DIR / 'dashboard.json'}")
    return raw_path


def build_parser(mode: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=f"Run {mode} teleoperation usage query")
    parser.add_argument("--start", help="开始日期 YYYYMMDD")
    parser.add_argument("--end", help="结束日期 YYYYMMDD")
    parser.add_argument("--engine", default="hive", help="DataLego query engine")
    parser.add_argument("--dry-run", action="store_true", help="只输出 SQL，不执行查询")
    parser.add_argument("--login", action="store_true", help="执行一次 Agora OAuth 登录")
    parser.set_defaults(mode=mode)
    return parser


def main(mode: str, argv: list[str] | None = None) -> int:
    parser = build_parser(mode)
    args = parser.parse_args(argv)
    if args.login:
        interactive_login()
        return 0
    if bool(args.start) != bool(args.end):
        parser.error("--start 和 --end 必须同时提供")
    customers = load_customers()
    if args.start and args.end:
        start, end = args.start, args.end
    else:
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
