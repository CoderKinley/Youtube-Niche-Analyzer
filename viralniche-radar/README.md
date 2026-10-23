# ViralNiche Radar — today’s MVP

A local research desk for choosing among 2–5 YouTube niches. Python 3.12+, FastAPI, SQLite, httpx, and vanilla HTML/CSS/JavaScript. No build step, account, cloud service, AI dependency, or scheduled jobs.

## Run on Windows

**Double-click `run.bat` in the parent `Niche App` folder.** It creates the environment, installs missing dependencies, starts the backend, waits for its health check to pass, and opens the frontend in your browser. FastAPI serves both the API and frontend, so one server runs the entire app. Keep its window open while using the app. The first launch needs internet access. You can open the dashboard before configuring a YouTube API key; searching requires the key below.

For a manual launch instead:

Open PowerShell in `viralniche-radar`:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Start the app:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Open **http://127.0.0.1:8000**, choose **Settings → YouTube API**, paste your key, and click **Save key**. Return to **Dashboard** to search immediately; no file editing or restart is needed. The **Guide** page contains setup and scoring help. Stop the server with Ctrl+C. No PowerShell activation script is needed. Python 3.12 is the target; a newer Python is also supported by the declared dependencies.

On macOS/Linux use `.venv/bin/python` in place of `.\.venv\Scripts\python.exe`.

The dashboard starts without a key and displays setup instructions. Saved research remains available. Searching requires a real key and internet access; no demonstration videos are substituted.

## Get a YouTube API key

1. Open [Google Cloud Console](https://console.cloud.google.com/) and select or create a project.
2. Go to **APIs & Services → Library**, find **YouTube Data API v3**, and enable it.
3. Go to **APIs & Services → Credentials → Create credentials → API key**.
4. Restrict that key to **YouTube Data API v3**. This app sends requests from Python; website/HTTP-referrer restrictions are unsuitable. Use an IP restriction only if it matches your outbound public IP.
5. Open **Settings → YouTube API**, paste your key, and click **Save key**. It becomes active immediately and remains saved for future launches. To replace it, paste another key into the same field and save again.

The password field sends the key to the local backend, which stores it in the ignored `.env` file. The app never returns the saved key to the browser or stores it in browser storage; the field clears after saving. `.env`, local databases, and virtual environments are ignored by Git. Existing `YOUTUBE_API_KEY` environment/`.env` configuration still works. Key format is checked on save; YouTube validates access when you search.

Quota varies by project and method; consult your [Cloud quota page](https://console.cloud.google.com/apis/api/youtube.googleapis.com/quotas) and [YouTube quota documentation](https://developers.google.com/youtube/v3/determine_quota_cost). Each analysis makes two search requests (popular and newest matches), retrieves statistics in batches of up to 50 IDs, and reads up to 50 recent uploads for each matched channel (up to 100 discovered channels). Duration filtering happens after collection. The two searches are merged and deduplicated. Requests run with at most five in flight. Saved research, comparison, sorting, and exports do not call YouTube. Quota errors are displayed without retrying automatically.

## Use it today

1. Search a niche keyword with a 7-, 14-, or 30-day lookback.
2. Study ranked videos, median channel baselines, outlier multipliers, average views/hour since upload, subscriber sizes, and engagement.
3. Read phrases repeated in at least three videos across at least two channels.
4. Search another 1–4 niches using the same lookback window.
5. Select 2–5 saved searches and click **Compare selected**. Keywords must be distinct and searches must contain results.
6. Open references on YouTube and **Export top 10** to CSV. Exports always use research-score order, regardless of the current table sort.

Searches persist in `data/viralniche.db` (created on startup). Reopening a search restores its original statistics and scores, even if a later search finds the same video with updated views. The latest 50 searches appear on the page.

## Channel Analyzer and Stats

- **Dashboard** stays focused on niche/video research, with a duration filter and links to the current search's Channels and Stats pages.
- **Channels** (`/channels`) filters discovered creators by duration class, visible subscribers, and number of measured uploads. Sort by evidence, median views, lifetime average view rate, or median views per subscriber. Click a channel for sampled uploads and a per-upload chart.
- Typical channel metrics exclude uploads under 24 hours old. Five measured uploads means a developing sample; ten means an established sample. Evidence labels describe sample size, not proven success. Top-video share above 50% flags one-hit concentration. Histories can include topics outside the keyword, and the latest-50 cap is shown explicitly.
- **Stats** (`/stats`) shows creator concentration, duration mix, publication-date charts, and measured view gains between repeated captures at least an hour apart. The latter searches up to 30 earlier overlapping snapshots; negative differences are count corrections. Publication-date charts are not daily growth charts.
- Each page can reopen a saved search without YouTube calls. **Refresh research** creates a new snapshot using quota. Old snapshots remain unchanged; refresh them to enable channel histories. No database schema migration or new dependency is required.

## Similar Channels

Open **Similar** (`/similar`) to browse channels already collected by niche searches. The library deduplicates channels across all saved searches and uses each channel's newest saved sample. Filtering and choosing a reference never contact YouTube. Older snapshots still provide names and matched-video evidence, with unavailable channel metrics left unknown.

Enter a channel name, @handle, channel ID, or modern YouTube channel URL, then click **Find similar**. A display name may require selecting the correct channel. Discovery runs only after this explicit action. Channel Analyzer also links to this page with the reference prefilled, without starting discovery.

- Saved reports are reused per channel and duration class, even without an API key. The saved date remains visible. Select **Refresh existing report** to request new data; refreshing is never automatic.
- A saved reference history is reused when available. New references and explicit refreshes fetch up to 20 recent uploads.
- Discovery derives at most two queries from recurring title words/phrases, searches recent videos, and examines at most 12 candidate channels and their latest 20 uploads within 90 days. It uses the existing five-request concurrency limit. Search requests and other reads consume their respective YouTube quotas; HTTP request count is not a quota-unit estimate.
- Title similarity uses local TF-IDF cosine similarity, with at least two shared informative words and supporting video examples. Generic promotional words are excluded. Performance does not increase the similarity score. This is lexical evidence, not verified audience overlap, storytelling/visual similarity, or a complete competitor list. Synonyms and multilingual titles can be missed.
- A local `related_reports` table is added on startup without changing existing search snapshots. Fresh failed requests do not overwrite saved reports. No paid AI service, new dependency, background search, or automatic refresh is introduced.

## Scoring and limits

**This is a research score, not a prediction that the video will go viral.**

Scoring version 2:

- Duration classes: short candidates (1-180 seconds), long videos (>180 seconds), and unknown. Duration does not verify YouTube Shorts classification.
- Research score: 35% outlier, 30% lifetime average views/hour, 15% engagement, 10% freshness, and 10% small-channel signal. Factors use tie-aware percentile ranks within duration classes. Rate comparisons also use age cohorts: <48h, 48-168h, 168-720h, and older. Singleton/tied factors receive 50; inspect sample size rather than treating a rank as a prediction.
- Outlier: views / max(median views of up to 20 earlier same-class uploads, 1). Unknown duration has no baseline. The outlier contribution is multiplied by min(baseline count / 10, 1), reducing sparse-baseline influence. Baseline counts below 10 are flagged. Cumulative views are not equal-age measurements.
- Average views/hour: views / max(age hours, 1), not current velocity. Stats can separately measure actual gains between saved captures.
- Displayed engagement: (likes + 3 * comments) / max(views, 1). Scoring uses max(views, 1000) to damp tiny samples. Missing counts contribute zero and are marked partial.
- Freshness: 100 through 24h, 90 through 48h, 80 through 72h, 65 through 7d, 40 through 14d, 20 through 30d, then 0, before normalization.
- Small-channel signal: views / max(subscribers, 1), capped at 10, only below 100,000 visible subscribers. Hidden counts remain unknown.
- Breakout requires score >=75, outlier >=2x, at least 5 baseline uploads, at least 1,000 views, and age >=6h. These are provisional research thresholds, not YouTube requirements.
- Phrase lift and distinct-video/creator requirements are unchanged.
- Opportunity: 30% median view-rate percentile, 30% breakout frequency, 20% small-channel breakout rate, 10% independent breakout creators / total creators, and 10% supported-baseline coverage. The former large-channel competition proxy is removed. Comparisons require matching duration filters, lookback windows, and version-2 snapshots.

Results combine up to 50 popular and 50 newest matches, deduplicated. This is a discovery sample, not a census of competitors, a revenue estimate, or proof of low competition. A high relative rank can occur in a weak sample.

## API

| Method | Endpoint | Purpose |
| --- | --- | --- |
| GET | `/api/health` | Server status and whether a key is configured (not key validity) |
| POST | `/api/settings/youtube-key` | Save `{"api_key":"your-generated-key"}` locally and activate it immediately; never returns the key |
| POST | `/api/search` | Analyze `{"query":"funny animation","days":30,"format":"short"}` (API defaults to all formats) |
| GET | `/api/searches` | Latest 50 saved searches |
| GET | `/api/searches/{id}` | Original research snapshot |
| GET | `/api/searches/{id}/channels?format=short` | Channel evidence; format is short, long, or all |
| GET | `/api/searches/{id}/stats` | Sample charts and measured view gains |
| GET | `/api/channel-library` | Deduplicated saved channels and saved report list; no YouTube calls |
| POST | `/api/related-channels` | Explicit discovery: `{"reference":"@handle","format":"short","refresh":false}`; may return channel choices |
| GET | `/api/related-channels/{channel_id}?format=short` | Reopen a saved similarity report; no YouTube calls |
| GET | `/api/compare?ids=1,2,3` | Rank 2–5 selected niches |
| GET | `/api/searches/{id}/export` | Top 10 research references as CSV |

Interactive local API documentation: http://127.0.0.1:8000/docs. Bind to loopback as shown above; the application is intended for one local user.

## Verify

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
node --check frontend/app.js
node --check frontend/research.js
node --check frontend/channels.js
node --check frontend/stats.js
node --check frontend/similar.js
node tests/test_frontend.cjs
```

Core tests also run with the standard library alone: `python -m unittest discover -s tests -p test_core.py -v`. Integration tests use mocked YouTube HTTP responses, spend no quota, and skip clearly if runtime dependencies are absent. Live verification additionally requires your API key.

## References

Inspected [youtube-niche-finder](https://github.com/pandich93/youtube-niche-finder) and [OpenOutlier](https://github.com/theograe/open-outlier); both repository licenses were MIT when checked on 2026-10-23. Their architectures were not ported and no implementation code was copied. Collection follows the official [search](https://developers.google.com/youtube/v3/docs/search/list), [video](https://developers.google.com/youtube/v3/docs/videos/list), [channel](https://developers.google.com/youtube/v3/docs/channels/list), and [uploads playlist](https://developers.google.com/youtube/v3/docs/playlistItems/list) APIs.

Workspace-local implementation skills and their sources are documented in `../skills/README.md`.
