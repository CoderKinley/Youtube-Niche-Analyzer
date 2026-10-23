"""Local research snapshots and explicitly requested related-channel reports."""

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from .models import Channel

SCHEMA = """
CREATE TABLE IF NOT EXISTS videos (
    video_id TEXT PRIMARY KEY, channel_id TEXT NOT NULL, title TEXT NOT NULL,
    published_at TEXT NOT NULL, duration_seconds INTEGER, thumbnail_url TEXT,
    views INTEGER, likes INTEGER, comments INTEGER, first_seen_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS channels (
    channel_id TEXT PRIMARY KEY, title TEXT NOT NULL, subscribers INTEGER,
    subscribers_hidden INTEGER NOT NULL DEFAULT 0, uploads_playlist_id TEXT,
    median_recent_views REAL
);
CREATE TABLE IF NOT EXISTS searches (
    id INTEGER PRIMARY KEY AUTOINCREMENT, query TEXT NOT NULL,
    days INTEGER NOT NULL, searched_at TEXT NOT NULL, result_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS search_videos (
    search_id INTEGER NOT NULL REFERENCES searches(id),
    video_id TEXT NOT NULL REFERENCES videos(video_id), breakout_score REAL,
    outlier_multiplier REAL, avg_views_per_hour REAL,
    PRIMARY KEY(search_id, video_id)
);
CREATE TABLE IF NOT EXISTS related_reports (
    channel_id TEXT NOT NULL, format TEXT NOT NULL, reference_key TEXT NOT NULL,
    searched_at TEXT NOT NULL, result_json TEXT NOT NULL,
    PRIMARY KEY(channel_id, format)
);
"""


class Database:
    def __init__(self, path: Path):
        self.path = path

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.path, timeout=15)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def initialize(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            connection.executescript(SCHEMA)

    def save(self, result: dict, channels: dict[str, Channel]) -> dict:
        with self.connect() as connection:
            for channel in channels.values():
                baselines = [v for v in result["videos"] if v["channel_id"] == channel.channel_id]
                newest = max(baselines, key=lambda v: v["published_at"], default={})
                connection.execute(
                    "INSERT OR REPLACE INTO channels VALUES (?, ?, ?, ?, ?, ?)",
                    (channel.channel_id, channel.title, channel.subscribers, int(channel.subscribers_hidden),
                     channel.uploads_playlist_id, newest.get("channel_baseline")),
                )
            cursor = connection.execute(
                "INSERT INTO searches(query, days, searched_at, result_json) VALUES (?, ?, ?, ?)",
                (result["query"], result["days"], result["searched_at"], "{}"),
            )
            result = {**result, "id": cursor.lastrowid}
            for video in result["videos"]:
                connection.execute(
                    """INSERT INTO videos VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(video_id) DO UPDATE SET channel_id=excluded.channel_id,
                    title=excluded.title, published_at=excluded.published_at,
                    duration_seconds=excluded.duration_seconds, thumbnail_url=excluded.thumbnail_url,
                    views=excluded.views, likes=excluded.likes, comments=excluded.comments""",
                    tuple(video[k] for k in ("video_id", "channel_id", "title", "published_at",
                                            "duration_seconds", "thumbnail_url", "views", "likes", "comments"))
                    + (result["searched_at"],),
                )
                connection.execute(
                    "INSERT INTO search_videos VALUES (?, ?, ?, ?, ?)",
                    (result["id"], video["video_id"], video["breakout_score"],
                     video["outlier_multiplier"], video["avg_views_per_hour"]),
                )
            connection.execute("UPDATE searches SET result_json=? WHERE id=?",
                               (json.dumps(result, ensure_ascii=False, allow_nan=False), result["id"]))
        return result

    def get(self, search_id: int) -> dict | None:
        with self.connect() as connection:
            row = connection.execute("SELECT result_json FROM searches WHERE id=?", (search_id,)).fetchone()
        return json.loads(row["result_json"]) if row else None

    def history(self) -> list[dict]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT id, query, days, searched_at FROM searches ORDER BY id DESC LIMIT 50"
            ).fetchall()
        return [dict(row) for row in rows]

    def observations(self, search_id: int) -> list[dict]:
        """Last 30 earlier overlapping snapshots, using the existing search/video index."""
        with self.connect() as connection:
            rows = connection.execute(
                """SELECT s.result_json FROM searches s WHERE s.id < ? AND EXISTS (
                    SELECT 1 FROM search_videos old JOIN search_videos current
                    ON old.video_id = current.video_id
                    WHERE old.search_id = s.id AND current.search_id = ?)
                    ORDER BY s.id DESC LIMIT 30""", (search_id, search_id)
            ).fetchall()
        return [json.loads(row["result_json"]) for row in rows]

    def saved_snapshots(self):
        """Stream saved research, newest first, to deduplicate channel profiles locally."""
        with self.connect() as connection:
            for row in connection.execute("SELECT result_json FROM searches ORDER BY id DESC"):
                yield json.loads(row["result_json"])

    def related_report(self, reference_key: str, video_format: str) -> dict | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT result_json FROM related_reports WHERE format=? AND (channel_id=? OR reference_key=?) ORDER BY searched_at DESC LIMIT 1",
                (video_format, reference_key, reference_key),
            ).fetchone()
        return json.loads(row["result_json"]) if row else None

    def save_related_report(self, result: dict, reference_key: str):
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO related_reports VALUES (?, ?, ?, ?, ?) ON CONFLICT(channel_id, format) DO UPDATE SET "
                "reference_key=excluded.reference_key, searched_at=excluded.searched_at, result_json=excluded.result_json",
                (result["reference"]["channel_id"], result["format"], reference_key, result["searched_at"],
                 json.dumps(result, ensure_ascii=False, allow_nan=False)),
            )

    def related_history(self) -> list[dict]:
        with self.connect() as connection:
            rows = connection.execute("SELECT channel_id, format, searched_at, json_extract(result_json, '$.reference.title') AS title "
                                      "FROM related_reports ORDER BY searched_at DESC").fetchall()
        return [dict(row) for row in rows]
