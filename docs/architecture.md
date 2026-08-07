# Architecture

## One-paragraph summary

Every Friday morning, a Mailchimp newsletter ("Things to do in Raleigh this
Weekend!") lists ~100 events across the Triangle. A five-script Python pipeline
ingests that email, enriches each event with an LLM, matches or creates its
venue in a registry, geocodes new venues, enriches new venues with a second LLM
pass, and commits the result. A static `index.html` hosted on GitHub Pages
loads three JSON files and renders a filterable, shareable, mappable view.

## Data flow

```
                Friday morning
                      │
                      ▼
   ┌─────────────────────────────────────────┐
   │  Gmail: "Things to do 919" newsletter   │
   └─────────────────────────────────────────┘
                      │
                      ▼  (agent copies body text or archive URL)
   ┌─────────────────────────────────────────┐
   │  scripts/ingest-email.py                 │
   │    parses FRIDAY/SATURDAY/SUNDAY blocks  │
   └─────────────────────────────────────────┘
                      │
                      ▼
      data/raw/raw-events-YYYY-MM-DD.json
      data/email-raw/newsletter-YYYY-MM-DD.{html,txt}
                      │
                      ▼
   ┌─────────────────────────────────────────┐
   │  scripts/update-metadata.py              │
   │  ├─ merges multi-day duplicates          │
   │  ├─ LLM-enriches each event (15s cap)    │
   │  ├─ matches venues against registry      │
   │  └─ auto-creates stubs for new venues    │
   └─────────────────────────────────────────┘
                      │
                      ▼
      data/events.json          (current — live site)
      data/archive/events-YYYY-MM-DD.json  (immutable history)
      data/archive/index.json   (regenerated manifest)
      data/venues.json          (updated with new stubs)
                      │
                      ▼
   ┌─────────────────────────────────────────┐
   │  scripts/geocode-venues.py               │
   │    Census (default) or Nominatim         │
   │    only fills blank lat/lng              │
   └─────────────────────────────────────────┘
                      │
                      ▼
   ┌─────────────────────────────────────────┐
   │  scripts/enrich-venues.py                │
   │  --only-slugs "<new stubs from step 2>"  │
   │  Perplexity `sonar`, 45s cap             │
   │  fills linkMain/socials/contacts/type    │
   └─────────────────────────────────────────┘
                      │
                      ▼  (git commit + push)
   ┌─────────────────────────────────────────┐
   │  GitHub Pages @ weekend.brewideas.net    │
   │  index.html fetches:                     │
   │    data/events.json                      │
   │    data/venues.json                      │
   │    data/archive/index.json               │
   └─────────────────────────────────────────┘
```

## Repository layout

```
events-hub/
├── index.html                    # THE web app (~1600 lines, no framework)
├── events-app.html               # Legacy redirect stub
├── favicon-96x96.png
├── CNAME                         # weekend.brewideas.net
├── README.md                     # Human-facing quick-start
├── assets/
│   ├── logo.png                  # currently hidden in CSS
│   └── confetti.min.js           # canvas-confetti, vendored
├── scripts/
│   ├── ingest-email.py           # Step 1: newsletter → raw JSON
│   ├── update-metadata.py        # Step 2: enrich + match venues + archive
│   ├── match-venues.py           # Library used by step 2 (also CLI-runnable)
│   ├── geocode-venues.py         # Step 3: lat/lng for new venues
│   ├── enrich-venues.py          # Step 4: LLM-enrich venue metadata
│   ├── venue_utils.py            # Address normalization, slugs, canonical keys
│   ├── seed-venues.py            # RETIRED — bootstrap-only, guarded
│   └── publish-website.py        # Local preview + optional deploy helper
├── docs/                         # ← YOU ARE HERE
└── data/
    ├── events.json               # CURRENT week — loaded by site
    ├── venues.json               # 446-entry registry (as of 2026-08-07)
    ├── venues-overrides.json     # Manual overrides preserved by seed script
    ├── venues-seed-report.md     # Bootstrap audit (shared asset)
    ├── raw/
    │   └── raw-events-YYYY-MM-DD.json   # parsed newsletter, dated
    ├── email-raw/
    │   ├── newsletter-YYYY-MM-DD.html   # source HTML (when --url used)
    │   └── newsletter-YYYY-MM-DD.txt    # source text (when --text-file used)
    └── archive/
        ├── events-YYYY-MM-DD.json       # frozen enriched week
        └── index.json                   # manifest, regenerated each run
```

## The three JSON files the site loads

| File                          | Loaded by     | Shape             | Cache header |
|-------------------------------|---------------|-------------------|--------------|
| `data/events.json`            | on boot       | `{week, events[]}`| `no-cache`   |
| `data/venues.json`            | on boot (non-blocking) | `{venues: {slug: obj}}` | `no-cache` |
| `data/archive/index.json`     | on boot       | `{current, weeks[]}` | `no-cache` |
| `data/archive/events-YYYY-MM-DD.json` | on week-picker selection | `{week, events[]}` | `no-cache` |

Everything else in `data/` is history — safe to prune, gitignore, or delete. The
site never fetches raw or email-raw files.

## External services

| Service              | Purpose                            | Auth               | Rate limit         |
|----------------------|------------------------------------|--------------------|--------------------|
| Gmail (agent-side)   | Retrieve the newsletter            | user's connector   | connector default  |
| Mailchimp archive    | Fetch full HTML (bypasses Gmail truncation) | none (public) | polite: ≤1 req/wk |
| Perplexity `sonar`   | Event + venue enrichment (with web search) | `PERPLEXITY_API_KEY` env var | 45s per call cap |
| US Census Geocoder   | Primary geocoding                  | none               | be gentle          |
| OSM Nominatim        | Fallback geocoding                 | User-Agent header  | ≤1 req/sec         |
| GitHub Pages         | Static hosting                     | git push to `main` | build queue        |

**No secrets in the repo.** `PERPLEXITY_API_KEY` is passed via environment
variable at the shell. It never appears in commits, scripts, or logs.

## Deployment

Pushing to `main` triggers a GitHub Pages build. Typical latency:

- `git push` → `gh api /pages/builds` returns `queued`
- Build completes in ~30–90 seconds
- CDN propagation adds another ~30 seconds

Force a build: `gh api --method POST repos/bkibbey/events-hub/pages/builds`.

The custom domain `weekend.brewideas.net` is served via `CNAME` + a CNAME
record at Cloudflare pointing to `bkibbey.github.io`.

## Hard invariants

Violating any of these breaks the site. Enforce them in code changes:

1. `data/events.json` MUST have shape `{week: "YYYY-MM-DD", events: [...]}`.
2. Every event MUST have `id` (integer, unique within the file) and `name`.
3. `data/venues.json` MUST have shape `{venues: {slug: venue-obj}}`. The
   `slug` field inside each venue MUST equal its key.
4. `data/archive/index.json` MUST have a `weeks[]` array sorted newest-first
   and a `current` field matching `events.json.week`.
5. Archive files are **immutable** in the sense that we never rewrite an
   already-shipped week without an explicit `--week YYYY-MM-DD` re-enrich, and
   even then we take a git commit as the audit trail.
6. Enrichment scripts NEVER overwrite non-empty fields. Blanks-only.
7. `seed-venues.py` NEVER runs weekly. It requires
   `--write --i-know-what-im-doing` and is documented as retired.
