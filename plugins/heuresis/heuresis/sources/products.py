"""Product and project sources: GitHub repositories and Hacker News stories."""

from __future__ import annotations

import os
import shutil
import subprocess
import urllib.parse

from heuresis.model import Record
from heuresis.sources import http, register


def github_token() -> str | None:
    if os.environ.get("GITHUB_TOKEN"):
        return os.environ["GITHUB_TOKEN"]
    gh = shutil.which("gh")
    if not gh:
        return None
    try:
        done = subprocess.run([gh, "auth", "token"], capture_output=True, text=True, timeout=10)
    except (subprocess.TimeoutExpired, OSError):
        return None
    if done.returncode != 0:
        return None
    return done.stdout.strip() or None


class GitHub:
    name, group = "github", "products"

    def available(self) -> tuple[bool, str]:
        return (True, "") if github_token() else (False, "no GITHUB_TOKEN and gh is not signed in")

    def search(self, query: str, limit: int) -> list[Record]:
        params = urllib.parse.urlencode({"q": query, "per_page": limit})
        headers = {
            "Authorization": f"Bearer {github_token()}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        data = http.json_object(
            http.get(f"https://api.github.com/search/repositories?{params}", headers)
        )
        return [
            Record(
                title=item["full_name"],
                url=item["html_url"],
                source=self.name,
                kind="repo",
                text=item.get("description") or "",
                date=(item.get("pushed_at") or "")[:10],
                evidence_url=f"https://api.github.com/repos/{item['full_name']}",
            )
            for item in data.get("items", [])
        ]

    def evidence(self, record: Record) -> str | None:
        return None


class HackerNews:
    name, group = "hacker_news", "products"

    def available(self) -> tuple[bool, str]:
        return True, ""

    def search(self, query: str, limit: int) -> list[Record]:
        params = urllib.parse.urlencode({"query": query, "tags": "story", "hitsPerPage": limit})
        data = http.json_object(http.get(f"https://hn.algolia.com/api/v1/search?{params}"))
        out = []
        for hit in data.get("hits", []):
            item = f"https://news.ycombinator.com/item?id={hit['objectID']}"
            out.append(
                Record(
                    title=hit.get("title") or "",
                    url=hit.get("url") or item,
                    source=self.name,
                    kind="web",
                    text=hit.get("story_text") or hit.get("title") or "",
                    date=(hit.get("created_at") or "")[:10],
                    evidence_url=f"https://hn.algolia.com/api/v1/items/{hit['objectID']}",
                )
            )
        return out

    def evidence(self, record: Record) -> str | None:
        return None


for _source in (GitHub(), HackerNews()):
    register(_source)
