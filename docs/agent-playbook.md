# Agent Playbook

Operating manual for AI agents (Claude, GPT, Cursor, Windsurf, or any future
model) working on this codebase. If you are one such agent, read this
document once at the start of any session.

## Ground rules

1. **Prefer connectors over browsers.**
   - Gmail URLs → use the Gmail connector (Perplexity: `gcal` /
     `gmail`; Codex/Claude Code: whatever `list_external_tools` returns).
   - GitHub URLs → use `github_mcp_direct` for API calls, or shell git
     with `api_credentials=["github"]` for `push`/`fetch`.
   - Only use `browser_task` if no connector exists.

2. **Never commit the Perplexity API key.**
   - It lives in environment variables only.
   - It has appeared inline in this conversation for continuity; do NOT
     paste it into any file or commit.
   - If you need it durably, use the user's saved custom credential.

3. **Hard timeouts are load-bearing.** Do not increase them casually.
   - Event enrichment: 15 seconds via
     `client.chat.completions.create(..., timeout=15.0)` with
     `max_retries=0` on the client.
   - Venue enrichment: 45 seconds via `urlopen(req, timeout=45)`.
   - The reason: one slow row will not block the batch. Retries turn a 15s
     hang into a 60s hang; disabled deliberately.

4. **Blanks-only enrichment.** Never overwrite a non-empty field. This is
   enforced by `compute_needs` and `apply_enrichment` in
   `enrich-venues.py`, and by the venue-matching logic in
   `match-venues.py`.

5. **`seed-venues.py` is retired.** It requires
   `--write --i-know-what-im-doing` and would rebuild the registry from
   scratch. Do not run it as part of weekly work. The stub-creation job
   is handled by `match_or_create` inside `update-metadata.py`.

6. **Idempotency.** Every script can be re-run safely with the same
   arguments. If you're not sure whether a step completed, just re-run —
   it will skip already-done work.

## The weekly ritual, in one sentence

```
ingest-email → update-metadata → geocode-venues → enrich-venues (only-slugs) → geocode-venues → git push → trigger Pages build
```

See [weekly-workflow.md](weekly-workflow.md) for the exact commands.

## Common tasks & their gotchas

### Fetching the newsletter

- **Gmail body truncation** happens at ~5011 bytes. If the FRIDAY section
  is fine but SUNDAY is missing or cut off mid-word, the body is
  truncated. Fall back to the Mailchimp archive.
- **View-in-browser URL** is the first hyperlink in every issue. Follow
  its redirect with `curl -sIL -A "Mozilla/5.0" '<url>'` to extract the
  `mc_cid` query parameter from the `Location:` header. That mc_cid is
  what `ingest-email.py --archive-id` wants.
- **Mailchimp 503**: rare but happens. Fall back to `--text-file` with
  the plain-text body from Gmail.

### Running `enrich-venues.py`

- **Always use `--only-slugs`.** Without it the script runs against every
  venue with any blank field. That's hundreds of venues and dozens of
  dollars.
- **Shell variable gotcha**: `SLUGS='...' python3 script "$SLUGS"`
  expands `$SLUGS` in the parent shell (empty). Use one of:
  ```bash
  # Preferred: pass inline
  python3 scripts/enrich-venues.py --only-slugs "slug1,slug2,slug3"

  # Or: export first
  export SLUGS='slug1,slug2,slug3'
  python3 scripts/enrich-venues.py --only-slugs "$SLUGS"

  # NEVER this — it silently runs against everything:
  SLUGS='...' python3 scripts/enrich-venues.py --only-slugs "$SLUGS"
  ```

### Committing

- `git status` before committing. Half-built features in `index.html`
  have been shipped by accident more than once. Stash unrelated changes:
  ```bash
  git stash push index.html -m "wip"
  git add -A && git commit -m "..."
  ```
- Use the `github` credential preset for `git push`:
  ```bash
  bash(command="cd /home/user/workspace/events-hub && git push origin main",
       api_credentials=["github"])
  ```
- The Pages build must be manually triggered when using the API:
  ```bash
  gh api --method POST repos/bkibbey/events-hub/pages/builds
  ```
  Wait 30–90 seconds, then verify:
  ```bash
  curl -s "https://weekend.brewideas.net/data/events.json?t=$(date +%s)" \
    | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['week'], len(d['events']))"
  ```

### Adding a new field to `events.json`

1. Add it to `SYSTEM_PROMPT` in `update-metadata.py` (the schema block).
2. Add a semantics row to `docs/data-model.md`.
3. Read it in `index.html` where cards are rendered. Assume it can be
   missing on old archive files — always default it.
4. Test end-to-end with `--limit 5 --no-current`.

### Adding a new field to `venues.json`

1. Update `create_venue_from_event` in `match-venues.py` to seed the
   field as an empty default.
2. Update `compute_needs` in `enrich-venues.py` to mark it as needed
   when blank.
3. Update `build_prompt` in `enrich-venues.py` to request it.
4. Update the JSON schema in `build_prompt`.
5. Update `apply_enrichment` to copy it in.
6. Update the schema doc in `docs/data-model.md`.
7. Run `enrich-venues.py --force --limit 3` to sanity-check on a few
   venues before running against real gaps.

### Fixing a duplicate venue

Duplicates happen when the newsletter uses a slightly different spelling
or city string. To merge:

1. In `venues.json`, pick the surviving slug (usually the more-enriched
   one).
2. Add the losing venue's `name` to the survivor's `aliases` array.
3. Copy any unique data (a `linkEvents`, a social, a contact) from the
   loser to the survivor.
4. Delete the losing key from `venues.json`.
5. Re-map events: `python scripts/match-venues.py --all`. This walks
   every archived events file and rewrites `venueId` values.
6. Commit: matcher changes + venues.json + affected archives.

### Re-enriching a past week

```bash
python scripts/update-metadata.py --week 2026-04-24
```

This reads `data/raw/raw-events-2026-04-24.json`, re-enriches, overwrites
`data/archive/events-2026-04-24.json`, and (if you don't pass
`--no-current`) also overwrites `data/events.json`. Almost always pair
this with `--no-current` unless you truly want the site to jump backwards.

## What NOT to do

- ❌ Increase timeouts to "give the model more time." The 15/45s caps
  were tuned specifically to prevent runaway costs and hung batches. If
  a call really needs more time, it needs a smaller prompt.
- ❌ Add retries to enrichment. The whole point of the design is that
  one slow row moves on. Retries reintroduce the exponential-hang
  failure mode we deliberately removed.
- ❌ Run `seed-venues.py`. It has a safety flag for a reason.
- ❌ Use `browser_task` for Gmail or GitHub. Connectors are 10× faster
  and more reliable.
- ❌ Commit `index.html` changes as part of a data-update commit unless
  the UI change is intentional and tested.
- ❌ Overwrite a non-empty field in `venues.json`. Blanks-only, always.
- ❌ Use `--force` on `enrich-venues.py` in production without a very
  specific reason. It bypasses the blanks-only guard.
- ❌ Add new fields to the top-level `state` object in `index.html`
  without also wiring them into `syncUrl()` and `applyUrlParamsToState()`
  if they should be shareable.

## Delegation guidance for parent agents

If you're an orchestrator agent spawning subagents to work on this repo:

- **Preload skills**: pass any loaded skills to the subagent via
  `preload_skills=[...]` so it doesn't re-load them.
- **File-based handoff**: for multi-step work, have the subagent write
  intermediate results to files under `/tmp/` or the repo, and pass file
  paths in the next objective.
- **Never delegate the API key inline**. Load it into the shell in the
  parent's setup, and pass the *presence* of `PERPLEXITY_API_KEY` in the
  subagent's environment.

## When you're unsure

- Read the target script's docstring first. Every script has one.
- Read `docs/data-model.md` for the schema you're touching.
- Read `docs/decision-log.md` for the reasoning behind
  counter-intuitive choices.
- If you're about to overwrite data, stop and ask the human.

## Environment quick-reference

```bash
# Repo root
/home/user/workspace/events-hub

# Python
python3.11+  (uses Path.is_relative_to)
pip install beautifulsoup4 openai rapidfuzz

# Env var
export PERPLEXITY_API_KEY='pplx-...'   # never in a commit

# Local dev server (if not using publish-website.py)
# Perplexity Computer users can use: pplx-tool start_server
```
