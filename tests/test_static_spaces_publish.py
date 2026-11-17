import hashlib
import json
import os
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import publish_static_spaces as publisher


class FakeResponse:
    def __init__(self, payload):
        self.payload = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return self.payload


class StaticSpacesPublishTests(unittest.TestCase):
    def setUp(self):
        self.root = publisher.PROJECT_ROOT
        self.contents = {
            name: (self.root / name).read_text(encoding="utf-8")
            for name in publisher.ASSET_NAMES
        }

    def files_written(self):
        return [
            {
                "path": f"/spaces/shared/teleoperation-usage/{name}",
                "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
                "size": len(content.encode("utf-8")),
            }
            for name, content in self.contents.items()
        ]

    def test_requires_authentik_token(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(publisher.StaticSpacesPublishError, "AUTHENTIK_USER_API_TOKEN"):
                publisher.publish_static_space(self.root)

    def test_publishes_all_dashboard_assets_and_verifies_files(self):
        requests = []

        def fake_urlopen(request, timeout):
            requests.append((request, timeout))
            if request.get_method() == "POST":
                return FakeResponse({
                    "slug": "teleoperation-usage",
                    "files_written": self.files_written(),
                    "subscription_warnings": [],
                })
            return FakeResponse({"files": [{"path": name} for name in self.contents]})

        with patch.dict(os.environ, {"AUTHENTIK_USER_API_TOKEN": "test-token"}), patch.object(
            publisher, "urlopen", side_effect=fake_urlopen
        ):
            result = publisher.publish_static_space(self.root)

        self.assertEqual(result["slug"], "teleoperation-usage")
        self.assertEqual([request.get_method() for request, _ in requests], ["POST", "GET"])
        payload = json.loads(requests[0][0].data.decode("utf-8"))
        self.assertEqual(payload["kind"], "shared")
        self.assertEqual(payload["slug"], "teleoperation-usage")
        self.assertTrue(payload["overwrite"])
        self.assertEqual({item["relative_path"] for item in payload["files"]}, set(self.contents))
        self.assertEqual(requests[0][0].get_header("Authorization"), "Bearer test-token")

    def test_reports_subscription_warnings_as_failure(self):
        def fake_urlopen(request, timeout):
            return FakeResponse({
                "files_written": self.files_written(),
                "subscription_warnings": [{"path": "index.html", "warning": "bad marker"}],
            })

        with patch.dict(os.environ, {"AUTHENTIK_USER_API_TOKEN": "test-token"}), patch.object(
            publisher, "urlopen", side_effect=fake_urlopen
        ), self.assertRaisesRegex(publisher.StaticSpacesPublishError, "subscription"):
            publisher.publish_static_space(self.root)


if __name__ == "__main__":
    unittest.main()
