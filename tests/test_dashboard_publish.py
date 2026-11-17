import contextlib
import io
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import usage_pipeline as pipeline


class DashboardPublishTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.remote = root / "remote.git"
        self.repo = root / "checkout"
        self.git("init", "--bare", str(self.remote), cwd=root)
        self.git("init", "-b", "main", str(self.repo), cwd=root)
        self.git("config", "user.name", "Test")
        self.git("config", "user.email", "test@example.com")
        self.git("config", "commit.gpgsign", "false")
        (self.repo / "index.html").write_text("initial", encoding="utf-8")
        self.git("add", "index.html")
        self.git("commit", "-m", "initial")
        self.git("remote", "add", "origin", str(self.remote))
        self.git("push", "-u", "origin", "main")
        self.real_run = subprocess.run
        for patcher in (
            patch.object(pipeline, "PROJECT_ROOT", self.repo),
            patch("sys.stdout", new_callable=io.StringIO),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def git(self, *args, cwd=None):
        return subprocess.run(
            ["git", *args], cwd=cwd or self.repo,
            capture_output=True, text=True, check=True,
        ).stdout.strip()

    def remote_head(self):
        return self.git("--git-dir", str(self.remote), "rev-parse", "refs/heads/main")

    def intercept_push(self, errors):
        self.push_count = 0

        def run(command, **kwargs):
            if command[:2] == ["git", "push"]:
                self.push_count += 1
                if self.push_count <= len(errors):
                    error = errors[self.push_count - 1]
                    if isinstance(error, Exception):
                        raise error
                    return subprocess.CompletedProcess(command, 128, "", error)
            return self.real_run(command, **kwargs)

        return patch.object(pipeline.subprocess, "run", side_effect=run)

    def test_reset_is_retried_and_remote_receives_one_commit(self):
        (self.repo / "index.html").write_text("new data", encoding="utf-8")
        with self.intercept_push(["Recv failure: Connection was reset"]), patch("time.sleep"):
            published = pipeline.push_dashboard_updates("dashboard update")
        self.assertTrue(published)
        self.assertEqual(self.remote_head(), self.git("rev-parse", "HEAD"))
        self.assertEqual(self.git("rev-list", "--count", "HEAD"), "2")

    def test_no_file_changes_still_pushes_pending_dashboard_commit(self):
        (self.repo / "index.html").write_text("pending data", encoding="utf-8")
        self.git("add", "index.html")
        self.git("commit", "-m", "pending dashboard")
        published = pipeline.push_dashboard_updates("no new query")
        self.assertTrue(published)
        self.assertEqual(self.remote_head(), self.git("rev-parse", "HEAD"))

    def test_already_published_dashboard_does_not_push_again(self):
        with self.intercept_push([]):
            self.assertFalse(pipeline.push_dashboard_updates("no changes"))
        self.assertEqual(self.push_count, 0)

    def test_push_only_preserves_uncommitted_page(self):
        (self.repo / "index.html").write_text("unfinished page", encoding="utf-8")
        before = self.git("rev-parse", "HEAD")
        self.assertFalse(pipeline.push_dashboard_updates("retry only", commit_changes=False))
        self.assertEqual(self.git("rev-parse", "HEAD"), before)
        self.assertEqual((self.repo / "index.html").read_text(encoding="utf-8"), "unfinished page")

    def test_unrelated_unpublished_commit_does_not_trigger_dashboard_push(self):
        (self.repo / "notes.txt").write_text("notes", encoding="utf-8")
        self.git("add", "notes.txt")
        self.git("commit", "-m", "notes only")
        before = self.remote_head()
        self.assertFalse(pipeline.push_dashboard_updates("retry only", commit_changes=False))
        self.assertEqual(self.remote_head(), before)

    def test_repeated_reset_keeps_commit_for_later_retry(self):
        (self.repo / "index.html").write_text("pending data", encoding="utf-8")
        before = self.remote_head()
        with self.intercept_push(["Connection was reset"] * 3), patch("time.sleep"):
            with self.assertRaises(pipeline.GitHubPublishError):
                pipeline.push_dashboard_updates("dashboard update")
        self.assertEqual(self.remote_head(), before)
        self.assertEqual(self.git("status", "--porcelain"), "")
        self.assertEqual(self.git("rev-list", "--count", "HEAD"), "2")
        self.assertTrue(pipeline.push_dashboard_updates("retry pending"))
        self.assertEqual(self.remote_head(), self.git("rev-parse", "HEAD"))

    def test_non_fast_forward_is_not_retried(self):
        (self.repo / "index.html").write_text("pending data", encoding="utf-8")
        before = self.remote_head()
        with self.intercept_push(["[rejected] main -> main (fetch first)"]):
            with self.assertRaises(pipeline.GitHubPublishError):
                pipeline.push_dashboard_updates("dashboard update")
        self.assertEqual(self.push_count, 1)
        self.assertEqual(self.remote_head(), before)

    def test_push_timeout_retries(self):
        (self.repo / "index.html").write_text("pending data", encoding="utf-8")
        error = subprocess.TimeoutExpired(["git", "push"], 60)
        with self.intercept_push([error]), patch("time.sleep"):
            self.assertTrue(pipeline.push_dashboard_updates("dashboard update"))
        self.assertEqual(self.remote_head(), self.git("rev-parse", "HEAD"))

    def test_unrelated_staged_changes_are_not_included_in_dashboard_commit(self):
        (self.repo / "index.html").write_text("new data", encoding="utf-8")
        (self.repo / "notes.txt").write_text("unfinished", encoding="utf-8")
        self.git("add", "notes.txt")
        self.assertTrue(pipeline.push_dashboard_updates("dashboard update"))
        self.assertEqual(self.git("diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD"), "index.html")
        self.assertEqual(self.git("diff", "--cached", "--name-only"), "notes.txt")


class PublishCliTests(unittest.TestCase):
    def test_push_only_does_not_load_customers_or_query(self):
        with patch.object(pipeline, "load_customers", side_effect=AssertionError("no query")), patch.object(
            pipeline, "push_dashboard_updates", return_value=True
        ) as publish:
            self.assertEqual(pipeline.main("daily", ["--push-only"]), 0)
        self.assertFalse(publish.call_args.kwargs["commit_changes"])

    def test_current_data_still_retries_pending_push(self):
        with patch.object(pipeline, "load_customers", return_value=[{"vid": "1"}]), patch.object(
            pipeline, "last_query_end", return_value="20261115"
        ), patch.object(pipeline, "daily_query_range", return_value=None), patch.object(
            pipeline, "push_dashboard_updates", return_value=True
        ) as publish, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(pipeline.main("daily", []), 0)
        publish.assert_called_once()
        self.assertFalse(publish.call_args.kwargs["commit_changes"])

    def test_push_failure_has_clear_message_and_nonzero_exit(self):
        stream = io.StringIO()
        with patch.object(pipeline, "push_dashboard_updates", side_effect=pipeline.GitHubPublishError("network reset")), contextlib.redirect_stdout(stream):
            self.assertEqual(pipeline.main("daily", ["--push-only"]), 1)
        self.assertIn("本地", stream.getvalue())
        self.assertIn("--push-only", stream.getvalue())

    def test_dry_run_when_current_does_not_push(self):
        with patch.object(pipeline, "load_customers", return_value=[{"vid": "1"}]), patch.object(
            pipeline, "last_query_end", return_value="20261115"
        ), patch.object(pipeline, "daily_query_range", return_value=None), patch.object(
            pipeline, "push_dashboard_updates", side_effect=AssertionError("dry run must not push")
        ), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(pipeline.main("daily", ["--dry-run"]), 0)


class StaticSpacesIntegrationTests(unittest.TestCase):
    def pipeline_mocks(self):
        stack = contextlib.ExitStack()
        stack.enter_context(patch.object(pipeline, "load_customers", return_value=[{"vid": "1"}]))
        stack.enter_context(patch.object(pipeline.auth, "init"))
        stack.enter_context(patch.object(pipeline, "submit_query", return_value=("job", "success", {})))
        stack.enter_context(patch.object(pipeline, "wait_for_job", return_value={"schema": [], "data": []}))
        stack.enter_context(patch.object(pipeline, "normalize_result", return_value=[]))
        stack.enter_context(patch.object(pipeline, "result_to_csv"))
        stack.enter_context(patch.object(pipeline, "_merge_raw_csv", return_value=[]))
        stack.enter_context(patch.object(pipeline, "_read_raw_csv", return_value=[]))
        return stack

    def test_daily_page_update_publishes_static_space(self):
        with self.pipeline_mocks(), patch.object(pipeline, "update_dashboard"), patch.object(
            pipeline, "record_query_end"
        ), patch.object(pipeline, "push_dashboard_updates", return_value=True), patch.object(
            pipeline, "publish_static_space"
        ) as publish:
            pipeline.run_query("20261116", "20261116", "daily")
        publish.assert_called_once_with()

    def test_daily_logs_use_shared_stages_and_daily_specific_wording(self):
        stream = io.StringIO()
        with self.pipeline_mocks(), patch.object(pipeline, "update_dashboard"), patch.object(
            pipeline, "record_query_end"
        ), patch.object(pipeline, "push_dashboard_updates", return_value=True), patch.object(
            pipeline, "publish_static_space"
        ), contextlib.redirect_stdout(stream):
            pipeline.run_query("20261116", "20261116", "daily")
        output = stream.getvalue()
        self.assertIn("[daily][开始]", output)
        self.assertIn("[daily][1/7]", output)
        self.assertIn("[daily][4/7] daily 主数据", output)
        self.assertIn("[daily][6/7] StaticSpaces", output)
        self.assertIn("[daily][7/7]", output)

    def test_weekly_logs_use_shared_stages_and_weekly_specific_wording(self):
        stream = io.StringIO()
        with self.pipeline_mocks(), patch.object(pipeline, "update_dashboard"), patch.object(
            pipeline, "record_query_end"
        ), patch.object(pipeline, "push_dashboard_updates", return_value=False), patch.object(
            pipeline, "publish_static_space"
        ), contextlib.redirect_stdout(stream):
            pipeline.run_query("20261102", "20261108", "weekly")
        output = stream.getvalue()
        self.assertIn("[weekly][开始]", output)
        self.assertIn("[weekly][1/7]", output)
        self.assertIn("[weekly][4/7] weekly 对账", output)
        self.assertIn("[weekly][6/7]", output)
        self.assertIn("[weekly][7/7]", output)

    def test_consistent_weekly_data_does_not_publish_static_space(self):
        with self.pipeline_mocks(), patch.object(pipeline, "update_dashboard"), patch.object(
            pipeline, "record_query_end"
        ), patch.object(pipeline, "push_dashboard_updates", return_value=False), patch.object(
            pipeline, "publish_static_space"
        ) as publish:
            pipeline.run_query("20261102", "20261108", "weekly")
        publish.assert_not_called()


if __name__ == "__main__":
    unittest.main()
