import unittest
from datetime import datetime, timedelta, timezone

from src.ai_github_radar import (
    build_report,
    compact_number,
    make_feishu_signature,
    rank_repositories,
)


NOW = datetime(2026, 6, 28, tzinfo=timezone.utc)


def repository(
    full_name: str,
    stars: int,
    created_days_ago: int = 30,
    pushed_days_ago: int = 1,
) -> dict:
    return {
        "full_name": full_name,
        "html_url": f"https://github.com/{full_name}",
        "description": "An AI application",
        "_categories": ["AI Agent"],
        "language": "Python",
        "stargazers_count": stars,
        "created_at": (NOW - timedelta(days=created_days_ago)).isoformat(),
        "pushed_at": (NOW - timedelta(days=pushed_days_ago)).isoformat(),
    }


class RadarTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = {
            "minimum_weekly_star_gain": 10,
            "active_within_days": 180,
            "new_project_days": 14,
            "report_size": {"rising": 10, "new": 10, "hot": 10},
        }

    def test_rising_uses_elapsed_time_normalized_to_week(self) -> None:
        current = [
            repository("acme/fast", 200),
            repository("acme/slow", 1000),
        ]
        snapshot = {
            "recorded_at": (NOW - timedelta(days=14)).isoformat(),
            "repositories": {
                "acme/fast": {"stars": 100},
                "acme/slow": {"stars": 950},
            },
        }
        result = rank_repositories(current, snapshot, self.config, NOW)
        self.assertEqual(result["rising"][0].full_name, "acme/fast")
        self.assertAlmostEqual(result["rising"][0].stars_per_week, 50)

    def test_new_and_inactive_filters(self) -> None:
        current = [
            repository("acme/new", 80, created_days_ago=3),
            repository("acme/old", 5000, created_days_ago=500, pushed_days_ago=300),
        ]
        result = rank_repositories(
            current,
            {"recorded_at": None, "repositories": {}},
            self.config,
            NOW,
        )
        self.assertEqual([item.full_name for item in result["new"]], ["acme/new"])
        self.assertNotIn("acme/old", [item.full_name for item in result["hot"]])
        self.assertNotIn("acme/new", [item.full_name for item in result["hot"]])

    def test_first_report_explains_baseline(self) -> None:
        report = build_report(
            {"rising": [], "new": [], "hot": []}, NOW, has_baseline=False
        )
        self.assertIn("首次运行正在建立 Star 基线", report)

    def test_helpers(self) -> None:
        self.assertEqual(compact_number(12500), "12.5k")
        self.assertEqual(
            make_feishu_signature(1599360473, "demo"),
            "l1N0gAcBjdwBvGm1xMjOF0XSyaLRpR7tuO5dHfhAYc8=",
        )


if __name__ == "__main__":
    unittest.main()
