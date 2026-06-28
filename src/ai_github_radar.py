from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import math
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config.json"
DEFAULT_SNAPSHOT = ROOT / "data" / "snapshot.json"
DEFAULT_REPORT = ROOT / "reports" / "latest.md"
SHANGHAI_TZ = timezone(timedelta(hours=8))


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as file:
        json.dump(value, file, ensure_ascii=False, indent=2)
        file.write("\n")


class GitHubClient:
    def __init__(
        self,
        token: str | None,
        api_version: str,
        search_delay_seconds: float = 2.1,
    ) -> None:
        self.token = token
        self.api_version = api_version
        self.search_delay_seconds = search_delay_seconds
        self.last_search_at = 0.0

    def _headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "ai-github-radar",
            "X-GitHub-Api-Version": self.api_version,
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def _request_json(self, url: str) -> dict[str, Any]:
        request = urllib.request.Request(url, headers=self._headers())
        for attempt in range(3):
            try:
                with urllib.request.urlopen(request, timeout=30) as response:
                    return json.loads(response.read().decode("utf-8"))
            except urllib.error.HTTPError as error:
                body = error.read().decode("utf-8", errors="replace")
                if error.code not in (403, 429) or attempt == 2:
                    raise RuntimeError(
                        f"GitHub API 请求失败（HTTP {error.code}）：{body}"
                    ) from error

                retry_after = error.headers.get("Retry-After")
                reset_at = error.headers.get("X-RateLimit-Reset")
                if retry_after:
                    wait_seconds = max(float(retry_after), 1.0)
                elif reset_at:
                    wait_seconds = max(float(reset_at) - time.time() + 1, 1.0)
                else:
                    wait_seconds = 60.0 * (attempt + 1)
                print(f"触发 GitHub 限流，{wait_seconds:.0f} 秒后重试……")
                time.sleep(min(wait_seconds, 180.0))
            except urllib.error.URLError as error:
                if attempt == 2:
                    raise RuntimeError(f"连接 GitHub API 失败：{error}") from error
                time.sleep(2**attempt)
        raise AssertionError("unreachable")

    def search_repositories(self, query: str, per_page: int) -> list[dict[str, Any]]:
        elapsed = time.monotonic() - self.last_search_at
        if elapsed < self.search_delay_seconds:
            time.sleep(self.search_delay_seconds - elapsed)

        parameters = urllib.parse.urlencode(
            {
                "q": query,
                "sort": "stars",
                "order": "desc",
                "per_page": min(max(per_page, 1), 100),
                "page": 1,
            }
        )
        try:
            result = self._request_json(
                f"https://api.github.com/search/repositories?{parameters}"
            )
        finally:
            self.last_search_at = time.monotonic()
        return result.get("items", [])


def repository_text(repository: dict[str, Any]) -> str:
    values = [
        repository.get("name", ""),
        repository.get("description") or "",
        " ".join(repository.get("topics") or []),
    ]
    return " ".join(values).lower()


def is_excluded(repository: dict[str, Any], excluded_keywords: list[str]) -> bool:
    text = repository_text(repository)
    return any(keyword.lower() in text for keyword in excluded_keywords)


def discover_repositories(
    client: GitHubClient,
    config: dict[str, Any],
    now: datetime,
) -> list[dict[str, Any]]:
    repositories: dict[int, dict[str, Any]] = {}
    minimum_stars = int(config["minimum_stars"])
    new_since = (now - timedelta(days=int(config["new_project_days"]))).date()
    language = str(config.get("language") or "").strip()
    common_qualifiers = [
        f"stars:>={minimum_stars}",
        "archived:false",
        "is:public",
    ]
    if language:
        common_qualifiers.append(f"language:{language}")

    for category in config["categories"]:
        category_name = category["name"]
        for raw_query in category["queries"]:
            base_query = " ".join([raw_query, *common_qualifiers])
            queries = [
                base_query,
                f"{base_query} created:>={new_since.isoformat()}",
            ]
            for query in queries:
                print(f"搜索 [{category_name}]：{query}")
                found = client.search_repositories(
                    query, int(config["results_per_query"])
                )
                for repository in found:
                    if repository.get("fork") or is_excluded(
                        repository, config.get("exclude_keywords", [])
                    ):
                        continue
                    repository_id = int(repository["id"])
                    if repository_id not in repositories:
                        repositories[repository_id] = {
                            **repository,
                            "_categories": [category_name],
                        }
                    elif category_name not in repositories[repository_id]["_categories"]:
                        repositories[repository_id]["_categories"].append(category_name)

    return list(repositories.values())


@dataclass(frozen=True)
class RankedRepository:
    full_name: str
    url: str
    description: str
    categories: tuple[str, ...]
    language: str
    stars: int
    stars_gained: int | None
    stars_per_week: float | None
    growth_rate: float | None
    created_at: datetime
    pushed_at: datetime | None


def rank_repositories(
    repositories: list[dict[str, Any]],
    previous_snapshot: dict[str, Any],
    config: dict[str, Any],
    now: datetime,
) -> dict[str, list[RankedRepository]]:
    previous_repositories = previous_snapshot.get("repositories", {})
    previous_recorded_at = parse_datetime(previous_snapshot.get("recorded_at"))
    elapsed_days = (
        max((now - previous_recorded_at).total_seconds() / 86400, 1.0)
        if previous_recorded_at
        else None
    )
    active_since = now - timedelta(days=int(config["active_within_days"]))
    new_since = now - timedelta(days=int(config["new_project_days"]))
    ranked: list[RankedRepository] = []

    for repository in repositories:
        full_name = repository["full_name"]
        stars = int(repository.get("stargazers_count", 0))
        old = previous_repositories.get(full_name)
        stars_gained: int | None = None
        stars_per_week: float | None = None
        growth_rate: float | None = None
        if old and elapsed_days is not None:
            old_stars = int(old.get("stars", 0))
            stars_gained = max(stars - old_stars, 0)
            stars_per_week = stars_gained * 7 / elapsed_days
            growth_rate = stars_gained / max(old_stars, 1)

        ranked.append(
            RankedRepository(
                full_name=full_name,
                url=repository["html_url"],
                description=(repository.get("description") or "暂无项目描述").strip(),
                categories=tuple(repository.get("_categories", ["其他"])),
                language=repository.get("language") or "未知",
                stars=stars,
                stars_gained=stars_gained,
                stars_per_week=stars_per_week,
                growth_rate=growth_rate,
                created_at=parse_datetime(repository["created_at"]) or now,
                pushed_at=parse_datetime(repository.get("pushed_at")),
            )
        )

    report_size = config["report_size"]
    rising = [
        item
        for item in ranked
        if item.stars_per_week is not None
        and item.stars_per_week >= int(config["minimum_weekly_star_gain"])
    ]
    rising.sort(
        key=lambda item: (
            item.stars_per_week or 0,
            math.log1p(item.stars) * (item.growth_rate or 0),
        ),
        reverse=True,
    )

    rising = rising[: int(report_size["rising"])]
    used_names = {item.full_name for item in rising}

    new = [
        item
        for item in ranked
        if item.created_at >= new_since and item.full_name not in used_names
    ]
    new.sort(key=lambda item: item.stars, reverse=True)
    new = new[: int(report_size["new"])]
    used_names.update(item.full_name for item in new)

    hot = [
        item
        for item in ranked
        if item.pushed_at is not None and item.pushed_at >= active_since
        and item.full_name not in used_names
    ]
    hot.sort(key=lambda item: item.stars, reverse=True)

    return {
        "rising": rising,
        "new": new,
        "hot": hot[: int(report_size["hot"])],
    }


def compact_number(value: int | float) -> str:
    if value >= 1_000_000:
        return f"{value / 1_000_000:.1f}m"
    if value >= 1_000:
        return f"{value / 1_000:.1f}k"
    return str(int(round(value)))


def clean_description(value: str, maximum: int = 120) -> str:
    value = " ".join(value.split()).replace("[", "［").replace("]", "］")
    return value if len(value) <= maximum else value[: maximum - 1] + "…"


def item_markdown(
    item: RankedRepository,
    index: int,
    kind: str,
    now: datetime,
) -> str:
    category = " / ".join(item.categories[:2])
    if kind == "rising":
        metric = (
            f"本期 +{compact_number(item.stars_gained or 0)} ⭐"
            f"（约 +{compact_number(item.stars_per_week or 0)}/周）"
        )
    elif kind == "new":
        age = max((now - item.created_at).days, 0)
        metric = f"创建 {age} 天｜{compact_number(item.stars)} ⭐"
    else:
        metric = f"{compact_number(item.stars)} ⭐｜{item.language}"
    return (
        f"{index}. [{item.full_name}]({item.url})\n"
        f"   {metric}｜{category}\n"
        f"   {clean_description(item.description)}"
    )


def build_report(
    rankings: dict[str, list[RankedRepository]],
    now: datetime,
    has_baseline: bool,
) -> str:
    local_now = now.astimezone(SHANGHAI_TZ)
    lines = [
        f"# AI GitHub 周报｜{local_now:%Y-%m-%d}",
        "",
        "聚焦 AI 应用项目；数据来自 GitHub 公开仓库。",
        "",
    ]
    sections = [
        ("rising", "🚀 升星最快"),
        ("new", "🌱 近期新项目"),
        ("hot", "🔥 持续热门"),
    ]
    for kind, title in sections:
        if kind == "rising" and not has_baseline:
            lines.extend(
                [
                    f"## {title}",
                    "",
                    "首次运行正在建立 Star 基线，下次运行后生成升星榜。",
                    "",
                ]
            )
            continue
        lines.extend([f"## {title}", ""])
        items = rankings[kind]
        if not items:
            lines.extend(["本期没有符合条件的项目。", ""])
            continue
        for index, item in enumerate(items, 1):
            lines.extend([item_markdown(item, index, kind, now), ""])
    return "\n".join(lines).rstrip() + "\n"


def report_to_feishu_markdown(report: str) -> str:
    lines = report.splitlines()
    converted: list[str] = []
    for line in lines:
        if line.startswith("# "):
            converted.append(f"**{line[2:]}**")
        elif line.startswith("## "):
            converted.append(f"\n**{line[3:]}**")
        else:
            converted.append(line)
    return "\n".join(converted)


def make_feishu_signature(timestamp: int, secret: str) -> str:
    string_to_sign = f"{timestamp}\n{secret}".encode("utf-8")
    digest = hmac.new(string_to_sign, b"", digestmod=hashlib.sha256).digest()
    return base64.b64encode(digest).decode("utf-8")


def push_to_feishu(webhook: str, secret: str | None, report: str) -> None:
    timestamp = int(time.time())
    payload: dict[str, Any] = {
        "msg_type": "interactive",
        "card": {
            "schema": "2.0",
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {"tag": "plain_text", "content": "AI GitHub 周报"},
                "template": "blue",
            },
            "body": {
                "elements": [
                    {
                        "tag": "markdown",
                        "content": report_to_feishu_markdown(report),
                        "text_size": "normal_v2",
                    }
                ]
            },
        },
    }
    if secret:
        payload["timestamp"] = str(timestamp)
        payload["sign"] = make_feishu_signature(timestamp, secret)

    request = urllib.request.Request(
        webhook,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"飞书推送失败（HTTP {error.code}）：{body}") from error
    if result.get("code", result.get("StatusCode", 0)) != 0:
        raise RuntimeError(f"飞书推送失败：{result}")


def make_snapshot(repositories: list[dict[str, Any]], now: datetime) -> dict[str, Any]:
    return {
        "version": 1,
        "recorded_at": now.isoformat(),
        "repositories": {
            repository["full_name"]: {
                "stars": int(repository.get("stargazers_count", 0)),
                "url": repository["html_url"],
            }
            for repository in sorted(
                repositories, key=lambda item: item["full_name"].lower()
            )
        },
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="每周 AI GitHub 项目雷达")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--snapshot", type=Path, default=DEFAULT_SNAPSHOT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="生成报告但不推送飞书，也不更新快照",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    config = load_json(args.config)
    previous_snapshot = (
        load_json(args.snapshot)
        if args.snapshot.exists()
        else {"version": 1, "recorded_at": None, "repositories": {}}
    )
    now = utc_now()
    github_token = os.getenv("GH_TOKEN") or os.getenv("GITHUB_TOKEN")
    if not github_token:
        print("提示：未设置 GH_TOKEN，将使用 GitHub 匿名请求额度。", file=sys.stderr)

    client = GitHubClient(
        github_token,
        config.get("github_api_version", "2026-03-10"),
        float(config.get("search_delay_seconds", 2.1)),
    )
    repositories = discover_repositories(client, config, now)
    print(f"去重及排除后发现 {len(repositories)} 个 AI 应用项目。")
    rankings = rank_repositories(
        repositories, previous_snapshot, config, now
    )
    has_baseline = bool(previous_snapshot.get("recorded_at"))
    report = build_report(rankings, now, has_baseline)

    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(report, encoding="utf-8", newline="\n")
    print(f"报告已生成：{args.report}")

    if args.dry_run:
        print("dry-run：跳过飞书推送和快照更新。")
        return 0

    webhook = os.getenv("FEISHU_WEBHOOK")
    if webhook:
        push_to_feishu(webhook, os.getenv("FEISHU_SECRET"), report)
        print("飞书推送成功。")
    else:
        print("提示：未设置 FEISHU_WEBHOOK，仅生成报告和快照。", file=sys.stderr)

    write_json(args.snapshot, make_snapshot(repositories, now))
    print(f"快照已更新：{args.snapshot}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
