import csv
import unittest
from pathlib import Path

from scripts.datalego_client import extract_access_context, result_to_csv


class DataLegoClientTests(unittest.TestCase):
    def test_extract_access_context_from_jwt_payload(self):
        import base64
        import json

        payload = base64.urlsafe_b64encode(json.dumps({
            "access_token": "access-token",
            "user": {"email": "user@example.com"},
        }).encode()).decode().rstrip("=")
        access_token, email = extract_access_context(f"header.{payload}.signature")
        self.assertEqual(access_token, "access-token")
        self.assertEqual(email, "user@example.com")

    def test_result_to_csv_writes_schema_and_bom(self):
        output = Path.cwd() / ".tmp_datalego_result.csv"
        try:
            count = result_to_csv({
                "schema": [{"name": "date"}, {"name": "value"}],
                "data": [[20261101, 12]],
            }, output)
            self.assertEqual(count, 1)
            self.assertTrue(output.read_bytes().startswith(b"\xef\xbb\xbf"))
            with output.open(encoding="utf-8-sig", newline="") as handle:
                self.assertEqual(list(csv.reader(handle)), [["date", "value"], ["20261101", "12"]])
        finally:
            output.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
