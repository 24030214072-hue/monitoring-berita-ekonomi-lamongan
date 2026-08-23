import os
import sqlite3
from collections.abc import Iterable, Iterator, Mapping
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import cast

import pandas as pd

from .config import (
    ALL_COLUMNS,
    DATABASE_PATH,
    LEGACY_CSV_PATH,
    MAX_CANDIDATE_ATTEMPTS,
    START_YEAR,
    UI_COLUMNS,
)
from .models import NewsArticle, NewsCandidate
from .text import news_fingerprint


class NewsRepository:
    def __init__(
        self,
        database_path: Path = DATABASE_PATH,
        legacy_csv_path: Path | None = LEGACY_CSV_PATH,
    ) -> None:
        self.database_path = database_path
        self.legacy_csv_path = legacy_csv_path
        self._initialize()
        self._migrate_legacy_csv()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.database_path, timeout=20)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS news_articles (
                    fingerprint TEXT PRIMARY KEY,
                    published_at TEXT NOT NULL,
                    media TEXT NOT NULL,
                    title TEXT NOT NULL,
                    issue TEXT NOT NULL,
                    sector TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    url TEXT NOT NULL,
                    content TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_news_articles_date ON news_articles(published_at)"
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS news_candidates (
                    fingerprint TEXT PRIMARY KEY,
                    published_at TEXT NOT NULL,
                    media TEXT NOT NULL,
                    title TEXT NOT NULL,
                    url TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    attempts INTEGER NOT NULL DEFAULT 0,
                    last_error TEXT NOT NULL DEFAULT '',
                    first_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    last_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    last_attempted_at TEXT
                )
                """
            )
            connection.execute(
                """
                UPDATE news_articles
                SET fingerprint=substr(published_at, 1, 4) || ':' || fingerprint
                WHERE instr(fingerprint, ':')=0
                """
            )
            connection.execute(
                """
                UPDATE news_candidates
                SET fingerprint=substr(published_at, 1, 4) || ':' || fingerprint
                WHERE instr(fingerprint, ':')=0
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_news_candidates_queue "
                "ON news_candidates(status, attempts, published_at)"
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS crawl_state (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
                """
            )

    def upsert(self, articles: Iterable[NewsArticle]) -> int:
        rows = [
            (
                news_fingerprint(item.title, item.published_at),
                item.published_at.isoformat(timespec="seconds"),
                item.media,
                item.title,
                item.issue,
                item.sector,
                item.summary,
                item.url,
                item.content,
                item.reason,
            )
            for item in articles
            if item.published_at.year >= START_YEAR
        ]
        if not rows:
            return 0
        with self._connect() as connection:
            connection.executemany(
                """
                INSERT INTO news_articles (
                    fingerprint, published_at, media, title, issue, sector,
                    summary, url, content, reason
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(fingerprint) DO UPDATE SET
                    published_at=excluded.published_at,
                    media=excluded.media,
                    title=excluded.title,
                    issue=excluded.issue,
                    sector=excluded.sector,
                    summary=excluded.summary,
                    url=excluded.url,
                    content=excluded.content,
                    reason=excluded.reason,
                    updated_at=CURRENT_TIMESTAMP
                """,
                rows,
            )
        return len(rows)

    def upsert_candidates(self, candidates: Iterable[NewsCandidate]) -> int:
        rows = [
            (
                news_fingerprint(item.title, item.published_at),
                item.published_at.isoformat(timespec="seconds"),
                item.media,
                item.title,
                item.url,
                item.summary,
            )
            for item in candidates
            if item.published_at.year >= START_YEAR
        ]
        if not rows:
            return 0
        with self._connect() as connection:
            connection.executemany(
                """
                INSERT INTO news_candidates (
                    fingerprint, published_at, media, title, url, summary
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(fingerprint) DO UPDATE SET
                    published_at=excluded.published_at,
                    media=excluded.media,
                    title=excluded.title,
                    url=excluded.url,
                    summary=CASE
                        WHEN length(excluded.summary) > length(news_candidates.summary)
                        THEN excluded.summary ELSE news_candidates.summary END,
                    last_seen_at=CURRENT_TIMESTAMP
                """,
                rows,
            )
            connection.execute(
                """
                UPDATE news_candidates
                SET status='accepted'
                WHERE fingerprint IN (SELECT fingerprint FROM news_articles)
                """
            )
        return len(rows)

    def pending_candidates(
        self,
        limit: int,
        year: int = START_YEAR,
        month: int | None = None,
    ) -> list[NewsCandidate]:
        conditions = ["status='pending'", "attempts < ?"]
        parameters: list[object] = [MAX_CANDIDATE_ATTEMPTS]
        if month is not None:
            start, end = self._month_range(year, month)
            conditions.extend(["published_at >= ?", "published_at < ?"])
            parameters.extend([start, end])
        else:
            conditions.extend(["published_at >= ?", "published_at < ?"])
            parameters.extend([f"{year}-01-01", f"{year + 1}-01-01"])
        parameters.append(limit)
        query = f"""
            SELECT published_at, media, title, url, summary, attempts
            FROM news_candidates
            WHERE {' AND '.join(conditions)}
            ORDER BY attempts ASC, published_at ASC
            LIMIT ?
        """
        with self._connect() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return [
            NewsCandidate(
                published_at=datetime.fromisoformat(row["published_at"]),
                media=row["media"],
                title=row["title"],
                url=row["url"],
                summary=row["summary"],
                attempts=row["attempts"],
            )
            for row in rows
        ]

    def mark_candidates(self, states: Mapping[str, tuple[str, str]]) -> None:
        if not states:
            return
        with self._connect() as connection:
            for fingerprint, (status, error) in states.items():
                if status == "retry":
                    connection.execute(
                        """
                        UPDATE news_candidates
                        SET attempts=attempts + 1,
                            status=CASE WHEN attempts + 1 >= ? THEN 'failed' ELSE 'pending' END,
                            last_error=?, last_attempted_at=CURRENT_TIMESTAMP
                        WHERE fingerprint=?
                        """,
                        (MAX_CANDIDATE_ATTEMPTS, error, fingerprint),
                    )
                else:
                    connection.execute(
                        """
                        UPDATE news_candidates
                        SET attempts=attempts + 1, status=?, last_error=?,
                            last_attempted_at=CURRENT_TIMESTAMP
                        WHERE fingerprint=?
                        """,
                        (status, error, fingerprint),
                    )

    def pending_count(
        self,
        year: int = START_YEAR,
        month: int | None = None,
    ) -> int:
        conditions = ["status='pending'", "attempts < ?"]
        parameters: list[object] = [MAX_CANDIDATE_ATTEMPTS]
        if month is not None:
            start, end = self._month_range(year, month)
            conditions.extend(["published_at >= ?", "published_at < ?"])
            parameters.extend([start, end])
        else:
            conditions.extend(["published_at >= ?", "published_at < ?"])
            parameters.extend([f"{year}-01-01", f"{year + 1}-01-01"])
        query = f"SELECT COUNT(*) FROM news_candidates WHERE {' AND '.join(conditions)}"
        with self._connect() as connection:
            return int(connection.execute(query, parameters).fetchone()[0])

    def candidate_status_counts(
        self,
        year: int = START_YEAR,
        month: int | None = None,
    ) -> dict[str, int]:
        conditions = ["published_at >= ?", "published_at < ?"]
        parameters: list[object] = [f"{year}-01-01", f"{year + 1}-01-01"]
        if month is not None:
            start, end = self._month_range(year, month)
            conditions = ["published_at >= ?", "published_at < ?"]
            parameters = [start, end]
        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        query = (
            "SELECT status, COUNT(*) AS total FROM news_candidates "
            f"{where_clause} GROUP BY status"
        )
        with self._connect() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return {str(row["status"]): int(row["total"]) for row in rows}

    @staticmethod
    def _month_range(year: int, month: int) -> tuple[str, str]:
        if year < START_YEAR:
            raise ValueError(f"Year must be {START_YEAR} or later.")
        if not 1 <= month <= 12:
            raise ValueError("Month must be between 1 and 12.")
        start = f"{year}-{month:02d}-01"
        end = (
            f"{year + 1}-01-01"
            if month == 12
            else f"{year}-{month + 1:02d}-01"
        )
        return start, end

    def discovery_month(self, maximum_month: int) -> int:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT value FROM crawl_state WHERE key='backfill_month'"
            ).fetchone()
        if not row:
            return 1
        try:
            return min(max(int(row["value"]), 1), maximum_month)
        except (TypeError, ValueError):
            return 1

    def advance_discovery_month(self, current_month: int, maximum_month: int) -> None:
        next_month = current_month + 1 if current_month < maximum_month else 1
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO crawl_state(key, value) VALUES('backfill_month', ?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value
                """,
                (str(next_month),),
            )

    def delete_by_fingerprints(self, fingerprints: Iterable[str]) -> int:
        values = list(set(fingerprints))
        if not values:
            return 0
        placeholders = ",".join("?" for _ in values)
        with self._connect() as connection:
            cursor = connection.execute(
                f"DELETE FROM news_articles WHERE fingerprint IN ({placeholders})",
                values,
            )
            return cursor.rowcount

    def load_dataframe(self, year: int = START_YEAR) -> pd.DataFrame:
        query = """
            SELECT
                published_at AS 'Tanggal Berita',
                media AS 'Media',
                title AS 'Judul Berita',
                issue AS 'Isu Ekonomi',
                sector AS 'Sektor',
                summary AS 'Ringkasan Berita',
                url AS 'Link Berita',
                content AS 'Isi Berita',
                reason AS 'Alasan AI'
            FROM news_articles
            WHERE published_at >= ? AND published_at < ?
            ORDER BY published_at DESC
        """
        with self._connect() as connection:
            frame = pd.read_sql_query(
                query,
                connection,
                params=[f"{year}-01-01", f"{year + 1}-01-01"],
            )
        for column in ALL_COLUMNS:
            if column not in frame.columns:
                frame[column] = ""
        return cast(pd.DataFrame, frame.loc[:, ALL_COLUMNS].copy())

    def clear(self, year: int | None = None) -> None:
        with self._connect() as connection:
            if year is None:
                connection.execute("DELETE FROM news_articles")
                connection.execute("DELETE FROM news_candidates")
                connection.execute("DELETE FROM crawl_state")
            else:
                start, end = f"{year}-01-01", f"{year + 1}-01-01"
                connection.execute(
                    "DELETE FROM news_articles WHERE published_at >= ? AND published_at < ?",
                    (start, end),
                )
                connection.execute(
                    "DELETE FROM news_candidates WHERE published_at >= ? AND published_at < ?",
                    (start, end),
                )
        if year is None and self.legacy_csv_path and self.legacy_csv_path.exists():
            self.legacy_csv_path.unlink()

    def export_legacy_csv(self) -> None:
        if self.legacy_csv_path is None:
            return
        frame = self.load_dataframe()[UI_COLUMNS]
        temporary = self.legacy_csv_path.with_suffix(".csv.tmp")
        frame.to_csv(temporary, index=False, encoding="utf-8-sig")
        os.replace(temporary, self.legacy_csv_path)

    def _migrate_legacy_csv(self) -> None:
        if self.legacy_csv_path is None or not self.legacy_csv_path.exists():
            return
        with self._connect() as connection:
            count = connection.execute("SELECT COUNT(*) FROM news_articles").fetchone()[0]
        if count:
            return
        try:
            frame = pd.read_csv(self.legacy_csv_path)
        except Exception:
            return
        if frame.empty or not set(UI_COLUMNS).issubset(frame.columns):
            return

        articles: list[NewsArticle] = []
        for _, row in frame.iterrows():
            parsed = pd.to_datetime(row["Tanggal Berita"], errors="coerce")
            if not isinstance(parsed, pd.Timestamp) or pd.isna(parsed):
                continue
            published = parsed.to_pydatetime()
            if published.year < START_YEAR:
                continue
            title = str(row["Judul Berita"])
            articles.append(
                NewsArticle(
                    published,
                    str(row["Media"]),
                    title,
                    str(row["Isu Ekonomi"]),
                    str(row["Sektor"]),
                    str(row["Ringkasan Berita"]),
                    str(row["Link Berita"]),
                    "",
                    "Migrasi data lama",
                    news_fingerprint(title, published),
                )
            )
        self.upsert(articles)
