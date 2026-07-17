#!/usr/bin/env python3
"""Seed data/venues.json from all archived weekly event files.

Two passes:
  1. Group by canonical (normalized_address, city, zip5). Ground truth.
  2. For groups with empty/missing address, fuzzy-match name within same city
     against already-anchored venues (>=85% similarity) to attach them.

Then within each merged group:
  - Pick canonical name = most-frequent, ties broken by fewer qualifiers, then shorter
  - Aggregate aliases (all other name variants)
  - Aggregate best address/zip (from any non-empty member)
  - Slugify canonical name (dedupe collisions with -2, -3, ...)

Applies data/venues-overrides.json aliases/merges before writing.

Runs in dry-run mode by default → writes venues-seed-report.md only.
Pass --write to also produce data/venues.json.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

# Allow running from repo root or scripts/
_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
from venue_utils import (  # noqa: E402
    canonical_key,
    clean_name_for_canonical,
    name_key,
    normalize_address,
    normalize_city,
    normalize_zip,
    qualifier_penalty,
    slugify,
)

try:
    from rapidfuzz import fuzz
except ImportError:  # pragma: no cover
    print("ERROR: rapidfuzz not installed. Run: pip install rapidfuzz", file=sys.stderr)
    sys.exit(1)


REPO_ROOT = _HERE.parent
ARCHIVE_DIR = REPO_ROOT / "data" / "archive"
VENUES_JSON = REPO_ROOT / "data" / "venues.json"
OVERRIDES_JSON = REPO_ROOT / "data" / "venues-overrides.json"
REPORT_MD = REPO_ROOT / "data" / "venues-seed-report.md"

FUZZY_THRESHOLD = 85  # user preference

# Fixed vocabulary of social platforms we track per venue (empty strings when unknown)
SOCIAL_PLATFORMS = [
    "facebook", "instagram", "twitter", "threads", "bluesky",
    "tiktok", "youtube", "reddit", "linkedin",
]

# Keyword-based venueType inference. Match against lowercased canonical name;
# each rule adds one tag. Order doesn't matter; a venue can get multiple tags.
VENUE_TYPE_RULES: list[tuple[re.Pattern, str]] = [
    # Kind
    (re.compile(r"\b(theatre|theater|opera|playhouse|auditorium|stage|performing\s+arts)\b", re.I), "theater"),
    (re.compile(r"\b(museum|gallery|planetarium|art\s+center)\b", re.I), "museum"),
    (re.compile(r"\b(comedy\s+club|improv|comedyworx|comedy\s+worx|dsi\s+comedy)\b", re.I), "comedy-club"),
    (re.compile(r"\b(music\s+hall|record\s+shop|amphitheat(re|er)|concert|live\s+music)\b", re.I), "music-venue"),
    (re.compile(r"\b(stadium|ballpark|arena|coliseum|lenovo\s+center|pnc\s+arena|dean\s+smith\s+center)\b", re.I), "stadium"),
    (re.compile(r"\b(park|field|garden|lawn|greenway|trail|meadow|arboretum|preserve|wildlife\s+refuge)\b", re.I), "park"),
    (re.compile(r"\b(plaza|square|commons)\b", re.I), "plaza"),
    (re.compile(r"\b(library)\b", re.I), "library"),
    (re.compile(r"\b(church|chapel|cathedral|synagogue|temple|methodist|baptist|presbyterian|unitarian|episcopal|catholic\s+church|parish)\b", re.I), "church"),
    (re.compile(r"\b(brewery|brewing|beer\s+lab|taproom|tap\s+yard|tap\s+room|ale\s+house|beer\s+garden)\b", re.I), "brewery"),
    (re.compile(r"\b(distillery|distilling)\b", re.I), "distillery"),
    (re.compile(r"\b(winery|vineyard|wine\s+bar)\b", re.I), "winery"),
    (re.compile(r"\b(bar|pub|tavern|lounge|dive|social\s+club|cocktail)\b", re.I), "bar"),
    (re.compile(r"\b(restaurant|kitchen|caf[eé]|coffee|diner|eatery|pizzeria|bakery)\b", re.I), "restaurant"),
    (re.compile(r"\b(hotel|inn|resort)\b", re.I), "hotel"),
    (re.compile(r"\b(community\s+center|rec\s+center|recreation\s+center|senior\s+center|ymca|jcc)\b", re.I), "community-center"),
    # School only when whole tokens like 'university', 'college', 'high school', 'elementary', not 'academy'
    # ('academy' as a bare word is too common in venue names like 'Academy Pavilion' at Downtown Cary Park)
    (re.compile(r"\b(university|college|high\s+school|elementary|middle\s+school|charter\s+school)\b", re.I), "school"),
    (re.compile(r"\b(farm|orchard|farmers?\s+market)\b", re.I), "farm"),
    (re.compile(r"\b(town\s+hall|city\s+hall|courthouse|county\s+building|state\s+capitol|state\s+house)\b", re.I), "government"),
    (re.compile(r"\b(market|marketplace|mercantile|bazaar)\b", re.I), "market"),
    (re.compile(r"\b(hall|ballroom|event\s+space|banquet|conference\s+center|convention\s+center)\b", re.I), "event-space"),
    (re.compile(r"\b(nightclub|dance\s+club|discotheque)\b", re.I), "club"),
    (re.compile(r"\b(historic|historical\s+site|heritage|landmark|manor|plantation)\b", re.I), "historic-site"),
    # Setting hints
    (re.compile(r"\b(park|field|garden|lawn|greenway|trail|amphitheat(re|er)|plaza|square|commons|stadium|ballpark|farm|orchard|market|festival\s+grounds|outdoor|rooftop|vineyard|preserve|beer\s+garden|meadow|arboretum)\b", re.I), "outdoor"),
    (re.compile(r"\b(theatre|theater|opera|playhouse|auditorium|museum|gallery|hall|ballroom|hotel|inn|library|nightclub|comedy\s+club|arena|coliseum|brewery|distillery|bar|pub|tavern|lounge|restaurant|church|chapel|cathedral|community\s+center|event\s+space|banquet|record\s+shop|conference\s+center|convention\s+center|planetarium|art\s+center|performing\s+arts)\b", re.I), "indoor"),
]


def empty_socials() -> dict:
    return {p: "" for p in SOCIAL_PLATFORMS}


def infer_venue_type(name: str, aliases: list[str]) -> list[str]:
    """Return sorted list of tag strings inferred from the canonical name.

    We deliberately do NOT match aliases because they often describe sub-locations
    within a venue (e.g. 'NCMA Cafe', 'Meymandi Exhibition Gallery', 'Academy Pavilion')
    that would produce misleading tags like 'restaurant' or 'gallery' at the parent venue.
    """
    haystack = name.lower()
    tags: set[str] = set()
    for rx, tag in VENUE_TYPE_RULES:
        if rx.search(haystack):
            tags.add(tag)
    return sorted(tags)


def load_overrides() -> dict:
    if not OVERRIDES_JSON.exists():
        return {"aliases": {}, "merges": {}, "dropped": [], "venues": {}}
    raw = json.loads(OVERRIDES_JSON.read_text())
    # Filter out _comment / _example / example entries
    def _clean(d: dict | None) -> dict:
        if not d:
            return {}
        return {k: v for k, v in d.items()
                if not k.startswith("_") and not k.startswith("example")}

    aliases = {k.lower(): v for k, v in _clean(raw.get("aliases")).items()}
    merges = _clean(raw.get("merges"))
    dropped = list(raw.get("dropped") or [])
    venues = _clean(raw.get("venues"))
    return {"aliases": aliases, "merges": merges, "dropped": dropped, "venues": venues}


def collect_raw_venues() -> list[dict]:
    """Return a list of raw venue observations, one per event.

    Each obs: {name, address, city, zip, state, event_name, week}
    """
    obs = []
    weeks_seen = 0
    for f in sorted(ARCHIVE_DIR.glob("events-*.json")):
        weeks_seen += 1
        data = json.loads(f.read_text())
        week = data.get("week") or f.stem.replace("events-", "")
        for e in data.get("events", []):
            venue = (e.get("venue") or "").strip()
            if not venue:
                continue
            obs.append({
                "name": venue,
                "address": (e.get("address") or "").strip(),
                "city": (e.get("city") or "").strip(),
                "zip": (e.get("zip") or "").strip(),
                "state": (e.get("state") or "NC").strip(),
                "event_name": e.get("name", ""),
                "week": week,
            })
    return obs, weeks_seen


def pick_canonical_name(members: list[dict]) -> str:
    """Choose display name from group members.

    Rank: (name_looks_like_address asc, frequency desc, qualifier_penalty asc,
    length asc, name asc)
    Names starting with a digit are deprioritized — those are almost always
    the `venue` field mis-populated with an address string.
    """
    freq = Counter(m["name"] for m in members)

    def looks_like_address(name: str) -> int:
        return 1 if re.match(r"^\d", name.strip()) else 0

    def key(name: str):
        return (
            looks_like_address(name),
            -freq[name],
            qualifier_penalty(name),
            len(name),
            name.lower(),
        )

    return sorted(freq.keys(), key=key)[0]


def pick_best_address(members: list[dict]) -> tuple[str, str, str, str]:
    """Return (address, city, zip, state) using most-common non-empty values."""
    def most_common(field: str) -> str:
        vals = [m[field] for m in members if m.get(field)]
        if not vals:
            return ""
        return Counter(vals).most_common(1)[0][0]

    return (
        most_common("address"),
        most_common("city"),
        most_common("zip"),
        most_common("state") or "NC",
    )


def build_groups(obs: list[dict], overrides: dict) -> dict:
    """Return {group_id: [members]} where group_id is a canonical key or synthetic."""
    aliases = overrides["aliases"]

    # Pass 1: exact override alias -> pre-assigned slug (deferred: we don't
    # know slug members yet, so mark and route later)
    forced_slug: dict[int, str] = {}
    for i, o in enumerate(obs):
        target = aliases.get(o["name"].lower())
        if target:
            forced_slug[i] = target

    # Pass 2: group by canonical (address+city+zip) key
    groups: dict[str, list[dict]] = defaultdict(list)
    unanchored: list[tuple[int, dict]] = []  # (obs_idx, obs)

    for i, o in enumerate(obs):
        if i in forced_slug:
            groups[f"__forced__{forced_slug[i]}"].append(o)
            continue
        ck = canonical_key(o["address"], o["city"], o["zip"])
        if ck:
            groups[ck].append(o)
        else:
            unanchored.append((i, o))

    # Pass 3: for unanchored (no address), fuzzy-match against groups in same city
    # Build (city -> [(group_id, canonical_name_key)]) index
    city_index: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
    for gid, members in groups.items():
        # Best canonical name so far for fuzzy comparison
        canon = pick_canonical_name(members)
        canon_key_ = name_key(canon)
        # Use the most common city among members
        city = Counter(m["city"] for m in members if m["city"]).most_common(1)
        city_norm = normalize_city(city[0][0]) if city else ""
        city_index[city_norm].append((gid, canon, canon_key_))

    still_unanchored: list[dict] = []
    for _i, o in unanchored:
        city_norm = normalize_city(o["city"])
        nk = name_key(o["name"])
        candidates = city_index.get(city_norm, [])
        best_gid, best_score = None, 0
        for gid, canon, canon_nk in candidates:
            if not canon_nk or not nk:
                continue
            score = fuzz.token_set_ratio(nk, canon_nk)
            if score > best_score:
                best_score, best_gid = score, gid
        if best_gid and best_score >= FUZZY_THRESHOLD:
            groups[best_gid].append({**o, "_fuzzy_score": best_score})
        else:
            still_unanchored.append(o)

    # Pass 4: fuzzy-cluster remaining unanchored by name within city
    used = [False] * len(still_unanchored)
    for i, o in enumerate(still_unanchored):
        if used[i]:
            continue
        cluster = [o]
        used[i] = True
        for j in range(i + 1, len(still_unanchored)):
            if used[j]:
                continue
            p = still_unanchored[j]
            if normalize_city(o["city"]) != normalize_city(p["city"]):
                continue
            score = fuzz.token_set_ratio(name_key(o["name"]), name_key(p["name"]))
            if score >= FUZZY_THRESHOLD:
                cluster.append(p)
                used[j] = True
        # Synthetic group id — use slug of first name + city
        synth_id = f"__syn__{slugify(o['name'])}--{slugify(o['city']) or 'nocity'}"
        groups[synth_id].extend(cluster)

    # Pass 5: name-based fuzzy cross-group merge.
    # If two DIFFERENT anchored groups share the same canonical name AND same city AND
    # the smaller group has <=2 events, absorb it into the larger one. This handles the
    # common case where AI enrichment gave a slightly-different address for the same venue.
    NAME_MERGE_THRESHOLD = 95  # very strict
    SMALL_GROUP_MAX = 2        # only absorb tiny groups this way

    # Build (city_norm, canonical_name_key) -> [(gid, size, canonical_name)]
    by_name_city: dict[tuple[str, str], list[tuple[str, int, str]]] = defaultdict(list)
    for gid, members in groups.items():
        if gid.startswith("__forced__") or gid.startswith("__syn__"):
            continue
        canon = pick_canonical_name(members)
        city_norm = normalize_city(
            Counter(m["city"] for m in members if m["city"]).most_common(1)[0][0]
            if any(m["city"] for m in members) else ""
        )
        nk = name_key(canon)
        if nk:
            by_name_city[(city_norm, nk)].append((gid, len(members), canon))

    absorb_map: dict[str, str] = {}  # loser gid -> winner gid
    for (city_norm, nk), entries in by_name_city.items():
        if len(entries) < 2:
            continue
        # Winner = largest group
        entries.sort(key=lambda x: (-x[1], x[0]))
        winner_gid, winner_size, _ = entries[0]
        for gid, size, _ in entries[1:]:
            if size <= SMALL_GROUP_MAX:
                # Same exact name_key means score 100 already
                absorb_map[gid] = winner_gid

    # Also handle near-matches with fuzz >=95
    canon_by_gid: dict[str, tuple[str, str]] = {}  # gid -> (city_norm, canonical_name)
    for gid, members in groups.items():
        if gid.startswith("__forced__") or gid.startswith("__syn__"):
            continue
        if gid in absorb_map:
            continue
        canon = pick_canonical_name(members)
        city_norm = normalize_city(
            Counter(m["city"] for m in members if m["city"]).most_common(1)[0][0]
            if any(m["city"] for m in members) else ""
        )
        canon_by_gid[gid] = (city_norm, canon)

    small_gids = [gid for gid, members in groups.items()
                  if not gid.startswith("__") and gid not in absorb_map
                  and len(members) <= SMALL_GROUP_MAX]
    large_gids = [gid for gid, members in groups.items()
                  if not gid.startswith("__") and gid not in absorb_map
                  and len(members) > SMALL_GROUP_MAX]

    for small_gid in small_gids:
        s_city, s_canon = canon_by_gid.get(small_gid, ("", ""))
        s_nk = name_key(s_canon)
        if not s_nk:
            continue
        best_gid, best_score = None, 0
        for large_gid in large_gids:
            l_city, l_canon = canon_by_gid[large_gid]
            if l_city != s_city:
                continue
            score = fuzz.token_set_ratio(s_nk, name_key(l_canon))
            if score > best_score:
                best_score, best_gid = score, large_gid
        if best_gid and best_score >= NAME_MERGE_THRESHOLD:
            absorb_map[small_gid] = best_gid

    # Apply absorptions
    for loser, winner in absorb_map.items():
        groups[winner].extend(groups[loser])
        del groups[loser]

    # Apply merges from overrides (post-grouping)
    merges = overrides["merges"]
    # merges act on final slugs (see finalize step).
    return groups, merges


def _build_venue_record(slug: str, members: list[dict], gid: str) -> dict:
    canonical = pick_canonical_name(members)
    addr, city, zp, state = pick_best_address(members)
    aliases = sorted(
        {m["name"] for m in members if m["name"] != canonical},
        key=str.lower,
    )
    return {
        "slug": slug,
        "name": canonical,
        "aliases": aliases,
        "address": addr,
        "city": city,
        "state": state,
        "zip": zp,
        "lat": None,
        "lng": None,
        "place_id": None,
        "linkMain": "",
        "linkEvents": "",
        "socials": empty_socials(),
        "contacts": [],
        "venueType": infer_venue_type(canonical, aliases),
        "eventCount": len(members),
        "sampleEvents": _sample_events(members),
        "reviewNeeded": not addr,
        "_gid": gid,
    }


def _apply_venue_overrides(record: dict, override: dict) -> None:
    """Merge per-venue overrides into a record. Simple fields overwrite;
    socials merge key-by-key; contacts and venueType overwrite entirely.
    """
    for field in ("linkMain", "linkEvents"):
        if field in override:
            record[field] = override[field]
    if "socials" in override and isinstance(override["socials"], dict):
        # Only accept known platforms; keep others empty
        for platform in SOCIAL_PLATFORMS:
            if platform in override["socials"]:
                record["socials"][platform] = override["socials"][platform] or ""
    if "contacts" in override and isinstance(override["contacts"], list):
        # Normalize every contact to the full shape
        normalized = []
        for c in override["contacts"]:
            if not isinstance(c, dict):
                continue
            normalized.append({
                "label": c.get("label", "") or "",
                "phone": c.get("phone", "") or "",
                "email": c.get("email", "") or "",
                "other": c.get("other", "") or "",
            })
        record["contacts"] = normalized
    if "venueType" in override and isinstance(override["venueType"], list):
        record["venueType"] = sorted({str(t) for t in override["venueType"] if t})


def finalize(groups: dict, merges: dict, dropped: list[str], venue_overrides: dict) -> dict:
    """Assign slugs and produce final venue registry keyed by slug."""
    provisional: dict[str, dict] = {}

    for gid, members in groups.items():
        if gid.startswith("__forced__"):
            forced_slug = gid.replace("__forced__", "")
            provisional[forced_slug] = _build_venue_record(forced_slug, members, gid)
            continue

        canonical = pick_canonical_name(members)
        _, city, _, _ = pick_best_address(members)

        # Slug generation with collision handling
        base = slugify(f"{canonical}-{city}") if city else slugify(canonical)
        slug = base
        n = 2
        while slug in provisional:
            slug = f"{base}-{n}"
            n += 1

        provisional[slug] = _build_venue_record(slug, members, gid)

    # Apply merges from overrides
    for loser, winner in merges.items():
        if loser in provisional and winner in provisional:
            L = provisional.pop(loser)
            W = provisional[winner]
            W["aliases"] = sorted(set(W["aliases"]) | {L["name"]} | set(L["aliases"]), key=str.lower)
            W["eventCount"] += L["eventCount"]
            W["sampleEvents"] = list({*W["sampleEvents"], *L["sampleEvents"]})[:5]
            # Re-infer venueType with merged aliases
            W["venueType"] = sorted(set(W["venueType"]) | set(infer_venue_type(W["name"], W["aliases"])))

    # Apply dropped list (silently remove)
    for slug in dropped:
        provisional.pop(slug, None)

    # Apply per-venue field overrides
    for slug, override in venue_overrides.items():
        if slug in provisional and isinstance(override, dict):
            _apply_venue_overrides(provisional[slug], override)

    # Drop internal keys
    for v in provisional.values():
        v.pop("_gid", None)

    return provisional


def _sample_events(members: list[dict]) -> list[str]:
    seen = []
    for m in members:
        n = m.get("event_name")
        if n and n not in seen:
            seen.append(n)
        if len(seen) >= 5:
            break
    return seen


def write_report(registry: dict, obs_count: int, weeks: int) -> None:
    lines = []
    lines.append("# Venue seed report")
    lines.append("")
    lines.append(f"- Generated: {datetime.now(timezone.utc).isoformat()}")
    lines.append(f"- Weeks scanned: {weeks}")
    lines.append(f"- Raw venue observations: {obs_count}")
    lines.append(f"- Unique venues after dedup: {len(registry)}")
    lines.append(
        f"- Venues needing review (no address): "
        f"{sum(1 for v in registry.values() if v['reviewNeeded'])}"
    )
    lines.append("")

    # Sort: reviewNeeded first, then eventCount desc, then name
    ordered = sorted(
        registry.values(),
        key=lambda v: (not v["reviewNeeded"], -v["eventCount"], v["name"].lower()),
    )

    # Section 1: needs review
    review = [v for v in ordered if v["reviewNeeded"]]
    if review:
        lines.append("## Needs review (no address — check before publishing)")
        lines.append("")
        for v in review:
            lines.append(f"### {v['name']} ({v['city'] or '?'}) — `{v['slug']}`")
            lines.append(f"- Events: {v['eventCount']}")
            if v["aliases"]:
                lines.append(f"- Aliases: {', '.join(v['aliases'])}")
            if v["sampleEvents"]:
                lines.append(f"- Sample events: {'; '.join(v['sampleEvents'])}")
            lines.append("")

    # Section 2: merged groups (2+ aliases)
    merged = [v for v in ordered if not v["reviewNeeded"] and v["aliases"]]
    lines.append(f"## Merged venues ({len(merged)} groups)")
    lines.append("")
    lines.append(
        "These venues have >=2 name variants that were merged. Verify no false merges."
    )
    lines.append("")
    for v in merged:
        addr_str = f"{v['address']}, {v['city']}" if v["address"] else v["city"]
        lines.append(f"### {v['name']} — `{v['slug']}` ({v['eventCount']} events)")
        lines.append(f"- Address: {addr_str}")
        if v["venueType"]:
            lines.append(f"- Type: {', '.join(v['venueType'])}")
        lines.append(f"- Aliases: {', '.join(v['aliases'])}")
        lines.append("")

    # Section 3: singletons — one-liners
    singles = [v for v in ordered if not v["reviewNeeded"] and not v["aliases"]]
    lines.append(f"## Singleton venues ({len(singles)})")
    lines.append("")
    lines.append("Venues with only one name variant. Included for completeness.")
    lines.append("")
    for v in singles:
        addr_str = f"{v['address']}, {v['city']}" if v["address"] else v["city"]
        type_str = f" [{', '.join(v['venueType'])}]" if v["venueType"] else ""
        lines.append(
            f"- **{v['name']}** — `{v['slug']}` — {v['eventCount']} events — {addr_str}{type_str}"
        )
    lines.append("")

    REPORT_MD.write_text("\n".join(lines))
    print(f"Report: {REPORT_MD.relative_to(REPO_ROOT)}")


def write_registry(registry: dict, weeks: int) -> None:
    payload = {
        "version": 1,
        "generated": datetime.now(timezone.utc).isoformat(),
        "source": f"seed-venues.py from {weeks} archived weeks",
        "venueCount": len(registry),
        "venues": {slug: v for slug, v in sorted(registry.items())},
    }
    VENUES_JSON.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
    print(f"Wrote registry: {VENUES_JSON.relative_to(REPO_ROOT)}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true", help="Write data/venues.json (else dry-run report only)")
    args = ap.parse_args()

    overrides = load_overrides()
    print(
        f"Overrides: {len(overrides['aliases'])} aliases, "
        f"{len(overrides['merges'])} merges, "
        f"{len(overrides['dropped'])} dropped, "
        f"{len(overrides['venues'])} venue overrides"
    )

    obs, weeks = collect_raw_venues()
    print(f"Loaded {len(obs)} venue observations from {weeks} archived weeks")

    groups, merges = build_groups(obs, overrides)
    print(f"Grouped into {len(groups)} raw clusters")

    registry = finalize(groups, merges, overrides["dropped"], overrides["venues"])
    print(f"Final registry: {len(registry)} unique venues")

    # venueType histogram
    tag_counts = Counter()
    untyped = 0
    for v in registry.values():
        if not v["venueType"]:
            untyped += 1
        for t in v["venueType"]:
            tag_counts[t] += 1
    print(f"venueType: {len(tag_counts)} distinct tags | {untyped} untyped venues")
    for tag, count in tag_counts.most_common():
        print(f"  {count:4d}  {tag}")

    write_report(registry, len(obs), weeks)
    if args.write:
        write_registry(registry, weeks)
    else:
        print("(dry-run: pass --write to save venues.json)")


if __name__ == "__main__":
    main()
