from dataclasses import dataclass
from datetime import datetime


@dataclass(slots=True)
class NewsCandidate:
    published_at: datetime
    media: str
    title: str
    url: str
    summary: str = ""


@dataclass(slots=True)
class AnalysisResult:
    is_economic: bool
    issue: str = ""
    sector: str = ""
    summary: str = ""
    reason: str = ""
    source: str = "rules"


@dataclass(slots=True)
class NewsArticle:
    published_at: datetime
    media: str
    title: str
    issue: str
    sector: str
    summary: str
    url: str
    content: str
    reason: str
    fingerprint: str
