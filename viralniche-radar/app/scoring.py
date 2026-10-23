"""Provisional research signals. All normalizations use the current sample."""

from bisect import bisect_left, bisect_right
from datetime import datetime, timezone
from statistics import median

from .models import Channel, Video

SMALL_CHANNEL_LIMIT = 100_000
BREAKOUT_THRESHOLD = 75
SCORING_VERSION = 2


def format_group(seconds: int) -> str:
    """Duration is a research proxy, not confirmation that YouTube classifies a Short."""
    return "unknown" if seconds <= 0 else "short" if seconds <= 180 else "long"


def age_group(hours: float) -> int:
    return 0 if hours < 48 else 1 if hours < 168 else 2 if hours <= 720 else 3


def percentiles(values: list[float]) -> list[float]:
    """Tie-aware percentile ranks; identical samples get neutral scores."""
    ordered = sorted(values)
    if len(set(ordered)) <= 1:
        return [50.0] * len(values)
    return [
        100 * (bisect_left(ordered, v) + (bisect_right(ordered, v) - bisect_left(ordered, v) - 1) / 2)
        / (len(values) - 1)
        for v in values
    ]


def freshness(age_hours: float) -> int:
    for hours, score in ((24, 100), (48, 90), (72, 80), (168, 65), (336, 40), (720, 20)):
        if age_hours <= hours:
            return score
    return 0


def score_label(score: float) -> str:
    if score >= 90:
        return "exceptional anomaly"
    if score >= 75:
        return "breakout candidate"
    if score >= 60:
        return "rising"
    if score >= 40:
        return "interesting"
    return "normal"


def rank_videos(
    videos: list[Video], channels: dict[str, Channel], uploads: dict[str, list[Video]],
    now: datetime | None = None,
) -> list[dict]:
    now = now or datetime.now(timezone.utc)
    rows = []
    for video in videos:
        channel = channels.get(video.channel_id, Channel(video.channel_id, "Unavailable channel"))
        # Compare only with uploads published BEFORE this candidate, never with itself or later hits.
        previous = sorted(
            (v for v in uploads.get(video.channel_id, [])
             if v.video_id != video.video_id and v.published_at < video.published_at
             and format_group(v.duration_seconds) == format_group(video.duration_seconds)
             and format_group(video.duration_seconds) != "unknown"),
            key=lambda v: v.published_at, reverse=True,
        )[:20]
        baseline = median(v.views for v in previous) if previous else None
        age = max((now - video.published_at).total_seconds() / 3600, 0)
        subscribers = None if channel.subscribers_hidden else channel.subscribers
        reach = video.views / max(subscribers, 1) if subscribers is not None else None
        small = subscribers is not None and subscribers < SMALL_CHANNEL_LIMIT
        outlier = video.views / max(baseline, 1) if baseline is not None else None
        rows.append({
            "video_id": video.video_id, "channel_id": video.channel_id, "title": video.title,
            "published_at": video.published_at.isoformat(), "views": video.views,
            "likes": video.likes, "comments": video.comments,
            "duration_seconds": video.duration_seconds, "thumbnail_url": video.thumbnail_url,
            "channel_title": channel.title, "subscriber_count": subscribers,
            "subscribers_hidden": channel.subscribers_hidden, "channel_baseline": baseline,
            "baseline_count": len(previous), "outlier_multiplier": outlier,
            "format_group": format_group(video.duration_seconds),
            "baseline_confidence": min(len(previous) / 10, 1),
            "age_hours": age, "avg_views_per_hour": video.views / max(age, 1),
            "engagement": ((video.likes or 0) + 3 * (video.comments or 0)) / max(video.views, 1),
            "engagement_incomplete": video.likes is None or video.comments is None,
            "engagement_signal": ((video.likes or 0) + 3 * (video.comments or 0)) / max(video.views, 1000),
            "freshness": freshness(age), "views_to_subscribers": reach,
            "small_channel": small, "small_channel_signal": min(reach or 0, 10) if small else 0,
        })
    if not rows:
        return []
    # Missing baselines/hidden subscribers receive zero for that factor, not fabricated measurements.
    factors = (("outlier_multiplier", .35), ("avg_views_per_hour", .30),
               ("engagement_signal", .15), ("freshness", .10), ("small_channel_signal", .10))
    for row in rows:
        row["breakout_score"] = 0.0
    for field, weight in factors:
        eligible = [row for row in rows if row[field] is not None and
                    (field != "small_channel_signal" or row["small_channel"])]
        groups = {}
        for row in eligible:
            # Compare rates with similarly aged videos of the same duration class.
            cohort = (row["format_group"], age_group(row["age_hours"]) if field == "avg_views_per_hour" else None)
            groups.setdefault(cohort, []).append(row)
        for group in groups.values():
            for row, normalized in zip(group, percentiles([r[field] for r in group])):
                if field == "avg_views_per_hour":
                    row["rate_cohort_count"] = len(group)
                    row["rate_percentile"] = normalized
                confidence = row["baseline_confidence"] if field == "outlier_multiplier" else 1
                row["breakout_score"] += normalized * weight * confidence
    for row in rows:
        row["breakout_score"] = round(row["breakout_score"], 1)
        row["score_label"] = score_label(row["breakout_score"])
        # Require measured relative performance in addition to the sample-relative score.
        row["is_breakout"] = (row["breakout_score"] >= BREAKOUT_THRESHOLD
                              and (row["outlier_multiplier"] or 0) >= 2
                              and row["baseline_count"] >= 5 and row["views"] >= 1000
                              and row["age_hours"] >= 6)
        row["evidence_note"] = ("Too early: under 6 hours" if row["age_hours"] < 6 else
                                "Limited baseline" if row["baseline_count"] < 5 else
                                "Small view sample" if row["views"] < 1000 else
                                "Developing baseline" if row["baseline_count"] < 10 else "Supported baseline")
        row["small_channel_breakout"] = row["is_breakout"] and row["small_channel"]
    return sorted(rows, key=lambda r: (r["breakout_score"], r["avg_views_per_hour"]), reverse=True)


def summarize(rows: list[dict], phrases: list[dict]) -> dict:
    def middle(field: str):
        values = [r[field] for r in rows if r[field] is not None]
        return median(values) if values else None

    channels = {r["channel_id"] for r in rows}
    breakout_channels = {r["channel_id"] for r in rows if r["is_breakout"]}
    known_subscribers = [r for r in rows if r["subscriber_count"] is not None]
    return {
        "video_count": len(rows), "channel_count": len(channels),
        "median_recent_views": middle("views"), "median_views_per_hour": middle("avg_views_per_hour"),
        "median_outlier_multiplier": middle("outlier_multiplier"),
        "breakout_videos": sum(r["is_breakout"] for r in rows),
        "independent_breakout_channels": len(breakout_channels),
        "small_channel_breakouts": sum(r["small_channel_breakout"] for r in rows),
        "baseline_coverage": sum(r["baseline_count"] >= 5 for r in rows),
        "top_phrase_concentration": max((p["video_count"] for p in phrases), default=0) / max(len(rows), 1),
        "large_channel_share": (sum(r["subscriber_count"] >= SMALL_CHANNEL_LIMIT for r in known_subscribers)
                                / len(known_subscribers)) if known_subscribers else None,
    }


def compare_niches(searches: list[dict]) -> list[dict]:
    """Compare evidence of performance; creator size is not a competition estimate."""
    if not searches:
        return []
    rates = percentiles([s["summary"]["median_views_per_hour"] or 0 for s in searches])
    results = []
    for search, rate in zip(searches, rates):
        summary = search["summary"]
        count = max(summary["video_count"], 1)
        components = {
            "recent_view_rate": rate,
            "breakout_frequency": 100 * summary["breakout_videos"] / count,
            "small_channel_breakout_rate": 100 * summary["small_channel_breakouts"] / count,
            "creator_diversity": 100 * summary["independent_breakout_channels"] / max(summary["channel_count"], 1),
            "baseline_coverage": 100 * summary["baseline_coverage"] / count,
        }
        score = sum(components[k] * w for k, w in zip(components, (.3, .3, .2, .1, .1)))
        results.append({"search_id": search["id"], "query": search["query"], "days": search["days"],
                        "summary": summary, "opportunity_score": round(score, 1), "components": components})
    return sorted(results, key=lambda r: r["opportunity_score"], reverse=True)
