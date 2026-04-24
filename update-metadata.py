#!/usr/bin/env python3
"""
update-metadata.py  —  Step 2 of the Raleigh Weekend Events pipeline
Enrich each raw event with AI research → events.json

Usage:
  export PERPLEXITY_API_KEY=pplx-...    # preferred
  # or: export OPENAI_API_KEY=sk-...
  python scripts/update-metadata.py [--raw-file raw-events.json] [--limit 5]

The script calls the AI API once per event and asks it to return structured JSON.
Results are written to events.json in the project root.
"""
import argparse, json, os, sys, time
from datetime import date
from pathlib import Path

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
    """Return (client, model) tuple — prefers Perplexity, falls back to OpenAI."""
    pplx_key = os.environ.get("PERPLEXITY_API_KEY")
    oai_key = os.environ.get("OPENAI_API_KEY")

    if pplx_key:
        try:
            from openai import OpenAI
            client = OpenAI(api_key=pplx_key, base_url="https://api.perplexity.ai")
            return client, "sonar"
        except ImportError:
            sys.exit("pip install openai")
    elif oai_key:
        try:
            from openai import OpenAI
            client = OpenAI(api_key=oai_key)
            return client, "gpt-4o-mini"
        except ImportError:
            sys.exit("pip install openai")
    else:
        sys.exit("Set PERPLEXITY_API_KEY or OPENAI_API_KEY environment variable.")


def enrich_event(client, model: str, raw_event: dict, week: str) -> dict:
    prompt = f"""Week: {week}
Day hint: {raw_event.get("day", "unknown")}
Source links: {", ".join(raw_event.get("source_links", [])) or "none"}
Raw listing:
{raw_event["raw"]}

Research this event and return the JSON schema."""

    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        temperature=0.2,
    )
    text = resp.choices[0].message.content.strip()
    # Strip markdown fences if model adds them
    text = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    enriched = json.loads(text)
    enriched["id"] = raw_event["id"]
    return enriched


def main():
    parser = argparse.ArgumentParser(description="Enrich raw events with AI → events.json")
    parser.add_argument("--raw-file", default="raw-events.json")
    parser.add_argument("--output", default="events.json")
    parser.add_argument("--limit", type=int, default=None, help="Only process first N events (for testing)")
    args = parser.parse_args()

    raw_path = Path(args.raw_file)
    if not raw_path.exists():
        sys.exit(f"Not found: {raw_path}. Run ingest-email.py first.")

    data = json.loads(raw_path.read_text())
    week = data.get("week", date.today().isoformat())
    raw_events = data.get("events", [])

    if args.limit:
        raw_events = raw_events[:args.limit]

    client, model = get_client()
    print(f"Using model: {model} | Enriching {len(raw_events)} events for week {week}")

    enriched = []
    for i, ev in enumerate(raw_events, 1):
        print(f"  [{i}/{len(raw_events)}] {ev.get('raw','')[:60]}...")
        try:
            result = enrich_event(client, model, ev, week)
            enriched.append(result)
        except Exception as e:
            print(f"    ERROR: {e} — skipping")
        time.sleep(0.5)  # be polite to the API

    output = {
        "week": week,
        "generated": date.today().isoformat(),
        "source": "Things to do in Raleigh this Weekend! — Thingstodo919",
        "events": enriched,
    }
    Path(args.output).write_text(json.dumps(output, indent=2))
    print(f"\nWrote {len(enriched)} enriched events to {args.output}")


if __name__ == "__main__":
    main()
