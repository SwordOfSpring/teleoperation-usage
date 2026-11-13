import unittest
from pathlib import Path

from scripts.usage_pipeline import (
    aggregate_rows,
    build_usage_sql,
    daily_query_range,
    normalize_week_argument,
    load_customers,
    previous_complete_week,
    reconcile_overview,
    reconcile_daily_raw,
    week_label_range,
    github_commit_message,
    weekly_query_range,
    write_dashboard_data,
)


class UsagePipelineTests(unittest.TestCase):
    def test_build_usage_sql_contains_date_vid_and_skus(self):
        sql = build_usage_sql("20261101", "20261102", ["1002", "1001", "1002"])
        self.assertIn("date BETWEEN 20261101 AND 20261102", sql)
        self.assertIn("'1001', '1002'", sql)
        self.assertIn("sku IN (1002, 1003, 2002, 2003, 2004, 2005, 2006, 2007)", sql)

    def test_aggregate_rows_splits_audio_video_by_role(self):
        customers = {"1001": {"vid": "1001", "company_id": "cid", "company_name": "客户A", "sale": "销售"}}
        rows = [
            {"date": "20261101", "vid": "1001", "sku": "1002", "value": "10"},
            {"date": "20261101", "vid": "1001", "sku": "1003", "value": "5"},
            {"date": "20261101", "vid": "1001", "sku": "2002", "value": "7"},
            {"date": "20261101", "vid": "1001", "sku": "2003", "value": "3"},
            {"date": "20261101", "vid": "1001", "sku": "2005", "value": "11"},
        ]
        result = aggregate_rows(rows, customers)[0]
        self.assertEqual(result["audio_host"], 10)
        self.assertEqual(result["audio_viewer"], 5)
        self.assertEqual(result["video_host"], 10)
        self.assertEqual(result["video_viewer"], 11)
        self.assertEqual(result["host_total"], 20)
        self.assertEqual(result["viewer_total"], 16)
        self.assertEqual(result["total"], 36)

    def test_weekly_aggregation_uses_iso_week(self):
        customers = {"1001": {"vid": "1001", "company_id": "", "company_name": "客户A", "sale": ""}}
        rows = [{"date": "20261109", "vid": "1001", "sku": "1002", "value": "2.5"}]
        result = aggregate_rows(rows, customers, "week")
        self.assertEqual(result[0]["week"], "2026-W46")
        self.assertEqual(result[0]["audio_host"], 2.5)

    def test_reconcile_overview_uses_weekly_when_daily_differs(self):
        daily = [{"date": "20261103", "vid": "1001", "total": 10, "audio_total": 10, "video_total": 0,
                  "audio_host": 10, "audio_viewer": 0, "video_host": 0, "video_viewer": 0,
                  "host_total": 10, "viewer_total": 0}]
        weekly_daily = [{"date": "20261103", "vid": "1001", "total": 12, "audio_total": 12, "video_total": 0,
                         "audio_host": 12, "audio_viewer": 0, "video_host": 0, "video_viewer": 0,
                         "host_total": 12, "viewer_total": 0}]
        result, summary = reconcile_overview(daily, weekly_daily)
        self.assertEqual(result[0]["total"], 12)
        self.assertEqual(result[0]["data_source"], "weekly_fallback")
        self.assertEqual(summary, {"checked": 1, "fallback": 1})

    def test_reconcile_overview_keeps_daily_when_values_match(self):
        row = {"date": "20261103", "vid": "1001", "total": 10, "audio_total": 10, "video_total": 0,
               "audio_host": 10, "audio_viewer": 0, "video_host": 0, "video_viewer": 0,
               "host_total": 10, "viewer_total": 0}
        result, summary = reconcile_overview([row], [dict(row)])
        self.assertEqual(result[0]["data_source"], "daily")
        self.assertEqual(summary, {"checked": 1, "fallback": 0})

    def test_previous_complete_week_is_monday_to_sunday(self):
        self.assertEqual(previous_complete_week(__import__("datetime").date(2026, 11, 12)), ("20261102", "20261108"))

    def test_daily_query_range_backfills_from_last_completed_date(self):
        from datetime import date
        self.assertEqual(
            daily_query_range(date(2026, 11, 13), last_end="20261110"),
            ("20261111", "20261112"),
        )

    def test_daily_query_range_returns_none_when_already_current(self):
        from datetime import date
        self.assertIsNone(daily_query_range(date(2026, 11, 13), last_end="20261112"))

    def test_weekly_query_range_backfills_multiple_missing_weeks(self):
        from datetime import date
        self.assertEqual(
            weekly_query_range(date(2026, 11, 13), last_end="20261025"),
            ("20261026", "20261108"),
        )

    def test_weekly_query_range_uses_previous_complete_week_first_run(self):
        from datetime import date
        self.assertEqual(
            weekly_query_range(date(2026, 11, 13), last_end=None),
            ("20261102", "20261108"),
        )

    def test_week_label_range_resolves_iso_week(self):
        self.assertEqual(week_label_range("2026-W25"), ("20260615", "20260621"))

    def test_normalize_week_argument_converts_flag_to_parser_option(self):
        self.assertEqual(
            normalize_week_argument(["--2026-W25", "--dry-run"]),
            ["--week", "2026-W25", "--dry-run"],
        )

    def test_reconcile_daily_raw_replaces_only_mismatched_weekly_rows(self):
        daily = [
            {"date": "20260615", "vid": "1001", "sku": "1002", "value": "10"},
            {"date": "20260615", "vid": "1001", "sku": "1003", "value": "5"},
        ]
        weekly = [
            {"date": "20260615", "vid": "1001", "sku": "1002", "value": "12"},
            {"date": "20260615", "vid": "1001", "sku": "1003", "value": "5"},
        ]
        result, summary = reconcile_daily_raw(daily, weekly)
        self.assertEqual(result[0]["value"], "12")
        self.assertEqual(result[1]["value"], "5")
        self.assertEqual(summary, {"checked": 2, "overwritten": 1, "added": 0})

    def test_reconcile_daily_raw_adds_weekly_rows_missing_from_daily(self):
        result, summary = reconcile_daily_raw([], [{"date": "20260615", "vid": "1001", "sku": "1002", "value": "12"}])
        self.assertEqual(result[0]["value"], "12")
        self.assertEqual(summary, {"checked": 0, "overwritten": 0, "added": 1})

    def test_github_commit_message_is_chinese_and_contains_query_range(self):
        message = github_commit_message("weekly", "20260615", "20260621", {"overwritten": 2})
        self.assertIn("周", message)
        self.assertIn("20260615", message)
        self.assertIn("20260621", message)
        self.assertIn("覆盖 2 条", message)

    def test_load_customers_reads_expected_columns(self):
        path = Path.cwd() / ".tmp_customers.xlsx"
        try:
            import openpyxl
            workbook = openpyxl.Workbook()
            sheet = workbook.active
            sheet.append(["NAME", "CID", "VID", "SALE"])
            sheet.append(["客户A", 123, 456, "销售"])
            workbook.save(path)
            workbook.close()
            result = load_customers(path)
            self.assertEqual(result, [{"vid": "456", "company_name": "客户A", "company_id": "123", "sale": "销售"}])
        finally:
            path.unlink(missing_ok=True)

    def test_write_dashboard_data_creates_json(self):
        import scripts.usage_pipeline as pipeline
        output_dir = Path.cwd() / ".tmp_dashboard"
        original = pipeline.USAGE_DIR
        original_index = pipeline.INDEX_PATH
        pipeline.USAGE_DIR = output_dir
        pipeline.INDEX_PATH = output_dir / "index.html"
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
            pipeline.INDEX_PATH.write_text(
                '<script id="teleoperation-data" type="application/json">{}</script>',
                encoding="utf-8",
            )
            output = write_dashboard_data([], [], [], generated_at="now")
            self.assertTrue(output.exists())
            self.assertIn('"valueUnit": "passthrough"', output.read_text(encoding="utf-8"))
            self.assertIn('"valueUnit": "passthrough"', pipeline.INDEX_PATH.read_text(encoding="utf-8"))
        finally:
            pipeline.USAGE_DIR = original
            pipeline.INDEX_PATH = original_index
            for child in output_dir.glob("*") if output_dir.exists() else []:
                child.unlink()
            if output_dir.exists():
                output_dir.rmdir()

    def test_write_dashboard_data_can_skip_index_embedding(self):
        import scripts.usage_pipeline as pipeline
        output_dir = Path.cwd() / ".tmp_dashboard_skip_index"
        original = pipeline.USAGE_DIR
        original_index = pipeline.INDEX_PATH
        pipeline.USAGE_DIR = output_dir
        pipeline.INDEX_PATH = output_dir / "index.html"
        source = '<script id="teleoperation-data" type="application/json">{"old": true}</script>'
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
            pipeline.INDEX_PATH.write_text(source, encoding="utf-8")
            write_dashboard_data([], [], [], generated_at="now", update_index=False)
            self.assertEqual(pipeline.INDEX_PATH.read_text(encoding="utf-8"), source)
        finally:
            pipeline.USAGE_DIR = original
            pipeline.INDEX_PATH = original_index
            for child in output_dir.glob("*") if output_dir.exists() else []:
                child.unlink()
            if output_dir.exists():
                output_dir.rmdir()


if __name__ == "__main__":
    unittest.main()
