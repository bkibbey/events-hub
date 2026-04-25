# Raleigh Weekend Events Hub

A responsive, filterable, shareable single-page events site powered by the
"Things to do in Raleigh this Weekend!" newsletter from
[Things To Do 919](https://www.thingstodo919.com).

[**→ Live site**](https://bkibbey.github.io/events-hub/)

## What this is

The newsletter ships a high-quality weekend events list every Friday morning. This project turns that email into a fast, filterable, shareable web app:

- **Pipeline**: fetch the newsletter → parse it → enrich each event with AI (tags, free/ticketed, multi-day, address, social links) → publish to a static site.
- **Site**: filter by day / city / tag, free-only toggle, full-text search, light/dark mode, and shareable URLs that pin selected events for friends.
- **Hosting**: GitHub Pages — single static `index.html` plus a small `data/events.json`.

## Quick start

```bash
pip install beautifulsoup4 openai
export PERPLEXITY_API_KEY=pplx-...   # preferred (has live web search)
# or:  export OPENAI_API_KEY=sk-...

# 1. Ingest the latest newsletter (paste the "View in browser" URL from the email)
python scripts/ingest-email.py --url 'https://us15.campaign-archive.com/?u=...&id=...'
#  → data/raw/raw-events-YYYY-MM-DD.json
#  → data/email-raw/newsletter-YYYY-MM-DD.html  (source HTML, archived)

# 2. Enrich with AI (auto-picks the most recent raw file)
python scripts/update-metadata.py
#  → data/archive/events-YYYY-MM-DD.json   (history)
#  → data/events.json                      (current — what the site loads)

# 3. Preview locally (opens http://localhost:8765/)
python scripts/publish-website.py

# 4. Deploy to GitHub Pages (commits + pushes)
python scripts/publish-website.py --target github
```

All scripts live in `scripts/` but resolve paths relative to the repo root, so they work no matter where you invoke them from. The examples above assume you run from the repo root.

## Repo layout

```
events-hub/
├── index.html                   # The web app — single page, no build step
├── events-app.html              # Redirect stub for legacy /events-app.html links
├── README.md
├── assets/
│   └── logo.png                  # currently hidden in CSS
├── scripts/
│   ├── ingest-email.py          # Step 1: fetch + parse newsletter → raw JSON
│   ├── update-metadata.py       # Step 2: merge + AI-enrich → events.json + archive
│   └── publish-website.py       # Step 3: validate + preview/deploy
└── data/
    ├── events.json                       # CURRENT snapshot — the only file the site fetches
    ├── email-raw/
    │   └── newsletter-YYYY-MM-DD.html    # source HTML, dated
    ├── raw/
    │   └── raw-events-YYYY-MM-DD.json    # parsed events, dated
    └── archive/
        └── events-YYYY-MM-DD.json        # enriched events, dated
```

`data/events.json` is the only file the website reads at runtime. The dated files in `email-raw/`, `raw/`, and `archive/` are history — keep them, prune them, or gitignore them; the live site doesn't care.

## How to get the newsletter URL

Open the email in Gmail, click "View this email in your browser" (top of the email), and copy the URL. It looks like:

```
https://us15.campaign-archive.com/?u=ddef6da2cf1e7abe0e37514bc&id=<campaign_id>
```

Alternatives:

```bash
# If you only have the campaign id (the part after id=):
python scripts/ingest-email.py --archive-id 291544bb7c

# If you saved the email as a local HTML file:
python scripts/ingest-email.py --email-file email.html
```

The `--email-file` mode tries to detect the campaign id inside the local file and auto-upgrades to the full archive URL. (Gmail truncates email bodies to ~3 KB; the Mailchimp archive page has the complete content.)

## What the parser extracts

The Thingstodo919 newsletter is structured with three day-heading sections (`FRIDAY`, `SATURDAY`, `SUNDAY`), each followed by a `<ul>` of events. Each event line is:

```
<Event Name>, <Venue>, <City>
```

The parser finds the day-heading cells (Mailchimp `mcnBoxedTextContentContainer`) and walks forward in document order, collecting `<li>` items until the next day section. For each event it captures:

- **name** — the linked event name
- **link** — destination URL (de-tracked by Mailchimp's archive page)
- **venue** — text segment between the name and the city
- **city** — last comma-separated segment
- **day** — section it appeared in
- **raw** — the full `<li>` text, kept around as AI context

A typical week produces 100–200 raw events across the three days.

## Multi-day deduplication

Many events appear on multiple days (festivals, theater runs, garden tours, etc.) — they're listed separately under FRIDAY, SATURDAY, and/or SUNDAY in the email. `update-metadata.py` merges these by name *before* AI enrichment, producing a single record with `days: ["Friday","Saturday"]` and `multiDay: true`. This typically saves 10–20% of LLM calls per week.

To skip merging: `--no-merge`.

## Re-enrich a past week

```bash
python scripts/update-metadata.py --week 2026-04-24
# Reads:  data/raw/raw-events-2026-04-24.json
# Writes: data/archive/events-2026-04-24.json   (overwrites)
# AND   : data/events.json                       (overwrites with that week's data)
```

Update only the archive, leave the live site alone:

```bash
python scripts/update-metadata.py --week 2026-04-24 --no-current
```

Test prompt/parser changes cheaply on a handful of events:

```bash
python scripts/update-metadata.py --limit 5 --no-current
```

## Cost note

With ~120–140 unique events per week (after multi-day merge), each enrichment run makes one LLM call per event. Per-call cost depends on the provider and prompt/response size, and live-search models like `sonar` also bill for search requests.

Rough order of magnitude on Perplexity `sonar` or OpenAI `gpt-4o-mini`: **a few dollars per week, worst case** — usually less, but plan for that ceiling. Always check current pricing on your provider's dashboard before running a full week, and start with `--limit 5` if you're trying a new model or prompt.

To keep costs down:

- `--limit N` enriches only the first N events (the newsletter lists prominent events first)
- `--no-current` writes the dated archive but doesn't replace `data/events.json` — useful when iterating on prompts
- Skip step 2 entirely — the cards still display name, venue, city, day, and link from raw data; tags and descriptions stay empty

## Site features

### Filters & UI

- **When / Where / Tags** dropdowns + **Free** toggle + **search** in a single row
- Active filters appear as dismissible chips below the row
- Multi-tag filtering is **AND** (pick "Music" + "Outdoor" → events with both)
- Tag chips inside cards are clickable and stay in sync with the header dropdowns
- Cards use a CSS-columns masonry layout (1 / 2 / 3 cols responsive)
- **Light / dark mode** toggle in the header (auto-saves preference)

### Shareable links

Select events on the site → click **Copy shareable link** → send to friends.

The link encodes selected event IDs as
`https://bkibbey.github.io/events-hub/?selected=1,3,7&week=2026-04-24`.
When opened, the friend sees **only** those events, with a dismissible amber "Shared events (N)" chip to expand back to the full list.

### About modal

Click the circled **i** in the header to open an in-app About modal. It fetches and renders this README inline (no jump to GitHub) — close on ✕, Esc, or backdrop click.

### Disclaimer banner

A floating "Experimental" banner at the bottom credits the Things To Do 919 newsletter and warns that AI-enriched details should be double-checked. It's dismissible per session (no localStorage persistence — reappears every reload). When events are selected, the banner lifts above the share pill so both stay visible.

## Branding

Color tokens and assets match [Things To Do 919](https://www.thingstodo919.com/about):

- Light: `--color-primary: #1f2bbf` (TTD indigo) · `--color-accent: #a6e22e` (lime)
- Dark : `--color-primary: #7c84ff` · `--color-accent: #b8f03d`
- A 3px lime accent stripe pinned to the top of the viewport

`assets/logo.png` is committed but currently hidden in CSS (`.logo-mark, .logo > a { display:none }`). To re-enable, delete that one rule.

## Dependencies

```bash
pip install beautifulsoup4 openai
```

Plus a Perplexity (preferred — has live web search) or OpenAI API key for step 2.

Python 3.11+ is recommended (the scripts use `Path.is_relative_to`).

## Credits

- Event data is curated by [Things To Do 919](https://www.thingstodo919.com).
  This project does not modify or republish their content; it links each event to its source.
- AI enrichment runs locally with your own Perplexity / OpenAI API key.
