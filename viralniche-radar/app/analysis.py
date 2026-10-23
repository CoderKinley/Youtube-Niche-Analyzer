"""Channel evidence from bounded upload samples; no market-wide competition claims."""

from collections import Counter
from datetime import datetime, timedelta
from statistics import median

from .scoring import format_group


def channel_profiles(candidates, channels, uploads, now, days):
    cutoff = now - timedelta(days=days)
    matched = Counter(v.channel_id for v in candidates)
    profiles = []
    for channel_id, matches in matched.items():
        channel = channels.get(channel_id)
        history = {v.video_id: v for v in uploads.get(channel_id, [])}
        # A matched candidate can fall outside the channel's latest 50 uploads.
        history.update({v.video_id: v for v in candidates if v.channel_id == channel_id})
        recent = sorted((v for v in history.values() if cutoff <= v.published_at <= now),
                        key=lambda v: v.published_at, reverse=True)
        samples = [{"video_id": v.video_id, "title": v.title, "views": v.views,
                    "published_at": v.published_at.isoformat(), "duration_seconds": v.duration_seconds,
                    "age_hours": (now - v.published_at).total_seconds() / 3600,
                    "format_group": format_group(v.duration_seconds)} for v in recent]
        known = bool(channel and not channel.subscribers_hidden and channel.subscribers is not None)
        profiles.append({
            "channel_id": channel_id, "title": channel.title if channel else "Unavailable channel",
            "subscribers": channel.subscribers if known else None, "matched_videos": matches,
            "upload_history_available": bool(uploads.get(channel_id)),
            "history_limit_reached": len(uploads.get(channel_id, [])) >= 50,
            "videos": samples,
        })
    return profiles


def analyze_channels(result, video_format="short"):
    profiles = result.get("channel_profiles")
    if profiles is None:
        return {"available": False, "channels": [], "coverage": {},
                "note": "Refresh this search to collect channel histories. Older saved research is unchanged."}
    rows = []
    for profile in profiles:
        videos = [v for v in profile["videos"] if video_format == "all" or v["format_group"] == video_format]
        if not videos:
            continue
        # New uploads have not had the same time to accumulate views. Keep them visible,
        # but exclude the first 24 hours from typical-performance and concentration metrics.
        measured = [v for v in videos if v["age_hours"] >= 24] if profile["upload_history_available"] else []
        views = [v["views"] for v in measured]
        total = sum(views)
        typical = median(views) if views else None
        top_share = max(views) / total if total else None
        supported = len(measured) >= 5
        rows.append({**{k: v for k, v in profile.items() if k != "videos"},
                     "videos": videos, "upload_count": len(videos), "measured_count": len(measured),
                     "median_views": typical,
                     "median_views_per_hour": median(v["views"] / v["age_hours"] for v in measured) if measured else None,
                     "median_views_to_subscribers": typical / profile["subscribers"]
                     if typical is not None and profile["subscribers"] else None,
                     "top_video_share": top_share,
                     "uploads_per_week": len(videos) * 7 / result["days"],
                     "evidence": "Established sample" if len(measured) >= 10 else "Developing sample" if supported else "Limited sample",
                     "performance_pattern": "Insufficient history" if not supported else
                     "No measured views" if not total else
                     "One-hit concentration" if top_share is not None and top_share > .5 else "Spread across uploads",
                     "supported": supported})
    rows.sort(key=lambda row: (row["supported"], row["median_views"] or 0), reverse=True)
    known = [r for r in rows if r["subscribers"] is not None]
    return {"available": True, "channels": rows,
            "coverage": {"discovered_channels": len(rows), "supported_channels": sum(r["supported"] for r in rows),
                         "small_channels": sum(r["subscribers"] < 100_000 for r in known),
                         "unknown_subscribers": len(rows) - len(known)},
            "note": "Discovery sample, not a count of competitors. Channel metrics include all sampled uploads in this duration class, "
                    "including topics outside your keyword. Typical views exclude uploads under 24 hours; "
                    "ages still vary. Short candidates (up to 3 minutes) are not confirmed YouTube Shorts."}


def sample_statistics(result, observations):
    videos = result["videos"]
    creators = Counter(v["channel_id"] for v in videos)
    totals = Counter()
    daily = {}
    formats = Counter()
    for video in videos:
        totals[video["channel_id"]] += video["views"]
        formats[format_group(video["duration_seconds"])] += 1
        day = video["published_at"][:10]
        entry = daily.setdefault(day, {"date": day, "uploads": 0, "views": 0})
        entry["uploads"] += 1
        entry["views"] += video["views"]
    overall = sum(totals.values())
    titles = {v["channel_id"]: v["channel_title"] for v in videos}
    return {"video_count": len(videos), "channel_count": len(creators),
            "total_views": overall,
            "top_channel_share": max(totals.values()) / overall if overall else None,
            "baseline_supported": sum(v["baseline_count"] >= 5 for v in videos),
            "formats": [{"format": key, "videos": formats[key]} for key in ("short", "long", "unknown")],
            "channel_views": [{"channel_id": cid, "title": titles[cid], "views": count,
                               "videos": creators[cid]} for cid, count in totals.most_common()],
            "uploads_by_date": [daily[day] for day in sorted(daily)],
            "growth": observed_growth(result, observations),
            "note": "Charts describe the saved discovery sample. Upload dates are not a history of daily views. "
                    "Public views do not establish monetization eligibility, revenue, or audience retention."}


def observed_growth(result, observations):
    captured = datetime.fromisoformat(result["searched_at"])
    previous = {}
    # Only earlier captures with a useful interval; never use a later search for a historical report.
    for snapshot in observations:
        hours = (captured - datetime.fromisoformat(snapshot["searched_at"])).total_seconds() / 3600
        if hours < 1:
            continue
        for video in snapshot["videos"]:
            existing = previous.get(video["video_id"])
            if existing is None or hours < existing["hours"]:
                previous[video["video_id"]] = {"hours": hours, "views": video["views"],
                                               "captured_at": snapshot["searched_at"]}
    rows = []
    for video in result["videos"]:
        earlier = previous.get(video["video_id"])
        if earlier is None:
            continue
        gained = video["views"] - earlier["views"]
        rows.append({"video_id": video["video_id"], "title": video["title"],
                     "previous_at": earlier["captured_at"], "captured_at": result["searched_at"],
                     "interval_hours": earlier["hours"], "views_gained": gained,
                     "views_per_hour": gained / earlier["hours"] if gained >= 0 else None,
                     "count_correction": gained < 0})
    return sorted(rows, key=lambda row: row["views_per_hour"] if row["views_per_hour"] is not None else -1, reverse=True)
