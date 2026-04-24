#!/usr/bin/env python3
"""
publish-website.py  —  Step 3 of the Raleigh Weekend Events pipeline
Validate events.json and serve locally or deploy to GitHub Pages / Netlify.

Usage:
  python scripts/publish-website.py                    # local preview (default)
  python scripts/publish-website.py --target github    # git commit + push
  python scripts/publish-website.py --target netlify   # netlify deploy --prod
"""
import argparse, http.server, json, os, socketserver, subprocess, sys, webbrowser
from pathlib import Path

PORT = 8765


def validate(events_file: str):
    path = Path(events_file)
    if not path.exists():
        sys.exit(f"Missing {events_file}. Run update-metadata.py first.")
    data = json.loads(path.read_text())
    assert "week" in data, "Missing 'week' key"
    assert "events" in data and isinstance(data["events"], list), "Missing 'events' list"
    assert len(data["events"]) > 0, "events list is empty"
    for ev in data["events"]:
        assert "id" in ev and "name" in ev, f"Event missing id/name: {ev}"
    print(f"✓ {events_file} valid — {len(data['events'])} events for week {data['week']}")


def serve_local(project_dir: str, html_file: str):
    os.chdir(project_dir)
    url = f"http://localhost:{PORT}/{html_file}"
    handler = http.server.SimpleHTTPRequestHandler

    class QuietHandler(handler):
        def log_message(self, *args):
            pass  # suppress request logs

    with socketserver.TCPServer(("", PORT), QuietHandler) as httpd:
        print(f"Serving at {url}")
        webbrowser.open(url)
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nServer stopped.")


def deploy_github(project_dir: str):
    os.chdir(project_dir)
    cmds = [
        ["git", "add", "events.json", "events-app.html"],
        ["git", "commit", "-m", f"Weekly events update"],
        ["git", "push"],
    ]
    for cmd in cmds:
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            sys.exit(f"Command failed: {' '.join(cmd)}\n{result.stderr}")
        print(result.stdout.strip() or " ".join(cmd))
    print("\n✓ Pushed to GitHub. GitHub Pages will update in ~1 min.")


def deploy_netlify(project_dir: str):
    os.chdir(project_dir)
    result = subprocess.run(["netlify", "deploy", "--prod", "--dir", "."], text=True)
    if result.returncode != 0:
        sys.exit("Netlify deploy failed. Is the Netlify CLI installed? (npm i -g netlify-cli)")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", default="local", choices=["local", "github", "netlify"])
    parser.add_argument("--events-file", default="events.json")
    parser.add_argument("--html-file", default="events-app.html")
    args = parser.parse_args()

    project_dir = Path(__file__).parent.parent.resolve()
    validate(str(project_dir / args.events_file))

    if args.target == "local":
        serve_local(str(project_dir), args.html_file)
    elif args.target == "github":
        deploy_github(str(project_dir))
    elif args.target == "netlify":
        deploy_netlify(str(project_dir))


if __name__ == "__main__":
    main()
