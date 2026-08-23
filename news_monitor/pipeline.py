import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date
from typing import Protocol

from .classifier import NewsClassifier
from .config import EXTRACTION_WORKERS, MAX_ARTICLES_TO_ANALYZE, START_YEAR
from .discovery import RSSDiscovery
from .extractor import ArticleExtractor
from .models import ExtractionResult, NewsArticle, NewsCandidate
from .repository import NewsRepository
from .text import news_fingerprint, normalize_text

logger = logging.getLogger(__name__)
ProgressCallback = Callable[[int, int, str], None]


class DiscoverySource(Protocol):
    def discover(
        self,
        windows: list[tuple[date, date]],
        on_batch: Callable[[list[NewsCandidate], int, int], None] | None = None,
    ) -> list[NewsCandidate]: ...


class ContentExtractor(Protocol):
    def extract(self, candidate: NewsCandidate) -> ExtractionResult: ...


@dataclass(slots=True)
class PipelineReport:
    discovered: int = 0
    queued: int = 0
    processing: int = 0
    analyzed: int = 0
    accepted: int = 0
    saved: int = 0
    removed: int = 0
    extraction_failed: int = 0
    rejected: int = 0
    ai_classified: int = 0
    fallback_classified: int = 0
    ai_error: str = ""
    search_period: str = ""


class NewsPipeline:
    def __init__(
        self,
        repository: NewsRepository,
        classifier: NewsClassifier,
        discovery: DiscoverySource | None = None,
        extractor: ContentExtractor | None = None,
    ) -> None:
        self.repository = repository
        self.classifier = classifier
        self.discovery = discovery or RSSDiscovery()
        self.extractor = extractor or ArticleExtractor()

    def run(
        self,
        progress: ProgressCallback | None = None,
        search_year: int = START_YEAR,
        search_month: int = 1,
    ) -> PipelineReport:
        report = PipelineReport()
        if search_year < START_YEAR:
            raise ValueError(f"Search year must be {START_YEAR} or later.")
        if not 1 <= search_month <= 12:
            raise ValueError("Search month must be between 1 and 12.")
        existing_queue = self.repository.pending_count(
            year=search_year,
            month=search_month,
        )

        if existing_queue >= MAX_ARTICLES_TO_ANALYZE:
            report.search_period = (
                f"{search_month:02d}/{search_year} — memproses antrean tersimpan"
            )
        else:
            windows = [self._month_window(search_year, search_month)]
            report.search_period = f"{search_month:02d}/{search_year}"

            def save_discovery_batch(
                batch: list[NewsCandidate],
                current: int,
                total: int,
            ) -> None:
                self.repository.upsert_candidates(batch)
                if progress:
                    progress(
                        current,
                        total,
                        f"Mencari sumber berita: {current}/{total}",
                    )

            discovered = self.discovery.discover(windows, save_discovery_batch)
            report.discovered = len(discovered)
            self.repository.upsert_candidates(discovered)

        candidates = self.repository.pending_candidates(
            MAX_ARTICLES_TO_ANALYZE,
            year=search_year,
            month=search_month,
        )
        report.processing = len(candidates)
        if not candidates:
            report.queued = self.repository.pending_count(
                year=search_year,
                month=search_month,
            )
            return report

        extracted = self._extract_parallel(candidates, progress)
        states: dict[str, tuple[str, str]] = {}
        prepared: list[tuple[NewsCandidate, ExtractionResult]] = []
        for candidate in candidates:
            fingerprint = news_fingerprint(candidate.title, candidate.published_at)
            result = extracted.get(fingerprint)
            if result is None or not result.success or len(normalize_text(result.content)) < 200:
                error = result.error if result else "Ekstraksi artikel tidak menghasilkan data."
                states[fingerprint] = ("retry", error)
                report.extraction_failed += 1
                continue
            prepared.append((candidate, result))

        analyses = self.classifier.classify_many(
            [(candidate.title, result.content) for candidate, result in prepared]
        )
        if len(analyses) != len(prepared):
            logger.error("Classifier returned %d results for %d articles", len(analyses), len(prepared))
            analyses = analyses[:len(prepared)]
            for candidate, result in prepared[len(analyses):]:
                analyses.append(self.classifier.classify_rules(candidate.title, result.content))

        accepted: list[NewsArticle] = []
        for index, ((candidate, extraction), analysis) in enumerate(
            zip(prepared, analyses),
            start=1,
        ):
            if progress:
                progress(index, len(prepared), f"Menganalisis: {candidate.title[:80]}")
            report.analyzed += 1
            fingerprint = news_fingerprint(candidate.title, candidate.published_at)
            if not analysis.is_economic or candidate.published_at.year != search_year:
                states[fingerprint] = ("rejected", analysis.reason)
                report.rejected += 1
                continue
            if analysis.source == "gemini":
                report.ai_classified += 1
            else:
                report.fallback_classified += 1
            accepted.append(
                NewsArticle(
                    published_at=candidate.published_at,
                    media=candidate.media,
                    title=candidate.title,
                    issue=analysis.issue,
                    sector=analysis.sector,
                    summary=analysis.summary,
                    url=extraction.resolved_url,
                    content=extraction.content,
                    reason=analysis.reason,
                    fingerprint=fingerprint,
                )
            )

        deduplicated = self._deduplicate_similar(accepted)
        kept = {article.fingerprint for article in deduplicated}
        for article in accepted:
            states[article.fingerprint] = (
                ("accepted", "") if article.fingerprint in kept
                else ("duplicate", "Berita serupa sudah dipilih dari sumber lain.")
            )

        report.accepted = len(deduplicated)
        report.saved = self.repository.upsert(deduplicated)
        self.repository.mark_candidates(states)
        report.queued = self.repository.pending_count(
            year=search_year,
            month=search_month,
        )
        report.ai_error = self.classifier.last_error
        return report

    @staticmethod
    def _month_window(year: int, month: int) -> tuple[date, date]:
        start = date(year, month, 1)
        end = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
        return start, end

    def _extract_parallel(
        self,
        candidates: list[NewsCandidate],
        progress: ProgressCallback | None,
    ) -> dict[str, ExtractionResult]:
        extracted_articles: dict[str, ExtractionResult] = {}
        total = len(candidates)
        with ThreadPoolExecutor(max_workers=EXTRACTION_WORKERS) as executor:
            futures = {executor.submit(self.extractor.extract, candidate): candidate for candidate in candidates}
            for index, future in enumerate(as_completed(futures), start=1):
                candidate = futures[future]
                fingerprint = news_fingerprint(candidate.title, candidate.published_at)
                try:
                    extracted_articles[fingerprint] = future.result()
                except Exception as exc:
                    logger.info("Extractor worker failed: %s", exc)
                    extracted_articles[fingerprint] = ExtractionResult(
                        candidate.url,
                        error=str(exc),
                    )
                if progress:
                    progress(index, total, f"Mengambil artikel: {candidate.title[:80]}")
        return extracted_articles

    @staticmethod
    def _deduplicate_similar(articles: list[NewsArticle]) -> list[NewsArticle]:
        kept: list[NewsArticle] = []
        token_sets: list[set[str]] = []
        for article in sorted(articles, key=lambda item: len(item.content), reverse=True):
            tokens = set(normalize_text(article.title).split())
            duplicate = False
            for existing in token_sets:
                union = tokens | existing
                similarity = len(tokens & existing) / len(union) if union else 0
                if similarity >= 0.72:
                    duplicate = True
                    break
            if not duplicate:
                kept.append(article)
                token_sets.append(tokens)
        return sorted(kept, key=lambda item: item.published_at, reverse=True)
