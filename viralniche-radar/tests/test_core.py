import copy
import math
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from app.database import Database
from app.keywords import extract_phrases
from app.models import Channel, Video
from app.scoring import compare_niches, freshness, percentiles, rank_videos, score_label, summarize

NOW = datetime(2026, 10, 23, 12, tzinfo=timezone.utc)


def video(identifier="candidate", views=1000, hours=10, channel="channel", title="Tiny robot prank"):
    return Video(identifier, channel, title, NOW - timedelta(hours=hours), views, 20, 5, 120)


class ScoringTests(unittest.TestCase):
    def setUp(self):
        self.channels = {"channel": Channel("channel", "Small creator", 1000, False)}

    def test_baseline_is_median_and_excludes_self_and_later_uploads(self):
        candidate = video(views=2000)
        uploads = [candidate, video("before1", 100, 20), video("before2", 200, 30),
                   video("before3", 10_000, 40), video("later", 999_999, 5)]
        row = rank_videos([candidate], self.channels, {"channel": uploads}, NOW)[0]
        self.assertEqual(row["baseline_count"], 3)
        self.assertEqual(row["channel_baseline"], 200)
        self.assertEqual(row["outlier_multiplier"], 10)
        self.assertEqual(row["avg_views_per_hour"], 200)
        self.assertAlmostEqual(row["engagement"], 35 / 2000)

    def test_baseline_uses_only_twenty_closest_earlier_uploads(self):
        uploads = [video(f"old-{i}", 100 if i < 20 else 999_999, 11 + i) for i in range(30)]
        row = rank_videos([video()], self.channels, {"channel": uploads}, NOW)[0]
        self.assertEqual(row["baseline_count"], 20)
        self.assertEqual(row["channel_baseline"], 100)

    def test_unknown_baseline_and_hidden_subscribers_stay_unknown(self):
        channels = {"channel": Channel("channel", "Hidden", 1000, True)}
        row = rank_videos([video()], channels, {}, NOW)[0]
        for field in ("outlier_multiplier", "channel_baseline", "subscriber_count", "views_to_subscribers"):
            self.assertIsNone(row[field])
        self.assertFalse(row["small_channel"])
        self.assertFalse(row["is_breakout"])

    def test_empty_and_zero_samples_are_finite(self):
        self.assertEqual(rank_videos([], {}, {}, NOW), [])
        row = rank_videos([video(views=0, hours=0)], self.channels,
                          {"channel": [video("old", 0, 2)]}, NOW)[0]
        self.assertEqual(row["outlier_multiplier"], 0)
        self.assertEqual(row["avg_views_per_hour"], 0)
        self.assertTrue(math.isfinite(row["breakout_score"]))
        self.assertFalse(row["is_breakout"])

    def test_subhour_average_uses_one_hour_floor(self):
        row = rank_videos([video(views=500, hours=.2)], {}, {}, NOW)[0]
        self.assertEqual(row["avg_views_per_hour"], 500)

    def test_relative_factors_and_weighted_rank(self):
        candidates = [video("low", 100, 36), video("high", 10_000, 8)]
        uploads = {"channel": [video(f"baseline-{i}", 100, 300 + i) for i in range(10)]}
        rows = rank_videos(candidates, self.channels, uploads, NOW)
        self.assertEqual(rows[0]["video_id"], "high")
        # Engagement is higher on the lower-view video because likes/comments are equal.
        self.assertEqual(rows[0]["breakout_score"], 85)
        self.assertTrue(rows[0]["small_channel_breakout"])
        self.assertEqual(rows[1]["breakout_score"], 15)

    def test_score_alone_does_not_create_breakouts(self):
        candidates = [video("low", 1000, 36), video("high", 2000, 8)]
        rows = rank_videos(candidates, self.channels,
                           {"channel": [video(f"baseline-{i}", 10_000, 300 + i) for i in range(10)]}, NOW)
        self.assertGreaterEqual(rows[0]["breakout_score"], 75)
        self.assertFalse(rows[0]["is_breakout"])

    def test_large_and_hidden_channels_do_not_get_small_channel_factor(self):
        channels = {"channel": Channel("channel", "Large", 100_000, False)}
        row = rank_videos([video()], channels, {}, NOW)[0]
        self.assertFalse(row["small_channel"])
        self.assertEqual(row["small_channel_signal"], 0)

    def test_percentiles_preserve_ties(self):
        self.assertEqual(percentiles([]), [])
        self.assertEqual(percentiles([0]), [50])
        self.assertEqual(percentiles([0, 0]), [50, 50])
        self.assertEqual(percentiles([1, 2, 2, 4]), [0, 50, 50, 100])

    def test_freshness_boundaries_and_labels(self):
        for hours, expected in ((0, 100), (24, 100), (25, 90), (48, 90), (49, 80),
                                (73, 65), (169, 40), (337, 20), (721, 0)):
            self.assertEqual(freshness(hours), expected)
        self.assertEqual([score_label(x) for x in (0, 40, 60, 75, 90)],
                         ["normal", "interesting", "rising", "breakout candidate", "exceptional anomaly"])

    def test_missing_engagement_and_channel_are_explicit(self):
        candidate = video()
        candidate.likes = candidate.comments = None
        row = rank_videos([candidate], {}, {}, NOW)[0]
        self.assertTrue(row["engagement_incomplete"])
        self.assertEqual(row["engagement"], 0)
        self.assertIsNone(row["subscriber_count"])


class PhraseTests(unittest.TestCase):
    def rows(self):
        return [
            {"title": "The tiny robot prank! tiny robot", "channel_id": "a", "is_breakout": True},
            {"title": "A tiny robot prank", "channel_id": "b", "is_breakout": True},
            {"title": "Tiny robot prank again", "channel_id": "a", "is_breakout": False},
            {"title": "Large building tour", "channel_id": "c", "is_breakout": False},
        ]

    def test_unique_video_and_channel_counts_and_breakout_lift(self):
        phrases = {p["phrase"]: p for p in extract_phrases(self.rows())}
        result = phrases["tiny robot prank"]
        self.assertEqual(result["video_count"], 3)
        self.assertEqual(result["channel_count"], 2)
        self.assertEqual(result["breakout_count"], 2)
        self.assertEqual(result["breakout_lift"], 1.33)
        self.assertNotIn("the", phrases)

    def test_single_creator_and_sparse_phrases_are_filtered(self):
        rows = self.rows()
        for row in rows:
            row["channel_id"] = "only"
        self.assertEqual(extract_phrases(rows), [])
        self.assertEqual(extract_phrases(self.rows()[:2]), [])

    def test_no_breakouts_has_zero_lift(self):
        rows = self.rows()
        for row in rows:
            row["is_breakout"] = False
        self.assertTrue(all(p["breakout_lift"] == 0 for p in extract_phrases(rows)))


class PersistenceAndComparisonTests(unittest.TestCase):
    def setUp(self):
        # Stay in the writable workspace even in restricted Windows runners.
        temp_root = Path(__file__).resolve().parent / ".tmp"
        temp_root.mkdir(exist_ok=True)
        self.temp = temp_root / uuid4().hex
        self.temp.mkdir()
        self.addCleanup(self.cleanup_database)
        self.database = Database(self.temp / "test.db")
        self.database.initialize()

    def cleanup_database(self):
        for file in self.temp.iterdir():
            file.unlink()
        self.temp.rmdir()

    def result(self, query="robot pranks", views=1000):
        channels = {"channel": Channel("channel", "Creator", 1000, False)}
        rows = rank_videos([video(views=views)], channels,
                           {"channel": [video("old", 100, 20)]}, NOW)
        return {"query": query, "days": 30, "searched_at": NOW.isoformat(), "videos": rows,
                "phrases": [], "summary": summarize(rows, []), "warnings": [], "api_requests": 4}, channels

    def test_overlapping_searches_preserve_original_snapshots(self):
        first, channels = self.result()
        first = self.database.save(first, channels)
        second, channels = self.result("another niche", 9000)
        second = self.database.save(second, channels)
        self.assertEqual(self.database.get(first["id"])["videos"][0]["views"], 1000)
        self.assertEqual(self.database.get(second["id"])["videos"][0]["views"], 9000)
        self.assertEqual(len(self.database.history()), 2)
        with self.database.connect() as connection:
            self.assertEqual(connection.execute("SELECT views FROM videos").fetchone()[0], 9000)
            self.assertEqual(connection.execute("SELECT count(*) FROM search_videos").fetchone()[0], 2)

    def test_parameterized_query_and_missing_record(self):
        result, channels = self.result("x'); DROP TABLE videos; --")
        saved = self.database.save(result, channels)
        self.assertEqual(self.database.get(saved["id"])["query"], result["query"])
        self.assertIsNone(self.database.get(999))
        self.assertEqual(len(self.database.history()), 1)

    def test_failed_save_is_atomic(self):
        result, channels = self.result()
        result["videos"][0]["views"] = float("nan")
        with self.assertRaises(ValueError):
            self.database.save(result, channels)
        self.assertEqual(self.database.history(), [])

    def test_opportunity_uses_selected_niche_samples(self):
        first, _ = self.result()
        first["id"] = 1
        second = copy.deepcopy(first)
        second.update(id=2, query="better niche")
        second["summary"].update(median_views_per_hour=10000, breakout_videos=1,
                                 small_channel_breakouts=1, independent_breakout_channels=1)
        ranked = compare_niches([first, second])
        self.assertEqual(ranked[0]["query"], "better niche")
        self.assertTrue(all(0 <= r["opportunity_score"] <= 100 for r in ranked))
        self.assertEqual(compare_niches([]), [])

    def test_empty_summary_is_honest(self):
        result = summarize([], [])
        self.assertEqual(result["video_count"], 0)
        self.assertIsNone(result["median_outlier_multiplier"])
        self.assertEqual(result["top_phrase_concentration"], 0)

    def test_unknown_subscribers_do_not_imply_lower_competition(self):
        rows = rank_videos([video()], {}, {}, NOW)
        summary = summarize(rows, [])
        self.assertIsNone(summary["large_channel_share"])
        searches = [{"id": 1, "query": "hidden", "days": 30, "summary": summary}]
        components = compare_niches(searches)[0]["components"]
        self.assertNotIn("lower_competition_proxy", components)
        self.assertEqual(components["baseline_coverage"], 0)

    def test_observations_only_return_earlier_overlapping_searches(self):
        first, channels = self.result()
        first["searched_at"] = (NOW - timedelta(hours=2)).isoformat()
        first = self.database.save(first, channels)
        unrelated, channels = self.result("unrelated")
        unrelated["videos"][0]["video_id"] = "unrelated"
        self.database.save(unrelated, channels)
        current, channels = self.result(views=2000)
        current = self.database.save(current, channels)
        self.database.save(current, channels)
        previous = self.database.observations(current["id"])
        self.assertEqual([s["id"] for s in previous], [first["id"]])
        self.assertEqual(self.database.observations(first["id"]), [])


if __name__ == "__main__":
    unittest.main()
