#!/usr/bin/env python3
"""
ingest-email.py  —  Step 1 of the Raleigh Weekend Events pipeline

Fetch and parse the "Things to do in Raleigh this Weekend!" newsletter
into a dated raw-events JSON file.

Three input modes (in order of preference):

  1. --url          Paste the Mailchimp "View in browser" URL or the campaign
                    archive URL. Script downloads and parses the hosted version.
                    This gets you the FULL email (Gmail truncates).

  2. --archive-id   If you only have the mc_cid (the campaign id), pass it.
                    Script constructs the archive URL automatically.

  3. --email-file   Local saved .html or .eml file. Used as a fallback.
                    The script will try to find a tracking URL in it and
                    auto-fetch the full archive; if that fails, it parses
                    the local file directly.

Output (default): data/raw/raw-events-{week}.json
The script also archives the source HTML to data/email-raw/{week}.html.

Usage:
  python ingest-email.py --url 'https://us15.campaign-archive.com/?u=...&id=...'
  python ingest-email.py --archive-id 291544bb7c
  python ingest-email.py --email-file email.html
"""
import argparse, json, re, sys
from datetime import date, timedelta
from pathlib import Path

try:
    from bs4 import BeautifulSoup
except ImportError:
    sys.exit("Missing dependency: pip install beautifulsoup4")

try:
    import urllib.request
except ImportError:
    sys.exit("Standard library urllib not available")


PROJECT_ROOT = Path(__file__).parent.resolve()
DEFAULT_RAW_DIR = PROJECT_ROOT / "data" / "raw"
DEFAULT_EMAIL_RAW_DIR = PROJECT_ROOT / "data" / "email-raw"

# Mailchimp list/account id for thingstodoinraleigh.com (stable across weeks)
THINGSTODO_LIST_U = "ddef6da2cf1e7abe0e37514bc"

DAY_RE = re.compile(r"^\s*(FRIDAY|SATURDAY|SUNDAY)\s*$")
USER_AGENT = "Mozilla/5.0 (compatible; events-hub-ingest/1.0)"


# ---------- Date helpers ----------

def get_weekend_date(ref: date) -> str:
    """Return the upcoming (or current) Friday as YYYY-MM-DD."""
    days_until_friday = (4 - ref.weekday()) % 7
    return (ref + timedelta(days=days_until_friday)).isoformat()


def default_output_path(week: str) -> Path:
    return DEFAULT_RAW_DIR / f"raw-events-{week}.json"


def default_email_html_path(week: str) -> Path:
    return DEFAULT_EMAIL_RAW_DIR / f"newsletter-{week}.html"


# ---------- Fetching ----------

def fetch_url(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as resp:
        # Mailchimp archive pages are utf-8
        return resp.read().decode("utf-8", errors="replace")


def construct_archive_url(archive_id: str, list_u: str = THINGSTODO_LIST_U) -> str:
    return f"https://us15.campaign-archive.com/?u={list_u}&id={archive_id}"


def find_archive_id_in_text(text: str) -> str | None:
    """Look for mc_cid=... or id=... in any URL we can find in the body."""
    # 'mc_cid=XXXX' is the canonical query param
    m = re.search(r"mc_cid=([0-9a-f]+)", text)
    if m:
        return m.group(1)
    # Some tracking URLs use id=XXXX (must be a hex string of reasonable length)
    for m in re.finditer(r"[?&]id=([0-9a-f]{8,})", text):
        return m.group(1)
    return None


def resolve_html(args) -> tuple[str, str]:
    """Return (html_content, source_label).

    Tries --url, --archive-id, --email-file in that order.
    For --email-file, attempts to upgrade to the full archive URL by extracting
    the mc_cid from any tracking link in the file.
    """
    if args.url:
        url = args.url
        # If user pasted a Mailchimp tracking URL, follow redirects automatically.
        print(f"Fetching: {url}")
        return fetch_url(url), url

    if args.archive_id:
        url = construct_archive_url(args.archive_id)
        print(f"Fetching: {url}")
        return fetch_url(url), url

    if args.email_file:
        local = Path(args.email_file)
        if not local.exists():
            sys.exit(f"Email file not found: {local}")
        local_html = local.read_text(encoding="utf-8", errors="ignore")
        # Try to upgrade to the full archive
        cid = find_archive_id_in_text(local_html)
        if cid:
            url = construct_archive_url(cid)
            print(f"Local file references campaign id {cid} — fetching full archive: {url}")
            try:
                return fetch_url(url), url
            except Exception as e:
                print(f"  Archive fetch failed ({e}); falling back to local file content")
        return local_html, str(local)

    sys.exit("Provide --url, --archive-id, or --email-file. See --help.")


# ---------- Parsing ----------

def find_day_cells(soup):
    """Find the <td class='mcnTextContent'> cells whose ENTIRE text is a day name
    AND which are inside an mcnBoxedTextContentContainer (the styled day-heading
    block in the Thingstodo919 template).

    Returns list of (day_name, td_element) in document order.
    """
    out = []
    for td in soup.find_all("td", class_="mcnTextContent"):
        text = td.get_text(strip=True)
        m = DAY_RE.match(text)
        if not m:
            continue
        # Confirm boxed-text ancestor
        ancestor = td.parent
        is_boxed = False
        while ancestor:
            cls = ancestor.get("class") or []
            if "mcnBoxedTextContentContainer" in cls or "mcnBoxedTextBlockInner" in cls:
                is_boxed = True
                break
            ancestor = ancestor.parent
        if is_boxed:
            out.append((m.group(1).capitalize(), td))
    return out


def is_event_li(li, day_cells_set) -> bool:
    """An event <li> is one that:
      - has an <a href> linking somewhere external
      - sits inside a <td class='mcnTextContent'> that is NOT a day-heading cell
      - is NOT inside a Mailchimp navigation block (Subscribe, Past Issues, etc.)
    """
    a = li.find("a", href=True)
    if not a or not a.get("href", "").startswith("http"):
        return False
    # Walk up to confirm we're inside an mcnTextContent that isn't a day cell,
    # and not inside obvious nav (mcnFollowContent, mcnDividerBlock, etc.)
    p = li.parent
    in_text_content = False
    while p:
        cls = p.get("class") or []
        if "mcnTextContent" in cls and p not in day_cells_set:
            in_text_content = True
        # Reject Mailchimp built-in social/follow blocks
        for blocklist in ("mcnFollowContent", "mcnFollowBlock", "templateColumns"):
            pass
        p = p.parent
    return in_text_content


def parse_event_li(li, current_day):
    """Extract structured fields from an event <li>.

    Pattern:  <li><a href="...">Event Name</a> , Venue, City</li>

    The trailing ', Venue, City' is plain text after the <a>. There can be
    extra whitespace and trailing nbsp. Return None if it doesn't look like an event.
    """
    a = li.find("a", href=True)
    if not a:
        return None

    name = a.get_text(strip=True)
    if not name or len(name) < 2:
        return None
    href = a.get("href", "")

    # Get the full <li> text and strip the name from the front
    full_text = li.get_text(separator=" ", strip=True)
    tail = full_text
    # Remove the name from the start (case-insensitive, allow trailing whitespace)
    if tail.lower().startswith(name.lower()):
        tail = tail[len(name):]
    # Strip leading commas/whitespace
    tail = tail.lstrip(" ,\u00a0\t").rstrip()

    # tail should now be "Venue, City" (sometimes "Venue, Sub, City")
    # Split on commas; last segment is the city.
    parts = [p.strip() for p in tail.split(",") if p.strip()]
    venue, city = "", ""
    if len(parts) == 0:
        # Some entries have just "Event Name" with no venue/city — keep them
        venue = ""
        city = ""
    elif len(parts) == 1:
        # "Venue" only
        venue = parts[0]
    else:
        # Last is city, rest joined is venue
        city = parts[-1]
        venue = ", ".join(parts[:-1])

    return {
        "name": name,
        "link": href,
        "venue": venue,
        "city": city,
        "day": current_day,
        "raw": full_text,
    }


def extract_events(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    day_cells = find_day_cells(soup)
    if not day_cells:
        print("WARNING: No day-heading cells (FRIDAY/SATURDAY/SUNDAY) found.")
        return []

    day_cells_set = set(td for _, td in day_cells)

    # Map of day-cell -> the day name that follows it
    # We collect events per day by scanning forward in document order from each day cell
    # until we hit the next day cell.
    events = []
    seen = 0
    for i, (day, cell) in enumerate(day_cells):
        next_cells = set(c for _, c in day_cells[i + 1:])
        for nxt in cell.find_all_next():
            if nxt in next_cells:
                break
            if nxt.name != "li":
                continue
            if not is_event_li(nxt, day_cells_set):
                continue
            parsed = parse_event_li(nxt, day)
            if parsed:
                seen += 1
                parsed["id"] = seen
                events.append(parsed)

    return events


# ---------- Main ----------

def main():
    parser = argparse.ArgumentParser(
        description="Fetch + parse Thingstodo919 newsletter → dated raw-events JSON",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    src = parser.add_mutually_exclusive_group(required=False)
    src.add_argument("--url", help="Mailchimp archive or 'View in browser' URL")
    src.add_argument("--archive-id", help="Mailchimp campaign id (mc_cid value)")
    src.add_argument("--email-file", help="Local saved email HTML/EML file")

    parser.add_argument("--week", default=None,
                        help="Weekend date YYYY-MM-DD (defaults to upcoming Friday)")
    parser.add_argument("--output", default=None,
                        help="Override output JSON path (default: data/raw/raw-events-{week}.json)")
    parser.add_argument("--save-html", default=None,
                        help="Override HTML archive path (default: data/email-raw/newsletter-{week}.html)")
    parser.add_argument("--no-save-html", action="store_true",
                        help="Skip saving the source HTML to data/email-raw/")
    args = parser.parse_args()

    if not (args.url or args.archive_id or args.email_file):
        parser.print_help()
        sys.exit("\nError: provide --url, --archive-id, or --email-file.")

    week = args.week or get_weekend_date(date.today())
    out_path = Path(args.output) if args.output else default_output_path(week)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    html, source_label = resolve_html(args)
    print(f"Source HTML: {len(html)} chars")

    # Archive the source HTML
    if not args.no_save_html:
        html_path = Path(args.save_html) if args.save_html else default_email_html_path(week)
        html_path.parent.mkdir(parents=True, exist_ok=True)
        html_path.write_text(html, encoding="utf-8")
        print(f"Saved source HTML: {html_path}")

    events = extract_events(html)
    if not events:
        print("WARNING: 0 events extracted. The newsletter template may have changed.")
    else:
        per_day = {}
        for ev in events:
            per_day[ev["day"]] = per_day.get(ev["day"], 0) + 1
        breakdown = ", ".join(f"{d}: {c}" for d, c in per_day.items())
        print(f"Extracted {len(events)} events ({breakdown})")

    output = {
        "week": week,
        "ingested": date.today().isoformat(),
        "source": source_label,
        "event_count": len(events),
        "events": events,
    }
    out_path.write_text(json.dumps(output, indent=2))
    print(f"Wrote: {out_path}")
    print(f"Next: python update-metadata.py --week {week}")


if __name__ == "__main__":
    main()
