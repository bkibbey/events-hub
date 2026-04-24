# Raleigh Weekend Events Hub

A responsive, filterable, shareable events site powered by the
"Things to do in Raleigh this Weekend!" newsletter.

## Quick start

```bash
pip install beautifulsoup4 openai
export PERPLEXITY_API_KEY=pplx-...   # or OPENAI_API_KEY=sk-...

# 1. Save the newsletter email as HTML, then:
python ingest-email.py --email-file email.html
#  → writes data/raw/raw-events-YYYY-MM-DD.json

# 2. Enrich with AI (auto-picks the most recent raw file)
python update-metadata.py
#  → writes data/archive/events-YYYY-MM-DD.json (history)
#  → writes data/events.json                    (current — what the site loads)

# 3. Preview locally
python publish-website.py

# 4. Deploy to GitHub Pages
python publish-website.py --target github
```

## Weekly workflow (every Friday)

1. Save the newsletter email as `email.html` (in your browser: View Source → Save, or "Save Page As → Webpage Complete")
2. Run steps 1–4 above (~5 minutes total)

The dated raw + archive files mean you can always re-enrich a past week, A/B-test prompt changes against historical data, or back-fill if a newsletter run goes wrong.

## File structure

```
events-hub/
├── events-app.html           # Web app (single-page, edit once)
├── ingest-email.py           # Step 1: HTML email → raw JSON
├── update-metadata.py        # Step 2: AI enrichment → events.json + archive
├── publish-website.py        # Step 3: validate + preview/deploy
├── README.md
└── data/
    ├── events.json           # CURRENT snapshot the site fetches
    ├── raw/
    │   └── raw-events-YYYY-MM-DD.json   # one per weekend, dated
    └── archive/
        └── events-YYYY-MM-DD.json       # one per weekend, dated
```

`data/events.json` is the only file the website reads. The dated files in `raw/` and `archive/` are history — keep them, prune them, gitignore them, your call.

## Re-enrich a past week

```bash
python update-metadata.py --week 2026-04-24
# Reads data/raw/raw-events-2026-04-24.json
# Writes data/archive/events-2026-04-24.json (overwrites previous archive for that week)
# AND overwrites data/events.json with that week's data
```

If you only want to update the archive without changing what the live site shows:

```bash
python update-metadata.py --week 2026-04-24 --no-current
```

## Shareable links

Select events on the site → click **Copy shareable link** → send to friends.
The link encodes selected event IDs as `?selected=1,3,7&week=2026-04-24`.
Friends see the full list with your picks highlighted at the top.

## Filters & UI

- **Day pills + Free toggle + search** in row 1 of the filter bar
- **Tag pills** in row 2, sorted by frequency, with counts
- Multi-tag filtering is **AND** — pick "Music" + "Outdoor" → only events with both tags
- Tag chips inside cards are clickable and stay in sync with the header pills
- Cards use a CSS-columns masonry layout (1/2/3 cols responsive)

## Dependencies

```bash
pip install beautifulsoup4 openai
```

You'll also need a Perplexity (preferred — has live web search) or OpenAI API key for step 2.
