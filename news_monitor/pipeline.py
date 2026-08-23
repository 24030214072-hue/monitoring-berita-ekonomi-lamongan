import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass

from .classifier import NewsClassifier
from .config import MAX_ARTICLES_TO_ANALYZE, TARGET_YEAR
from .discovery import RSSDiscovery
from .extractor import ArticleExtractor
from .models import NewsArticle, NewsCandidate
from .repository import NewsRepository
from .text import normalize_text, title_fingerprint

logger = logging.getLogger(__name__)
ProgressCallback = Callable[[int, int, str], None]


@dataclass(slots=True)
class PipelineReport:
    discovered: int = 0
    analyzed: int = 0
    accepted: int = 0
    saved: int = 0
    removed: int = 0
    ai_classified: int = 0
    fallback_classified: int = 0
    ai_error: str = ""


class NewsPipeline:
    def __init__(
        self,
        repository: NewsRepository,
        classifier: NewsClassifier,
        discovery: RSSDiscovery | None = None,
        extractor: ArticleExtractor | None = None,
    ) -> None:
        self.repository = repository
        self.classifier = classifier
        self.discovery = discovery or RSSDiscovery()
        self.extractor = extractor or ArticleExtractor()

    def run(self, progress: ProgressCallback | None = None) -> PipelineReport:
        report = PipelineReport()
        candidates = self.discovery.discover()
        report.discovered = len(candidates)
        if not candidates:
            return report

        candidates = candidates[:MAX_ARTICLES_TO_ANALYZE]
        extracted_articles = self._extract_parallel(candidates, progress)
        accepted: list[NewsArticle] = []
        total = len(candidates)
        prepared = [
            (
                candidate,
                *extracted_articles.get(
                    title_fingerprint(candidate.title),
                    (candidate.url, candidate.summary),
                ),
            )
            for candidate in candidates
        ]
        prepared = [
            item
            for item in prepared
            if len(normalize_text(item[2])) >= 200
        ]
        analyses = self.classifier.classify_many(
            [(candidate.title, content) for candidate, _, content in prepared]
        )
        report.ai_classified = sum(
            result.is_economic and result.source == "gemini"
            for result in analyses
        )
        report.fallback_classified = sum(
            result.is_economic and result.source != "gemini"
            for result in analyses
        )

        for index, ((candidate, resolved_url, content), analysis) in enumerate(
            zip(prepared, analyses),
            start=1,
        ):
            if progress:
                progress(index, total, f"Menganalisis: {candidate.title[:80]}")
            report.analyzed += 1
            if not analysis.is_economic or candidate.published_at.year != TARGET_YEAR:
                continue
            accepted.append(
                NewsArticle(
                    published_at=candidate.published_at,
                    media=candidate.media,
                    title=candidate.title,
                    issue=analysis.issue,
                    sector=analysis.sector,
                    summary=analysis.summary,
                    url=resolved_url,
                    content=content,
                    reason=analysis.reason,
                    fingerprint=title_fingerprint(candidate.title),
                )
            )

        accepted = self._deduplicate_similar(accepted)
        report.accepted = len(accepted)
        accepted_fingerprints = {article.fingerprint for article in accepted}
        discovered_fingerprints = {
            title_fingerprint(candidate.title)
            for candidate in candidates
        }
        report.removed = self.repository.delete_by_fingerprints(
            discovered_fingerprints - accepted_fingerprints
        )
        report.saved = self.repository.upsert(accepted)
        report.ai_error = self.classifier.last_error
        return report

    def _extract_parallel(
        self,
        candidates: list[NewsCandidate],
        progress: ProgressCallback | None,
    ) -> dict[str, tuple[str, str]]:
        extracted_articles: dict[str, tuple[str, str]] = {}
        total = len(candidates)
        with ThreadPoolExecutor(max_workers=6) as executor:
            futures = {executor.submit(self.extractor.extract, candidate): candidate for candidate in candidates}
            for index, future in enumerate(as_completed(futures), start=1):
                candidate = futures[future]
                try:
                    extracted_articles[title_fingerprint(candidate.title)] = future.result()
                except Exception as exc:
                    logger.info("Extractor worker failed: %s", exc)
                    extracted_articles[title_fingerprint(candidate.title)] = (
                        candidate.url,
                        candidate.summary,
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
