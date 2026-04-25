#!/usr/bin/env python3
"""
publish-website.py  —  Step 3 of the Raleigh Weekend Events pipeline
Validate data/events.json and serve locally or deploy to GitHub Pages / Netlify.

Usage:
  python scripts/publish-website.py                    # local preview (default)
  python scripts/publish-website.py --target github    # git commit + push (Pages)
  python scripts/publish-website.py --target netlify   # netlify deploy --prod
"""
import argparse, http.server, json, os, socketserver, subprocess, sys, webbrowser
from pathlib import Path

PORT = 8765
# Project root is one level up from scripts/
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_EVENTS = PROJECT_ROOT / "data" / "events.json"
DEFAULT_HTML = "index.html"


def validate(events_file: Path):
    if not events_file.exists():
        sys.exit(f"Missing {events_file}. Run update-metadata.py first.")
    data = json.loads(events_file.read_text())
    assert "week" in data, "Missing 'week' key"
    assert "events" in data and isinstance(data["events"], list), "Missing 'events' list"
    assert len(data["events"]) > 0, "events list is empty"
    for ev in data["events"]:
        assert "id" in ev and "name" in ev, f"Event missing id/name: {ev}"
    print(f"✓ {events_file} valid — {len(data['events'])} events for week {data['week']}")
    return data


def serve_local(html_file: str):
    os.chdir(PROJECT_ROOT)
    url = f"http://localhost:{PORT}/{html_file}"
    handler = http.server.SimpleHTTPRequestHandler

    class QuietHandler(handler):
        def log_message(self, *args):
            pass

    with socketserver.TCPServer(("", PORT), QuietHandler) as httpd:
        print(f"Serving at {url}")
        webbrowser.open(url)
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nServer stopped.")


def deploy_github(week: str | None):
    os.chdir(PROJECT_ROOT)
    paths = ["data/events.json", "index.html", "events-app.html"]
    # Include the archive file for this week if it exists
    if week:
        archive = Path("data/archive") / f"events-{week}.json"
        if archive.exists():
            paths.append(str(archive))
    # Include any new raw files
    raw_dir = Path("data/raw")
    if raw_dir.exists():
        paths.append("data/raw")

    msg = f"Weekly events update ({week})" if week else "Weekly events update"
    cmds = [
        ["git", "add"] + paths,
        ["git", "commit", "-m", msg],
        ["git", "push"],
    ]
    for cmd in cmds:
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            # commit step failing on "nothing to commit" is fine — keep going
            stderr = result.stderr.lower()
            if "nothing to commit" in stderr or "nothing to commit" in result.stdout.lower():
                print("(no changes to commit)")
                continue
            sys.exit(f"Command failed: {' '.join(cmd)}\n{result.stderr}")
        print(result.stdout.strip() or " ".join(cmd))
    print("\n✓ Pushed to GitHub. GitHub Pages will update in ~1 min.")


def deploy_netlify():
    os.chdir(PROJECT_ROOT)
    result = subprocess.run(["netlify", "deploy", "--prod", "--dir", "."], text=True)
    if result.returncode != 0:
        sys.exit("Netlify deploy failed. Is the Netlify CLI installed? (npm i -g netlify-cli)")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", default="local", choices=["local", "github", "netlify"])
    parser.add_argument("--events-file", default=str(DEFAULT_EVENTS))
    parser.add_argument("--html-file", default=DEFAULT_HTML)
    args = parser.parse_args()

    events_path = Path(args.events_file)
    if not events_path.is_absolute():
        events_path = PROJECT_ROOT / events_path
    data = validate(events_path)
    week = data.get("week")

    if args.target == "local":
        serve_local(args.html_file)
    elif args.target == "github":
        deploy_github(week)
    elif args.target == "netlify":
        deploy_netlify()


if __name__ == "__main__":
    main()
