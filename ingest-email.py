#!/usr/bin/env python3
"""
ingest-email.py  —  Step 1 of the Raleigh Weekend Events pipeline
Parse the "Things to do in Raleigh this Weekend!" HTML email into a dated
raw-events JSON file.

Default output: data/raw/raw-events-{weekend-friday}.json

Usage:
  python ingest-email.py --email-file path/to/email.html
  python ingest-email.py --email-file email.html --week 2026-04-24
  python ingest-email.py --email-file email.html --output some/path.json
"""
import argparse, json, sys
from datetime import date, timedelta
from pathlib import Path

try:
    from bs4 import BeautifulSoup
except ImportError:
    sys.exit("Missing dependency: pip install beautifulsoup4")


PROJECT_ROOT = Path(__file__).parent.resolve()
DEFAULT_RAW_DIR = PROJECT_ROOT / "data" / "raw"


def get_weekend_date(ref: date) -> str:
    """Return the upcoming (or current) Friday as YYYY-MM-DD.

    If ref is a Friday, returns ref. Otherwise returns the next Friday.
    """
    days_until_friday = (4 - ref.weekday()) % 7
    return (ref + timedelta(days=days_until_friday)).isoformat()


def default_output_path(week: str) -> Path:
    return DEFAULT_RAW_DIR / f"raw-events-{week}.json"


def extract_events(html: str) -> list[dict]:
    """Heuristic extractor — TODO: tune to actual newsletter selectors."""
    soup = BeautifulSoup(html, "html.parser")
    events = []
    event_id = 1

    candidates = soup.find_all(["li", "p"])

    day_markers = {
        "friday": "Friday",
        "saturday": "Saturday",
        "sunday": "Sunday",
    }

    current_day = None
    for el in candidates:
        text = el.get_text(separator=" ", strip=True)
        if not text or len(text) < 8:
            continue

        low = text.lower()
        for marker, day in day_markers.items():
            if marker in low and len(text) < 50:
                current_day = day
                break

        if len(text) < 15 or len(text) > 400:
            continue

        skip_patterns = ["unsubscribe", "privacy policy", "view in browser",
                         "forward this", "copyright", "©", "all rights reserved"]
        if any(p in low for p in skip_patterns):
            continue

        links = [a.get("href", "") for a in el.find_all("a", href=True)]
        links = [l for l in links if l.startswith("http")]

        events.append({
            "id": event_id,
            "raw": text,
            "day": current_day,
            "source_links": links,
        })
        event_id += 1

    return events


def main():
    parser = argparse.ArgumentParser(description="Parse weekend events email → dated raw-events JSON")
    parser.add_argument("--email-file", required=True, help="Path to saved email HTML file")
    parser.add_argument("--week", default=None, help="Weekend date YYYY-MM-DD (defaults to upcoming Friday)")
    parser.add_argument("--output", default=None,
                        help="Override output path (default: data/raw/raw-events-{week}.json)")
    args = parser.parse_args()

    email_path = Path(args.email_file)
    if not email_path.exists():
        sys.exit(f"Email file not found: {email_path}")

    week = args.week or get_weekend_date(date.today())
    out_path = Path(args.output) if args.output else default_output_path(week)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    html = email_path.read_text(encoding="utf-8", errors="ignore")
    events = extract_events(html)

    if not events:
        print("WARNING: No events found. Check the HTML structure of your email.")

    output = {
        "week": week,
        "ingested": date.today().isoformat(),
        "source_file": str(email_path),
        "event_count": len(events),
        "events": events,
    }

    out_path.write_text(json.dumps(output, indent=2))
    print(f"Wrote {len(events)} raw events to {out_path}")
    print(f"Next: python update-metadata.py --week {week}")


if __name__ == "__main__":
    main()
