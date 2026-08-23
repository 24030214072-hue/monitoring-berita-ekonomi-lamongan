import logging
from collections.abc import Iterable, Mapping
from typing import Any
from urllib.parse import quote_plus, urlparse

import feedparser
from bs4 import BeautifulSoup

from .config import (
    MAX_CANDIDATES,
    MAX_RESULTS_PER_QUERY,
    REQUEST_TIMEOUT,
    SEARCH_TOPICS,
    TARGET_YEAR,
)
from .http import build_session
from .models import NewsCandidate
from .text import (
    canonicalize_url,
    clean_text,
    hostname_label,
    parse_feed_date,
    title_fingerprint,
)

logger = logging.getLogger(__name__)


class RSSDiscovery:
    """Discover 2026 Lamongan news from independent RSS search providers."""

    def __init__(self) -> None:
        self.session = build_session()

    def discover(self) -> list[NewsCandidate]:
        candidates: list[NewsCandidate] = []
        for topic in SEARCH_TOPICS:
            query = f'Lamongan {topic} after:{TARGET_YEAR}-01-01 before:{TARGET_YEAR + 1}-01-01'
            candidates.extend(self._google_news(query))
            candidates.extend(self._bing_news(query))

        unique: dict[str, NewsCandidate] = {}
        for candidate in candidates:
            if candidate.published_at.year != TARGET_YEAR:
                continue
            key = title_fingerprint(candidate.title)
            existing = unique.get(key)
            if existing is None or len(candidate.summary) > len(existing.summary):
                unique[key] = candidate

        return sorted(unique.values(), key=lambda item: item.published_at, reverse=True)[:MAX_CANDIDATES]

    def _fetch_feed(self, url: str) -> Iterable[Mapping[str, Any]]:
        try:
            response = self.session.get(url, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
            feed = feedparser.parse(response.content)
            if getattr(feed, "bozo", False) and not getattr(feed, "entries", []):
                logger.warning("Invalid RSS feed from %s", urlparse(url).netloc)
                return []
            return feed.entries[:MAX_RESULTS_PER_QUERY]
        except Exception as exc:
            logger.warning("RSS discovery failed for %s: %s", urlparse(url).netloc, exc)
            return []

    def _google_news(self, query: str) -> list[NewsCandidate]:
        url = (
            "https://news.google.com/rss/search?q="
            f"{quote_plus(query)}&hl=id&gl=ID&ceid=ID:id"
        )
        results: list[NewsCandidate] = []
        for entry in self._fetch_feed(url):
            candidate = self._candidate_from_entry(entry, provider="google")
            if candidate:
                results.append(candidate)
        return results

    def _bing_news(self, query: str) -> list[NewsCandidate]:
        url = f"https://www.bing.com/news/search?q={quote_plus(query)}&format=rss&mkt=id-ID"
        results: list[NewsCandidate] = []
        for entry in self._fetch_feed(url):
            candidate = self._candidate_from_entry(entry, provider="bing")
            if candidate:
                results.append(candidate)
        return results

    def _candidate_from_entry(
        self,
        entry: Mapping[str, Any],
        provider: str,
    ) -> NewsCandidate | None:
        published_at = parse_feed_date(entry)
        if published_at is None or published_at.year != TARGET_YEAR:
            return None

        title = clean_text(entry.get("title", ""))
        summary_html = entry.get("summary", "") or entry.get("description", "")
        summary = clean_text(summary_html)
        url = canonicalize_url(entry.get("link", ""))

        if provider == "google":
            publisher_url = self._publisher_url_from_summary(summary_html)
            if publisher_url:
                url = publisher_url

        source = ""
        source_data = entry.get("source")
        if source_data:
            source = clean_text(source_data.get("title", ""))
        if not source:
            source = hostname_label(url)
        if provider == "google" and " - " in title:
            possible_title, possible_source = title.rsplit(" - ", 1)
            if possible_title and possible_source:
                title = possible_title.strip()
                source = possible_source.strip()

        if not title or not url:
            return None
        return NewsCandidate(published_at, source, title, url, summary)

    @staticmethod
    def _publisher_url_from_summary(summary_html: str) -> str:
        soup = BeautifulSoup(str(summary_html), "html.parser")
        for anchor in soup.find_all("a", href=True):
            url = canonicalize_url(str(anchor["href"]))
            if url and "news.google.com" not in urlparse(url).netloc.casefold():
                return url
        return ""
