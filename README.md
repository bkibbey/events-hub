# Raleigh Weekend Events Hub

A responsive, filterable, shareable events site powered by the
"Things to do in Raleigh this Weekend!" newsletter.

## Quick start

```bash
pip install beautifulsoup4 openai
export PERPLEXITY_API_KEY=pplx-...   # or OPENAI_API_KEY=sk-...

# 1. Save the newsletter email as HTML, then:
python scripts/ingest-email.py --email-file email.html

# 2. Enrich with AI research
python scripts/update-metadata.py

# 3. Preview locally
python scripts/publish-website.py

# 4. Deploy (GitHub Pages)
python scripts/publish-website.py --target github
```

## Weekly workflow (every Friday)

1. Save the newsletter email as `email.html`
2. Run steps 1–4 above (~5 minutes total)

## Shareable links

Select events on the site → click **Copy shareable link** → send to friends.
The link encodes selected event IDs as `?selected=1,3,7&week=2026-04-24`.
Friends see the full event list with your picks highlighted at the top.

## File structure

```
raleigh-weekend-events/
├── events-app.html          # Responsive web app (edit once, reuse weekly)
├── events.json              # This week's enriched event data (replaced weekly)
├── README.md
└── scripts/
    ├── ingest-email.py      # Parse newsletter HTML → raw-events.json
    ├── update-metadata.py   # AI enrichment → events.json
    └── publish-website.py   # Validate + preview/deploy
```
