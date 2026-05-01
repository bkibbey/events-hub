#!/usr/bin/env python3
"""
update-metadata.py  —  Step 2 of the Raleigh Weekend Events pipeline
Enrich each raw event with AI research → dated archive + current events.json

Outputs:
  data/archive/events-{week}.json   (history, never overwritten)
  data/events.json                  (current snapshot, what the website fetches)

Usage:
  export PERPLEXITY_API_KEY=pplx-...    # preferred (has live web search)
  # or: export OPENAI_API_KEY=sk-...
  python scripts/update-metadata.py                       # auto-pick most recent raw file
  python scripts/update-metadata.py --week 2026-04-24     # pick by weekend date
  python scripts/update-metadata.py --raw-file path.json  # explicit input
  python scripts/update-metadata.py --limit 5             # test on first N events
"""
import argparse, json, os, re, sys, time
from datetime import date
from pathlib import Path

# Project root is one level up from scripts/
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
ARCHIVE_DIR = DATA_DIR / "archive"
CURRENT_FILE = DATA_DIR / "events.json"

ALLOWED_TAGS = [
    "Music", "Food", "Beer", "Wine", "Festival", "Theater", "Comedy",
    "Sports", "Arts & Crafts", "Outdoor", "Family", "Adult", "21+",
    "Film", "Museum", "Market", "Bluegrass", "Jazz", "Dance",
    "LGBTQ+", "Free", "Ticketed", "Charity", "Holiday", "Parade",
]

SYSTEM_PROMPT = """You are a local events researcher for the Raleigh/Durham/Chapel Hill NC area (the Triangle).
Given a raw event listing, research the event and return ONLY valid JSON matching this schema exactly.
Do not include markdown, code fences, or commentary—just the JSON object.

Schema:
{
  "name": "string — official event name",
  "tagline": "string — one punchy sentence",
  "venue": "string — venue name",
  "address": "string — street address or 'TBD'",
  "city": "string — city name",
  "zip": "string — 5-digit ZIP or empty string",
  "days": ["Friday"|"Saturday"|"Sunday"],
  "multiDay": boolean,
  "scheduleNote": "string — e.g. 'Fri 6–10 PM · Sat 12–8 PM' or empty",
  "free": boolean,
  "freeNote": "string — ticket price or 'Free admission' or empty",
  "ticketUrl": "string URL or null",
  "website": "string URL or null",
  "facebook": "string URL or null",
  "instagram": "string URL or null",
  "tags": ["pick 2-6 from the allowed list"],
  "description": "string — 1-2 sentence description, factual"
}

Allowed tags: """ + ", ".join(ALLOWED_TAGS)


def get_client():
    """Return (client, model) — Perplexity preferred, OpenAI fallback."""
    pplx_key = os.environ.get("PERPLEXITY_API_KEY")
    oai_key = os.environ.get("OPENAI_API_KEY")

    if pplx_key:
        try:
            from openai import OpenAI
            return OpenAI(api_key=pplx_key, base_url="https://api.perplexity.ai"), "sonar"
        except ImportError:
            sys.exit("pip install openai")
    elif oai_key:
        try:
            from openai import OpenAI
            return OpenAI(api_key=oai_key), "gpt-4o-mini"
        except ImportError:
            sys.exit("pip install openai")
    else:
        sys.exit("Set PERPLEXITY_API_KEY or OPENAI_API_KEY environment variable.")


def find_raw_file(week: str | None) -> Path:
    """Locate raw-events file. If week given, use that exact file. Otherwise pick latest."""
    if week:
        p = RAW_DIR / f"raw-events-{week}.json"
        if not p.exists():
            sys.exit(f"Not found: {p}. Run ingest-email.py --week {week} first.")
        return p
    candidates = sorted(RAW_DIR.glob("raw-events-*.json"))
    if not candidates:
        sys.exit(f"No raw-events files found in {RAW_DIR}. Run ingest-email.py first.")
    # Pick by lexicographic sort (works because filenames are ISO dates)
    return candidates[-1]


def enrich_event(client, model: str, raw_event: dict, week: str) -> dict:
    # Support both old raw shape and the new richer shape from ingest-email.py
    name = raw_event.get("name") or raw_event.get("raw", "")
    venue = raw_event.get("venue", "")
    city = raw_event.get("city", "")
    day = raw_event.get("day") or "unknown"
    link = raw_event.get("link")
    # source_links was the old shape; link is the new shape
    src_links = raw_event.get("source_links") or ([link] if link else [])

    prompt = f"""Week: {week}
Event name: {name}
Day hint: {day}
Venue (from newsletter): {venue or "unknown"}
City (from newsletter): {city or "unknown"}
Link: {link or "none"}
Source links: {", ".join(src_links) or "none"}

Raw listing line: {raw_event.get("raw", "")}

Research this event for the weekend of {week} and return the JSON schema.
Use the provided link as the 'website' or 'ticketUrl' if appropriate.
Keep the 'name' field close to the provided event name; correct only obvious typos."""

    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        temperature=0.2,
    )
    text = resp.choices[0].message.content.strip()
    text = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    enriched = json.loads(text)
    enriched["id"] = raw_event["id"]
    return enriched


def merge_multiday(events: list[dict]) -> list[dict]:
    """Merge events with the same (case-insensitive) name across days into one
    entry with a `days` list. The first occurrence's other fields win.
    """
    by_name: dict[str, dict] = {}
    order: list[str] = []
    for ev in events:
        key = (ev.get("name") or ev.get("raw", "")).strip().lower()
        if not key:
            # No name to merge on — keep as-is with a unique key
            key = f"__noname__{len(order)}"
        if key in by_name:
            existing = by_name[key]
            existing.setdefault("days", [])
            d = ev.get("day")
            if d and d not in existing["days"]:
                existing["days"].append(d)
        else:
            merged = dict(ev)
            merged["days"] = [ev["day"]] if ev.get("day") else []
            by_name[key] = merged
            order.append(key)
    out = [by_name[k] for k in order]
    # Re-id after merge to keep ids contiguous
    for i, ev in enumerate(out, 1):
        ev["id"] = i
    return out


def main():
    parser = argparse.ArgumentParser(description="Enrich raw events with AI → dated archive + events.json")
    parser.add_argument("--raw-file", default=None, help="Explicit raw-events JSON path")
    parser.add_argument("--week", default=None, help="Weekend date YYYY-MM-DD (picks data/raw/raw-events-{week}.json)")
    parser.add_argument("--limit", type=int, default=None, help="Only process first N events (for testing)")
    parser.add_argument("--no-current", action="store_true", help="Skip updating data/events.json (only write archive)")
    parser.add_argument("--no-merge", action="store_true", help="Do not merge same-named events across days")
    args = parser.parse_args()

    raw_path = Path(args.raw_file) if args.raw_file else find_raw_file(args.week)
    print(f"Reading raw events from: {raw_path}")

    data = json.loads(raw_path.read_text())
    week = data.get("week", date.today().isoformat())
    raw_events = data.get("events", [])

    if not args.no_merge:
        before = len(raw_events)
        raw_events = merge_multiday(raw_events)
        after = len(raw_events)
        if before != after:
            print(f"Merged {before} → {after} events (multi-day deduplication)")

    if args.limit:
        raw_events = raw_events[:args.limit]
        print(f"Limiting to first {args.limit} events")

    client, model = get_client()
    print(f"Using model: {model} | Enriching {len(raw_events)} events for week {week}")

    enriched = []
    for i, ev in enumerate(raw_events, 1):
        print(f"  [{i}/{len(raw_events)}] {ev.get('raw','')[:60]}...")
        try:
            result = enrich_event(client, model, ev, week)
            # If we pre-merged days, prefer the merged days list over what the AI returns
            if ev.get("days") and len(ev["days"]) > 1:
                result["days"] = ev["days"]
                result["multiDay"] = True
            enriched.append(result)
        except Exception as e:
            print(f"    ERROR: {e} — skipping")
        time.sleep(0.5)

    output = {
        "week": week,
        "generated": date.today().isoformat(),
        "source": "Things to do in Raleigh this Weekend! — Thingstodo919",
        "raw_source": str(raw_path.relative_to(PROJECT_ROOT)) if raw_path.is_relative_to(PROJECT_ROOT) else str(raw_path),
        "events": enriched,
    }
    payload = json.dumps(output, indent=2)

    # 1. Always write the dated archive
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    archive_path = ARCHIVE_DIR / f"events-{week}.json"
    archive_path.write_text(payload)
    print(f"\n✓ Archive: {archive_path}  ({len(enriched)} events)")

    # 2. Update the current snapshot the website reads
    if not args.no_current:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        CURRENT_FILE.write_text(payload)
        print(f"✓ Current: {CURRENT_FILE}  (website will load this)")
    else:
        print("(skipped writing data/events.json — use without --no-current to update the live site data)")

    # 3. Regenerate the archive manifest so the front-end week picker can list periods
    write_archive_manifest()


def write_archive_manifest():
    """Build data/archive/index.json listing every dated archive file, newest first.

    The website fetches this manifest to populate the week-picker dropdown.
    GitHub Pages has no directory listing, so this static index is required.
    """
    files = sorted(ARCHIVE_DIR.glob("events-*.json"), reverse=True)
    weeks = []
    for f in files:
        try:
            body = json.loads(f.read_text())
        except Exception as exc:
            print(f"  warn: skipping {f.name} ({exc})")
            continue
        weeks.append({
            "week": f.stem.replace("events-", ""),
            "file": f.name,
            "count": len(body.get("events", [])),
            "generated": body.get("generated"),
        })
    manifest = {
        "current": weeks[0]["week"] if weeks else None,
        "weeks": weeks,
    }
    (ARCHIVE_DIR / "index.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"✓ Manifest: {ARCHIVE_DIR / 'index.json'}  ({len(weeks)} week(s))")


if __name__ == "__main__":
    main()
