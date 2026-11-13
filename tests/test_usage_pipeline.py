import unittest
from pathlib import Path

from scripts.usage_pipeline import (
    aggregate_rows,
    build_usage_sql,
    daily_query_range,
    load_customers,
    previous_complete_week,
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
        pipeline.USAGE_DIR = output_dir
        try:
            output = write_dashboard_data([], [], [], generated_at="now")
            self.assertTrue(output.exists())
            self.assertIn('"valueUnit": "passthrough"', output.read_text(encoding="utf-8"))
        finally:
            pipeline.USAGE_DIR = original
            for child in output_dir.glob("*") if output_dir.exists() else []:
                child.unlink()
            if output_dir.exists():
                output_dir.rmdir()


if __name__ == "__main__":
    unittest.main()
