import unittest

from scripts.usage_pipeline import should_update_index


class DashboardUpdatePolicyTests(unittest.TestCase):
    def test_daily_query_always_updates_index(self):
        self.assertTrue(should_update_index("daily", {}))

    def test_weekly_query_updates_index_when_daily_is_overwritten(self):
        self.assertTrue(should_update_index("weekly", {"overwritten": 1, "added": 0}))

    def test_weekly_query_skips_index_when_data_matches(self):
        self.assertFalse(should_update_index("weekly", {"overwritten": 0, "added": 0}))


if __name__ == "__main__":
    unittest.main()
