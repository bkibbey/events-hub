#!/usr/bin/env python3
"""Enrich venues in data/venues.json using Perplexity API.

For each venue, ask ONLY for the fields that are currently blank. Fields we
enrich: address (if TBD/blank), linkMain, linkEvents, socials (per platform),
contacts, venueType.

We never overwrite non-empty values. Manual overrides in venues-overrides.json
already flow into venues.json via the seed script, so those are honored too.

Requires env var: PERPLEXITY_API_KEY

Flags:
  --limit N            Process at most N venues (default: all needing enrichment)
  --only-slugs a,b,c   Only process these specific slugs
  --dry-run            Show which venues would be enriched + what fields, no API calls
  --force              Ask for all fields regardless of current values
  --model NAME         Perplexity model (default: sonar)
  --sleep N            Seconds between requests (default: 0.5)
"""
from __future__ import annotations
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

_HERE = Path(__file__).parent.resolve()
REPO_ROOT = _HERE.parent
VENUES_JSON = REPO_ROOT / "data" / "venues.json"

PPLX_URL = "https://api.perplexity.ai/chat/completions"

# Fixed vocab; mirrored from seed-venues.py so we can constrain enricher output.
SOCIAL_PLATFORMS = [
    "facebook", "instagram", "twitter", "threads", "bluesky",
    "tiktok", "youtube", "reddit", "linkedin",
]

# venueType vocabulary. Enricher must pick from this set.
VENUE_TYPE_VOCAB = [
    "theater", "museum", "comedy-club", "music-venue", "stadium", "park",
    "plaza", "library", "church", "brewery", "distillery", "winery", "bar",
    "restaurant", "hotel", "community-center", "school", "farm", "government",
    "market", "event-space", "club", "historic-site", "indoor", "outdoor",
]

PLACEHOLDER_ADDRS = {
    "", "tbd", "tba", "t.b.d.", "n/a", "none", "null", "unknown", "various",
    "various locations", "see website", "see details", "multiple locations",
}


def address_is_blank(v: dict) -> bool:
    a = (v.get("address") or "").strip().lower()
    return a in PLACEHOLDER_ADDRS


def compute_needs(v: dict, force: bool) -> dict:
    """Return dict of {field: True/False} for what we should ask for."""
    if force:
        return {
            "address": True,
            "linkMain": True,
            "linkEvents": True,
            "socials": True,
            "contacts": True,
            "venueType": True,
        }
    socials = v.get("socials") or {}
    return {
        "address": address_is_blank(v),
        "linkMain": not (v.get("linkMain") or ""),
        "linkEvents": not (v.get("linkEvents") or ""),
        # "socials" as a bucket: True if ANY platform is empty
        "socials": any(not (socials.get(p) or "") for p in SOCIAL_PLATFORMS),
        "contacts": not v.get("contacts"),
        "venueType": not v.get("venueType"),
    }


def build_prompt(v: dict, needs: dict) -> tuple[str, dict]:
    """Return (user_prompt, json_schema) tailored to this venue's needs."""
    name = v.get("name") or v["slug"]
    city = v.get("city") or ""
    state = v.get("state") or "NC"
    current_addr = v.get("address") or ""

    lines = [
        f"Find current, accurate public information about this venue:",
        f"  Name: {name}",
        f"  City: {city}, {state}",
    ]
    if not needs.get("address") and current_addr:
        lines.append(f"  Address (already known): {current_addr}")
    lines.append("")
    lines.append("Return ONLY fields listed below. Use empty string \"\" for anything you cannot confidently verify. Do not guess. Do not include fields for other venues with similar names.")
    lines.append("")
    lines.append("Fields requested:")

    if needs.get("address"):
        lines.append("- address: Full street address (e.g. \"123 Vivian St\"). City/state/zip go in separate fields if you know them.")
        lines.append("- addressCity: City name only.")
        lines.append("- addressZip: 5-digit ZIP code only.")
    if needs.get("linkMain"):
        lines.append("- linkMain: URL of the venue's primary/homepage website.")
    if needs.get("linkEvents"):
        lines.append("- linkEvents: URL of the venue's public events/calendar page (if different from linkMain).")
    if needs.get("socials"):
        lines.append(
            "- socials: Object with these keys (all optional; use \"\" for platforms you can't verify): "
            + ", ".join(SOCIAL_PLATFORMS)
            + ". Values must be full URLs to the venue's official account."
        )
    if needs.get("contacts"):
        lines.append(
            "- contacts: Array of contact objects. Each item: "
            "{label: role or person name+title, phone: string or \"\", email: string or \"\", other: URL/handle or \"\"}. "
            "Prefer venue-level contacts (box office, booking, general inquiries) over individual staff unless staff are publicly listed."
        )
    if needs.get("venueType"):
        lines.append(
            "- venueType: Array of 1-3 tags from this fixed vocabulary ONLY: "
            + ", ".join(VENUE_TYPE_VOCAB)
            + ". Include a 'kind' tag (e.g. theater, park, bar) and a 'setting' tag (indoor or outdoor) if applicable."
        )

    # Build a JSON schema that only requires present fields
    props = {}
    if needs.get("address"):
        props["address"] = {"type": "string"}
        props["addressCity"] = {"type": "string"}
        props["addressZip"] = {"type": "string"}
    if needs.get("linkMain"):
        props["linkMain"] = {"type": "string"}
    if needs.get("linkEvents"):
        props["linkEvents"] = {"type": "string"}
    if needs.get("socials"):
        props["socials"] = {
            "type": "object",
            "properties": {p: {"type": "string"} for p in SOCIAL_PLATFORMS},
        }
    if needs.get("contacts"):
        props["contacts"] = {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "label": {"type": "string"},
                    "phone": {"type": "string"},
                    "email": {"type": "string"},
                    "other": {"type": "string"},
                },
                "required": ["label", "phone", "email", "other"],
            },
        }
    if needs.get("venueType"):
        props["venueType"] = {
            "type": "array",
            "items": {"type": "string", "enum": VENUE_TYPE_VOCAB},
        }

    schema = {
        "schema": {
            "type": "object",
            "properties": props,
            "required": list(props.keys()),
            "additionalProperties": False,
        }
    }

    return "\n".join(lines), schema


def call_perplexity(user_prompt: str, schema: dict, model: str, api_key: str,
                   timeout: int = 60) -> dict | None:
    body = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are a data verification assistant. Return ONLY facts you "
                    "can verify from official venue websites or reputable sources. "
                    "Use empty strings for anything unverifiable. Never fabricate."
                ),
            },
            {"role": "user", "content": user_prompt},
        ],
        "response_format": {
            "type": "json_schema",
            "json_schema": schema,
        },
        "temperature": 0.0,
    }
    req = urllib.request.Request(
        PPLX_URL,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        print(f"    HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:300]}", file=sys.stderr)
        return None
    except Exception as e:
        print(f"    ERR: {e}", file=sys.stderr)
        return None

    try:
        content = payload["choices"][0]["message"]["content"]
        return json.loads(content)
    except Exception as e:
        print(f"    parse ERR: {e}  raw: {payload}", file=sys.stderr)
        return None


def clean_address(addr: str, city: str, state: str, zp: str) -> str:
    """Strip trailing city/state/zip and their variants from an address string."""
    if not addr:
        return ""
    s = addr.strip().rstrip(",").strip()
    lower = s.lower()
    # Strip trailing ZIP
    if zp:
        import re as _re
        s = _re.sub(rf",?\s*\b{_re.escape(zp)}(-\d{{4}})?\s*$", "", s).strip().rstrip(",").strip()
    # Strip trailing state
    if state:
        lower = s.lower()
        idx = lower.rfind(f", {state.lower()}")
        if idx > 0 and idx > len(s) - len(state) - 3:
            s = s[:idx].strip()
    # Strip trailing city
    if city:
        lower = s.lower()
        idx = lower.rfind(f", {city.lower()}")
        if idx > 0 and idx > len(s) - len(city) - 3:
            s = s[:idx].strip()
    return s.strip().rstrip(",").strip()


def apply_enrichment(v: dict, data: dict, needs: dict, dry: bool = False) -> list[str]:
    """Merge enrichment result into venue. Return list of changed field names.

    Only writes blank fields (per compute_needs), never overwrites.
    """
    changed = []

    def _set(field: str, new_val):
        # Non-destructive: only apply if current value is blank
        cur = v.get(field)
        blank = (
            cur is None
            or cur == ""
            or (isinstance(cur, list) and len(cur) == 0)
        )
        if blank and new_val not in ("", None, []):
            if not dry:
                v[field] = new_val
            changed.append(field)

    if needs.get("address") and data.get("address"):
        cleaned = clean_address(
            data["address"],
            data.get("addressCity") or v.get("city") or "",
            v.get("state") or "NC",
            data.get("addressZip") or v.get("zip") or "",
        )
        _set("address", cleaned)
    if needs.get("address") and data.get("addressCity"):
        # City is stored separately; only fill if blank
        if not (v.get("city") or "").strip():
            if not dry:
                v["city"] = data["addressCity"].strip()
            changed.append("city")
    if needs.get("address") and data.get("addressZip"):
        if not (v.get("zip") or "").strip():
            if not dry:
                v["zip"] = data["addressZip"].strip()
            changed.append("zip")
    if needs.get("linkMain") and data.get("linkMain"):
        _set("linkMain", data["linkMain"].strip())
    if needs.get("linkEvents") and data.get("linkEvents"):
        _set("linkEvents", data["linkEvents"].strip())

    if needs.get("socials") and isinstance(data.get("socials"), dict):
        cur_socials = v.setdefault("socials", {p: "" for p in SOCIAL_PLATFORMS})
        for p in SOCIAL_PLATFORMS:
            new = (data["socials"].get(p) or "").strip()
            if new and not (cur_socials.get(p) or ""):
                if not dry:
                    cur_socials[p] = new
                changed.append(f"socials.{p}")

    if needs.get("contacts") and isinstance(data.get("contacts"), list):
        # Normalize every contact to the canonical shape
        normalized = []
        for c in data["contacts"]:
            if not isinstance(c, dict):
                continue
            normalized.append({
                "label": (c.get("label") or "").strip(),
                "phone": (c.get("phone") or "").strip(),
                "email": (c.get("email") or "").strip(),
                "other": (c.get("other") or "").strip(),
            })
        # Drop empty contacts (all four fields blank)
        normalized = [c for c in normalized if any(c.values())]
        if normalized and not v.get("contacts"):
            if not dry:
                v["contacts"] = normalized
            changed.append("contacts")

    if needs.get("venueType") and isinstance(data.get("venueType"), list):
        tags = sorted({
            t.strip().lower() for t in data["venueType"]
            if isinstance(t, str) and t.strip().lower() in VENUE_TYPE_VOCAB
        })
        if tags and not v.get("venueType"):
            if not dry:
                v["venueType"] = tags
            changed.append("venueType")

    return changed


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--only-slugs", default=None)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--model", default="sonar")
    ap.add_argument("--sleep", type=float, default=0.5)
    args = ap.parse_args()

    api_key = os.environ.get("PERPLEXITY_API_KEY")
    if not api_key and not args.dry_run:
        print("ERROR: PERPLEXITY_API_KEY env var not set", file=sys.stderr)
        return 2

    only = set(s.strip() for s in args.only_slugs.split(",")) if args.only_slugs else None
    if only is not None:
        print(f"--only-slugs filter active with {len(only)} slug(s)")

    registry = json.loads(VENUES_JSON.read_text())
    venues = registry["venues"]

    # Build target list
    targets: list[tuple[str, dict, dict]] = []
    for slug, v in venues.items():
        if only and slug not in only:
            continue
        needs = compute_needs(v, args.force)
        if not any(needs.values()):
            continue
        targets.append((slug, v, needs))

    if args.limit:
        targets = targets[: args.limit]

    print(f"Model: {args.model}  (sleep {args.sleep}s)")
    print(f"Venues needing enrichment: {len(targets)} (of {len(venues)} total)")
    if not targets:
        return 0

    if args.dry_run:
        for slug, v, needs in targets[:20]:
            wants = [k for k, ok in needs.items() if ok]
            print(f"  DRY {slug}: {v['name']} -> ask for {wants}")
        if len(targets) > 20:
            print(f"  ... and {len(targets)-20} more")
        return 0

    stats = {"ok": 0, "fail": 0, "unchanged": 0, "fields_updated": 0}
    for i, (slug, v, needs) in enumerate(targets, 1):
        wants = [k for k, ok in needs.items() if ok]
        print(f"[{i}/{len(targets)}] {slug}: needs {wants}")
        prompt, schema = build_prompt(v, needs)
        result = call_perplexity(prompt, schema, args.model, api_key)
        if result is None:
            stats["fail"] += 1
        else:
            changed = apply_enrichment(v, result, needs, dry=False)
            if changed:
                stats["ok"] += 1
                stats["fields_updated"] += len(changed)
                print(f"    updated: {changed}")
            else:
                stats["unchanged"] += 1
                print(f"    no changes (API returned blanks)")

        # Checkpoint save every 5 venues (was 25 — better resilience for small batches)
        if i % 5 == 0:
            registry["enrichedAt"] = datetime.now(timezone.utc).isoformat()
            VENUES_JSON.write_text(json.dumps(registry, indent=2) + "\n")
            print(f"    (checkpoint saved at {i}/{len(targets)})")

        if i < len(targets):
            time.sleep(args.sleep)

    # Final save
    registry["enrichedAt"] = datetime.now(timezone.utc).isoformat()
    VENUES_JSON.write_text(json.dumps(registry, indent=2) + "\n")

    print()
    print(f"Done. OK: {stats['ok']} | Unchanged: {stats['unchanged']} | Failed: {stats['fail']}")
    print(f"Total fields updated: {stats['fields_updated']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
