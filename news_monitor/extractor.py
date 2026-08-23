import logging
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from .config import ARTICLE_MAX_CHARS, REQUEST_TIMEOUT
from .http import build_session
from .models import ExtractionResult, NewsCandidate
from .resolver import GoogleNewsResolver
from .text import clean_text

logger = logging.getLogger(__name__)

CONTENT_SELECTORS = (
    "article",
    "main article",
    "[itemprop='articleBody']",
    ".article-content",
    ".article__body",
    ".detail__body-text",
    ".read__content",
    ".post-content",
    ".entry-content",
)


class ArticleExtractor:
    def __init__(self) -> None:
        self.session = build_session()
        self.resolver = GoogleNewsResolver()

    def extract(self, candidate: NewsCandidate) -> ExtractionResult:
        resolved_url = self.resolver.resolve(candidate.url)
        if not resolved_url:
            return ExtractionResult(candidate.url, error="Tautan penerbit tidak dapat diselesaikan.")
        try:
            response = self.session.get(resolved_url, timeout=REQUEST_TIMEOUT, allow_redirects=True)
            response.raise_for_status()
            content_type = response.headers.get("content-type", "")
            if "html" not in content_type.casefold():
                return ExtractionResult(resolved_url, error="Halaman penerbit bukan HTML.")
            text = self._extract_html(response.text)
            if len(text) < 200:
                return ExtractionResult(resolved_url, error="Isi artikel kurang dari 200 karakter.")
            return ExtractionResult(
                resolved_url=resolved_url,
                content=text[:ARTICLE_MAX_CHARS],
                success=True,
            )
        except Exception as exc:
            logger.info("Article extraction failed for %s: %s", resolved_url, exc)
            return ExtractionResult(resolved_url, error=str(exc))

    @staticmethod
    def _extract_html(document: str) -> str:
        soup = BeautifulSoup(document, "html.parser")
        for tag in soup.select("script, style, nav, footer, header, aside, form, noscript, iframe"):
            tag.decompose()

        for selector in CONTENT_SELECTORS:
            container = soup.select_one(selector)
            if container:
                paragraphs = [clean_text(node.get_text(" ", strip=True)) for node in container.find_all("p")]
                text = clean_text(" ".join(part for part in paragraphs if part))
                if len(text) >= 120:
                    return text

        paragraphs = [clean_text(node.get_text(" ", strip=True)) for node in soup.find_all("p")]
        text = clean_text(" ".join(part for part in paragraphs if part))
        if text:
            return text

        description = soup.select_one("meta[name='description'], meta[property='og:description']")
        return clean_text(description.get("content", "")) if description else ""
