import os
import sqlite3
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from pathlib import Path

import pandas as pd

from .config import ALL_COLUMNS, DATABASE_PATH, LEGACY_CSV_PATH, TARGET_YEAR, UI_COLUMNS
from .models import NewsArticle


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

    def upsert(self, articles: Iterable[NewsArticle]) -> int:
        rows = [
            (
                item.fingerprint,
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
            if item.published_at.year == TARGET_YEAR
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

    def load_dataframe(self) -> pd.DataFrame:
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
            WHERE substr(published_at, 1, 4) = ?
            ORDER BY published_at DESC
        """
        with self._connect() as connection:
            frame = pd.read_sql_query(query, connection, params=[str(TARGET_YEAR)])
        for column in ALL_COLUMNS:
            if column not in frame.columns:
                frame[column] = ""
        return frame[ALL_COLUMNS]

    def clear(self) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM news_articles")
        if self.legacy_csv_path and self.legacy_csv_path.exists():
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
        required = set(UI_COLUMNS)
        if frame.empty or not required.issubset(frame.columns):
            return
        articles: list[NewsArticle] = []
        from .text import title_fingerprint

        for _, row in frame.iterrows():
            published = pd.to_datetime(row["Tanggal Berita"], errors="coerce")
            if pd.isna(published) or published.year != TARGET_YEAR:
                continue
            title = str(row["Judul Berita"])
            articles.append(
                NewsArticle(
                    published.to_pydatetime(),
                    str(row["Media"]),
                    title,
                    str(row["Isu Ekonomi"]),
                    str(row["Sektor"]),
                    str(row["Ringkasan Berita"]),
                    str(row["Link Berita"]),
                    "",
                    "Migrasi data lama",
                    title_fingerprint(title),
                )
            )
        self.upsert(articles)
