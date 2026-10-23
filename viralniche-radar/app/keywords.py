"""Title n-grams, counted once per video and across independent channels."""

import re
from collections import defaultdict

STOP_WORDS = set("""a an the and or but if then than to of in on at by for from with without
is are was were be been being it its this that these those i me my we our you your he she
his her they their them as so not no yes do does did done how what why when where who
which will would can could should just very more most new video videos official shorts
short youtube part episode ft vs""".split())


def extract_phrases(rows: list[dict]) -> list[dict]:
    occurrences: dict[str, list[dict]] = defaultdict(list)
    total_breakouts = sum(row["is_breakout"] for row in rows)
    for row in rows:
        words = [w for w in re.findall(r"[^\W_]+", row["title"].lower(), re.UNICODE)
                 if w not in STOP_WORDS and not w.isdigit()]
        phrases = {" ".join(words[i:i + size]) for size in (1, 2, 3)
                   for i in range(len(words) - size + 1)}
        for phrase in phrases:
            occurrences[phrase].append(row)
    results = []
    for phrase, videos in occurrences.items():
        channels = {v["channel_id"] for v in videos}
        if len(videos) < 3 or len(channels) < 2:
            continue
        breakouts = sum(v["is_breakout"] for v in videos)
        sample_rate = total_breakouts / max(len(rows), 1)
        lift = (breakouts / len(videos)) / sample_rate if sample_rate else 0
        results.append({"phrase": phrase, "video_count": len(videos), "channel_count": len(channels),
                        "breakout_count": breakouts, "breakout_frequency": breakouts / len(videos),
                        "breakout_lift": round(lift, 2)})
    return sorted(results, key=lambda p: (-p["breakout_lift"], -p["breakout_count"],
                                         -p["channel_count"], -p["video_count"], p["phrase"]))[:30]
