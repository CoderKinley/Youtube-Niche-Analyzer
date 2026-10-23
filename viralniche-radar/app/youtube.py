"""Bounded YouTube Data API collection; no scraping or background polling."""

import asyncio
from datetime import datetime, timedelta, timezone

import httpx
import isodate

from .models import Channel, Video


class YouTubeError(Exception):
    def __init__(self, message: str, status_code: int = 502):
        super().__init__(message)
        self.status_code = status_code


def parse_video(item: dict) -> Video | None:
    snippet, stats = item.get("snippet", {}), item.get("statistics", {})
    if "publishedAt" not in snippet or "viewCount" not in stats:
        return None  # Deleted, private, or otherwise unmeasurable videos.
    thumbnails = snippet.get("thumbnails", {})
    thumbnail = next((thumbnails[k]["url"] for k in ("medium", "high", "default") if k in thumbnails), "")
    duration = isodate.parse_duration(item.get("contentDetails", {}).get("duration", "PT0S"))
    return Video(
        video_id=item["id"], channel_id=snippet["channelId"], title=snippet["title"],
        published_at=datetime.fromisoformat(snippet["publishedAt"].replace("Z", "+00:00")),
        views=int(stats["viewCount"]),
        likes=int(stats["likeCount"]) if "likeCount" in stats else None,
        comments=int(stats["commentCount"]) if "commentCount" in stats else None,
        duration_seconds=int(duration.total_seconds()), thumbnail_url=thumbnail,
    )


class YouTubeClient:
    def __init__(self, api_key: str, client: httpx.AsyncClient):
        self.api_key = api_key
        self.client = client
        self.limit = asyncio.Semaphore(5)
        self.request_count = 0

    async def get(self, resource: str, **params) -> dict:
        async with self.limit:
            try:
                self.request_count += 1
                response = await self.client.get(
                    f"https://www.googleapis.com/youtube/v3/{resource}",
                    params=params, headers={"X-Goog-Api-Key": self.api_key},
                )
            except httpx.TimeoutException:
                raise YouTubeError("YouTube timed out. Please try again.", 504) from None
            except httpx.RequestError:
                raise YouTubeError("Could not connect to YouTube. Check your internet connection.") from None
        if response.is_error:
            try:
                errors = response.json().get("error", {}).get("errors", [])
                reason = errors[0].get("reason", "") if errors else ""
            except (ValueError, AttributeError, IndexError):
                reason = ""
            if reason in {"quotaExceeded", "dailyLimitExceeded", "rateLimitExceeded"} or response.status_code == 429:
                raise YouTubeError("YouTube API quota or rate limit reached. Check your Cloud Console quota.", 429)
            if reason in {"keyInvalid", "accessNotConfigured", "ipRefererBlocked", "forbidden"} or response.status_code in {400, 401, 403}:
                raise YouTubeError("YouTube rejected the API request. Check your key, API access, and key restrictions.", 502)
            if response.status_code == 404:
                raise YouTubeError("This channel's uploads playlist is unavailable.", 404)
            raise YouTubeError("YouTube returned an error. Please try again.")
        try:
            return response.json()
        except ValueError:
            raise YouTubeError("YouTube returned an unreadable response.") from None

    async def videos(self, ids: list[str]) -> list[Video]:
        ids = list(dict.fromkeys(ids))
        async def batch(chunk):
            data = await self.get("videos", part="snippet,statistics,contentDetails", id=",".join(chunk))
            return [video for item in data.get("items", []) if (video := parse_video(item)) is not None]
        batches = await asyncio.gather(*(batch(ids[i:i + 50]) for i in range(0, len(ids), 50)))
        return [v for group in batches for v in group]

    async def channels(self, channel_ids: list[str]) -> dict[str, Channel]:
        channel_ids = list(dict.fromkeys(channel_ids))
        channel_pages = await asyncio.gather(*(self.get("channels", part="snippet,statistics,contentDetails",
                                                       id=",".join(channel_ids[i:i + 50]))
                                               for i in range(0, len(channel_ids), 50)))
        channels = {}
        for item in (item for page in channel_pages for item in page.get("items", [])):
            stats = item.get("statistics", {})
            hidden = stats.get("hiddenSubscriberCount", False) or "subscriberCount" not in stats
            channels[item["id"]] = Channel(
                channel_id=item["id"], title=item["snippet"]["title"],
                subscribers=None if hidden else int(stats["subscriberCount"]), subscribers_hidden=hidden,
                uploads_playlist_id=item.get("contentDetails", {}).get("relatedPlaylists", {}).get("uploads", ""),
            )
        return channels

    async def uploads(self, channels: dict[str, Channel], known: dict[str, Video] | None = None,
                      max_results: int = 50) -> tuple[dict[str, list[Video]], list[str]]:
        warnings = []

        async def upload_ids(channel: Channel) -> tuple[str, list[str]]:
            if not channel.uploads_playlist_id:
                warnings.append(f"No uploads playlist for {channel.title}; its baseline is unavailable.")
                return channel.channel_id, []
            try:
                playlist = await self.get("playlistItems", part="contentDetails",
                                          playlistId=channel.uploads_playlist_id, maxResults=max_results)
            except YouTubeError as error:
                if error.status_code != 404:
                    raise
                warnings.append(f"Uploads unavailable for {channel.title}; its baseline is unavailable.")
                return channel.channel_id, []
            return channel.channel_id, [i["contentDetails"]["videoId"] for i in playlist.get("items", [])
                                        if "videoId" in i.get("contentDetails", {})]

        playlist_ids = dict(await asyncio.gather(*(upload_ids(c) for c in channels.values())))
        all_ids = list(dict.fromkeys(v for group in playlist_ids.values() for v in group))
        known = dict(known or {})
        known.update({v.video_id: v for v in await self.videos([v for v in all_ids if v not in known])})
        uploads = {cid: [known[i] for i in ids if i in known and known[i].channel_id == cid]
                   for cid, ids in playlist_ids.items()}
        return uploads, warnings

    async def collect(self, query: str, days: int) -> tuple[list[Video], dict[str, Channel], dict[str, list[Video]], list[str]]:
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(days=days)
        pages = await asyncio.gather(*(self.get(
            "search", part="snippet", type="video", q=query, maxResults=50,
            order=order, publishedAfter=cutoff.isoformat(), publishedBefore=now.isoformat(),
        ) for order in ("viewCount", "date")))
        ids = list(dict.fromkeys(i["id"]["videoId"] for data in pages for i in data.get("items", [])
                                if "videoId" in i.get("id", {})))
        candidates = [v for v in await self.videos(ids) if cutoff <= v.published_at <= now]
        if not candidates:
            return [], {}, {}, []
        channel_ids = list(dict.fromkeys(v.channel_id for v in candidates))
        channels = await self.channels(channel_ids)
        uploads, warnings = await self.uploads(channels, {v.video_id: v for v in candidates})
        if len(channels) < len(channel_ids):
            warnings.append("Some channels were unavailable; their subscriber counts and baselines are unknown.")
        return candidates, channels, uploads, warnings
