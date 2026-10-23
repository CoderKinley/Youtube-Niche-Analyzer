"""Run from the project directory: python -m uvicorn app.main:app."""

import asyncio
import csv
import io
import os
import re
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

import httpx
from dotenv import load_dotenv, set_key
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, SecretStr
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .database import Database
from .analysis import analyze_channels, channel_profiles, sample_statistics
from .related import discover_related, parse_reference, public_profile, resolve_channel, saved_channels
from .keywords import extract_phrases
from .scoring import SCORING_VERSION, compare_niches, format_group, rank_videos, summarize
from .youtube import YouTubeClient, YouTubeError

ROOT = Path(__file__).resolve().parent.parent
DISCLAIMER = "This is a research score, not a prediction that the video will go viral."


class SearchInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    query: str = Field(min_length=2, max_length=120)
    days: int = Field(default=30, ge=1, le=30, strict=True)
    format: Literal["all", "short", "long"] = "all"


class YouTubeKeyInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    api_key: SecretStr


class RelatedInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    reference: str = Field(min_length=2, max_length=200)
    format: Literal["all", "short", "long"] = "short"
    refresh: bool = Field(default=False, strict=True)


def create_app(database_path: Path | None = None, env_path: Path | None = None) -> FastAPI:
    database = Database(database_path or ROOT / "data" / "viralniche.db")
    env_path = env_path or ROOT / ".env"
    load_dotenv(env_path)

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        database.initialize()
        application.state.search_lock = asyncio.Lock()
        yield

    application = FastAPI(title="ViralNiche Radar", lifespan=lifespan)
    application.add_middleware(TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "[::1]"])

    @application.exception_handler(RequestValidationError)
    async def validation_error(request: Request, error: RequestValidationError):
        if request.url.path == "/api/settings/youtube-key":
            # Pydantic errors can otherwise echo the submitted secret in their input field.
            return JSONResponse({"detail": "Enter an API key using letters, numbers, underscores, or hyphens (20–200 characters)."},
                                status_code=422, headers={"Cache-Control": "no-store"})
        return await request_validation_exception_handler(request, error)

    @application.middleware("http")
    async def local_browser_boundary(request: Request, call_next):
        # A foreign webpage must not spend this local tool's YouTube quota.
        if request.method == "POST":
            origin = request.headers.get("origin")
            if origin and (urlsplit(origin).netloc != request.headers.get("host") or
                           urlsplit(origin).scheme != request.url.scheme):
                return JSONResponse({"detail": "Use the dashboard on this local server."}, status_code=403)
            if request.headers.get("content-type", "").split(";", 1)[0] != "application/json":
                return JSONResponse({"detail": "Send an application/json request."}, status_code=415)
        response = await call_next(request)
        if request.url.path in {"/", "/settings", "/guide", "/channels", "/stats", "/similar"} or request.url.path.startswith("/static/"):
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; script-src 'self'; style-src 'self'; "
                "img-src 'self' https://i.ytimg.com https://img.youtube.com; "
                "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
            )
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @application.get("/api/health")
    def health():
        return {"status": "ok", "youtube_key_configured": bool(os.getenv("YOUTUBE_API_KEY", "").strip())}

    @application.post("/api/settings/youtube-key")
    def save_youtube_key(payload: YouTubeKeyInput):
        key = payload.api_key.get_secret_value().strip()
        if not re.fullmatch(r"[A-Za-z0-9_-]{20,200}", key):
            raise HTTPException(422, "Enter an API key using letters, numbers, underscores, or hyphens (20–200 characters).")
        try:
            set_key(str(env_path), "YOUTUBE_API_KEY", key)
        except OSError:
            raise HTTPException(500, "Could not save your key on this computer. Check the app folder's write permissions.") from None
        os.environ["YOUTUBE_API_KEY"] = key
        return {"youtube_key_configured": True}

    @application.post("/api/search")
    async def search(payload: SearchInput):
        key = os.getenv("YOUTUBE_API_KEY", "").strip()
        if not key:
            raise HTTPException(503, "Add your YouTube API key in Settings → YouTube API, then try again.")
        if application.state.search_lock.locked():
            raise HTTPException(409, "An analysis is already running. Wait for it to finish.")
        async with application.state.search_lock:
            async with httpx.AsyncClient(timeout=httpx.Timeout(30, connect=10), follow_redirects=False) as client:
                youtube = YouTubeClient(key, client)
                try:
                    candidates, channels, uploads, warnings = await youtube.collect(payload.query, payload.days)
                except YouTubeError as error:
                    raise HTTPException(error.status_code, str(error)) from None
            now = datetime.now(timezone.utc)
            if payload.format != "all":
                candidates = [v for v in candidates if format_group(v.duration_seconds) == payload.format]
            videos = rank_videos(candidates, channels, uploads, now)
            phrases = extract_phrases(videos)
            sparse = sum(v["baseline_count"] < 10 for v in videos)
            if sparse:
                warnings.append(f"{sparse} videos have fewer than 10 earlier uploads in the same duration class. Their baseline contribution is reduced.")
            if any(v["engagement_incomplete"] for v in videos):
                warnings.append("Some engagement counts are unavailable; missing likes/comments contribute zero.")
            result = {
                "query": payload.query, "days": payload.days, "searched_at": now.isoformat(),
                "format": payload.format, "scoring_version": SCORING_VERSION,
                "channel_profiles": channel_profiles(candidates, channels, uploads, now, payload.days),
                "videos": videos, "phrases": phrases, "summary": summarize(videos, phrases),
                "warnings": warnings, "api_requests": youtube.request_count, "disclaimer": DISCLAIMER,
            }
            return await asyncio.to_thread(database.save, result, channels)

    @application.get("/api/searches")
    def history():
        return database.history()

    def require_search(search_id: int) -> dict:
        result = database.get(search_id)
        if result is None:
            raise HTTPException(404, "Search not found.")
        return result

    @application.get("/api/searches/{search_id}")
    def get_search(search_id: int):
        return require_search(search_id)

    @application.get("/api/searches/{search_id}/channels")
    def get_channels(search_id: int, format: Literal["all", "short", "long"] = "short"):
        return analyze_channels(require_search(search_id), format)

    @application.get("/api/searches/{search_id}/stats")
    def get_stats(search_id: int):
        return sample_statistics(require_search(search_id), database.observations(search_id))

    @application.get("/api/channel-library")
    def channel_library():
        return {"channels": [public_profile(profile) for profile in saved_channels(database.saved_snapshots())],
                "reports": database.related_history()}

    @application.get("/api/related-channels/{channel_id}")
    def saved_related(channel_id: str, format: Literal["all", "short", "long"] = "short"):
        report = database.related_report(channel_id, format)
        if report is None:
            raise HTTPException(404, "No saved related-channel report for this duration class.")
        return {**report, "cached": True, "requests_this_action": 0}

    @application.post("/api/related-channels")
    async def related_channels(payload: RelatedInput):
        try:
            kind, reference = parse_reference(payload.reference)
        except ValueError as error:
            raise HTTPException(422, str(error)) from None
        if not payload.refresh:
            cached = await asyncio.to_thread(database.related_report, reference, payload.format)
            if cached:
                return {**cached, "cached": True, "requests_this_action": 0}
        library = await asyncio.to_thread(lambda: saved_channels(database.saved_snapshots()))
        matching = [profile for profile in library if profile["channel_id"] == reference or
                    kind == "name" and profile["title"].casefold() == reference.casefold()]
        if len(matching) > 1:
            return {"choices": [{"channel_id": p["channel_id"], "title": p["title"],
                                  "description": "Saved channel: " + ", ".join(p["niches"])} for p in matching],
                    "requests_this_action": 0}
        seed = matching[0] if matching else None
        if seed and not payload.refresh:
            cached = await asyncio.to_thread(database.related_report, seed["channel_id"], payload.format)
            if cached:
                return {**cached, "cached": True, "requests_this_action": 0}
        key = os.getenv("YOUTUBE_API_KEY", "").strip()
        if not key:
            raise HTTPException(503, "Add your YouTube API key in Settings to discover related channels. Saved channels remain available.")
        if application.state.search_lock.locked():
            raise HTTPException(409, "An analysis is already running. Wait for it to finish.")
        async with application.state.search_lock:
            async with httpx.AsyncClient(timeout=httpx.Timeout(30, connect=10), follow_redirects=False) as client:
                youtube = YouTubeClient(key, client)
                try:
                    if seed:
                        channel_id = seed["channel_id"]
                    else:
                        channel_id, choices = await resolve_channel(youtube, kind, reference)
                        if choices:
                            return {"choices": choices, "requests_this_action": youtube.request_count}
                    if not payload.refresh:
                        cached = await asyncio.to_thread(database.related_report, channel_id, payload.format)
                        if cached:
                            return {**cached, "cached": True, "requests_this_action": youtube.request_count}
                    report = await discover_related(youtube, channel_id, payload.format, None if payload.refresh else seed)
                except YouTubeError as error:
                    raise HTTPException(error.status_code, str(error)) from None
            await asyncio.to_thread(database.save_related_report, report, reference if kind != "name" else channel_id)
            return {**report, "cached": False, "requests_this_action": youtube.request_count}

    @application.get("/api/compare")
    def compare(ids: str = Query(min_length=1, max_length=80)):
        try:
            search_ids = list(dict.fromkeys(int(value) for value in ids.split(",")))
        except ValueError:
            raise HTTPException(422, "Supply comma-separated search IDs.") from None
        if not 2 <= len(search_ids) <= 5 or any(i < 1 for i in search_ids):
            raise HTTPException(422, "Select 2 to 5 distinct searches.")
        searches = [require_search(i) for i in search_ids]
        if len({s["days"] for s in searches}) > 1:
            raise HTTPException(422, "Compare searches with the same lookback window.")
        if len({s.get("format", "all") for s in searches}) > 1:
            raise HTTPException(422, "Compare searches with the same video format.")
        if any(s.get("scoring_version", 1) != SCORING_VERSION for s in searches):
            raise HTTPException(422, "Refresh these searches to compare them with the current scoring method.")
        if len({s["query"].casefold() for s in searches}) != len(searches):
            raise HTTPException(422, "Select distinct niche keywords.")
        if any(not s["videos"] for s in searches):
            raise HTTPException(422, "Empty searches cannot be ranked. Choose niches with results.")
        return {"niches": compare_niches(searches), "note": (
            "Opportunity ranks performance evidence in your selected samples, not market competition. "
            "Searches combine up to 50 popular and 50 newest matches, deduplicated. "
            "Baseline coverage replaces the former large-channel competition proxy."
        )}

    @application.get("/api/searches/{search_id}/export")
    def export(search_id: int):
        result = require_search(search_id)
        fields = ["title", "channel_title", "url", "breakout_score", "score_label", "published_at",
                  "age_hours", "views", "avg_views_per_hour", "outlier_multiplier", "channel_baseline",
                  "baseline_count", "subscriber_count", "views_to_subscribers", "likes", "comments",
                  "engagement", "duration_seconds"]
        output = io.StringIO(newline="")
        writer = csv.DictWriter(output, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for video in result["videos"][:10]:
            row = {**video, "url": f"https://www.youtube.com/watch?v={video['video_id']}"}
            # Titles and channel names are untrusted spreadsheet content.
            for field in ("title", "channel_title"):
                value = row[field]
                if value.lstrip().startswith(("=", "+", "-", "@")) or value.startswith(("\t", "\r", "\n")):
                    row[field] = "'" + value
            writer.writerow(row)
        return Response(content="\ufeff" + output.getvalue(), media_type="text/csv",
                        headers={"Content-Disposition": f'attachment; filename="viralniche-top10-{search_id}.csv"'})

    @application.get("/")
    def index():
        return FileResponse(ROOT / "frontend" / "index.html")

    @application.get("/settings")
    def settings_page():
        return FileResponse(ROOT / "frontend" / "settings.html")

    @application.get("/guide")
    def guide_page():
        return FileResponse(ROOT / "frontend" / "guide.html")

    @application.get("/channels")
    def channels_page():
        return FileResponse(ROOT / "frontend" / "channels.html")

    @application.get("/stats")
    def stats_page():
        return FileResponse(ROOT / "frontend" / "stats.html")

    @application.get("/similar")
    def similar_page():
        return FileResponse(ROOT / "frontend" / "similar.html")

    application.mount("/static", StaticFiles(directory=ROOT / "frontend"), name="static")
    return application


app = create_app()
