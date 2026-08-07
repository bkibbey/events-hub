# Weekly Workflow

The complete Friday-morning routine. This is the single most common operation
on this codebase. Copy the commands, adjust the date, ship it.

## Prerequisites

- `PERPLEXITY_API_KEY` in the environment (never in a commit)
- Python 3.11+
- `pip install beautifulsoup4 openai rapidfuzz`
- Write access to the repo (agents use the `github` credential preset)

## The 8 steps

### 1. Retrieve the newsletter

Preferred: use a Gmail connector to fetch by subject line, then save the body.

**As an AI agent**:
```
list_external_tools(queries=["gmail"])
call_external_tool(source_id="gcal", tool_name="search_email",
   arguments={"queries": ["Things to do in Raleigh this Weekend"]})
```

The Gmail API sometimes truncates the body at ~5011 bytes. Check the byte
count — if the last "SUNDAY" section is missing or an event trails off
mid-word, extract the "View in browser" URL from the top of the email and
follow it to the Mailchimp archive.

### 2. Ingest

Three ingest modes, prefer them in this order:

**A. Plain-text body** (preferred when the Gmail connector returns a complete body):

```bash
# Save the body to a temp file first (from the connector's output).
python scripts/ingest-email.py --text-file /tmp/newsletter-2026-08-07.txt \
  --week 2026-08-07
```

**B. Mailchimp campaign id** (when Gmail truncated):

```bash
# Extract mc_cid by following the "View in browser" redirect:
curl -sIL -A "Mozilla/5.0" '<view-in-browser-url>' | grep -iE "^(HTTP|location)"
# Look for mc_cid=XXXXXX in the Location header.

python scripts/ingest-email.py --archive-id XXXXXX --week 2026-08-07
```

**C. Saved HTML file**:

```bash
python scripts/ingest-email.py --email-file /path/to/saved-email.html \
  --week 2026-08-07
```

Any of the three writes:
- `data/raw/raw-events-2026-08-07.json` (parser output)
- `data/email-raw/newsletter-2026-08-07.{txt,html}` (source archive)

Expected event count: 80–200. If < 40, the parser probably tripped on unusual
Mailchimp markup — inspect the raw file before continuing.

### 3. Enrich events + auto-create venue stubs

```bash
export PERPLEXITY_API_KEY='pplx-...'
python scripts/update-metadata.py --week 2026-08-07
```

What this does:

1. Loads `data/raw/raw-events-2026-08-07.json`.
2. Merges multi-day duplicates (`First Friday` on Fri+Sat → one event with
   `days: ["Friday","Saturday"]`).
3. For each event, calls Perplexity `sonar` with a 15-second hard cap.
4. Matches each event's venue against `data/venues.json` (name → canonkey →
   fuzzy).
5. If no match, creates a new venue stub via `match_or_create`.
6. Writes:
   - `data/archive/events-2026-08-07.json` (this week's frozen record)
   - `data/events.json` (the live-site snapshot)
   - `data/venues.json` (updated ONLY if stubs were created)
   - `data/archive/index.json` (regenerated manifest)

The script prints a `Next:` line with the exact `--only-slugs` command for
step 5. **Copy that line** — the same list of slugs is needed twice.

Typical output:
```
✓ Venue match: 79/87 matched existing venues [name:70 canonkey:7 fuzzy:2]  |  created:8
✓ venues.json updated with 8 new stub(s):
    + forest-theatre-chapel-hill
    + peck-plume-cary
    ...
  Next: run geocode-venues.py + enrich-venues.py --only-slugs "forest-theatre-chapel-hill,peck-plume-cary,..."
```

### 4. Geocode new venues

```bash
python scripts/geocode-venues.py --provider census
```

The Census provider is free, no key required, US-only, and handles bulk well.
Falls back to `--provider nominatim` for anything outside the US (rare — this
data is Triangle-local).

Typical output: `Done. OK: 7 | Empty: 62`. The 62 "empty" are venues without
enough address info; they carry `lat: null` and are hidden from the map view
until enriched.

### 5. Enrich new venue stubs

```bash
python scripts/enrich-venues.py --only-slugs "forest-theatre-chapel-hill,peck-plume-cary,..."
```

**Do not omit `--only-slugs`.** Without it the script will run against every
venue with any blank field (~200+ venues, hundreds of API calls). The
`--only-slugs` argument is the safety belt.

**Shell gotcha (learned the hard way, 2026-07-24):** passing the slug list
via `SLUGS='...' python3 script "$SLUGS"` expands `$SLUGS` in the *parent*
shell — which is empty because `SLUGS=...` in front of a command only sets
it for the child. Result: enrich-venues sees no filter and runs against
everything. **Always pass the slug string directly as an argument.**

Per-venue hard cap: 45 seconds. `max_retries=0`. Timeouts print
`TIMEOUT after 45s` and move on. Checkpoints every 5 venues so partial runs
save progress.

### 6. Geocode again (only if enrichment filled in addresses)

```bash
python scripts/geocode-venues.py --provider census
```

`enrich-venues.py` sometimes discovers an address the newsletter omitted. If
so, this pass picks it up. Safe to skip if `OK: 0` was expected.

### 7. Commit

```bash
git add -A
git commit -m "Weekly update 2026-08-07: <event-count> events, <new-venue-count> new venue stubs enriched

- Ingested newsletter (<bytes> bytes)
- <n> events (Fri: X, Sat: Y, Sun: Z) after dedup
- <matched>/<total> events matched existing venues (name:X, canonkey:Y, fuzzy:Z)
- <k> new venue stubs auto-created: slug1, slug2, ...
- <k>/<k> stubs enriched: <fields> fields updated, 0 timeouts
- Geocoded <n> new stubs (Census provider)"
```

Then push (agents use the `github` credential preset for the `bash` call):

```bash
git push origin main
```

### 8. Trigger the Pages build + verify

```bash
gh api --method POST repos/bkibbey/events-hub/pages/builds
```

Wait ~30s, then:

```bash
curl -s "https://weekend.brewideas.net/data/events.json?t=$(date +%s)" \
  | python3 -c "import json,sys; d=json.load(sys.stdin); print('events:', len(d['events']), 'week:', d['week'])"
```

Should show the new week.

## What NOT to do

- **Do not run `seed-venues.py`.** It requires
  `--write --i-know-what-im-doing` and would rebuild the registry from scratch.
  It exists only for auditability and disaster recovery.
- **Do not `git add` `index.html` during a data update** unless you intend to
  ship UI changes. Half-built features have been accidentally committed this
  way — always run `git status` and stash unrelated markup before committing.
- **Do not use `browser_task` for Gmail or GitHub URLs.** Use the connectors:
  `gcal`/`gmail` and `github_mcp_direct` (or `api_credentials=["github"]`
  for shell git operations).
- **Do not enrich existing venues that already have data.** The
  blanks-only invariant is enforced in `enrich-venues.py::compute_needs`,
  but running without `--only-slugs` still spends tokens computing needs.

## Estimated time & cost

Rough budget for a typical week:

- Newsletter fetch: instant (Gmail connector)
- Ingest: < 5 seconds
- Event enrichment: ~90 events × 3–6 seconds each with `sonar` = 5–10 minutes
- Venue matching: instant
- Geocode: 10–60 seconds (~1s per venue)
- Venue enrichment: ~10 new stubs × 8–15 seconds each = 2–3 minutes
- Commit + push + Pages build: 60–90 seconds

**Total: ~10–15 minutes per week.**

Cost: single-digit dollars per week worst case on Perplexity `sonar`. Usually
less. See README.md for the current guidance.

## When something breaks

- **Parser produces 0–3 events**: The Mailchimp markup likely changed. Check
  `data/email-raw/newsletter-{week}.html` and adjust `find_day_cells()` in
  `ingest-email.py`.
- **Every event enrichment times out**: The 15-second cap is doing its job.
  Check network from your environment; if fine, the model may be rate-limited.
  Wait 5 minutes and retry — the scripts are idempotent.
- **Matcher creates duplicates**: Same venue with two slightly different
  spellings. Add the alt name to the canonical venue's `aliases` array in
  `venues.json` and re-run — the fuzzy matcher will catch it next time.
- **Pages doesn't update**: Check `gh api repos/bkibbey/events-hub/pages/builds`
  — the most recent build may have `status: "errored"`. Read `error.message`.
- **Live-site venue map is empty**: Almost always a geocoding gap. Run
  `geocode-venues.py --provider census` — new stubs may not have been
  geocoded yet.
