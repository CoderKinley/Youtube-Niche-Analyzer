# Youtube-Niche-Analyzer

A local YouTube research app with a minimal dark red interface. Discover niche videos, study smaller channels, compare saved research, and explicitly find related channels.

## Run

On Windows, double-click **run.bat**. It prepares the Python environment, starts the app, and opens your browser. Add your YouTube Data API key in **Settings → YouTube API**.

## Pages

- **Dashboard:** niche discovery, ranked videos, recurring phrases, and saved comparisons.
- **Channels:** typical performance, evidence size, one-hit concentration, and upload details.
- **Similar:** channels already found in saved searches, plus explicit name/handle/URL searches for related creators. Browsing saved channels and reports makes no YouTube requests.
- **Stats:** sample charts and measured view gains between saved captures.
- **Guide / Settings:** methodology, setup, and API-key management.

Python, FastAPI, SQLite, and vanilla JavaScript. No paid AI service or frontend build step. Public statistics are research signals, not guaranteed virality, revenue, or low competition.

See [setup, methodology, API, and tests](viralniche-radar/README.md). API keys, local databases, test scratch files, and virtual environments are excluded from Git.
