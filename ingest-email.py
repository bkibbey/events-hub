#!/usr/bin/env python3
"""
ingest-email.py  —  Step 1 of the Raleigh Weekend Events pipeline
Parse the "Things to do in Raleigh this Weekend!" HTML email into raw-events.json

Usage:
  python scripts/ingest-email.py --email-file path/to/email.html [--week 2026-04-25]
"""
import argparse, json, re, sys
from datetime import date, timedelta
from pathlib import Path

try:
    from bs4 import BeautifulSoup
except ImportError:
    sys.exit("Missing dependency: pip install beautifulsoup4")


def get_weekend_date(ref: date) -> str:
    """Return the upcoming Friday as YYYY-MM-DD."""
    days_until_friday = (4 - ref.weekday()) % 7
    return (ref + timedelta(days=days_until_friday)).isoformat()


def extract_events(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    events = []
    event_id = 1

    # Strategy: look for <li> or <p> items that contain event-like text.
    # Adapt these selectors to the actual newsletter structure.
    candidates = soup.find_all(["li", "p"])

    # Day markers we scan for in surrounding context
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

        # Detect day headings
        low = text.lower()
        for marker, day in day_markers.items():
            if marker in low and len(text) < 50:
                current_day = day
                break

        # Skip very short or header-like lines
        if len(text) < 15 or len(text) > 400:
            continue

        # Skip if it looks like navigation/footer boilerplate
        skip_patterns = ["unsubscribe", "privacy policy", "view in browser",
                         "forward this", "copyright", "©", "all rights reserved"]
        if any(p in low for p in skip_patterns):
            continue

        # Extract any URLs in the element
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
    parser = argparse.ArgumentParser(description="Parse weekend events email → raw-events.json")
    parser.add_argument("--email-file", required=True, help="Path to saved email HTML file")
    parser.add_argument("--week", default=None, help="Week date YYYY-MM-DD (defaults to upcoming Friday)")
    parser.add_argument("--output", default="raw-events.json", help="Output file path")
    args = parser.parse_args()

    email_path = Path(args.email_file)
    if not email_path.exists():
        sys.exit(f"Email file not found: {email_path}")

    week = args.week or get_weekend_date(date.today())
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

    out_path = Path(args.output)
    out_path.write_text(json.dumps(output, indent=2))
    print(f"Wrote {len(events)} raw events to {out_path}")


if __name__ == "__main__":
    main()
