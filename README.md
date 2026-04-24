# Raleigh Weekend Events Hub

A responsive, filterable, shareable events site powered by the
"Things to do in Raleigh this Weekend!" newsletter.

[Live site](https://bkibbey.github.io/events-hub/events-app.html)

## Quick start

```bash
pip install beautifulsoup4 openai
export PERPLEXITY_API_KEY=pplx-...   # or OPENAI_API_KEY=sk-...

# 1. Ingest the latest newsletter (paste the "View in browser" URL from the email):
python ingest-email.py --url 'https://us15.campaign-archive.com/?u=...&id=...'
#  → writes data/raw/raw-events-YYYY-MM-DD.json
#  → also archives the source HTML to data/email-raw/newsletter-YYYY-MM-DD.html

# 2. Enrich with AI (auto-picks the most recent raw file)
python update-metadata.py
#  → merges same-named events across days into multi-day entries
#  → writes data/archive/events-YYYY-MM-DD.json (history)
#  → writes data/events.json                    (current — what the site loads)

# 3. Preview locally
python publish-website.py

# 4. Deploy to GitHub Pages
python publish-website.py --target github
```

## How to get the newsletter URL

Open the email in Gmail, click "View this email in your browser" (usually at the top), and copy the URL. It looks like:

```
https://us15.campaign-archive.com/?u=ddef6da2cf1e7abe0e37514bc&id=<campaign_id>
```

Alternatives:

```bash
# If you only have the campaign id (the part after id=):
python ingest-email.py --archive-id 291544bb7c

# If you saved the email as a local HTML file:
python ingest-email.py --email-file email.html
```

The `--email-file` mode will try to detect the campaign id inside the local file and auto-fetch the full archive (Gmail truncates email bodies to ~3KB; the archive URL has the complete content).

## What the parser extracts

The Thingstodo919 newsletter is structured with three day-heading sections (`FRIDAY`, `SATURDAY`, `SUNDAY`), each followed by a `<ul>` of events. Each event line is:

```
<Event Name>, <Venue>, <City>
```

The parser finds the day-heading cells (Mailchimp `mcnBoxedTextContentContainer`) and walks forward in document order, collecting `<li>` items until the next day section. For each event it captures:

- **name** — the linked event name
- **link** — the destination URL (already de-tracked by Mailchimp's archive page)
- **venue** — text segment between the name and the city
- **city** — last comma-separated segment
- **day** — section it appeared in
- **raw** — the full `<li>` text for AI context

A typical week extracts 100–200 events across the three days.

## Multi-day deduplication

Many events appear on multiple days (festivals, theater runs, etc.) — they're listed separately under FRIDAY, SATURDAY, and/or SUNDAY in the email. `update-metadata.py` merges these by name before AI enrichment, producing a single record with `days: ["Friday","Saturday"]` and `multiDay: true`. This typically saves 10–20% of LLM calls per week.

To skip merging: `--no-merge`.

## Re-enrich a past week

```bash
python update-metadata.py --week 2026-04-24
# Reads data/raw/raw-events-2026-04-24.json
# Writes data/archive/events-2026-04-24.json (overwrites previous archive)
# AND overwrites data/events.json with that week's data
```

If you only want to update the archive without changing what the live site shows:

```bash
python update-metadata.py --week 2026-04-24 --no-current
```

To test prompt changes without spending on full enrichment:

```bash
python update-metadata.py --limit 5 --no-current
```

## Cost note

With ~120–140 unique events per week (after multi-day merge), each enrichment run is one LLM call per event. On Perplexity `sonar` that's roughly **$0.20–$0.40/week**. On OpenAI `gpt-4o-mini` it's similar. To cut costs:

- Use `--limit N` to enrich only the top N (the newsletter lists prominent events first)
- Or skip AI entirely and ship the raw parsed data; tags/descriptions stay empty but cards still display name, venue, city, day, link

## File structure

```
events-hub/
├── events-app.html           # Web app (single-page, edit once)
├── ingest-email.py           # Step 1: fetch + parse newsletter → raw JSON
├── update-metadata.py        # Step 2: merge + AI enrichment → events.json + archive
├── publish-website.py        # Step 3: validate + preview/deploy
├── README.md
└── data/
    ├── events.json                       # CURRENT snapshot the site fetches
    ├── email-raw/
    │   └── newsletter-YYYY-MM-DD.html    # source HTML, dated
    ├── raw/
    │   └── raw-events-YYYY-MM-DD.json    # parsed events, dated
    └── archive/
        └── events-YYYY-MM-DD.json        # enriched events, dated
```

`data/events.json` is the only file the website reads. The dated files in `email-raw/`, `raw/`, and `archive/` are history — keep them, prune them, gitignore them, your call.

## Shareable links

Select events on the site → click **Copy shareable link** → send to friends.
The link encodes selected event IDs as `?selected=1,3,7&week=2026-04-24`.
Friends see the full list with your picks highlighted and pinned at the top.

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

Plus a Perplexity (preferred — has live web search) or OpenAI API key for step 2.
