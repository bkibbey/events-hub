#!/usr/bin/env python3
"""Attach venueId to each event in a week's events JSON.

Matching passes (in order — first match wins):
  1. Exact match: event.venue (lowercased) matches a venue's canonical name
     or any alias.
  2. Address+city key: normalize the event's address+city and compare against
     each venue's canonical_key. Same logic used in seed-venues.py.
  3. Fuzzy name match: rapidfuzz partial_ratio >= 85 against canonical name
     and aliases, restricted to same city.

Writes a `venueId` field onto every event object. Sets it to null if no match
is found (usually a data-quality issue: mistyped city, brand-new venue, etc.).

By default operates on data/events.json. Pass --week YYYY-MM-DD to operate
on data/archive/events-YYYY-MM-DD.json instead. Pass --all to process the
current file plus every archive.

Flags:
  --week YYYY-MM-DD    Backfill one archived week
  --all                Backfill current + every archive
  --dry-run            Show match stats without writing
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

_HERE = Path(__file__).parent.resolve()
sys.path.insert(0, str(_HERE))

from venue_utils import canonical_key, name_key, slugify  # noqa: E402
from rapidfuzz import fuzz  # noqa: E402

# Kept in sync with seed-venues.py — the fixed vocabulary of social platforms.
# If seed-venues ever adds/removes one, mirror it here.
SOCIAL_PLATFORMS = (
    "facebook", "instagram", "twitter", "tiktok", "youtube",
    "linkedin", "reddit", "threads", "bluesky",
)

REPO_ROOT = _HERE.parent
VENUES_JSON = REPO_ROOT / "data" / "venues.json"
EVENTS_JSON = REPO_ROOT / "data" / "events.json"
ARCHIVE_DIR = REPO_ROOT / "data" / "archive"

FUZZY_THRESHOLD = 85


def build_indexes(registry: dict) -> dict:
    """Precompute lookup tables from the venue registry.

    Returns:
      name_to_slug:   dict[name_lower] -> slug   (canonical names + aliases)
      canonkey_to_slug: dict[canonical_key] -> slug   (address+city key)
      by_city:        dict[city_lower] -> list[(slug, name_lower, aliases_lower)]
    """
    venues = registry["venues"]
    name_to_slug: dict[str, str] = {}
    canonkey_to_slug: dict[str, str] = {}
    by_city: dict[str, list] = {}

    for slug, v in venues.items():
        # name index (canonical + aliases)
        names = [v.get("name") or ""] + list(v.get("aliases") or [])
        for n in names:
            n_lower = n.strip().lower()
            if n_lower and n_lower not in name_to_slug:
                name_to_slug[n_lower] = slug

        # address+city canonical key
        addr = v.get("address") or ""
        city = v.get("city") or ""
        zp = v.get("zip") or ""
        ck = canonical_key(addr, city, zp)
        if ck and ck not in canonkey_to_slug:
            canonkey_to_slug[ck] = slug

        # by-city index for fuzzy fallback
        city_lower = city.strip().lower()
        entry = (slug, (v.get("name") or "").strip().lower(),
                 [a.strip().lower() for a in (v.get("aliases") or [])])
        by_city.setdefault(city_lower, []).append(entry)

    return {
        "name_to_slug": name_to_slug,
        "canonkey_to_slug": canonkey_to_slug,
        "by_city": by_city,
    }


def match_event(event: dict, idx: dict) -> tuple[str | None, str]:
    """Return (slug or None, reason).

    Reason is one of: 'name', 'canonical_key', 'fuzzy', 'no_match'.
    """
    venue = (event.get("venue") or "").strip().lower()
    city = (event.get("city") or "").strip().lower()
    address = event.get("address") or ""

    # Pass 1: exact name match (canonical or alias)
    if venue and venue in idx["name_to_slug"]:
        return idx["name_to_slug"][venue], "name"

    # Pass 2: address+city canonical key
    ck = canonical_key(address, city, event.get("zip") or "")
    if ck and ck in idx["canonkey_to_slug"]:
        return idx["canonkey_to_slug"][ck], "canonical_key"

    # Pass 3: fuzzy name match within same city
    if venue and city:
        candidates = idx["by_city"].get(city, [])
        best_score = 0
        best_slug = None
        for slug, name_lower, aliases_lower in candidates:
            score = fuzz.partial_ratio(venue, name_lower)
            for a in aliases_lower:
                if a:
                    score = max(score, fuzz.partial_ratio(venue, a))
            if score > best_score:
                best_score = score
                best_slug = slug
        if best_score >= FUZZY_THRESHOLD:
            return best_slug, "fuzzy"

    return None, "no_match"


def _empty_socials() -> dict:
    return {p: "" for p in SOCIAL_PLATFORMS}


def _unique_slug(base: str, registry: dict) -> str:
    """Return base, base-2, base-3, ... until we find a slug not in the registry."""
    venues = registry["venues"]
    if base not in venues:
        return base
    n = 2
    while f"{base}-{n}" in venues:
        n += 1
    return f"{base}-{n}"


def create_venue_from_event(event: dict, registry: dict, idx: dict) -> str:
    """Insert a new venue stub into `registry` derived from `event`, update the
    live indexes in `idx`, and return the new slug.

    Stub fields (address, city, state, zip) come from the event. Enrichment
    (linkMain, socials, contacts, lat/lng, place_id) is left blank for later
    passes (enrich-venues.py, geocode-venues.py).
    """
    name = (event.get("venue") or "").strip() or "Unknown Venue"
    city = (event.get("city") or "").strip()
    state = (event.get("state") or "NC").strip()

    # Slug convention matches seed-venues.py: "{name}-{city}" if city is set,
    # otherwise just "{name}".
    base = slugify(name)
    if city:
        base = f"{base}-{slugify(city)}"
    slug = _unique_slug(base, registry)

    record = {
        "slug": slug,
        "name": name,
        "aliases": [],
        "address": (event.get("address") or "").strip(),
        "city": city,
        "state": state,
        "zip": (event.get("zip") or "").strip(),
        "lat": None,
        "lng": None,
        "place_id": None,
        "linkMain": "",
        "linkEvents": "",
        "socials": _empty_socials(),
        "contacts": [],
        "venueType": [],
        "eventCount": 1,
        "sampleEvents": [event.get("name", "")[:120]] if event.get("name") else [],
        "reviewNeeded": not (event.get("address") or "").strip(),
        "createdBy": "match-venues.auto",
    }
    registry["venues"][slug] = record

    # Keep indexes fresh so subsequent events this batch can match against the
    # newly-created venue (avoids creating three copies of the same new venue
    # when it appears in three events).
    idx["name_to_slug"][name.lower()] = slug
    ck = canonical_key(record["address"], city, record["zip"])
    if ck:
        idx["canonkey_to_slug"][ck] = slug
    idx["by_city"].setdefault(city.lower(), []).append(
        (slug, name.lower(), [])
    )
    return slug


def match_or_create(event: dict, registry: dict, idx: dict) -> tuple[str, str]:
    """Match an event's venue against the registry. On no_match, insert a
    new stub venue and return its slug (with reason='created'). Caller is
    responsible for persisting `registry` after processing all events.
    """
    slug, reason = match_event(event, idx)
    if slug:
        return slug, reason
    new_slug = create_venue_from_event(event, registry, idx)
    return new_slug, "created"


def process_events_file(path: Path, idx: dict, dry: bool) -> dict:
    """Match all events in a file. Returns stats dict."""
    data = json.loads(path.read_text())
    if isinstance(data, dict):
        events = data.get("events", [])
    else:
        events = data

    stats = {"total": len(events), "name": 0, "canonical_key": 0,
             "fuzzy": 0, "no_match": 0, "no_match_events": []}

    for ev in events:
        slug, reason = match_event(ev, idx)
        ev["venueId"] = slug
        stats[reason] = stats.get(reason, 0) + 1
        if reason == "no_match":
            stats["no_match_events"].append({
                "name": ev.get("name", ""),
                "venue": ev.get("venue", ""),
                "city": ev.get("city", ""),
            })

    if not dry:
        # Preserve original structure
        if isinstance(data, dict):
            data["events"] = events
            path.write_text(json.dumps(data, indent=2) + "\n")
        else:
            path.write_text(json.dumps(events, indent=2) + "\n")

    return stats


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--week", default=None,
                    help="Backfill single archived week (YYYY-MM-DD)")
    ap.add_argument("--all", action="store_true",
                    help="Backfill current events.json + every archived week")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    registry = json.loads(VENUES_JSON.read_text())
    idx = build_indexes(registry)
    print(f"Venue registry loaded: {len(registry['venues'])} venues")
    print(f"  name index: {len(idx['name_to_slug'])} entries")
    print(f"  canonical_key index: {len(idx['canonkey_to_slug'])} entries")

    # Determine files to process
    files: list[Path] = []
    if args.all:
        files.append(EVENTS_JSON)
        for p in sorted(ARCHIVE_DIR.glob("events-*.json")):
            files.append(p)
    elif args.week:
        p = ARCHIVE_DIR / f"events-{args.week}.json"
        if not p.exists():
            print(f"ERROR: {p} does not exist", file=sys.stderr)
            return 2
        files.append(p)
    else:
        files.append(EVENTS_JSON)

    grand = {"total": 0, "name": 0, "canonical_key": 0, "fuzzy": 0, "no_match": 0}
    for f in files:
        print(f"\n=== {f.relative_to(REPO_ROOT)} ===")
        s = process_events_file(f, idx, args.dry_run)
        for k in grand:
            grand[k] += s.get(k, 0)
        matched = s["name"] + s["canonical_key"] + s["fuzzy"]
        pct = 100 * matched // s["total"] if s["total"] else 0
        print(f"  {matched}/{s['total']} matched ({pct}%)"
              f"  [name:{s['name']} canonkey:{s['canonical_key']} fuzzy:{s['fuzzy']}]"
              f"  no_match:{s['no_match']}")
        if s["no_match_events"] and s["no_match"] <= 15:
            for e in s["no_match_events"]:
                print(f"    NO MATCH: '{e['venue']}' in {e['city']!r} (event: {e['name'][:60]})")

    if len(files) > 1:
        print(f"\n=== GRAND TOTAL ===")
        matched = grand["name"] + grand["canonical_key"] + grand["fuzzy"]
        pct = 100 * matched // grand["total"] if grand["total"] else 0
        print(f"  {matched}/{grand['total']} matched ({pct}%)")
        print(f"  by pass: name={grand['name']} canonkey={grand['canonical_key']} fuzzy={grand['fuzzy']}")
        print(f"  unmatched: {grand['no_match']}")

    if args.dry_run:
        print("\n(dry run — no files written)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
