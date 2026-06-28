import unittest
from datetime import datetime, timedelta, timezone

from src.ai_github_radar import (
    build_report,
    classify_categories,
    compact_number,
    make_feishu_signature,
    normalize_analysis,
    parse_trending_html,
    rank_repositories,
)


NOW = datetime(2026, 6, 28, tzinfo=timezone.utc)


def repository(
    full_name: str,
    stars: int,
    created_days_ago: int = 30,
    pushed_days_ago: int = 1,
    official_rank: int | None = None,
    weekly_stars: int | None = None,
) -> dict:
    return {
        "full_name": full_name,
        "html_url": f"https://github.com/{full_name}",
        "name": full_name.split("/")[-1],
        "description": "An AI agent application",
        "_categories": ["AI Agent"],
        "topics": ["ai-agent"],
        "language": "Python",
        "stargazers_count": stars,
        "created_at": (NOW - timedelta(days=created_days_ago)).isoformat(),
        "pushed_at": (NOW - timedelta(days=pushed_days_ago)).isoformat(),
        "_official_rank": official_rank,
        "_weekly_stars": weekly_stars,
    }


class RadarTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = {
            "minimum_weekly_star_gain": 10,
            "new_project_days": 14,
            "report_size": {"official": 10, "rising": 10, "new": 10},
        }

    def test_parse_trending_preserves_official_order(self) -> None:
        html = """
        <article class="Box-row">
          <h2><a href="/acme/first">acme / first</a></h2>
          <p class="col-9 color-fg-muted my-1 pr-4">First AI app</p>
          <span itemprop="programmingLanguage">TypeScript</span>
          <a href="/acme/first/stargazers">12,345</a>
          <span class="d-inline-block float-sm-right">2,735 stars this week</span>
        </article>
        <article class="Box-row">
          <h2><a href="/acme/second">acme / second</a></h2>
          <img src="avatar.png">
          <p class="col-9 color-fg-muted my-1 pr-4">Second AI app</p>
          <span itemprop="programmingLanguage">Python</span>
          <a href="/acme/second/stargazers">900</a>
          <span class="d-inline-block float-sm-right">524 stars this week</span>
        </article>
        """
        items = parse_trending_html(html)
        self.assertEqual(
            [item["full_name"] for item in items],
            ["acme/first", "acme/second"],
        )
        self.assertEqual(items[0]["weekly_stars"], 2735)
        self.assertEqual(items[1]["language"], "Python")

    def test_category_classification_is_language_independent(self) -> None:
        categories = [
            {"name": "AI Agent", "keywords": ["ai agent", "agentic"]},
            {"name": "MCP 应用", "keywords": ["mcp server"]},
        ]
        result = classify_categories(
            {
                "name": "助手",
                "description": "An agentic automation app",
                "topics": [],
            },
            categories,
        )
        self.assertEqual(result, ["AI Agent"])

    def test_official_order_and_rising_supplement_do_not_duplicate(self) -> None:
        current = [
            repository("acme/official-2", 200, official_rank=5, weekly_stars=80),
            repository("acme/official-1", 500, official_rank=2, weekly_stars=120),
            repository("acme/rising", 300),
        ]
        snapshot = {
            "recorded_at": (NOW - timedelta(days=7)).isoformat(),
            "repositories": {
                "acme/official-2": {"stars": 100},
                "acme/official-1": {"stars": 300},
                "acme/rising": {"stars": 100},
            },
        }
        result = rank_repositories(current, snapshot, self.config, NOW)
        self.assertEqual(
            [item.full_name for item in result["official"]],
            ["acme/official-1", "acme/official-2"],
        )
        self.assertEqual(
            [item.full_name for item in result["rising"]],
            ["acme/rising"],
        )

    def test_rising_is_normalized_to_one_week(self) -> None:
        current = [repository("acme/fast", 200)]
        snapshot = {
            "recorded_at": (NOW - timedelta(days=14)).isoformat(),
            "repositories": {"acme/fast": {"stars": 100}},
        }
        result = rank_repositories(current, snapshot, self.config, NOW)
        self.assertAlmostEqual(result["rising"][0].stars_per_week, 50)

    def test_report_uses_chinese_analysis(self) -> None:
        item = rank_repositories(
            [repository("acme/app", 100, official_rank=1, weekly_stars=50)],
            {"recorded_at": None, "repositories": {}},
            self.config,
            NOW,
        )
        report = build_report(
            item,
            {
                "acme/app": {
                    "summary_zh": "一个智能应用",
                    "application": "帮助用户自动完成任务",
                    "use_cases": ["自动化"],
                    "target_users": "开发者",
                }
            },
            NOW,
            has_baseline=False,
        )
        self.assertIn("官网第 1 名｜本周 +50", report)
        self.assertIn("中文简介：一个智能应用", report)

    def test_analysis_normalization_and_helpers(self) -> None:
        analysis = normalize_analysis(
            {
                "summary_zh": "简介",
                "application": "说明",
                "use_cases": ["用途一", "用途二"],
                "target_users": "开发者",
            }
        )
        self.assertEqual(analysis["use_cases"], ["用途一", "用途二"])
        self.assertEqual(compact_number(12500), "12.5k")
        self.assertEqual(
            make_feishu_signature(1599360473, "demo"),
            "l1N0gAcBjdwBvGm1xMjOF0XSyaLRpR7tuO5dHfhAYc8=",
        )


if __name__ == "__main__":
    unittest.main()
