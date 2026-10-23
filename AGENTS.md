# Project workflow

- Build the local MVP in `viralniche-radar` according to `TODAY_MVP_ViralNiche_Radar.md`. Keep FastAPI/SQLite/vanilla JavaScript and bounded scope. The user has requested separate Dashboard, API Settings, and Guide pages with a minimal dark charcoal and deep red theme. Use their selected minimal niche-discovery symbol for the logo; preserve this direction unless they change it.
- For nontrivial implementation, load `skills/karpathy-guidelines/SKILL.md` once per conversation. Before completion claims, load `skills/verification-before-completion/SKILL.md` if not already loaded. These workspace copies are the project’s installed skills; do not fetch them again each turn.
- Prefer direct implementation, small modules, batched reads, and concise progress reports. Load only references needed for the current change.
- From `viralniche-radar`, run `python -m unittest discover -s tests -v` for relevant backend changes and `node --check frontend/app.js` for JavaScript changes. Report skipped integration tests and missing live API verification explicitly.
- Keep API keys in `.env`, never in chat, frontend code, logs, or tracked files. Do not replace live results with sample data.
