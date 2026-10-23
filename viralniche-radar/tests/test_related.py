import copy
import unittest
from datetime import datetime, timedelta, timezone

import httpx

from app.related import discovery_queries, discover_related, parse_reference, rank_related, resolve_channel, saved_channels
from app.youtube import YouTubeClient

A, B, C = ("UC" + letter * 22 for letter in "abc")


def profile(cid=A, title="Tiny robot prank", views=1000):
    now = datetime.now(timezone.utc)
    return {"channel_id": cid, "title": cid, "subscribers": 1000, "upload_history_available": True,
            "captured_at": now.isoformat(), "window_days": 30,
            "videos": [{"video_id": f"{cid}-{i}", "title": title, "views": views, "duration_seconds": 60,
                        "age_hours": 48 + i, "published_at": (now - timedelta(hours=48 + i)).isoformat()}
                       for i in range(4)]}


class RelatedAlgorithms(unittest.TestCase):
    def test_reference_parsing_rejects_foreign_urls_and_supports_handles_and_channel_urls(self):
        self.assertEqual(parse_reference("https://www.youtube.com/@RobotLab/shorts"), ("handle", "@robotlab"))
        self.assertEqual(parse_reference("youtube.com/channel/" + A), ("id", A))
        self.assertEqual(parse_reference("Robot Lab"), ("name", "Robot Lab"))
        for value in ("https://evil.example/@robot", "https://youtube.com.evil.example/@robot",
                      "https://youtube.com/watch?v=abc", "https://youtube.com/channel/bad", "@bad handle"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_reference(value)

    def test_query_budget_and_generic_titles(self):
        self.assertLessEqual(len(discovery_queries(profile()["videos"])), 2)
        self.assertEqual(discovery_queries(profile(title="Viral shorts subscribe official 2026")["videos"]), [])

    def test_similarity_requires_shared_title_evidence_and_excludes_reference(self):
        seed, match, unrelated = profile(), profile(B), profile(C, "Sourdough bread recipes", 10_000_000)
        result = rank_related(seed, [seed, match, unrelated], "short")
        self.assertEqual([row["channel_id"] for row in result], [B])
        self.assertEqual(result[0]["matching_uploads"], 4)
        self.assertEqual(result[0]["match_evidence"], "Repeated title overlap")
        self.assertEqual(len(result[0]["examples"]), 3)
        self.assertTrue(0 <= result[0]["similarity"] <= 100)
        match["videos"][0]["views"] = 1_000_000_000
        self.assertEqual(rank_related(seed, [match, unrelated], "short")[0]["similarity"], result[0]["similarity"])

    def test_wrong_duration_and_single_word_overlap_are_not_matches(self):
        seed, candidate = profile(), profile(B, "Robot cooking recipes")
        self.assertEqual(rank_related(seed, [candidate], "short"), [])
        candidate = profile(B)
        for video in candidate["videos"]:
            video["duration_seconds"] = 600
        self.assertEqual(rank_related(seed, [candidate], "short"), [])

    def test_saved_library_deduplicates_newest_profiles_and_keeps_source_niches(self):
        one = profile()
        one.update(matched_videos=1, history_limit_reached=False)
        newest = {"id": 2, "query": "robot", "days": 30, "searched_at": "2026-10-23T12:00:00+00:00",
                  "channel_profiles": [one], "videos": []}
        older = copy.deepcopy(newest)
        older.update(id=1, query="animation")
        older["channel_profiles"][0]["title"] = "Old title"
        library = saved_channels([newest, older])
        self.assertEqual(len(library), 1)
        self.assertEqual(library[0]["title"], A)
        self.assertEqual(library[0]["niches"], ["robot", "animation"])
        self.assertEqual(library[0]["search_id"], 2)


class RelatedCollectionTests(unittest.IsolatedAsyncioTestCase):
    def response(self, request):
        self.calls.append((request.url.path.rsplit("/", 1)[-1], dict(request.url.params)))
        self.assertEqual(request.headers["X-Goog-Api-Key"], "test-key")
        self.assertNotIn("key", request.url.params)
        resource, params = self.calls[-1]
        if resource == "search":
            if params["type"] == "channel":
                return httpx.Response(200, json={"items": [{"id": {"channelId": cid}, "snippet": {"title": cid}} for cid in (A, B)]})
            return httpx.Response(200, json={"items": [{"id": {"videoId": "candidate"}, "snippet": {"channelId": cid}} for cid in (A, B, C)]})
        if resource == "channels":
            ids = [A] if "forHandle" in params else params["id"].split(",")
            return httpx.Response(200, json={"items": [{"id": cid, "snippet": {"title": cid},
                "statistics": {"subscriberCount": "1000"}, "contentDetails": {"relatedPlaylists": {"uploads": cid}}} for cid in ids]})
        if resource == "playlistItems":
            self.assertEqual(params["maxResults"], "20")
            return httpx.Response(200, json={"items": [{"contentDetails": {"videoId": params["playlistId"] + ":" + str(i)}} for i in range(4)]})
        if resource == "videos":
            items = []
            for identifier in params["id"].split(","):
                cid = identifier.split(":")[0]
                items.append({"id": identifier, "snippet": {"title": "Tiny robot prank" if cid != C else "Sourdough bread recipe",
                    "channelId": cid, "publishedAt": (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()},
                    "statistics": {"viewCount": "1000"}, "contentDetails": {"duration": "PT60S"}})
            return httpx.Response(200, json={"items": items})
        raise AssertionError(resource)

    async def test_full_discovery_and_saved_reference_reuse(self):
        self.calls = []
        async with httpx.AsyncClient(transport=httpx.MockTransport(self.response)) as client:
            youtube = YouTubeClient("test-key", client)
            report = await discover_related(youtube, A, "short")
        self.assertEqual([row["channel_id"] for row in report["channels"]], [B])
        self.assertEqual(report["examined_channels"], 2)
        self.assertEqual(len([r for r, _ in self.calls if r == "search"]), 2)
        self.assertTrue(report["channels"][0]["examples"])
        total = len(self.calls)
        self.calls = []
        async with httpx.AsyncClient(transport=httpx.MockTransport(self.response)) as client:
            report = await discover_related(YouTubeClient("test-key", client), A, "short", profile())
        self.assertEqual(len(self.calls), total - 3)
        self.assertFalse(any(resource == "playlistItems" and params["playlistId"] == A for resource, params in self.calls))

    async def test_name_requires_selection_and_handle_resolves_exact_channel(self):
        self.calls = []
        async with httpx.AsyncClient(transport=httpx.MockTransport(self.response)) as client:
            youtube = YouTubeClient("test-key", client)
            cid, choices = await resolve_channel(youtube, "name", "Robot Lab")
            self.assertIsNone(cid)
            self.assertEqual(len(choices), 2)
            self.assertEqual(len(self.calls), 1)
            cid, choices = await resolve_channel(youtube, "handle", "@robotlab")
            self.assertEqual(cid, A)
            self.assertIsNone(choices)

    async def test_candidate_channel_budget_is_capped_at_twelve(self):
        self.calls = []
        def many_candidates(request):
            if request.url.path.endswith("/search"):
                self.calls.append(("search", dict(request.url.params)))
                return httpx.Response(200, json={"items": [{"snippet": {"channelId": "UC" + str(i).zfill(22)}} for i in range(25)]})
            return self.response(request)
        async with httpx.AsyncClient(transport=httpx.MockTransport(many_candidates)) as client:
            report = await discover_related(YouTubeClient("test-key", client), A, "short", profile())
        self.assertEqual(report["examined_channels"], 12)
        self.assertEqual(len([r for r, _ in self.calls if r == "playlistItems"]), 12)
        self.assertEqual(len([r for r, _ in self.calls if r == "search"]), 2)


if __name__ == "__main__":
    unittest.main()
