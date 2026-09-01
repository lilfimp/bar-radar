# BAR RADAR — Venue Discovery & Menu Finder (Phase 1)

Builds a validated list of ~1,000 active German bar venues, each with a working
drinks-menu URL, at €0 recurring cost. Runs as scheduled batches via GitHub
Actions, writing to SQLite and exporting CSV.

## 1. Architecture

```
 ┌────────────┐   ┌──────────┐   ┌───────────────┐   ┌──────────────┐   ┌────────┐
 │ Discovery  │→│ Dedupe   │→│ Website Find  │→│ Menu Crawl + │→│ Export │
 │ (Overpass) │   │          │   │ + Verify      │   │ Validate     │   │ CSV    │
 └────────────┘   └──────────┘   └───────────────┘   └──────────────┘   └────────┘
        │                                                     │
        └───────────────────── SQLite (single source of truth) ─────┘
```

- **Discovery** (`src/discovery/`): pulls candidate venues from OpenStreetMap
  via the Overpass API — free, no key, structured data (name, coords,
  address, sometimes website).
- **Dedupe**: fuzzy name + geo-proximity match removes near-duplicate OSM
  entries before they ever hit the DB.
- **Enrichment** (`src/enrichment/`): finds the venue's website (OSM tag,
  else a free DuckDuckGo HTML search fallback), crawls it for menu-looking
  links (HTML page / PDF / image / external platform), then fetches and
  scores the best candidate for actual drinks content.
- **SQLite** (`db/`): one file, no server, trivially portable, cheap to
  commit as CSV snapshots. Schema is Phase-2-ready (see §3).
- **Orchestration** (`src/pipeline/`): three CLI entrypoints — discovery
  batch, enrichment batch, CSV export — each idempotent and safe to re-run.
- **GitHub Actions** (`.github/workflows/`): discovery runs twice daily
  (cheap), enrichment runs every 4 hours in batches of ~75 (does the HTTP-
  heavy work), both commit updated CSV exports back to the repo.

No paid APIs, no proxies, no persistent server. Playwright is wired in as an
optional dependency only, for a future JS-heavy-site fallback — not required
for the baseline pipeline to work.

## 2. Free data sources

| Source | Use | Notes |
|---|---|---|
| **Overpass API** (OpenStreetMap) | Primary discovery: `amenity=bar/pub`, `cuisine~cocktail` inside each city's administrative boundary | No key, generous for polite/batched use, includes many `website` tags already |
| **DuckDuckGo HTML search** (`html.duckduckgo.com/html/`) | Fallback website lookup when OSM has no website tag | No key; used sparingly, only for venues missing a website |
| Venue's own website | Menu discovery (HTML links, PDFs, images, external menu platforms) | requests + BeautifulSoup; PDF text via `pypdf` |
| *(optional, not yet wired)* City tourism boards / Wikivoyage nightlife lists | Extra discovery coverage in Tier 2/3 cities where OSM density is thinner | Left as a hook — site-specific scrapers only pay off if OSM under-delivers for a given city |

## 3. Database schema

Phase 1 tables (used now) + Phase 2 scaffolding (empty, ready for the next
stage) — see `db/schema.sql` for the authoritative DDL.

```
venues            venue_id PK, venue_name, city, tier, category, address,
                  latitude, longitude, osm_type, osm_id, website_url,
                  website_status, discovery_source, discovery_query,
                  venue_confidence, status, created_at, updated_at

menu_sources      menu_source_id PK, venue_id FK, menu_url,
                  menu_source_type, menu_status, menu_confidence,
                  discovered_at, last_checked_at, is_primary

manual_review     review_id PK, venue_id FK, stage, reason, created_at, resolved

-- Phase 2 (empty scaffolding today):
menu_snapshots    snapshot_id PK, menu_source_id FK, captured_at,
                  content_hash, raw_content_path, status
menu_items        item_id PK, snapshot_id FK, item_name, item_category,
                  price, raw_text
brand_mentions    mention_id PK, item_id FK, brand_name, confidence
change_events     event_id PK, venue_id FK, event_type, detected_at, details
```

`v_export` is a SQL view joining `venues` + primary `menu_sources` into
exactly the columns the spec requires — `export.py` just selects from it.

## 4. Repo structure

```
bar-radar/
├── README.md
├── requirements.txt
├── .gitignore
├── config/
│   ├── cities.yaml          # tier/quota config (edit this to change targets)
│   └── settings.yaml        # keywords, thresholds, batch sizes, HTTP config
├── db/
│   ├── schema.sql
│   └── database.py          # all SQLite access goes through here
├── src/
│   ├── discovery/
│   │   ├── overpass_source.py
│   │   └── dedupe.py
│   ├── enrichment/
│   │   ├── website_finder.py
│   │   ├── menu_crawler.py
│   │   └── menu_validator.py
│   ├── pipeline/
│   │   ├── run_discovery.py   # CLI: batch 1
│   │   ├── run_enrichment.py  # CLI: batch 2
│   │   └── export.py          # CLI: CSV export
│   └── utils/
│       ├── config.py
│       ├── http_utils.py
│       └── logging_utils.py
├── data/
│   ├── bar_radar.db           # gitignored, generated locally / cached in CI
│   ├── exports/                # bar_radar_venues.csv, bar_radar_valid.csv
│   └── manual_review/          # manual_review.csv
├── tests/
│   ├── test_dedupe.py
│   └── test_menu_validator.py
└── .github/workflows/
    ├── discover.yml
    └── enrich.yml
```

## 5. Implementation plan

1. **Local bring-up** (this delivery): schema, discovery, dedupe, website
   finder, menu crawler/validator, orchestration CLIs, tests — all runnable
   locally in VS Code before touching CI.
2. **Local dry run**: `run_discovery --cities Berlin --limit 1` against a
   couple of cities, inspect `data/bar_radar.db` with a SQLite viewer,
   sanity-check candidate counts and address/category quality.
3. **Enrichment dry run**: small `--batch-size 10` run, manually spot-check
   5-10 `VALID_MENU` results and 5-10 `manual_review` entries to calibrate
   `confidence_thresholds` in `settings.yaml`.
4. **Scale up locally**: run full discovery across all cities once, then
   run enrichment repeatedly until per-city quotas are met or the manual
   review pile stabilizes.
5. **Wire up GitHub Actions**: push repo, add the two workflows, confirm a
   manual `workflow_dispatch` run completes and commits CSVs.
6. **Turn on schedules**: discovery 2x/day, enrichment every 4h; monitor
   Actions minutes usage and CSV growth for a few days.
7. **Manual review pass**: periodically review `manual_review.csv`
   (currently a CSV triage list — Phase 1 does not auto-resolve these).
8. **Phase 2 hook-in**: once venues.csv is stable at ~1,000 `VALID_MENU`
   rows, start populating `menu_snapshots`/`menu_items` by re-fetching each
   `menu_sources.menu_url` on a schedule and diffing against the last
   snapshot's `content_hash` → `change_events`.

## 6. Main technical risks

- **Overpass coverage gaps**: OSM bar density varies by city; some Tier 3
  cities may not hit their candidate multiplier from Overpass alone. Config
  has a hook for adding editorial/tourism-site scrapers per city if needed.
- **JS-rendered menus**: sites that render the menu client-side won't yield
  content to plain `requests`. Playwright is stubbed in as an opt-in
  dependency for exactly this case, kept out of the default path to protect
  runtime/cost.
- **False positives/negatives in menu validation**: keyword-based scoring is
  a heuristic, not NLP. Expect to tune `confidence_thresholds` and
  `menu_content_keywords` after reviewing the first few hundred results.
- **Free search fallback fragility**: DuckDuckGo's HTML endpoint has no
  official API contract and can change markup or rate-limit. It's used only
  as a fallback (OSM website tag is preferred), and failures degrade
  gracefully to `manual_review` rather than crashing the batch.
- **CI state persistence**: GitHub Actions cache is best-effort (LRU
  eviction, not guaranteed durable). The workflows commit CSV exports every
  run as the durable record; if you want the *database* itself durable
  across runs too, switch to committing `data/bar_radar.db` directly instead
  of relying on `actions/cache` (trade-off: bigger repo diffs).
- **Politeness / blocking**: `http_utils.py` adds a per-host delay and
  retry, but aggressive crawling of many small venue sites in a short window
  can still trip basic bot protection — hence `BLOCKED` as a first-class
  `menu_status` rather than a hard failure.
- **PDF menu quality**: scanned (image-only) PDFs won't yield extractable
  text via `pypdf` and will score low — these currently land in
  `manual_review` rather than being falsely marked `NO_MENU_FOUND`... note
  today they *do* fall to `NO_MENU_FOUND` if `pypdf` returns empty text;
  flagged here as a known Phase 1 simplification (OCR is a Phase 2 concern).

---

## Running locally (VS Code on Windows)

```powershell
# 1. Clone and set up a virtual environment
git clone https://github.com/YOUR_USERNAME/bar-radar.git
cd bar-radar
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

# 2. Initialize the database (creates data/bar_radar.db from schema.sql)
python -c "from db.database import init_db; init_db()"

# 3. Run the test suite (no network required)
pytest -v

# 4. Discover candidates for a single city (small, fast smoke test)
python -m src.pipeline.run_discovery --cities Berlin --limit 1

# 5. Enrich a small batch and inspect results
python -m src.pipeline.run_enrichment --batch-size 10

# 6. Export CSVs
python -m src.pipeline.export
# -> data/exports/bar_radar_venues.csv
# -> data/exports/bar_radar_valid.csv
# -> data/manual_review/manual_review.csv
```

Open `data/bar_radar.db` with the "SQLite Viewer" VS Code extension (or
DB Browser for SQLite) to inspect rows directly while iterating.

**Before running against all ~1,000 target venues**, edit
`config/settings.yaml` → `http.user_agent` to include your real repo URL —
identifying your bot honestly is part of being a polite, free-tier-friendly
scraper.
