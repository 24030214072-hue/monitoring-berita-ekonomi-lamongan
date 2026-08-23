import hashlib
import html
import re
from collections.abc import Mapping
from datetime import datetime
from email.utils import parsedate_to_datetime
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from bs4 import BeautifulSoup

TRACKING_PARAMETERS = {
    "fbclid",
    "gclid",
    "ocid",
    "ref",
    "source",
    "utm_campaign",
    "utm_content",
    "utm_medium",
    "utm_source",
    "utm_term",
}


def clean_text(value: object) -> str:
    if value is None:
        return ""
    text = BeautifulSoup(html.unescape(str(value)), "html.parser").get_text(" ")
    return re.sub(r"\s+", " ", text).strip()


def normalize_text(value: object) -> str:
    text = clean_text(value).casefold()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def title_fingerprint(title: str) -> str:
    return hashlib.sha256(normalize_text(title).encode("utf-8")).hexdigest()


def canonicalize_url(url: str) -> str:
    if not url:
        return ""
    parsed = urlparse(url.strip())
    if parsed.scheme not in {"http", "https"}:
        return ""
    query = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if key.casefold() not in TRACKING_PARAMETERS
        and not key.casefold().startswith("utm_")
    ]
    return urlunparse(
        (parsed.scheme.casefold(), parsed.netloc.casefold(), parsed.path, "", urlencode(query), "")
    )


def parse_feed_date(entry: Mapping[str, object]) -> datetime | None:
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if parsed:
        return datetime(*parsed[:6])

    raw = entry.get("published", "") or entry.get("updated", "")
    if not raw:
        return None
    try:
        value = parsedate_to_datetime(raw)
        return value.replace(tzinfo=None) if value.tzinfo else value
    except (TypeError, ValueError, OverflowError):
        return None


def truncate_words(text: str, limit: int = 80) -> str:
    words = clean_text(text).split()
    if len(words) <= limit:
        return " ".join(words)
    return " ".join(words[:limit]).rstrip(".,;:") + "…"


def extractive_summary(title: str, content: str, limit: int = 80) -> str:
    cleaned_title = normalize_text(title)
    sentences = re.split(r"(?<=[.!?])\s+", clean_text(content))
    selected: list[str] = []

    for sentence in sentences:
        sentence = clean_text(sentence)
        normalized = normalize_text(sentence)
        if len(sentence.split()) < 6 or not normalized:
            continue
        title_words = set(cleaned_title.split())
        sentence_words = set(normalized.split())
        overlap = len(title_words & sentence_words) / max(len(title_words), 1)
        if overlap >= 0.85 and len(sentence_words) <= len(title_words) + 5:
            continue
        selected.append(sentence)
        if len(selected) == 3:
            break

    if not selected:
        return truncate_words(clean_text(content), limit)
    return truncate_words(" ".join(selected), limit)


def hostname_label(url: str) -> str:
    host = urlparse(url).netloc.casefold().removeprefix("www.")
    return host or "Media tidak diketahui"
