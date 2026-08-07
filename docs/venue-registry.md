# Venue Registry

The venue registry (`data/venues.json`) is the most subtle piece of the
system. It de-duplicates the ~30-40 unique venues per week into a persistent
catalog, links every event to its venue via `venueId`, enables the map view,
and stores enrichment (socials, contacts, hours) that survives across weeks.

## Why we have a registry

The newsletter refers to the same venue with several spellings:

- "Red Hat Amphitheater" / "Red Hat Amp." / "Red Hat"
- "Coastal Credit Union Music Park" / "Coastal Credit Union" / "Walnut Creek"

Without a registry, each spelling would be a separate row on the map, and
we'd re-research the same venue every week. With a registry, all spellings
resolve to one slug and enrichment happens once.

## Shape

```jsonc
{
  "venues": {
    "red-hat-amphitheater-raleigh": {
      "slug": "red-hat-amphitheater-raleigh",
      "name": "Red Hat Amphitheater",
      "aliases": ["Red Hat Amp.", "Red Hat", "Red Hat Amp"],
      "address": "500 S McDowell St",
      "city": "Raleigh",
      "state": "NC",
      "zip": "27601",
      "lat": 35.7746, "lng": -78.6398,
      "place_id": "12345", "osm_id": "way/54321",
      "linkMain": "https://...",
      "linkEvents": "",
      "socials": {"facebook": "...", "instagram": "...", ...},
      "contacts": [{"label": "...", "phone": "...", "email": "...", "other": ""}],
      "venueType": ["music-venue"],
      "eventCount": 47,
      "sampleEvents": ["The Wallflowers", "Bronco"],
      "reviewNeeded": false,
      "createdBy": "match-venues.auto"    // optional; present for auto-created
    }
  }
}
```

See [data-model.md](data-model.md) for full field semantics.

## Matching pipeline

Every event goes through this pipeline inside `update-metadata.py` (via
`match-venues.py::match_or_create`):

```
event.venue = "Red Hat Amp"
event.address = ""
event.city = "Raleigh"
event.zip = ""
              │
              ▼
   ┌─────────────────────────┐
   │ Pass 1: name_to_slug    │
   │  "red hat amp" → slug?  │
   └─────────────────────────┘
              │  hit → return (slug, "name")
              │  miss ↓
   ┌─────────────────────────┐
   │ Pass 2: canonkey_to_slug│
   │  key = canonical_key(   │
   │    addr, city, zip5)    │
   └─────────────────────────┘
              │  hit → return (slug, "canonkey")
              │  miss (or blank address) ↓
   ┌─────────────────────────┐
   │ Pass 3: fuzzy within    │
   │        same city        │
   │  rapidfuzz partial_ratio│
   │        ≥ 85             │
   └─────────────────────────┘
              │  hit → return (slug, "fuzzy")
              │  miss ↓
   ┌─────────────────────────┐
   │ create_venue_from_event │
   │  → new stub in registry │
   │  → updates in-mem index │
   │  → returns (slug, "created")
   └─────────────────────────┘
```

**Order matters.** Name match is exact and cheap; canonical-key match handles
name-typos when the address is known; fuzzy is the escape hatch, restricted
to same-city to prevent "Ritz Raleigh" matching "Ritz Durham".

### Index construction (`build_indexes`)

```python
idx = {
    "name_to_slug":     {"321 coffee": "321-coffee-raleigh", ...},
    "canonkey_to_slug": {"615 hillsborough street|raleigh|27603": "321-coffee-raleigh", ...},
    "by_city":          {"raleigh": [(slug, lowername, aliases), ...], ...},
}
```

Aliases are also indexed into `name_to_slug`, so adding `"Red Hat"` to a
venue's `aliases` array immediately makes that spelling resolve.

### Canonical key normalization (`venue_utils.canonical_key`)

- Lowercase
- Collapse `st`/`street`, `ave`/`avenue`, `blvd`/`boulevard`, etc. (see
  `_STREET_ABBR` in `venue_utils.py`)
- Strip punctuation
- 5-digit zip only

`"615 Hillsborough St, Raleigh, NC 27603-1234"` and
`"615 hillsborough street, raleigh, 27603"` produce the same key.

## Auto-created stubs

When `match_or_create` doesn't find a match, it inserts a stub:

```python
{
    "slug": <generated>,
    "name": event.venue,
    "aliases": [],
    "address": event.address,          # from LLM enrichment of the event
    "city": event.city,
    "state": event.state or "NC",
    "zip": event.zip,
    "lat": None, "lng": None,
    "place_id": None,                  # osm_id NOT included until geocoded
    "linkMain": "", "linkEvents": "",
    "socials": {all 9 platforms: ""},
    "contacts": [],
    "venueType": [],
    "eventCount": 1,
    "sampleEvents": [event.name[:120]],
    "reviewNeeded": True if address is blank else False,
    "createdBy": "match-venues.auto",
}
```

Then it updates the in-memory indexes so that if the same venue name appears
in later events in the same batch, they all resolve to this stub (rather than
creating duplicates).

**Follow-up required**: The stub has no lat/lng, no linkMain, no socials, no
contacts, no venueType. Steps 4–5 of the [weekly-workflow](weekly-workflow.md)
(geocode + enrich) fill these in.

## Statistics (as of 2026-08-07)

Snapshot of registry health from the most recent run:

| Metric               | Count | % of total |
|----------------------|-------|-----------|
| Total venues         | 446   | 100%      |
| Geocoded (lat set)   | 384   | 86%       |
| With `linkMain`      | 412   | 92%       |
| With any contact     | 418   | 94%       |
| With any social      | 223   | 50%       |
| With `venueType`     | 338   | 76%       |

Coverage is deliberately imperfect. Some venues (e.g. "Downtown Raleigh"
as a venue string) are conceptual and don't have a single address. Others
are one-off pop-ups that will never appear again. We don't try to be a
CRM; we try to make weekend planning slightly easier.

## Manual editing

Direct edits to `data/venues.json` are the officially blessed way to:

- Add an alias to catch a new spelling
- Correct a wrong address or phone
- Add a linkEvents URL the enricher missed
- Merge two accidentally-duplicated stubs (delete one, add its name to the
  survivor's `aliases`, then re-run `match-venues.py --all` to rewrite
  `venueId`s in the archive)

After manual edits, run:

```bash
python scripts/match-venues.py --dry-run
```

to sanity-check that no events lost their `venueId` mapping.

## When the matcher creates a duplicate

The most common failure mode: same venue, different city string, e.g.
"Peck & Plume" in Cary vs "Peck & Plume" (no city) in the newsletter.

Fix:

1. Manually merge in `venues.json`:
   - Keep the more-enriched record
   - Add the other's `name` to the survivor's `aliases`
   - Delete the duplicate key
2. Re-run: `python scripts/match-venues.py --all`
3. Commit both files.

Do NOT delete a venue key without first making sure no event references
it — `match-venues.py --all` will surface those.
