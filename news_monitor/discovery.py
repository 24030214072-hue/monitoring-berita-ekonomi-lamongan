import logging
from collections.abc import Callable, Iterable, Mapping
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta
from typing import Any
from urllib.parse import quote_plus, urlparse

import feedparser
from bs4 import BeautifulSoup

from .config import (
    DISCOVERY_WORKERS,
    MAX_CANDIDATES,
    MAX_RESULTS_PER_QUERY,
    REQUEST_TIMEOUT,
    SEARCH_TOPICS,
    START_YEAR,
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
DateWindow = tuple[date, date]
DiscoveryBatchCallback = Callable[[list[NewsCandidate], int, int], None]


class RSSDiscovery:
    """Discover Lamongan news through bounded, date-windowed RSS searches."""

    def discover(
        self,
        windows: list[DateWindow] | None = None,
        on_batch: DiscoveryBatchCallback | None = None,
    ) -> list[NewsCandidate]:
        default_year = max(START_YEAR, date.today().year)
        windows = windows or [(date(default_year, 1, 1), date(default_year + 1, 1, 1))]
        requests_to_run: list[tuple[str, str, date, date]] = []
        for start, end in self._unique_windows(windows):
            for topic in SEARCH_TOPICS:
                query_start = start - timedelta(days=1)
                query = (
                    f'Lamongan ({topic}) after:{query_start.isoformat()} '
                    f'before:{end.isoformat()}'
                )
                requests_to_run.append(("google", query, start, end))
                requests_to_run.append(("bing", query, start, end))

        candidates: list[NewsCandidate] = []
        total_requests = len(requests_to_run)
        completed = 0
        with ThreadPoolExecutor(max_workers=DISCOVERY_WORKERS) as executor:
            futures = {
                executor.submit(self._search, provider, query): (provider, start, end)
                for provider, query, start, end in requests_to_run
            }
            for future in as_completed(futures):
                provider, start, end = futures[future]
                completed += 1
                try:
                    results = future.result()
                except Exception as exc:
                    logger.warning("%s discovery worker failed: %s", provider, exc)
                    results = []
                batch = [
                    candidate
                    for candidate in results
                    if start <= candidate.published_at.date() < end
                ]
                candidates.extend(batch)
                if on_batch:
                    on_batch(self._deduplicate(batch), completed, total_requests)

        return self._deduplicate(candidates)[:MAX_CANDIDATES]

    @staticmethod
    def _unique_windows(windows: list[DateWindow]) -> list[DateWindow]:
        valid = {
            (start, end)
            for start, end in windows
            if start < end and start.year >= START_YEAR
        }
        return sorted(valid)

    def _search(self, provider: str, query: str) -> list[NewsCandidate]:
        if provider == "google":
            return self._google_news(query)
        return self._bing_news(query)

    def _fetch_feed(self, url: str) -> Iterable[Mapping[str, Any]]:
        try:
            with build_session() as session:
                response = session.get(url, timeout=REQUEST_TIMEOUT)
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
        return [
            candidate
            for entry in self._fetch_feed(url)
            if (candidate := self._candidate_from_entry(entry, provider="google"))
        ]

    def _bing_news(self, query: str) -> list[NewsCandidate]:
        url = f"https://www.bing.com/news/search?q={quote_plus(query)}&format=rss&mkt=id-ID"
        return [
            candidate
            for entry in self._fetch_feed(url)
            if (candidate := self._candidate_from_entry(entry, provider="bing"))
        ]

    def _candidate_from_entry(
        self,
        entry: Mapping[str, Any],
        provider: str,
    ) -> NewsCandidate | None:
        published_at = parse_feed_date(entry)
        if published_at is None or published_at.year < START_YEAR:
            return None

        title = clean_text(entry.get("title", ""))
        summary_html = entry.get("summary", "") or entry.get("description", "")
        summary = clean_text(summary_html)
        url = canonicalize_url(entry.get("link", ""))

        if provider == "google":
            publisher_url = self._publisher_url_from_summary(str(summary_html))
            if publisher_url:
                url = publisher_url

        source = ""
        source_data = entry.get("source")
        if isinstance(source_data, Mapping):
            source = clean_text(source_data.get("title", ""))
        elif source_data:
            source = clean_text(source_data)
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
    def _deduplicate(candidates: list[NewsCandidate]) -> list[NewsCandidate]:
        by_url: dict[str, NewsCandidate] = {}
        for candidate in sorted(candidates, key=lambda item: item.published_at, reverse=True):
            existing = by_url.get(candidate.url)
            if existing is None or len(candidate.summary) > len(existing.summary):
                by_url[candidate.url] = candidate

        by_title: dict[str, NewsCandidate] = {}
        for candidate in by_url.values():
            key = title_fingerprint(candidate.title)
            existing = by_title.get(key)
            if existing is None or len(candidate.summary) > len(existing.summary):
                by_title[key] = candidate
        return sorted(by_title.values(), key=lambda item: item.published_at, reverse=True)

    @staticmethod
    def _publisher_url_from_summary(summary_html: str) -> str:
        soup = BeautifulSoup(summary_html, "html.parser")
        for anchor in soup.find_all("a", href=True):
            url = canonicalize_url(str(anchor["href"]))
            if url and "news.google.com" not in urlparse(url).netloc.casefold():
                return url
        return ""
