"""Small, dependency-free records shared by the collector and scoring code."""

from dataclasses import dataclass
from datetime import datetime


@dataclass
class Video:
    video_id: str
    channel_id: str
    title: str
    published_at: datetime
    views: int
    likes: int | None = None
    comments: int | None = None
    duration_seconds: int = 0
    thumbnail_url: str = ""


@dataclass
class Channel:
    channel_id: str
    title: str
    subscribers: int | None = None
    subscribers_hidden: bool = True
    uploads_playlist_id: str = ""
