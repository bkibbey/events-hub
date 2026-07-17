#!/usr/bin/env python3
"""Geocode venues in data/venues.json using a pluggable provider.

Providers:
  census    US Census Bureau Geocoder — free, no key, US-only. Best for bulk.
            https://geocoding.geo.census.gov/
  nominatim OpenStreetMap Nominatim — free, no key, worldwide. Strict rate limits
            (4 req/min for long-running scripts, ~300/day empirical cap).
            Good for one-off adds after initial seed.

Only touches venues where lat is None AND address is truthy.
Populates: lat, lng, place_id, osm_id.

Flags:
  --provider census|nominatim   Which provider to use (default: census)
  --dry-run                     Show what would be geocoded without calling API
  --limit N                     Process at most N venues (useful for testing)
  --only-slugs a,b,c            Only process these specific slugs
  --force                       Re-geocode even venues with lat already set
  --sleep N                     Seconds between requests (default: provider-appropriate)
"""
from __future__ import annotations
import argparse
import json
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

_HERE = Path(__file__).parent.resolve()
REPO_ROOT = _HERE.parent
VENUES_JSON = REPO_ROOT / "data" / "venues.json"

USER_AGENT = "events-hub-venue-geocoder/1.0 (https://github.com/bkibbey/events-hub)"


# ------------------------------------------------------------
# Query building (shared)
# ------------------------------------------------------------


def build_full_query(v: dict) -> str:
    """Full 'address, city, state, zip' string with dedup."""
    addr = (v.get("address") or "").strip()
    city = (v.get("city") or "").strip()
    state = (v.get("state") or "").strip()
    zp = (v.get("zip") or "").strip()

    parts = [addr] if addr else []
    addr_lower = addr.lower()
    if city and city.lower() not in addr_lower:
        parts.append(city)
    if state and state.lower() not in addr_lower:
        parts.append(state)
    if zp and zp not in addr_lower:
        parts.append(zp)
    return ", ".join(parts)


# ------------------------------------------------------------
# Provider: Nominatim (OpenStreetMap)
# ------------------------------------------------------------

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"


def geocode_nominatim(v: dict, timeout: int = 15) -> dict | None:
    """Return normalized geocode dict or None.

    Result shape: {lat, lng, place_id, osm_id, raw}
    """
    query = build_full_query(v)
    if not query:
        return None
    params = {
        "q": query,
        "format": "json",
        "addressdetails": 0,
        "limit": 1,
        "countrycodes": "us",
    }
    url = f"{NOMINATIM_URL}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        print(f"    ERR (nominatim): {e}", file=sys.stderr)
        return None
    if not data:
        return None
    r = data[0]
    if not r.get("lat") or not r.get("lon"):
        return None
    osm_type = r.get("osm_type", "")
    osm_id = r.get("osm_id")
    osm = f"{osm_type}/{osm_id}" if osm_type and osm_id is not None else None
    return {
        "lat": float(r["lat"]),
        "lng": float(r["lon"]),
        "place_id": str(r["place_id"]) if r.get("place_id") is not None else None,
        "osm_id": osm,
        "provider": "nominatim",
    }


# ------------------------------------------------------------
# Provider: US Census Geocoder
# ------------------------------------------------------------
#
# One-line address endpoint:
#   https://geocoding.geo.census.gov/geocoder/locations/onelineaddress
#   ?address={...}&benchmark=Public_AR_Current&format=json
#
# Docs: https://geocoding.geo.census.gov/geocoder/Geocoding_Services_API.pdf
# No API key required. No documented per-second rate limit; practical guidance
# is to keep it modest. Batch endpoint supports up to 10k addresses at once,
# but for our incremental use single-address is fine.

CENSUS_URL = "https://geocoding.geo.census.gov/geocoder/locations/onelineaddress"


def geocode_census(v: dict, timeout: int = 20) -> dict | None:
    """Return normalized geocode dict or None."""
    query = build_full_query(v)
    if not query:
        return None
    params = {
        "address": query,
        "benchmark": "Public_AR_Current",
        "format": "json",
    }
    url = f"{CENSUS_URL}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        print(f"    ERR (census): {e}", file=sys.stderr)
        return None

    matches = (data.get("result") or {}).get("addressMatches") or []
    if not matches:
        return None
    m = matches[0]
    coords = m.get("coordinates") or {}
    lat = coords.get("y")
    lng = coords.get("x")
    if lat is None or lng is None:
        return None
    return {
        "lat": float(lat),
        "lng": float(lng),
        # Census returns a matchedAddress + tigerLine.tigerLineId which we can use
        # as a stable identifier for the street segment.
        "place_id": None,
        "osm_id": None,
        "census_tigerline": (m.get("tigerLine") or {}).get("tigerLineId"),
        "matched_address": m.get("matchedAddress"),
        "provider": "census",
    }


# ------------------------------------------------------------
# Provider registry + defaults
# ------------------------------------------------------------

PROVIDERS = {
    "census": {
        "fn": geocode_census,
        "default_sleep": 0.25,  # Census is generous; small pause is polite
    },
    "nominatim": {
        "fn": geocode_nominatim,
        # Nominatim policy: 4 req/min for long-running scripts = 15s/request.
        # Practical: use for small ad-hoc runs only.
        "default_sleep": 1.1,
    },
}


# ------------------------------------------------------------
# Core loop
# ------------------------------------------------------------


def needs_geo(v: dict, force: bool) -> bool:
    if not v.get("address"):
        return False
    if force:
        return True
    return v.get("lat") is None


def apply_result(v: dict, result: dict) -> None:
    """Merge a normalized provider result into a venue record."""
    v["lat"] = result["lat"]
    v["lng"] = result["lng"]
    if result.get("place_id"):
        v["place_id"] = result["place_id"]
    if result.get("osm_id"):
        v["osm_id"] = result["osm_id"]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--provider", choices=list(PROVIDERS.keys()), default="census")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--only-slugs", default=None,
                    help="comma-separated slugs to process")
    ap.add_argument("--force", action="store_true",
                    help="re-geocode even if lat is set")
    ap.add_argument("--sleep", type=float, default=None,
                    help="seconds between requests (default: provider-appropriate)")
    args = ap.parse_args()

    provider_cfg = PROVIDERS[args.provider]
    geocode_fn = provider_cfg["fn"]
    sleep_s = args.sleep if args.sleep is not None else provider_cfg["default_sleep"]

    only = set(s.strip() for s in args.only_slugs.split(",")) if args.only_slugs else None

    registry = json.loads(VENUES_JSON.read_text())
    venues = registry["venues"]

    # One-time schema migration: ensure osm_id field on every venue
    added_osm_id = 0
    for slug, v in venues.items():
        if "osm_id" not in v:
            v["osm_id"] = None
            added_osm_id += 1
    if added_osm_id:
        print(f"Schema: added osm_id field to {added_osm_id} venues")

    # Build target list
    targets: list[tuple[str, dict]] = []
    for slug, v in venues.items():
        if only and slug not in only:
            continue
        if not needs_geo(v, args.force):
            continue
        targets.append((slug, v))

    if args.limit:
        targets = targets[: args.limit]

    print(f"Provider: {args.provider} (sleep {sleep_s}s)")
    print(f"Geocoding {len(targets)} venues (of {len(venues)} total)")
    if args.dry_run:
        for slug, v in targets:
            print(f"  DRY {slug}: {build_full_query(v)}")
        return 0

    stats = {"ok": 0, "empty": 0}
    for i, (slug, v) in enumerate(targets, 1):
        query = build_full_query(v)
        print(f"[{i}/{len(targets)}] {slug}: {query}")
        result = geocode_fn(v)
        if result is None:
            stats["empty"] += 1
            print("    -> no result")
        else:
            apply_result(v, result)
            extra = ""
            if result.get("osm_id"):
                extra = f"  ({result['osm_id']})"
            elif result.get("census_tigerline"):
                extra = f"  (tigerLine {result['census_tigerline']})"
            print(f"    -> {v['lat']:.5f}, {v['lng']:.5f}{extra}")
            stats["ok"] += 1

        # Save incrementally every 25 to survive interruption
        if i % 25 == 0:
            registry["geocodedAt"] = datetime.now(timezone.utc).isoformat()
            VENUES_JSON.write_text(json.dumps(registry, indent=2) + "\n")
            print(f"    (checkpoint saved at {i}/{len(targets)})")

        # Rate limit
        if i < len(targets):
            time.sleep(sleep_s)

    # Final save
    registry["geocodedAt"] = datetime.now(timezone.utc).isoformat()
    VENUES_JSON.write_text(json.dumps(registry, indent=2) + "\n")

    print()
    print(f"Done. OK: {stats['ok']} | Empty: {stats['empty']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
