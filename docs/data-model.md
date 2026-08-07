# Data Model

Canonical schemas for every JSON file in `data/`. This is the source of truth
— the scripts are implementations of this spec.

## `data/events.json` (the live snapshot)

```jsonc
{
  "week": "2026-08-07",          // YYYY-MM-DD, the Friday of the weekend
  "generated": "2026-08-07",     // ISO date of the ingest run
  "events": [
    {
      "id": 1,                    // INT, unique within this file, 1-indexed
      "name": "First Friday",
      "tagline": "One-punchy-sentence descriptor",
      "venue": "Downtown Raleigh",
      "venueId": "downtown-raleigh-raleigh",  // slug into venues.json, or null
      "address": "TBD",
      "city": "Raleigh",
      "zip": "",
      "days": ["Friday"],         // subset of ["Friday","Saturday","Sunday"]
      "multiDay": false,          // true iff days.length > 1
      "scheduleNote": "Fri 5–11:30 PM (varies by venue)",
      "free": true,
      "freeNote": "Free admission",
      "ticketUrl": "https://us.list-manage.com/...",   // may be tracking URL
      "website": "https://downtownraleigh.org/...",    // canonical destination
      "facebook": null,            // legacy per-event social (kept for old rows)
      "instagram": "https://www.instagram.com/firstfridayral/",
      "tags": ["Arts & Crafts", "Music", "Market", "Free", "Family"],
      "description": "One paragraph of context."
    }
  ]
}
```

### Event field semantics

| Field           | Type              | Nullable | Notes |
|-----------------|-------------------|----------|-------|
| `id`            | int               | no       | Contiguous 1..N within the file |
| `name`          | string            | no       | Newsletter name, corrected for obvious typos only |
| `tagline`       | string            | yes ("") | LLM-generated |
| `venue`         | string            | yes ("") | Newsletter's venue string |
| `venueId`       | string            | yes (null) | Slug into `venues.json`; null = matcher failed |
| `address`       | string            | yes ("") | "TBD" allowed when unknown |
| `city`          | string            | yes ("") | Populated from newsletter or LLM |
| `zip`           | string            | yes ("") | 5-digit or empty; never zip+4 |
| `days`          | string[]          | no       | Ordered subset of Fri/Sat/Sun |
| `multiDay`      | boolean           | no       | `days.length > 1` |
| `scheduleNote`  | string            | yes ("") | Free-form time info |
| `free`          | boolean           | no       | LLM's best inference |
| `freeNote`      | string            | yes ("") | e.g. "Free admission, food for purchase" |
| `ticketUrl`     | string            | yes ("") | Can be a Mailchimp tracking URL |
| `website`       | string            | yes ("") | Canonical destination if resolvable |
| `facebook`      | string \| null    | yes      | Legacy — new rows use venue socials instead |
| `instagram`     | string \| null    | yes      | Legacy — new rows use venue socials instead |
| `tags`          | string[]          | no       | From `ALLOWED_TAGS` in `update-metadata.py` |
| `description`   | string            | yes ("") | 1–2 paragraphs |

### Tag vocabulary (`ALLOWED_TAGS`)

Enrichment prompt constrains the LLM to this set:

```
Music, Food, Beer, Wine, Festival, Theater, Comedy, Sports,
Arts & Crafts, Outdoor, Family, Adult, 21+, Film, Museum, Market,
Bluegrass, Jazz, Dance, LGBTQ+, Free, Ticketed, Charity, Holiday, Parade
```

Changes to this list are safe — the frontend derives its filter menu from
whatever tags appear in the loaded events.

---

## `data/venues.json` (the registry)

```jsonc
{
  "venues": {
    "321-coffee-raleigh": {
      "slug": "321-coffee-raleigh",         // MUST equal the dict key
      "name": "321 Coffee",
      "aliases": [],                         // alt spellings for matcher
      "address": "615 Hillsborough St",
      "city": "Raleigh",
      "state": "NC",
      "zip": "27603",
      "lat": 35.7805516,
      "lng": -78.6433547,
      "place_id": "343922951",               // Census tigerLine OR OSM place_id
      "osm_id": "way/18916382",              // present when Nominatim geocoded
      "linkMain": "https://321coffee.com/",
      "linkEvents": "",                      // events page, may be blank
      "socials": {
        "facebook":  "",                     // ALL 9 keys always present
        "instagram": "https://www.instagram.com/drink321coffee/",
        "twitter":   "",
        "threads":   "",
        "bluesky":   "",
        "tiktok":    "",
        "youtube":   "",
        "reddit":    "",
        "linkedin":  "https://www.linkedin.com/company/321coffee"
      },
      "contacts": [                          // one row per contact, all channels on the row
        {
          "label": "Event Catering",
          "phone": "",
          "email": "catering@321coffee.com",
          "other": ""
        }
      ],
      "venueType": ["restaurant"],           // subset of VENUE_TYPE_VOCAB
      "eventCount": 1,
      "sampleEvents": ["ArtPutt First Friday"],
      "reviewNeeded": false,
      "createdBy": "match-venues.auto"       // present when auto-created
    }
  }
}
```

### Venue field semantics

| Field         | Type              | Nullable | Notes |
|---------------|-------------------|----------|-------|
| `slug`        | string            | no       | kebab-case; `{name}-{city}` when city is known |
| `name`        | string            | no       | Canonical (most-frequent among the newsletter's names) |
| `aliases`     | string[]          | no       | Alt names the matcher accepts |
| `address`     | string            | yes ("") | Full street address or "" |
| `city`        | string            | yes ("") | |
| `state`       | string            | no       | Default "NC" |
| `zip`         | string            | yes ("") | 5-digit; blank ok |
| `lat`         | number \| null    | yes      | WGS84 latitude |
| `lng`         | number \| null    | yes      | WGS84 longitude |
| `place_id`    | string \| null    | yes      | Provider identifier (Census tigerLine or OSM place_id) |
| `osm_id`      | string \| null    | yes      | When Nominatim resolved it — kept alongside `place_id` |
| `linkMain`    | string            | yes ("") | Homepage |
| `linkEvents`  | string            | yes ("") | Events/calendar page if distinct from homepage |
| `socials`     | object            | no       | All 9 keys always present, values may be "" |
| `contacts`    | array of objects  | no       | May be empty; one contact per row |
| `venueType`   | string[]          | no       | Subset of `VENUE_TYPE_VOCAB` |
| `eventCount`  | int               | no       | Advisory — how many events have referenced this venue |
| `sampleEvents`| string[]          | no       | Advisory — example event names for humans |
| `reviewNeeded`| boolean           | no       | True when auto-created without an address |
| `createdBy`   | string            | yes (missing) | `"match-venues.auto"` for auto-created stubs |

### Social platforms (fixed vocabulary)

```
facebook, instagram, twitter, tiktok, youtube, linkedin,
reddit, threads, bluesky
```

**Rule**: every venue's `socials` object contains all 9 keys, always. Blanks are
`""`, not `null` and not missing. If we ever add or drop a platform, we must
update both `enrich-venues.py::SOCIAL_PLATFORMS` and
`match-venues.py::SOCIAL_PLATFORMS` in lockstep.

### Venue type vocabulary

```
theater, museum, comedy-club, music-venue, stadium, park, plaza, library,
church, brewery, distillery, winery, bar, restaurant, hotel, community-center,
school, farm, government, market, event-space, club, historic-site,
indoor, outdoor
```

Multi-select allowed. Enrichment prompt constrains the LLM to this set.

---

## `data/archive/index.json` (the manifest)

Regenerated at the end of every `update-metadata.py` run.

```jsonc
{
  "current": "2026-08-07",     // must equal data/events.json.week
  "weeks": [
    { "week": "2026-08-07", "file": "events-2026-08-07.json", "count": 87, "generated": "2026-08-07" },
    { "week": "2026-07-31", "file": "events-2026-07-31.json", "count": 91, "generated": "2026-07-31" },
    // ... newest-first ...
  ]
}
```

Sorted newest-first. `count` is the number of events in the archive file.
`generated` is currently identical to `week` but is kept as a separate field
so we can distinguish "the weekend this is for" from "the day we ran ingest"
if the schedule ever drifts.

---

## `data/raw/raw-events-YYYY-MM-DD.json` (parser output)

Produced by `ingest-email.py`; consumed by `update-metadata.py`.

```jsonc
{
  "week": "2026-08-07",
  "generated": "2026-08-07T14:42:11Z",
  "source": {
    "type": "text-file" | "url" | "archive-id" | "email-file",
    "path_or_url": "...",
    "archive_id": "..."
  },
  "events": [
    {
      "id": 1,                          // unique within this raw file
      "day": "Friday",
      "name": "First Friday",
      "venue": "Downtown Raleigh",
      "city": "Raleigh",
      "link": "https://...",
      "raw": "First Friday, Downtown Raleigh, Raleigh"   // full li text
    }
  ]
}
```

`id` in the raw file is *not* preserved through enrichment — the merge step
re-ids after collapsing multi-day duplicates.

---

## `data/email-raw/newsletter-YYYY-MM-DD.{html,txt}` (source archive)

Verbatim copy of the newsletter as of ingest. Kept for:

- Auditing the parser when a week produces unexpected output.
- Re-running enrichment with a new prompt without needing to re-fetch the email.
- Historical record — the Mailchimp archive URL is not guaranteed to persist.

`.html` when `--url` / `--archive-id` / `--email-file` was used. `.txt` when
`--text-file` was used (i.e. body was retrieved via a Gmail connector).

---

## Invariants across files

- `events.json.week` == `archive/index.json.current` == `archive/events-{week}.json.week`
- Every `event.venueId` (when non-null) exists as a key in `venues.json.venues`.
- Every `venues.json.venues[slug].slug` field equals its parent key.
- `days` values are exactly `"Friday"`, `"Saturday"`, `"Sunday"` (title-case).
- ZIPs are 5-digit strings or empty. Never zip+4, never numeric.
- `state` defaults to `"NC"` but is preserved when the newsletter provides
  another (e.g. Virginia border venues).

## Backward compatibility notes

- Old events (pre-2026-07-17) may have `facebook` / `instagram` at the event
  level. New events rely on the venue's `socials` object. The frontend reads
  both and prefers venue-level when both exist.
- Some legacy venues lack `osm_id` (Census-geocoded). This is intentional —
  keep both fields when present, don't unify them.
- `venues-overrides.json` used to be the merge target for manual corrections
  during the seed era. Post-retirement of `seed-venues.py`, changes are made
  directly in `venues.json` and the overrides file is dormant.
