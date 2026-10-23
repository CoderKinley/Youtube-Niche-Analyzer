"""Offline contract tests: never contact YouTube or spend API quota."""

import csv
import importlib.util
import io
import os
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

REQUIRED = ("fastapi", "httpx", "dotenv", "isodate")
missing = [name for name in REQUIRED if importlib.util.find_spec(name) is None]
if missing:
    raise unittest.SkipTest(f"Install requirements.txt for API tests; missing: {', '.join(missing)}")

import httpx
from dotenv import dotenv_values
from fastapi.testclient import TestClient

from app.main import create_app
from app.youtube import YouTubeClient, YouTubeError, parse_video


def youtube_fixture(request: httpx.Request) -> httpx.Response:
    """Two candidates and ten earlier uploads per creator, using real API shapes."""
    assert request.headers["X-Goog-Api-Key"] == "test-key"
    assert "key" not in request.url.params
    resource = request.url.path.rsplit("/", 1)[-1]
    now = datetime.now(timezone.utc)
    if resource == "search":
        assert request.url.params["type"] == "video"
        assert request.url.params["order"] in {"viewCount", "date"}
        return httpx.Response(200, json={"items": [{"id": {"videoId": f"candidate-{c}"}} for c in "ab"]})
    if resource == "channels":
        return httpx.Response(200, json={"items": [
            {"id": c, "snippet": {"title": f"Creator {c}"},
             "statistics": {"subscriberCount": "1000", "hiddenSubscriberCount": c == "b"},
             "contentDetails": {"relatedPlaylists": {"uploads": f"uploads-{c}"}}} for c in "ab"
        ]})
    if resource == "playlistItems":
        channel = request.url.params["playlistId"][-1]
        return httpx.Response(200, json={"items": [
            {"contentDetails": {"videoId": identifier}}
            for identifier in [f"candidate-{channel}"] + [f"old-{channel}-{i}" for i in range(10)]
        ]})
    if resource == "videos":
        items = []
        for identifier in request.url.params["id"].split(","):
            candidate = identifier.startswith("candidate")
            channel = identifier.split("-")[1]
            views = 100_000 if identifier == "candidate-a" else 1000 if candidate else 100
            hours = (8 if channel == "a" else 36) if candidate else 240
            items.append({
                "id": identifier,
                "snippet": {"title": "=untrusted title" if channel == "a" else "Tiny robot prank",
                            "channelId": channel, "publishedAt": (now - timedelta(hours=hours)).isoformat(),
                            "thumbnails": {"medium": {"url": "https://i.ytimg.com/vi/id/mqdefault.jpg"}}},
                "statistics": {"viewCount": str(views), "likeCount": str(views // 10), "commentCount": "2"},
                "contentDetails": {"duration": "PT2M10S"},
            })
        return httpx.Response(200, json={"items": items})
    raise AssertionError(f"Unexpected YouTube resource: {resource}")


class ApiTests(unittest.TestCase):
    def setUp(self):
        temp_root = Path(__file__).resolve().parent / ".tmp"
        temp_root.mkdir(exist_ok=True)
        self.temp = temp_root / uuid4().hex
        self.temp.mkdir()
        self.addCleanup(self.cleanup_database)
        environment = patch.dict(os.environ, {"YOUTUBE_API_KEY": "test-key"})
        environment.start()
        self.addCleanup(environment.stop)
        original_client = httpx.AsyncClient
        mocked = patch("app.main.httpx.AsyncClient", side_effect=lambda **kwargs: original_client(
            transport=httpx.MockTransport(youtube_fixture), **kwargs))
        mocked.start()
        self.addCleanup(mocked.stop)
        self.env_path = self.temp / ".env"
        self.client = TestClient(create_app(self.temp / "test.db", env_path=self.env_path), base_url="http://localhost")
        self.client.__enter__()
        self.addCleanup(lambda: self.client.__exit__(None, None, None))

    def cleanup_database(self):
        for file in self.temp.iterdir():
            file.unlink()
        self.temp.rmdir()

    def analyze(self, query="robot prank", days=30):
        response = self.client.post("/api/search", json={"query": query, "days": days})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_full_collection_scoring_persistence_comparison_and_csv(self):
        first = self.analyze()
        self.assertEqual(first["api_requests"], 7)
        self.assertEqual(len(first["videos"]), 2)
        top = first["videos"][0]
        self.assertEqual(top["video_id"], "candidate-a")
        self.assertEqual(top["baseline_count"], 10)
        self.assertEqual(top["channel_baseline"], 100)
        self.assertEqual(top["outlier_multiplier"], 1000)
        self.assertEqual(top["duration_seconds"], 130)
        self.assertTrue(top["small_channel_breakout"])
        self.assertIsNone(first["videos"][1]["subscriber_count"])
        self.assertEqual(self.client.get(f"/api/searches/{first['id']}").json(), first)
        second = self.analyze("funny animation")
        self.assertEqual(len(self.client.get("/api/searches").json()), 2)
        comparison = self.client.get(f"/api/compare?ids={first['id']},{second['id']}")
        self.assertEqual(comparison.status_code, 200)
        self.assertEqual(len(comparison.json()["niches"]), 2)
        export = self.client.get(f"/api/searches/{first['id']}/export")
        self.assertEqual(export.status_code, 200)
        rows = list(csv.DictReader(io.StringIO(export.content.decode("utf-8-sig"))))
        self.assertEqual(len(rows), 2)
        self.assertTrue(rows[0]["title"].startswith("'="))
        self.assertEqual(rows[0]["url"], "https://www.youtube.com/watch?v=candidate-a")

    def test_missing_key_has_actionable_error(self):
        with patch.dict(os.environ, {"YOUTUBE_API_KEY": ""}):
            self.assertFalse(self.client.get("/api/health").json()["youtube_key_configured"])
            response = self.client.post("/api/search", json={"query": "robot"})
        self.assertEqual(response.status_code, 503)
        self.assertIn("Settings", response.json()["detail"])

    def test_key_save_is_persistent_private_and_immediately_used(self):
        key = "new-key-" + "X" * 32
        self.env_path.write_text("# Keep this comment\nOTHER_SETTING=keep\nYOUTUBE_API_KEY=previous\n", encoding="utf-8")
        response = self.client.post("/api/settings/youtube-key", json={"api_key": f" {key} "})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"youtube_key_configured": True})
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertNotIn(key, response.text)
        self.assertEqual(dotenv_values(self.env_path)["YOUTUBE_API_KEY"], key)
        self.assertEqual(dotenv_values(self.env_path)["OTHER_SETTING"], "keep")
        self.assertIn("# Keep this comment", self.env_path.read_text(encoding="utf-8"))
        seen = []

        async def collect(client, query, days):
            seen.append(client.api_key)
            return [], {}, {}, []

        with patch("app.main.YouTubeClient.collect", new=collect):
            self.analyze()
        self.assertEqual(seen, [key])
        self.assertNotIn(key, self.client.get("/api/health").text)
        with patch.dict(os.environ):
            os.environ.pop("YOUTUBE_API_KEY", None)
            app = create_app(self.temp / "restart.db", env_path=self.env_path)
            with TestClient(app, base_url="http://localhost") as restarted:
                self.assertTrue(restarted.get("/api/health").json()["youtube_key_configured"])
                self.assertEqual(os.environ["YOUTUBE_API_KEY"], key)

    def test_invalid_keys_never_echo_secrets_or_overwrite_configuration(self):
        secret = "private-input-" + "X" * 32
        for payload in ({"api_key": ""}, {"api_key": "too-short"},
                        {"api_key": secret + "\nINJECTED=value"}, {"api_key": "X" * 201},
                        {"api_key": {"secret": secret}}, {"api_key": secret, "extra": secret}, {}):
            with self.subTest(fields=list(payload)):
                response = self.client.post("/api/settings/youtube-key", json=payload)
                self.assertEqual(response.status_code, 422)
                self.assertNotIn(secret, response.text)
                self.assertEqual(os.environ["YOUTUBE_API_KEY"], "test-key")
                self.assertFalse(self.env_path.exists())

    def test_key_save_failure_does_not_activate_unsaved_key(self):
        key = "new-key-" + "X" * 32
        with patch("app.main.set_key", side_effect=PermissionError("sensitive filesystem error")):
            response = self.client.post("/api/settings/youtube-key", json={"api_key": key})
        self.assertEqual(response.status_code, 500)
        self.assertNotIn(key, response.text)
        self.assertNotIn("sensitive filesystem error", response.text)
        self.assertEqual(os.environ["YOUTUBE_API_KEY"], "test-key")

    def test_foreign_webpage_cannot_replace_key(self):
        response = self.client.post("/api/settings/youtube-key", json={"api_key": "X" * 39},
                                    headers={"origin": "https://foreign.example"})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(os.environ["YOUTUBE_API_KEY"], "test-key")
        self.assertFalse(self.env_path.exists())

    def test_invalid_inputs_do_not_start_a_collection(self):
        for payload in ({"query": " "}, {"query": "x"}, {"query": "valid", "days": 0},
                        {"query": "valid", "days": 31}, {"query": "valid", "days": True},
                        {"query": "valid", "days": "30"}, {"query": "valid", "extra": 1}):
            with self.subTest(payload=payload):
                self.assertEqual(self.client.post("/api/search", json=payload).status_code, 422)
        self.assertEqual(self.client.get("/api/searches").json(), [])

    def test_local_origin_and_host_boundaries(self):
        response = self.client.post("/api/search", json={"query": "robot"}, headers={"origin": "https://foreign.example"})
        self.assertEqual(response.status_code, 403)
        response = self.client.post("/api/search", content='{"query":"robot"}')
        self.assertEqual(response.status_code, 415)
        self.assertEqual(self.client.get("/api/health", headers={"host": "foreign.example"}).status_code, 400)

    def test_comparison_validation(self):
        first = self.analyze()
        duplicate = self.analyze()
        other_window = self.analyze("other niche", 7)
        for ids in ("x,2", "1", "1,1", "1,2,3,4,5,6", "-1,2",
                    f"{first['id']},{duplicate['id']}", f"{first['id']},{other_window['id']}"):
            with self.subTest(ids=ids):
                self.assertEqual(self.client.get(f"/api/compare?ids={ids}").status_code, 422)
        self.assertEqual(self.client.get("/api/compare?ids=999,998").status_code, 404)

    def test_quota_failure_is_sanitized_and_not_saved(self):
        async def fail(*args):
            raise YouTubeError("YouTube API quota reached.", 429)
        with patch("app.main.YouTubeClient.collect", side_effect=fail):
            response = self.client.post("/api/search", json={"query": "robot"})
        self.assertEqual(response.status_code, 429)
        self.assertNotIn("test-key", response.text)
        self.assertEqual(self.client.get("/api/searches").json(), [])

    def test_page_and_assets(self):
        root = self.client.get("/")
        self.assertEqual(root.status_code, 200)
        self.assertIn("ViralNiche Radar", root.text)
        self.assertIn("script-src 'self'", root.headers["content-security-policy"])
        for asset in ("app.js", "common.js", "settings.js", "research.js", "channels.js", "stats.js", "styles.css"):
            self.assertEqual(self.client.get(f"/static/{asset}").status_code, 200)
        self.assertEqual(self.client.get("/static/../.env").status_code, 404)
        self.assertEqual(self.client.get("/api/searches/999").status_code, 404)
        self.assertEqual(self.client.get("/api/searches/999/export").status_code, 404)

    def test_settings_and_guide_have_separate_pages(self):
        dashboard = self.client.get("/")
        self.assertNotIn('id="api-key"', dashboard.text)
        self.assertNotIn("Scoring details", dashboard.text)
        self.assertIn('href="/settings"', dashboard.text)
        settings = self.client.get("/settings")
        self.assertEqual(settings.status_code, 200)
        self.assertIn('id="api-key"', settings.text)
        self.assertNotIn('id="search-form"', settings.text)
        guide = self.client.get("/guide")
        self.assertEqual(guide.status_code, 200)
        self.assertIn("Scoring details", guide.text)
        self.assertNotIn('id="api-key"', guide.text)
        for response in (settings, guide):
            self.assertIn("script-src 'self'", response.headers["content-security-policy"])

    def test_channel_analysis_and_statistics_are_persisted_without_more_youtube_calls(self):
        first = self.analyze()
        with patch("app.main.YouTubeClient.collect", side_effect=AssertionError("Unexpected quota use")):
            channels = self.client.get(f"/api/searches/{first['id']}/channels").json()
            self.assertTrue(channels["available"])
            self.assertEqual(channels["coverage"]["discovered_channels"], 2)
            self.assertEqual(channels["coverage"]["unknown_subscribers"], 1)
            creator = next(c for c in channels["channels"] if c["channel_id"] == "a")
            self.assertEqual(creator["measured_count"], 10)
            self.assertEqual(creator["median_views"], 100)
            self.assertEqual(len(creator["videos"]), 11)
            long = self.client.get(f"/api/searches/{first['id']}/channels?format=long").json()
            self.assertEqual(long["channels"], [])
            stats = self.client.get(f"/api/searches/{first['id']}/stats").json()
            self.assertEqual(stats["total_views"], 101000)
            self.assertEqual(stats["growth"], [])
            self.assertEqual(stats["formats"][0]["videos"], 2)
        self.assertEqual(self.client.get(f"/api/searches/{first['id']}/channels?format=invalid").status_code, 422)
        for suffix in ("channels", "stats"):
            self.assertEqual(self.client.get(f"/api/searches/999/{suffix}").status_code, 404)

    def test_channel_and_stats_pages_are_separate_and_secure(self):
        for path, script in (("/channels", "channels.js"), ("/stats", "stats.js")):
            page = self.client.get(path)
            self.assertEqual(page.status_code, 200)
            self.assertIn(script, page.text)
            self.assertIn("script-src 'self'", page.headers["content-security-policy"])
            self.assertNotIn('id="api-key"', page.text)
        dashboard = self.client.get("/").text
        self.assertNotIn('id="channel-rows"', dashboard)
        self.assertNotIn('id="creator-chart"', dashboard)

    def test_format_filter_and_mismatched_comparison(self):
        first = self.analyze()
        second = self.client.post("/api/search", json={"query": "short niche", "format": "short"}).json()
        self.assertEqual(len(second["videos"]), 2)
        self.assertEqual(second["scoring_version"], 2)
        response = self.client.get(f"/api/compare?ids={first['id']},{second['id']}")
        self.assertEqual(response.status_code, 422)
        long = self.client.post("/api/search", json={"query": "long niche", "format": "long"}).json()
        self.assertEqual(long["videos"], [])
        self.assertEqual(long["channel_profiles"], [])
        self.assertEqual(self.client.post("/api/search", json={"query": "invalid", "format": "shorts"}).status_code, 422)

    def test_legacy_searches_can_be_opened_but_require_refresh_for_channel_history_and_comparison(self):
        import json
        from app.database import Database
        first = self.analyze()
        second = self.analyze("another niche")
        legacy = dict(first)
        legacy.pop("channel_profiles")
        legacy.pop("scoring_version")
        db = Database(self.temp / "test.db")
        with db.connect() as connection:
            connection.execute("UPDATE searches SET result_json=? WHERE id=?", (json.dumps(legacy), first["id"]))
        self.assertEqual(self.client.get(f"/api/searches/{first['id']}").status_code, 200)
        self.assertFalse(self.client.get(f"/api/searches/{first['id']}/channels").json()["available"])
        self.assertEqual(self.client.get(f"/api/searches/{first['id']}/stats").status_code, 200)
        response = self.client.get(f"/api/compare?ids={first['id']},{second['id']}")
        self.assertEqual(response.status_code, 422)
        self.assertIn("Refresh", response.json()["detail"])

    def test_saved_channel_library_never_calls_youtube_and_is_deduplicated(self):
        self.analyze()
        self.analyze("another niche")
        with patch("app.main.YouTubeClient.get", side_effect=AssertionError("No network for browsing")):
            library = self.client.get("/api/channel-library").json()
            self.assertEqual(len(library["channels"]), 2)
            self.assertEqual(len(library["channels"][0]["niches"]), 2)
            self.assertNotIn("videos", library["channels"][0])
            self.assertEqual(library["reports"], [])
            page = self.client.get("/similar")
            self.assertEqual(page.status_code, 200)
            self.assertIn("script-src 'self'", page.headers["content-security-policy"])

    def test_related_reports_are_cached_and_refresh_is_explicit(self):
        self.analyze()
        seen = []
        async def discover(youtube, channel_id, video_format, seed):
            seen.append(seed)
            youtube.request_count = 3
            return {"reference": {"channel_id": channel_id, "title": "Creator a"}, "format": video_format,
                    "searched_at": datetime.now(timezone.utc).isoformat(), "channels": [], "api_requests": 3}
        payload = {"reference": "Creator a", "format": "short"}
        with patch("app.main.discover_related", new=discover):
            first = self.client.post("/api/related-channels", json=payload)
            self.assertEqual(first.status_code, 200, first.text)
            self.assertFalse(first.json()["cached"])
            self.assertIsNotNone(seen[0])
            with patch.dict(os.environ, {"YOUTUBE_API_KEY": ""}):
                cached = self.client.post("/api/related-channels", json=payload)
                self.assertEqual(cached.status_code, 200)
                self.assertTrue(cached.json()["cached"])
                self.assertEqual(cached.json()["requests_this_action"], 0)
                self.assertEqual(self.client.get("/api/related-channels/a?format=short").status_code, 200)
                self.assertEqual(self.client.get("/api/related-channels/a?format=long").status_code, 404)
                self.assertEqual(self.client.post("/api/related-channels", json={**payload, "refresh": True}).status_code, 503)
            refreshed = self.client.post("/api/related-channels", json={**payload, "refresh": True})
            self.assertEqual(refreshed.status_code, 200)
            self.assertEqual(len(seen), 2)
            self.assertIsNone(seen[-1])
            self.assertEqual(len(self.client.get("/api/channel-library").json()["reports"]), 1)

    def test_related_requests_validate_and_fail_without_saving(self):
        for payload in ({"reference": "x"}, {"reference": "https://evil.example/@x"},
                        {"reference": "robot", "format": "bad"}, {"reference": "robot", "refresh": "true"}):
            self.assertEqual(self.client.post("/api/related-channels", json=payload).status_code, 422)
        cid = "UC" + "a" * 22
        with patch("app.main.discover_related", side_effect=YouTubeError("Quota reached", 429)):
            response = self.client.post("/api/related-channels", json={"reference": cid})
        self.assertEqual(response.status_code, 429)
        self.assertEqual(self.client.get("/api/channel-library").json()["reports"], [])
        self.assertEqual(self.client.post("/api/related-channels", json={"reference": cid},
                        headers={"origin": "https://foreign.example"}).status_code, 403)


class YouTubeClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_popular_and_newest_results_are_deduplicated_and_channels_are_batched(self):
        orders, channel_batches = [], []
        now = datetime.now(timezone.utc)
        def response(request):
            resource = request.url.path.rsplit("/", 1)[-1]
            if resource == "search":
                order = request.url.params["order"]
                orders.append(order)
                start = 0 if order == "viewCount" else 25
                return httpx.Response(200, json={"items": [{"id": {"videoId": str(i)}} for i in range(start, start + 50)]})
            if resource == "videos":
                identifiers = request.url.params["id"].split(",")
                self.assertLessEqual(len(identifiers), 50)
                return httpx.Response(200, json={"items": [
                    {"id": i, "snippet": {"title": i, "channelId": i, "publishedAt": (now - timedelta(days=2)).isoformat()},
                     "statistics": {"viewCount": "100"}, "contentDetails": {"duration": "PT30S"}} for i in identifiers]})
            if resource == "channels":
                identifiers = request.url.params["id"].split(",")
                channel_batches.append(len(identifiers))
                return httpx.Response(200, json={"items": [{"id": i, "snippet": {"title": i},
                    "statistics": {"subscriberCount": "100"}} for i in identifiers]})
            raise AssertionError(resource)
        async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as client:
            videos, channels, _, _ = await YouTubeClient("test-key", client).collect("niche", 30)
        self.assertEqual(set(orders), {"date", "viewCount"})
        self.assertEqual(len(videos), 75)
        self.assertEqual(len(channels), 75)
        self.assertEqual(sorted(channel_batches), [25, 50])

    async def test_batching_never_exceeds_fifty_ids(self):
        sizes = []
        def response(request):
            sizes.append(len(request.url.params["id"].split(",")))
            return httpx.Response(200, json={"items": []})
        async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as client:
            await YouTubeClient("test-key", client).videos([str(i) for i in range(105)])
        self.assertEqual(sorted(sizes), [5, 50, 50])

    async def test_quota_errors_are_mapped_without_exposing_provider_message(self):
        def response(request):
            return httpx.Response(403, json={"error": {"message": "secret-provider-data", "errors": [{"reason": "quotaExceeded"}]}})
        async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as client:
            with self.assertRaises(YouTubeError) as caught:
                await YouTubeClient("test-key", client).get("search")
        self.assertEqual(caught.exception.status_code, 429)
        self.assertNotIn("secret-provider-data", str(caught.exception))

    async def test_timeouts_have_clear_error(self):
        def response(request):
            raise httpx.ReadTimeout("private-request-data")
        async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as client:
            with self.assertRaises(YouTubeError) as caught:
                await YouTubeClient("test-key", client).get("search")
        self.assertEqual(caught.exception.status_code, 504)
        self.assertNotIn("private-request-data", str(caught.exception))

    def test_private_or_unmeasurable_video_is_skipped(self):
        self.assertIsNone(parse_video({"id": "private"}))


if __name__ == "__main__":
    unittest.main()
