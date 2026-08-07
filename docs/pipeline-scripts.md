# Pipeline Scripts Reference

Each script in `scripts/` has a single job and honors these conventions:

- Runs from anywhere (`Path(__file__).parent.parent` for the repo root).
- Idempotent — re-running with the same inputs produces the same outputs
  (modulo LLM non-determinism).
- Hard per-call timeouts, `max_retries=0` — no infinite retries.
- Blanks-only enrichment — never overwrites existing values.
- Prints a `Next:` line pointing to the follow-up script.

## `ingest-email.py` — parse the newsletter

**Input**: one of `--url`, `--archive-id`, `--email-file`, `--text-file`.

**Output**:
- `data/raw/raw-events-{week}.json`
- `data/email-raw/newsletter-{week}.{html,txt}`

**Flags**:

| Flag              | Purpose |
|-------------------|---------|
| `--url URL`       | Mailchimp "View in browser" or archive URL |
| `--archive-id ID` | Just the `mc_cid` value (10-char hex or decimal) |
| `--email-file FP` | Local `.html` or `.eml` file |
| `--text-file FP`  | Plain-text body (from Gmail connector output) |
| `--week YYYY-MM-DD` | Weekend date; defaults to the upcoming/current Friday |
| `--output PATH`   | Override output path |
| `--save-html PATH`| Override email-raw path |
| `--no-save-html`  | Skip writing to `email-raw/` |

**Parser logic**:
- HTML mode: finds day-heading `<td>`s with class `mcnBoxedTextContentContainer`
  matching `/^(FRIDAY|SATURDAY|SUNDAY)$/i`, then walks the document forward
  collecting `<li>` items until the next day heading.
- Text mode: splits on blank-line-separated `FRIDAY` / `SATURDAY` / `SUNDAY`
  headers, then parses each line as `<name> (<url>) , <venue>, <city>` with
  wrapped lines auto-folded.

**Failure modes**:
- Gmail truncation at ~5011 bytes — parser silently produces fewer events.
  Detect by checking the FRIDAY/SATURDAY/SUNDAY event counts against
  historical norms (30–40 per section).
- Mailchimp 503 (bot blocking) — fall back to `--text-file` mode.

---

## `update-metadata.py` — enrich events + match venues

**Input**: `--week YYYY-MM-DD` or auto-picks the most recent
`data/raw/raw-events-*.json`.

**Output**:
- `data/archive/events-{week}.json`
- `data/events.json` (unless `--no-current`)
- `data/venues.json` (only when new stubs were created)
- `data/archive/index.json`

**Flags**:

| Flag                | Purpose |
|---------------------|---------|
| `--raw-file PATH`   | Explicit raw JSON path |
| `--week YYYY-MM-DD` | Pick by week |
| `--limit N`         | Process first N events (for testing prompts) |
| `--no-current`      | Skip updating `data/events.json` |
| `--no-merge`        | Skip multi-day deduplication |

**Environment**: `PERPLEXITY_API_KEY` (preferred) or `OPENAI_API_KEY`.

**Prompt**: see [enrichment-flows.md](enrichment-flows.md) for the full
`SYSTEM_PROMPT` and per-event user prompt.

**Timeout**: 15 seconds per event via `openai.OpenAI(...).chat.completions.create(..., timeout=15.0)`.
`max_retries=0` on the client. One slow row moves on, batch continues.

**Venue matching**: after enrichment, each event's venue is matched against
`data/venues.json` in three passes:

1. Exact name lookup (`name_to_slug` index, lowercase)
2. Canonical key lookup (address + city + zip5, normalized) via
   `venue_utils.canonical_key`
3. Fuzzy match (`rapidfuzz.fuzz.partial_ratio` ≥ 85) restricted to same city

If all three miss, `match_or_create` inserts a stub via
`create_venue_from_event`. The in-memory index is updated so that duplicate
new venues within the same batch resolve to the same slug.

**Prints follow-up command**: The `Next:` line contains the exact
`--only-slugs` string for `enrich-venues.py`. Copy that verbatim.

---

## `match-venues.py` — venue matching library + CLI

Primarily used as a library by `update-metadata.py`, but also callable
standalone to backfill `venueId` on old archive files.

**Exposed functions**:

- `build_indexes(registry)` → `{name_to_slug, canonkey_to_slug, by_city}`
- `match_event(event, idx)` → `(slug_or_None, reason)`
- `create_venue_from_event(event, registry, idx)` → new slug
- `match_or_create(event, registry, idx)` → `(slug, reason)`
- `process_events_file(path, idx, dry)` → stats dict

**CLI flags**:

| Flag                | Purpose |
|---------------------|---------|
| `--week YYYY-MM-DD` | Backfill a specific archived week |
| `--all`             | Backfill current + every archive |
| `--dry-run`         | Show stats without writing |

**Fuzzy threshold**: `FUZZY_THRESHOLD = 85`. Lower produces false matches;
higher misses legitimate variants like "The Ritz" vs "Ritz Raleigh".

**Slug convention**: `slugify(name) + "-" + slugify(city)`. Collisions get
`-2`, `-3`, etc. appended by `_unique_slug`.

---

## `geocode-venues.py` — lat/lng resolver

**Input**: `data/venues.json`.

**Output**: same file, updated in place. Adds `lat`, `lng`, `place_id`, and
(for Nominatim) `osm_id`.

**Providers**:

| Provider     | Auth | Coverage | Rate limit | Default sleep |
|--------------|------|----------|-----------|---------------|
| `census`     | none | US only  | be gentle | 0.1s          |
| `nominatim`  | User-Agent header | worldwide | 1 req/s | 1.0s |

**Flags**:

| Flag                    | Purpose |
|-------------------------|---------|
| `--provider census|nominatim` | Which service (default: `census`) |
| `--dry-run`             | Show what would be geocoded |
| `--limit N`             | Cap at N venues |
| `--only-slugs a,b,c`    | Specific slugs only |
| `--force`               | Re-geocode even venues with `lat` set |
| `--sleep N`             | Override inter-request delay |

**Idempotency**: A venue with `lat` set is skipped unless `--force`. Safe to
re-run any time.

**place_id vs osm_id**: We keep both fields. Census returns a `tigerLine`
value which we store in `place_id`. Nominatim returns both a Nominatim
place_id (stored in `place_id`) and an OSM object id (stored in `osm_id` as
`way/12345` or `node/67890`). See [decision-log.md](decision-log.md).

---

## `enrich-venues.py` — LLM enrichment of venue metadata

**Input**: `data/venues.json`.

**Output**: same file, updated in place. Fills only blank fields.

**Environment**: `PERPLEXITY_API_KEY` required.

**Flags**:

| Flag                     | Purpose |
|--------------------------|---------|
| `--limit N`              | Process at most N |
| `--only-slugs a,b,c`     | Specific slugs only (STRONGLY RECOMMENDED) |
| `--dry-run`              | Preview which fields would be filled |
| `--force`                | Overwrite existing fields (danger zone) |
| `--model NAME`           | Default `sonar` |
| `--sleep N`              | Inter-request delay (default 0.5s) |

**Timeout**: 45 seconds per venue via `urllib.request.urlopen(req, timeout=45)`.
Explicit `TimeoutError` / `socket.timeout` branch logs `TIMEOUT after 45s`.

**Blanks-only logic** (`compute_needs`):
- `address` — needed if blank or `"TBD"`
- `linkMain` — needed if `""`
- `linkEvents` — needed if `""` (rarely filled — many venues don't have a
  distinct events page)
- `socials.<platform>` — needed per-platform if `""`
- `contacts` — needed if `[]`
- `venueType` — needed if `[]`

**Checkpoint**: writes `venues.json` every 5 processed venues. Safe to Ctrl-C.

**Response format**: JSON schema enforced. Fixed vocabulary for `venueType`
and `socials.platform` keys. See [enrichment-flows.md](enrichment-flows.md).

---

## `publish-website.py` — local preview + deploy helper

Not part of the weekly ritual anymore (we `git push` directly for GitHub
Pages), but kept for two use cases:

- **Local preview**: `python scripts/publish-website.py` opens
  `http://localhost:8765/` with the current `data/events.json`.
- **Netlify deploy**: `python scripts/publish-website.py --target netlify`
  runs `netlify deploy --prod` if you're using an alternate host.

**Validation**: Before serving, asserts `week` is present, `events` is a
non-empty list, and every event has `id` and `name`. Fails fast on
schema violations.

---

## `venue_utils.py` — shared library

Not directly invoked. Provides address/name normalization used by matcher and
geocoder.

**Exports**:
- `slugify(text)` — kebab-case slug from any string
- `name_key(name)` — lowercase, punctuation-stripped
- `canonical_key(address, city, zip5)` — normalized composite key for
  address-based matching
- `_STREET_ABBR` dict — expands `st`→`street`, `ave`→`avenue`, etc.

---

## `seed-venues.py` — RETIRED, do not run weekly

This script bootstrapped the initial `venues.json` from all archived event
files. It is preserved for two reasons:

1. **Auditability** — you can see how the registry was originally derived.
2. **Disaster recovery** — if `venues.json` is corrupted or lost, this can
   rebuild it from archives (with merge-preserve logic that keeps existing
   enrichment intact).

**Safety guard**: Requires `--write --i-know-what-im-doing`. Without both
flags it refuses to touch anything.

**Weekly stub creation** is now handled by
`match-venues.py::match_or_create`, invoked by `update-metadata.py`. Do not
substitute one for the other.
