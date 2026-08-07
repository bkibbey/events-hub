# Evolution

The story of how this project got built, in roughly chronological order.
Purpose: preserve the reasoning behind decisions that are no longer visible
in the code, and record the user's voice and prompt patterns.

## Genesis (April 2026)

**User intent**: "The Things To Do 919 newsletter is great but hard to
scan on my phone. Turn it into a filterable web app."

**Approach**: Parse the weekly Mailchimp email, run each event through an
LLM to add tags + a short description, ship a single-page site to GitHub
Pages. No backend. No auth. No database.

**First commit** (Apr 24, 2026): 74 events, minimal `index.html`, one
`update-metadata.py` script combining ingest + enrichment.

## Early features (April–May 2026)

Rapid iteration. The user often said things like *"make it feel more like
a real site"* and *"make the sharing feel intentional."*

Highlights:
- Split ingest from enrichment so prompts could be iterated cheaply
  (`--limit 5 --no-current`).
- Multi-day dedup: same-named events on Fri + Sat merge before enrichment.
  Cut LLM calls per week by 10–20%.
- Filter chips, dark mode, holiday confetti, iframe embed docs.
- Shuffle sort (re-randomize on every load).
- Shareable links (`?selected=1,3,7&week=YYYY-MM-DD`).

## The venue registry (July 2026)

**Prompt pattern** (user, verbatim in spirit): *"Every week I see the same
venues over and over. Can we build a proper registry?"*

Started with `seed-venues.py`: rebuild venue records from every archive
weekend. Group by canonical address key first (ground truth), then fuzzy-
match orphans within same city.

Produced `data/venues.json` with ~407 initial venues. Added a
`docs/venues-seed-report.md` audit.

Follow-ups:
- **Geocoding** (`c290139`, July 2026): pluggable providers, Census as
  default (free, no key, bulk-friendly), Nominatim as fallback.
- **Enrichment** (`d9e35df`): first pass over all 407 venues to fill
  `linkMain`, socials, contacts, `venueType`. This was the batch run that
  taught us the hard-timeout lesson.
- **Matching + map** (`f9eb93f`): `match-venues.py` library, Leaflet map
  view, `venueId` on every event, seed-preserve logic that keeps
  enrichment intact if seed is re-run.

## The hard-timeout epiphany (July 24, 2026)

**What happened**: a full weekly enrichment run hung. Individual API
calls stalled for 90+ seconds while the openai SDK dutifully retried.
The user asked *"did you get stuck and burn all my credits?"* and it
turned out yes, several dollars of tokens were spent on hung retries.

**The fix** (commit `98285f2`, July 31, 2026):

- `client.max_retries = 0` on the OpenAI client
- `timeout=15.0` on every `client.chat.completions.create` call
- `urllib.urlopen(req, timeout=45)` on every Perplexity direct HTTPS call
- Explicit `except (TimeoutError, socket.timeout)` branch that logs
  `TIMEOUT after 45s` and moves on
- Per-call, not per-batch: one row can time out while the next succeeds

**User's exact framing** (paraphrased for durability): *"Rather than cap
batches, I would prefer to cap 1 enrichment for venue to 45 seconds, and
1 enrichment to an event to 15 seconds. Adjust the scripts."*

**User's follow-up clarification**: *"So if we run a batch of some sort,
1 row could timeout, the next row could succeed? That's the intent, I'm
just confirming."* — Yes, exactly. Confirmed and shipped.

## Retiring seed-venues (July 31, 2026)

**Prompt pattern**: *"Why would we run seed-venues more than once?"*

Answer: we shouldn't. The weekly cadence was creating new venues via
seed-venues, but that meant re-computing 400+ venue records to add 10.
Extracted the stub-creation logic into `match-venues.py::match_or_create`
and gated `seed-venues.py` behind `--write --i-know-what-im-doing`.

**Rule the user asked for and we honored**: *"Seed venues was intended to
be a one-time script, never run it again. Matcher should auto-add new
venues."*

That's now the rule. Documented in
[decision-log.md](decision-log.md#retiring-seed-venuespy).

## Shell env-var incident (July 24, 2026)

A dumb bug that burned real money and is worth remembering.

Tried to pass the new-venue slug list to `enrich-venues.py` like this:

```bash
SLUGS='slug1,slug2' python3 scripts/enrich-venues.py --only-slugs "$SLUGS"
```

`$SLUGS` expands in the *parent* shell, where it's empty. The child
process saw `--only-slugs ""` and treated it as "no filter." Ran against
all 425 venues.

**Fix**: pass the slug string directly as a literal argument. Documented
in [agent-playbook.md](agent-playbook.md#running-enrich-venuespy).

## Weekly cadence (July–August 2026)

Since the timeout + auto-create changes shipped, weekly updates take
~10–15 minutes end-to-end with zero credit surprises. Typical run:

- 90 events (Fri:30 / Sat:35 / Sun:30 after dedup)
- 80 matched to existing venues (name:70 / canonkey:5 / fuzzy:5)
- 10 new venue stubs auto-created
- 10 stubs enriched, 30–40 fields updated, 0 timeouts
- Push, trigger build, verify live in under 90 seconds

## Incomplete: venue filter UI (July 31, 2026)

User request: *"We should add a venue filter to the filters."* with
preferences *"Type-ahead single-venue picker"* and *"Only venues with
events this week."*

Started but not finished:
- Markup + CSS added to `index.html` (`#ddVenue`, `#venueSearchInput`,
  `#venueList`, `.venue-item` styles)
- State model, populate function, input handler, URL sync, chip render,
  clear-all wiring, and Playwright test — all missing

Session was interrupted before completion. When resumed, either finish
the JS or revert the markup so the UI doesn't ship a broken dropdown.
See [frontend.md](frontend.md#incomplete-features).

## Documentation phase (August 2026)

Reason for these docs: the user is planning to work in other tools
(Claude Code, Codex, others) to try out different AI technologies. Not
leaving Perplexity — trying things in parallel.

Goal (verbatim): *"Document this thoroughly enough in the code base so
that we can make efficient progress even without this conversation as
background/context."*

That's what this directory is.

## Prompt patterns that worked well

Preserved for future reference:

1. **Task-list framing.** The user often asks for a multi-step outcome
   ("update the site with this week's data") and lets the agent build
   an internal todo list. Works because the agent can revise the list as
   it goes.
2. **Preference-first when there are options.** *"Type-ahead single-venue
   picker"* and *"Only venues with events this week"* — chosen from a
   menu of alternatives the agent surfaced. Faster than open-ended
   exploration.
3. **Constraints stated as invariants, not requests.** *"Cap 1 enrichment
   for venue to 45 seconds"* rather than *"can we make it faster?"*
   Ambiguity dies fast this way.
4. **Confirmation of subtle behavior.** *"So if we run a batch of some
   sort, 1 row could timeout, the next row could succeed? That's the
   intent, I'm just confirming."* — Explicit confirmation of the mental
   model prevents drift.
5. **Retirement over deletion.** When `seed-venues.py` was no longer
   needed, the user chose to keep it in-tree with a safety flag rather
   than delete it. Preserved auditability without risking accidental
   invocation.
