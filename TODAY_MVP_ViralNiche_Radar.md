# ViralNiche Radar — TODAY MVP

**Deadline:** Today, October 23, 2026  
**Goal:** Finish the niche-finder early enough to choose a channel niche, create the channel, and start the first video this evening.

## 1. Today's hard rule

Do not build the full research platform today.

Today's product only needs to answer:

1. What recent videos are unusually successful?
2. Are small channels breaking out in this niche?
3. Which sub-topics/phrases repeat among those breakouts?
4. Which niche looks most promising for me to start today?

Anything that does not help answer those four questions is postponed.

## 2. Build today

### Must have

- YouTube Data API integration
- Search a niche keyword
- Fetch recent videos
- Fetch video statistics
- Fetch channel statistics
- Fetch previous uploads for each candidate channel
- Calculate channel median views
- Calculate outlier multiplier
- Calculate video age
- Calculate average views/hour since upload
- Calculate simple engagement
- Calculate small-channel breakout signal
- Calculate one provisional breakout score
- Extract repeated 1–3 word phrases from titles
- Rank videos
- Rank 2–5 niches manually tested by the user
- Export/display top 10 videos worth manually studying

### Do NOT build today

- historical snapshot engine
- acceleration
- scheduled jobs
- alerts
- React
- PostgreSQL
- Docker
- login
- cloud hosting
- LLM/VLM
- Whisper
- video analysis
- script generation
- thumbnail analysis
- embeddings
- browser extension
- MCP
- multi-user features

## 3. Stack

```text
Python 3.12
FastAPI
SQLite
httpx
Vanilla HTML/CSS/JS
YouTube Data API v3
```

Install:

```text
fastapi
uvicorn[standard]
httpx
python-dotenv
isodate
```

## 4. Simple architecture

```text
YouTube Search
      ↓
Video IDs
      ↓
Video statistics
      ↓
Channel statistics
      ↓
Channel recent uploads
      ↓
Channel median baseline
      ↓
Outlier multiplier
      ↓
Age-adjusted view rate
      ↓
Breakout score
      ↓
Title phrase extraction
      ↓
Dashboard
```

## 5. Core formulas

### Video age

```text
age_hours = (now - published_at) / 3600
```

### Average views/hour

```text
avg_views_per_hour = views / max(age_hours, 1)
```

Label it **Average views/hour since upload**. Do not call it live velocity.

### Channel baseline

Fetch approximately 10–20 previous uploads.

```text
channel_baseline = median(previous_video_views)
```

Use median, not mean.

### Outlier multiplier

```text
outlier_multiplier = current_video_views / max(channel_baseline, 1)
```

Interpretation:

```text
<1x   below normal
1–2x  normal/strong
2–5x  notable
5–10x major outlier
10x+  exceptional relative performance
```

### Engagement

```text
like_rate = likes / views
comment_rate = comments / views
engagement = like_rate + (comment_rate * 3)
```

### Subscriber reach

If subscribers are visible:

```text
views_to_subscribers = views / max(subscribers, 1)
```

Do not use this when subscriber count is hidden.

## 6. Today breakout score

Normalize each factor to 0–100 within the currently collected niche sample.

```text
Breakout Score =
35% outlier multiplier
30% age-adjusted views/hour
15% engagement
10% freshness
10% small-channel signal
```

Suggested labels:

```text
0–39   normal
40–59  interesting
60–74  rising
75–89  breakout candidate
90–100 exceptional anomaly
```

The UI must say:

> This is a research score, not a prediction that the video will go viral.

## 7. Freshness score

```text
0–24h      100
24–48h      90
2–3 days    80
3–7 days    65
7–14 days   40
14–30 days  20
```

## 8. Title phrase discovery

No AI required.

From titles:

1. lowercase
2. strip punctuation
3. remove stop words
4. generate 1-word, 2-word, and 3-word phrases
5. count phrase frequency
6. count unique channels using the phrase
7. calculate frequency among breakout videos

Show only phrases appearing across at least:

```text
3 videos
2 different channels
```

Rank phrases that appear disproportionately in high-breakout videos.

## 9. Dashboard

One page only.

```text
------------------------------------------------------------
VIRALNICHE RADAR

Search niche:
[ funny animation                         ] [Analyze]
------------------------------------------------------------

TOP BREAKOUTS

Score | Age | Views | Views/hr | Outlier | Subs | Video
92      8h    480K     60K       14.1x    18K    ...
87     15h    770K     51K        9.3x    42K    ...
81     22h    310K     14K       11.8x     9K    ...

------------------------------------------------------------

EMERGING PHRASES

giant baby
tiny monster
wrong door
robot prank

------------------------------------------------------------

NICHE SUMMARY

Median recent views:
Median views/hour:
Median outlier:
Small-channel breakouts:
Independent breakout channels:
------------------------------------------------------------
```

## 10. Niche comparison

Analyze 3–5 candidate niches separately.

For each calculate:

```text
median views/hour
median outlier multiplier
number of breakout videos
number of unique breakout channels
number of small-channel breakouts
top phrase concentration
```

Basic opportunity score:

```text
Opportunity =
30% recent view-rate percentile
30% breakout frequency
20% small-channel breakout rate
10% independent creator diversity
10% lower competition
```

The purpose is to rank your candidate niches, not the entire YouTube market.

## 11. Today's implementation order

### Phase 1 — Make it work

Implement:

```text
GET /api/health
POST /api/search
```

Input:

```json
{
  "query": "funny animation",
  "days": 30
}
```

Output real videos.

### Phase 2 — Enrich

For each video obtain:

```text
video_id
title
published_at
views
likes
comments
channel_id
channel_title
subscriber_count
duration
thumbnail
```

Display them.

### Phase 3 — Channel baseline

For promising candidate channels:

1. obtain uploads playlist
2. fetch latest 10–20 uploads
3. retrieve their video stats
4. calculate median views
5. calculate candidate outlier multiplier

### Phase 4 — Rank

Calculate:

```text
age
views/hour
outlier multiplier
engagement
freshness
small-channel signal
breakout score
```

Sort descending by breakout score.

### Phase 5 — Phrases

Run title n-gram extraction.

Display top recurring phrases among breakout videos.

### Phase 6 — Compare niches

Manually run approximately:

```text
3–5 searches
```

Choose the winner.

STOP CODING.

## 12. Minimum SQLite tables

Only four tables are needed today.

```sql
CREATE TABLE videos (
    video_id TEXT PRIMARY KEY,
    channel_id TEXT NOT NULL,
    title TEXT NOT NULL,
    published_at TEXT NOT NULL,
    duration_seconds INTEGER,
    thumbnail_url TEXT,
    views INTEGER,
    likes INTEGER,
    comments INTEGER,
    first_seen_at TEXT NOT NULL
);

CREATE TABLE channels (
    channel_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    subscribers INTEGER,
    subscribers_hidden INTEGER NOT NULL DEFAULT 0,
    uploads_playlist_id TEXT,
    median_recent_views REAL
);

CREATE TABLE searches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    query TEXT NOT NULL,
    searched_at TEXT NOT NULL
);

CREATE TABLE search_videos (
    search_id INTEGER NOT NULL,
    video_id TEXT NOT NULL,
    breakout_score REAL,
    outlier_multiplier REAL,
    avg_views_per_hour REAL,
    PRIMARY KEY(search_id, video_id)
);
```

## 13. File structure

```text
viralniche-radar/
├── README.md
├── requirements.txt
├── .env
├── app/
│   ├── main.py
│   ├── youtube.py
│   ├── database.py
│   ├── scoring.py
│   ├── keywords.py
│   └── models.py
├── frontend/
│   ├── index.html
│   ├── app.js
│   └── styles.css
└── data/
    └── viralniche.db
```

## 14. Reference repositories

Inspect these before reinventing functionality:

```text
https://github.com/pandich93/youtube-niche-finder
https://github.com/theograe/open-outlier
```

Verify current licenses before reusing code.

Use them primarily for:

```text
YouTube API patterns
channel upload retrieval
outlier logic
data-model ideas
```

Do not port their full architectures.

## 15. Prompt for ChatGPT/Codex

```text
Read README.md completely.

This project must be usable TODAY.

Do not implement anything in the "Do NOT build today" section.

First inspect:

https://github.com/pandich93/youtube-niche-finder
https://github.com/theograe/open-outlier

Verify licenses before copying code.

Build the application vertically:

1. FastAPI project
2. SQLite initialization
3. YouTube API client
4. search one niche
5. retrieve video stats
6. retrieve channel stats
7. retrieve recent channel uploads
8. calculate median channel baseline
9. calculate outlier multiplier
10. calculate age-adjusted views/hour
11. calculate simple breakout score
12. extract recurring title n-grams
13. render everything on one local webpage

Use:
Python 3.12 + FastAPI + SQLite + vanilla HTML/CSS/JS.

Do not use:
React, Docker, PostgreSQL, Redis, LLMs, VLMs, Whisper,
FFmpeg, embeddings, cloud services, authentication or MCP.

Keep the program runnable after every step.

Prioritize functionality over architecture and styling.

When the dashboard successfully ranks real YouTube results,
STOP feature development and report how to run it.
```

## 16. When to stop coding

Stop when the program can show:

```text
Top breakout videos
+
Outlier multiplier
+
Age-adjusted views/hour
+
Channel size
+
Recurring title phrases
+
Comparison of your 3–5 chosen niches
```

That is sufficient for today's decision.

## 17. Evening channel workflow

Once the software works:

1. Test 3–5 niches.
2. Save the top 10–20 breakout videos.
3. Manually watch them.
4. For each manually note:
   - hook
   - setup
   - rising action
   - conflict
   - false recovery
   - second escalation
   - payoff
   - ending
5. Look for a repeated mechanism, not a video to clone.
6. Choose:
   - channel niche
   - main character/style
   - channel name
   - profile image
   - banner
   - first concept
7. Create the channel.
8. Start producing the first video.

Do not return to software development unless something is actually blocking the content decision.

## 18. Tomorrow/later

Only after channel creation should you add:

```text
historical snapshots
true observed velocity
acceleration
automatic refresh
alerts
better keyword trend history
regional comparison
```

# Today's success condition

By this evening you should have:

```text
✓ working local niche radar
✓ chosen niche
✓ list of reference videos
✓ list of promising content patterns
✓ channel created
✓ first video concept selected
```

The software does not need to be perfect.

It needs to get you to the first upload.
