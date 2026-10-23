import unittest
from datetime import timedelta

from app.analysis import analyze_channels, channel_profiles, observed_growth, sample_statistics
from app.models import Channel
from app.scoring import rank_videos
from test_core import NOW, video


class ChannelAnalysisTests(unittest.TestCase):
    def result(self, uploads, candidates=None, subscribers=1000, history_available=True):
        candidates = candidates if candidates is not None else uploads[:1]
        channels = {"channel": Channel("channel", "Creator", subscribers, subscribers is None)}
        history = {"channel": uploads} if history_available else {}
        return {"query": "niche", "days": 30, "searched_at": NOW.isoformat(),
                "videos": rank_videos(candidates, channels, history, NOW),
                "channel_profiles": channel_profiles(candidates, channels, history, NOW, 30)}

    def test_one_large_hit_does_not_raise_typical_views_or_imply_repeat_success(self):
        uploads = [video(f"regular-{i}", 100, 48 + i) for i in range(9)] + [video("hit", 1_000_000, 100)]
        row = analyze_channels(self.result(uploads))["channels"][0]
        self.assertEqual(row["median_views"], 100)
        self.assertGreater(row["top_video_share"], .99)
        self.assertEqual(row["performance_pattern"], "One-hit concentration")
        self.assertEqual(row["evidence"], "Established sample")

    def test_new_future_and_old_uploads_do_not_distort_recent_measured_metrics(self):
        uploads = [video("recent", 10_000, 1), video("measured", 200, 24),
                   video("old", 1_000_000, 800), video("future", 1_000_000, -1)]
        row = analyze_channels(self.result(uploads))["channels"][0]
        self.assertEqual(row["upload_count"], 2)
        self.assertEqual(row["measured_count"], 1)
        self.assertEqual(row["median_views"], 200)
        self.assertEqual(row["performance_pattern"], "Insufficient history")

    def test_duration_filters_do_not_mix_short_candidates_and_long_videos(self):
        short, long, unknown = video("short", 200, 48), video("long", 90000, 48), video("unknown", 80000, 48)
        short.duration_seconds, long.duration_seconds, unknown.duration_seconds = 180, 181, 0
        result = self.result([short, long, unknown])
        self.assertEqual(analyze_channels(result, "short")["channels"][0]["median_views"], 200)
        self.assertEqual(analyze_channels(result, "long")["channels"][0]["median_views"], 90000)
        self.assertEqual(analyze_channels(result, "all")["channels"][0]["measured_count"], 3)

    def test_duplicates_are_removed_and_missing_history_is_not_claimed_as_measured(self):
        one = video(hours=48)
        row = analyze_channels(self.result([one, one]))["channels"][0]
        self.assertEqual(row["measured_count"], 1)
        row = analyze_channels(self.result([one], history_available=False))["channels"][0]
        self.assertEqual(row["upload_count"], 1)
        self.assertEqual(row["measured_count"], 0)
        self.assertIsNone(row["median_views"])

    def test_unknown_subscribers_and_zero_view_concentration_remain_unknown(self):
        report = analyze_channels(self.result([video(views=0, hours=24)], subscribers=None))
        self.assertEqual(report["coverage"]["small_channels"], 0)
        self.assertEqual(report["coverage"]["unknown_subscribers"], 1)
        self.assertIsNone(report["channels"][0]["top_video_share"])
        self.assertIsNone(report["channels"][0]["median_views_to_subscribers"])

    def test_legacy_empty_and_truncated_histories_are_explicit(self):
        self.assertFalse(analyze_channels({})["available"])
        self.assertEqual(analyze_channels(self.result([]))["channels"], [])
        report = analyze_channels(self.result([video(str(i), hours=48 + i) for i in range(50)]))
        self.assertTrue(report["channels"][0]["history_limit_reached"])


class ImprovedScoringTests(unittest.TestCase):
    def test_baseline_filters_duration_class_and_unknown_duration_has_no_baseline(self):
        short, long, unknown = video("short", 100, 20), video("long", 1_000_000, 30), video("unknown", 80000, 40)
        short.duration_seconds, long.duration_seconds, unknown.duration_seconds = 180, 181, 0
        candidate = video(views=1000, hours=10)
        rows = rank_videos([candidate], {}, {"channel": [short, long, unknown]}, NOW)
        self.assertEqual(rows[0]["baseline_count"], 1)
        self.assertEqual(rows[0]["outlier_multiplier"], 10)
        candidate.duration_seconds = 0
        self.assertIsNone(rank_videos([candidate], {}, {"channel": [unknown]}, NOW)[0]["outlier_multiplier"])

    def test_sparse_baseline_is_discounted_and_cannot_flag_breakout(self):
        channels = {"channel": Channel("channel", "Creator", 1000, False)}
        candidates = [video("high", 100_000, 8), video("low", 100, 36)]
        baseline = [video(str(i), 100, 60 + i) for i in range(10)]
        sparse = rank_videos(candidates, channels, {"channel": baseline[:1]}, NOW)[0]
        supported = rank_videos(candidates, channels, {"channel": baseline}, NOW)[0]
        self.assertLess(sparse["breakout_score"], supported["breakout_score"])
        self.assertFalse(sparse["is_breakout"])
        self.assertTrue(supported["is_breakout"])
        candidates[0].published_at = NOW - timedelta(hours=2)
        self.assertFalse(rank_videos(candidates, channels, {"channel": baseline}, NOW)[0]["is_breakout"])

    def test_rate_is_ranked_in_age_cohort_and_tiny_engagement_is_damped(self):
        # Changing an old video's rate cannot alter the young cohort's rate rank.
        young = video("young", 10000, 8)
        old = video("old", 10000, 200)
        a = rank_videos([young, old], {}, {}, NOW)
        old.views = 1000000
        b = rank_videos([young, old], {}, {}, NOW)
        get = lambda rows: next(r for r in rows if r["video_id"] == "young")
        self.assertEqual(get(a)["rate_percentile"], get(b)["rate_percentile"])
        self.assertEqual(get(a)["rate_cohort_count"], 1)
        tiny = rank_videos([video(views=5)], {}, {}, NOW)[0]
        self.assertLess(tiny["engagement_signal"], tiny["engagement"])


class GrowthTests(unittest.TestCase):
    def snapshot(self, hours, views):
        return {"searched_at": (NOW - timedelta(hours=hours)).isoformat(),
                "videos": [{"video_id": "same", "title": "A video", "views": views}]}

    def test_growth_uses_nearest_eligible_capture_not_latest_too_close_or_future(self):
        result = self.snapshot(0, 1000)
        observations = [self.snapshot(4, 100), self.snapshot(-1, 2000), self.snapshot(.5, 900), self.snapshot(2, 600)]
        row = observed_growth(result, observations)[0]
        self.assertEqual(row["interval_hours"], 2)
        self.assertEqual(row["views_gained"], 400)
        self.assertEqual(row["views_per_hour"], 200)

    def test_count_corrections_and_missing_capture_do_not_fabricate_rates(self):
        result = self.snapshot(0, 100)
        self.assertEqual(observed_growth(result, []), [])
        row = observed_growth(result, [self.snapshot(1, 200)])[0]
        self.assertEqual(row["views_gained"], -100)
        self.assertTrue(row["count_correction"])
        self.assertIsNone(row["views_per_hour"])

    def test_empty_statistics_and_publication_counts(self):
        stats = sample_statistics({"videos": [], "searched_at": NOW.isoformat()}, [])
        self.assertEqual(stats["total_views"], 0)
        self.assertIsNone(stats["top_channel_share"])
        row = rank_videos([video(hours=48)], {}, {}, NOW)[0]
        stats = sample_statistics({"videos": [row], "searched_at": NOW.isoformat()}, [])
        self.assertEqual(stats["uploads_by_date"][0]["uploads"], 1)
        self.assertEqual(stats["uploads_by_date"][0]["views"], 1000)


if __name__ == "__main__":
    unittest.main()
