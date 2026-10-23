"""Bounded, explicit related-channel discovery using public title evidence."""

import asyncio
import math
import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from urllib.parse import unquote, urlsplit

from .analysis import analyze_channels, channel_profiles
from .keywords import STOP_WORDS
from .scoring import format_group
from .youtube import YouTubeError

EXTRA_STOP = {"viral", "trending", "subscribe", "like", "watch", "channel", "shortsfeed", "fyp", "www", "com", "http", "https"}


def words(title):
    return [word for word in re.findall(r"[^\W_]+", title.casefold())
            if len(word) > 2 and not word.isdigit() and word not in STOP_WORDS | EXTRA_STOP]


def topic_counts(videos):
    counts = Counter()
    for video in videos:
        counts.update(set(words(video["title"])))
    return counts


def saved_channels(snapshots):
    library = {}
    for snapshot in snapshots:
        report = analyze_channels(snapshot, "all")
        if report["available"]:
            profiles = report["channels"]
        else:
            # Older snapshots still provide channel names and matched videos; do not
            # invent complete upload histories or typical channel performance.
            profiles = []
            for video in snapshot["videos"]:
                if not any(row["channel_id"] == video["channel_id"] for row in profiles):
                    profiles.append({"channel_id": video["channel_id"], "title": video["channel_title"],
                                     "subscribers": video["subscriber_count"], "median_views": None,
                                     "measured_count": 0, "upload_history_available": False,
                                     "videos": [v for v in snapshot["videos"] if v["channel_id"] == video["channel_id"]]})
        for profile in profiles:
            cid = profile["channel_id"]
            if cid not in library:
                videos = profile["videos"]
                library[cid] = {**profile, "search_id": snapshot["id"], "captured_at": snapshot["searched_at"],
                                "window_days": snapshot["days"], "niches": [],
                                "topics": [word for word, _ in topic_counts(videos).most_common(6)],
                                "short_share": sum(format_group(v["duration_seconds"]) == "short" for v in videos) / len(videos) if videos else None}
            if snapshot["query"] not in library[cid]["niches"]:
                library[cid]["niches"].append(snapshot["query"])
    return list(library.values())


def public_profile(profile):
    return {key: value for key, value in profile.items() if key != "videos"}


def parse_reference(reference):
    reference = reference.strip()
    if "://" in reference or reference.lower().startswith(("youtube.com/", "www.youtube.com/", "m.youtube.com/")):
        parsed = urlsplit(reference if "://" in reference else "https://" + reference)
        if parsed.scheme not in {"https", "http"} or parsed.hostname not in {"youtube.com", "www.youtube.com", "m.youtube.com"}:
            raise ValueError("Use a YouTube channel URL, @handle, channel ID, or channel name.")
        parts = [unquote(part) for part in parsed.path.split("/") if part]
        if parts and parts[0].startswith("@"):
            reference = parts[0]
        elif len(parts) >= 2 and parts[0] == "channel":
            reference = parts[1]
            if not re.fullmatch(r"UC[\w-]{22}", reference, re.ASCII):
                raise ValueError("That channel URL does not contain a valid channel ID.")
        else:
            raise ValueError("Use the channel's @handle or /channel/ URL, rather than a video or legacy custom URL.")
    if reference.startswith("@"):
        if len(reference) < 2 or any(char.isspace() or char in "/?#" for char in reference):
            raise ValueError("Enter a valid @handle.")
        return "handle", reference.casefold()
    if re.fullmatch(r"UC[\w-]{22}", reference, re.ASCII):
        return "id", reference
    return "name", reference


def discovery_queries(videos):
    counts = topic_counts(videos)
    pairs = Counter()
    for video in videos:
        tokens = words(video["title"])
        pairs.update(set(" ".join(tokens[i:i + 2]) for i in range(len(tokens) - 1) if tokens[i] != tokens[i + 1]))
    queries = [pair for pair, count in pairs.most_common() if count >= 2][:2]
    top = [word for word, _ in counts.most_common(6)]
    for start in (0, 2):
        query = " ".join(top[start:start + 2])
        if query and query not in queries and len(queries) < 2:
            queries.append(query)
    return queries


def rank_related(reference, candidates, video_format):
    def selected(profile):
        return [v for v in profile["videos"] if video_format == "all" or format_group(v["duration_seconds"]) == video_format]
    reference_videos = selected(reference)
    reference_counts = topic_counts(reference_videos)
    rows = [(profile, selected(profile)) for profile in candidates if profile["channel_id"] != reference["channel_id"]]
    counters = [reference_counts] + [topic_counts(videos) for _, videos in rows]
    documents = Counter(word for counts in counters for word in counts)
    idf = {word: 1 + math.log((1 + len(counters)) / (1 + count)) for word, count in documents.items()}

    def vector(counts):
        values = {word: (1 + math.log(count)) * idf[word] for word, count in counts.items()}
        length = math.sqrt(sum(value * value for value in values.values()))
        return {word: value / length for word, value in values.items()} if length else {}

    origin = vector(reference_counts)
    result = []
    for (profile, videos), counts in zip(rows, counters[1:]):
        shared = sorted(set(counts) & set(reference_counts), key=lambda w: (-min(counts[w], reference_counts[w]), w))
        if len(shared) < 2:
            continue
        matches = [v for v in videos if len(set(words(v["title"])) & set(shared)) >= 2]
        if not matches:
            continue
        candidate = vector(counts)
        score = 100 * sum(weight * candidate.get(word, 0) for word, weight in origin.items())
        result.append({**public_profile(profile), "similarity": round(min(score, 100), 1),
                       "shared_topics": shared[:8], "matching_uploads": len(matches), "sampled_uploads": len(videos),
                       "match_evidence": "Repeated title overlap" if len(matches) >= 3 else "Limited title overlap",
                       "examples": [{"video_id": v["video_id"], "title": v["title"]} for v in matches[:3]]})
    return sorted(result, key=lambda r: (r["similarity"], r["matching_uploads"]), reverse=True)


async def resolve_channel(youtube, kind, reference):
    if kind == "id":
        return reference, None
    if kind == "handle":
        response = await youtube.get("channels", part="snippet", forHandle=reference)
        if not response.get("items"):
            raise YouTubeError("No channel found for that handle.", 404)
        return response["items"][0]["id"], None
    response = await youtube.get("search", part="snippet", type="channel", q=reference, maxResults=5)
    choices = [{"channel_id": item["id"]["channelId"], "title": item["snippet"]["title"],
                "description": item["snippet"].get("description", "")[:200]}
               for item in response.get("items", []) if item.get("id", {}).get("channelId")]
    if not choices:
        raise YouTubeError("No channels found. Try an @handle or channel URL.", 404)
    return None, choices


async def discover_related(youtube, channel_id, video_format, seed=None):
    now = datetime.now(timezone.utc)
    if seed is None or not seed.get("upload_history_available"):
        channels = await youtube.channels([channel_id])
        if channel_id not in channels:
            raise YouTubeError("This channel is unavailable.", 404)
        uploads, warnings = await youtube.uploads(channels, max_results=20)
        videos = uploads.get(channel_id, [])
        snapshot = {"days": 90, "channel_profiles": channel_profiles(videos[:1], channels, uploads, now, 90)}
        profiles = analyze_channels(snapshot, "all")["channels"]
        if not profiles:
            raise YouTubeError("No recent public uploads to analyze for this channel.", 422)
        seed = {**profiles[0], "captured_at": now.isoformat(), "window_days": 90}
    else:
        warnings = []
    seed_videos = [v for v in seed["videos"] if video_format == "all" or format_group(v["duration_seconds"]) == video_format][:20]
    queries = discovery_queries(seed_videos)
    if not queries:
        raise YouTubeError("Not enough title evidence in this duration class. Try All formats or refresh the channel.", 422)
    pages = await asyncio.gather(*(youtube.get("search", part="snippet", type="video", q=query,
        maxResults=25, order="relevance", publishedAfter=(now - timedelta(days=90)).isoformat(),
        publishedBefore=now.isoformat()) for query in queries))
    # Round-robin results so one query cannot consume the whole candidate budget.
    ids = []
    for index in range(25):
        for page in pages:
            items = page.get("items", [])
            if index < len(items):
                cid = items[index].get("snippet", {}).get("channelId")
                if cid and cid != channel_id and cid not in ids:
                    ids.append(cid)
    ids = ids[:12]
    channels = await youtube.channels(ids)
    uploads, candidate_warnings = await youtube.uploads(channels, max_results=20)
    warnings.extend(candidate_warnings)
    anchors = [items[0] for items in uploads.values() if items]
    snapshot = {"days": 90, "channel_profiles": channel_profiles(anchors, channels, uploads, now, 90)}
    # Metrics and similarity use the same requested duration class.
    profiles = analyze_channels(snapshot, video_format)["channels"]
    matches = rank_related({**seed, "videos": seed_videos}, profiles, video_format)
    return {"reference": public_profile(seed), "format": video_format, "searched_at": now.isoformat(),
            "queries": queries, "channels": matches, "examined_channels": len(channels),
            "warnings": warnings, "api_requests": youtube.request_count,
            "note": "Title similarity is a lexical research signal, not verified audience overlap, visual style, or low competition. "
                    "Discovery checks up to 12 channels and their latest 20 uploads within 90 days. "
                    "Performance statistics are separate from similarity. Reference titles may come from saved research."}
