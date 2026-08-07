# Enrichment Flows

The system does two distinct LLM enrichments:

1. **Event enrichment** (`update-metadata.py`) — one call per event, per week.
   ~90 calls/week. Produces the event card content shown on the site.
2. **Venue enrichment** (`enrich-venues.py`) — one call per venue, one-time
   per venue (blanks-only). Produces the venue metadata used by the map view
   and future events at the same venue.

Both use Perplexity `sonar` (has live web search) as the default model with
`OPENAI_API_KEY` fallback on the event side. Both have hard per-call
timeouts and `max_retries=0`.

## Guiding principles

- **Blanks-only.** Enrichment never overwrites a non-empty field. Manual
  corrections are preserved forever.
- **Fixed vocabularies.** Tags, venue types, and social platforms come from
  hard-coded lists in the scripts, embedded in the prompt as `enum` schemas.
  The LLM cannot invent categories.
- **Hard timeouts, no retries.** Per-call ceiling of 15s (event) / 45s
  (venue). No exponential backoff, no retry-on-failure. One row can time
  out while the next succeeds.
- **JSON-only output.** No prose, no code fences, no commentary. Prompt
  enforces this; parser strips markdown fences defensively anyway.
- **Web search allowed but not required.** `sonar` will search the web when
  useful. We don't try to force it.

---

## Event enrichment

### Where it happens

`scripts/update-metadata.py::enrich_event()`, called per raw event by the
main loop after multi-day merging.

### Model + client

```python
from openai import OpenAI

client = OpenAI(
    api_key=os.environ["PERPLEXITY_API_KEY"],
    base_url="https://api.perplexity.ai",
    max_retries=0,          # hard cap — no retry storms
)
```

Falls back to `OPENAI_API_KEY` with `base_url=None` (i.e. api.openai.com) if
Perplexity is not set. In practice we always use Perplexity for the live
web search.

### System prompt

Verbatim from `scripts/update-metadata.py`:

```
You are a local events researcher for the Raleigh/Durham/Chapel Hill NC
area (the Triangle). Given a raw event listing, research the event and
return ONLY valid JSON matching this schema exactly. Do not include
markdown, code fences, or commentary—just the JSON object.

Schema:
{
  "name":         string,   // official event name
  "tagline":      string,   // one punchy sentence
  "venue":        string,   // venue name
  "address":      string,   // street address or 'TBD'
  "city":         string,
  "zip":          string,   // 5-digit ZIP or ""
  "days":         [Friday|Saturday|Sunday],
  "multiDay":     boolean,
  "scheduleNote": string,   // e.g. 'Fri 6–10 PM · Sat 12–8 PM' or ""
  "free":         boolean,
  "freeNote":     string,   // e.g. "Free with RSVP" or ""
  "ticketUrl":    string,   // ticket page, or the newsletter link
  "website":      string,   // official destination
  "facebook":     string|null,
  "instagram":    string|null,
  "tags":         string[], // FROM ALLOWED_TAGS ONLY (see ALLOWED_TAGS)
  "description":  string    // one paragraph
}
```

### Per-event user prompt

```
Week: 2026-08-07
Event name: First Friday
Day hint: Friday
Venue (from newsletter): Downtown Raleigh
City (from newsletter): Raleigh
Link: https://us.list-manage.com/...
Source links: https://us.list-manage.com/...

Raw listing line: First Friday, Downtown Raleigh, Raleigh

Research this event for the weekend of 2026-08-07 and return the JSON
schema. Use the provided link as the 'website' or 'ticketUrl' if
appropriate. Keep the 'name' field close to the provided event name;
correct only obvious typos.
```

### Timeout

15 seconds per call, enforced via the OpenAI SDK's `timeout` parameter:

```python
resp = client.chat.completions.create(
    model=model,
    messages=[...],
    temperature=0.2,
    timeout=15.0,
)
```

An `openai.APITimeoutError` (or any exception) causes the event to be
skipped — the loop continues. Skipped events retain their raw fields
(name, venue, city, day, link) but have no tagline, tags, or description.

### Multi-day merging (pre-enrichment)

Before enrichment, `merge_multiday()` collapses same-named events across
FRIDAY/SATURDAY/SUNDAY into one record with a `days: [...]` array. This
saves 10–20% of LLM calls per week. `--no-merge` disables it.

### Venue matching (post-enrichment)

After the event dict is finalized, `match_or_create` attaches a `venueId`.
See [venue-registry.md](venue-registry.md).

---

## Venue enrichment

### Where it happens

`scripts/enrich-venues.py`. Runs after `update-metadata.py` and
`geocode-venues.py`, filtered by `--only-slugs` to the newly-created stubs.

### Model + client

Direct HTTPS to `https://api.perplexity.ai/chat/completions` via `urllib`
(no OpenAI SDK). This lets us use Perplexity's structured-outputs feature
with a JSON schema.

```python
req = urllib.request.Request(
    PPLX_URL,
    data=json.dumps({
        "model": model,               # default: "sonar"
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": user_prompt}
        ],
        "response_format": {
            "type": "json_schema",
            "json_schema": schema,     # dynamically built per-venue
        },
    }).encode(),
    headers={
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    },
)
with urllib.request.urlopen(req, timeout=45) as resp:  # HARD CAP
    ...
```

### Blanks-only logic (`compute_needs`)

For each venue, compute which fields need filling:

```python
needs = {
    "address":    address_is_blank(v),         # True if "" or "TBD"
    "linkMain":   v.get("linkMain") == "",
    "linkEvents": v.get("linkEvents") == "",
    "socials":    any(v["socials"][p] == "" for p in SOCIAL_PLATFORMS),
    "contacts":   v.get("contacts") == [],
    "venueType":  v.get("venueType") == [],
}
```

If every value is False, the venue is skipped (no API call).

### Dynamic prompt + schema

The prompt is built per-venue to ask ONLY for the fields that are blank:

```
Find current, accurate public information about this venue:
  Name: Peck & Plume
  City: Cary, NC

Return ONLY fields listed below. Use empty string "" for anything you
cannot confidently verify. Do not guess. Do not include fields for other
venues with similar names.

Fields requested:
- address: Full street address (e.g. "123 Vivian St"). ...
- linkMain: URL of the venue's primary/homepage website.
- linkEvents: URL of the venue's public events/calendar page ...
- socials: Object with these keys: facebook, instagram, twitter, threads,
    bluesky, tiktok, youtube, reddit, linkedin.
- contacts: Array of contact objects. Each item: {label, phone, email, other}.
- venueType: Array of 1-3 tags from this fixed vocabulary ONLY: theater,
    museum, comedy-club, music-venue, stadium, park, plaza, library, church,
    brewery, distillery, winery, bar, restaurant, hotel, community-center,
    school, farm, government, market, event-space, club, historic-site,
    indoor, outdoor.
```

The JSON schema mirrors this — only the requested fields are in
`schema.properties.required`. Perplexity's structured-outputs feature
enforces the contract server-side.

### `apply_enrichment`

- For each returned field, if we asked for it and the venue's stored value
  is blank, copy it in.
- Skip fields we didn't ask for (defense against model hallucination).
- Never overwrite a non-empty stored value even if we did ask (defensive
  belt-and-suspenders — the `needs` check already prevented this).
- Log the exact list of updated field paths, e.g.
  `['linkMain', 'socials.facebook', 'socials.instagram', 'contacts', 'venueType']`.

### Timeout

45 seconds. Longer than event enrichment because we're asking for more
fields (address + socials + contacts + type) and `sonar` often runs several
web searches per venue.

The timeout is real: `urlopen(timeout=45)` raises `TimeoutError` /
`socket.timeout` after 45 seconds regardless of what the API is doing.
Explicit branch logs `TIMEOUT after 45s` and moves on.

### Checkpoint

Every 5 processed venues, `venues.json` is written to disk. If the process
dies (Ctrl-C, credits exhausted, network blip), you lose at most 4 venues
of progress. Re-running with the same `--only-slugs` will skip already-
enriched ones (blanks-only).

---

## Cost & rate limits

Rough per-run budget on Perplexity `sonar`:

- Event enrichment: ~90 events × ~$0.01/call = **~$0.90/week**
- Venue enrichment: ~10 new stubs × ~$0.02/call = **~$0.20/week**
- Total: **~$1/week** for a typical Triangle-events cadence.

`sonar` bills per-request for search grounding on top of tokens. Costs shown
here are order-of-magnitude only — check the Perplexity dashboard.

**Sleep interval**: default 0.5 seconds between calls. This is well below
Perplexity's stated limits but keeps the pace polite. Increase with
`--sleep 1.0` if you see 429 responses.

## Prompt evolution history

- **v1 (April 2026)**: Loose free-form prompt. LLM invented tags outside
  our vocabulary. Fixed by enumerating `ALLOWED_TAGS` in the prompt.
- **v2 (May 2026)**: Added `tagline` and `scheduleNote` fields based on
  card design needs.
- **v3 (July 2026)**: Extracted venue enrichment into `enrich-venues.py`
  with per-venue blanks-only prompts. Prior versions re-asked for the same
  venue every time it appeared, wasting tokens.
- **v4 (July 24, 2026)**: Hard timeouts added (15s event, 45s venue),
  `max_retries=0` on the OpenAI client. Prior versions could hang for
  minutes when the API stalled.
- **v5 (July 31, 2026)**: `match_or_create` auto-creates venue stubs during
  event enrichment; `seed-venues.py` retired. Prior versions required a
  weekly re-seed pass that was noisy and slow.
