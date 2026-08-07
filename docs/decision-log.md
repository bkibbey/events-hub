# Decision Log

Short-form architecture decision records (ADRs) for choices that could
otherwise get re-litigated. Each one lists the context, the decision, the
consequences, and — where applicable — what to do differently if it turns
out wrong.

Newest first.

---

## ADR-010: Docs live in `docs/`, not the wiki

**Date**: 2026-08-07 · **Status**: Accepted

**Context**: The user wants to work in other AI tools (Claude Code, Codex,
etc.) and needs the project's context to travel with the repo.

**Decision**: All operational and architectural documentation lives in
`docs/` inside the repo, versioned alongside code. No external wiki, no
Notion, no README.md sprawl.

**Consequences**:
- Any agent that clones the repo has full context.
- Docs drift when scripts change. Mitigation: docs cross-reference exact
  filenames + line numbers where practical, and the docstring at the top
  of every script is the tie-breaker.
- The docs are Markdown, no JS, no build step — matches the site's own
  ethos.

---

## ADR-009: Half-built UI must be stashed, not shipped

**Date**: 2026-08-07 · **Status**: Accepted (learned the hard way)

**Context**: The venue filter UI (markup + CSS) was added in one session
but the JavaScript was never finished. During a weekly data update, a
`git add -A` would have shipped a broken dropdown to production.

**Decision**: Before every weekly commit, run `git status` and stash any
`index.html` changes not directly related to that week's data update.

**Consequences**:
- One more manual step in the weekly ritual.
- Better than the alternative: shipping a UI that shows a dropdown with
  no click behavior.
- Documented in [weekly-workflow.md](weekly-workflow.md#7-commit).

---

## ADR-008: `enrich-venues.py` MUST require `--only-slugs` in practice

**Date**: 2026-07-31 · **Status**: Norm, not enforcement

**Context**: Without `--only-slugs`, the enricher runs against every
venue with any blank field. That's ~200 venues × several API calls each.
An accidental invocation cost real money.

**Decision**: The script does NOT technically require `--only-slugs`
(force-of-argument enforcement felt draconian), but the weekly workflow
and agent playbook document its absence as a red flag. Reviewers should
challenge any invocation without `--only-slugs`.

**Consequences**:
- Human/agent discipline required.
- Escape hatch preserved for the rare case where a bulk re-enrichment is
  legitimately intended (e.g. a new field added to the schema).
- Consider changing to hard-required-arg if this ever recurs.

---

## ADR-007: Retiring `seed-venues.py`

**Date**: 2026-07-31 · **Status**: Accepted (user directive)

**Context**: Weekly runs used to invoke `seed-venues.py` to pick up new
venues. But re-seeding also re-computed all ~400 existing venue records,
which was slow and noisy — even with merge-preserve logic, diff review
was painful.

**Decision**: Stub creation moved into `match-venues.py::match_or_create`,
invoked automatically by `update-metadata.py`. `seed-venues.py` is
retired: kept in-tree for auditability, gated behind
`--write --i-know-what-im-doing`.

**Consequences**:
- Weekly diffs are minimal: only new venues touch `venues.json`.
- Registry rebuild is still possible if `venues.json` is ever lost.
- Two code paths for "insert a new venue" (seed-time and weekly-time)
  became one.

---

## ADR-006: Hard per-call timeouts, `max_retries=0`

**Date**: 2026-07-31 · **Status**: Accepted (user directive)

**Context**: A batch enrichment run hung for tens of minutes when the
API stalled, with the SDK dutifully retrying failed requests. Costs went
higher than expected. User asked for per-call caps, not per-batch caps.

**Decision**:
- Event enrichment: 15s cap via `openai.OpenAI(..., max_retries=0)` + per-call
  `timeout=15.0`.
- Venue enrichment: 45s cap via `urllib.urlopen(req, timeout=45)`.
- One slow row does not block subsequent rows.

**Consequences**:
- Occasionally an event ships with just its raw fields (no LLM
  enrichment). Acceptable — those rows show name/venue/city/link on the
  card, just no tagline or tags.
- Cost per week is predictable.
- Removed all retry-on-timeout code. Do not add it back without an ADR
  overturning this one.

---

## ADR-005: Blanks-only enrichment

**Date**: 2026-07-24 · **Status**: Accepted

**Context**: Early enrichment overwrote fields wholesale, which nuked
manual corrections. Users maintained `venues-overrides.json` as a
workaround, which was clunky.

**Decision**: Enrichment scripts (`update-metadata.py` for events,
`enrich-venues.py` for venues) only fill fields that are blank. Never
overwrite. `--force` exists as an escape hatch but is rarely appropriate.

**Consequences**:
- Manual edits to `venues.json` are permanent.
- Prompt is dynamically built to ask only for blank fields (saves
  tokens).
- `venues-overrides.json` becomes vestigial (kept for backward compat,
  no longer required).

---

## ADR-004: Keep both `place_id` and `osm_id`

**Date**: 2026-07-17 · **Status**: Accepted (user directive)

**Context**: Census returns a `tigerLine` id, Nominatim returns a
`place_id` and a separate OSM object id (`way/12345`). Was tempted to
unify.

**Decision**: Keep both fields. `place_id` holds whatever the provider's
primary identifier is (Census tigerLine OR Nominatim place_id).
`osm_id` holds the OSM object id when available.

**Consequences**:
- Two identifier fields, but each has clear provider semantics.
- Downstream tooling that wants an OSM object can find it directly.
- No lossy unification.

---

## ADR-003: Contacts as one row per contact

**Date**: 2026-07-17 · **Status**: Accepted (user directive)

**Context**: A venue can have multiple contact points (box office, event
catering, general). Considered separate arrays per channel.

**Decision**: One object per contact, with all channels on that row:

```json
{"label": "Event Catering", "phone": "", "email": "catering@x.com", "other": ""}
```

**Consequences**:
- Easier to render — one card per contact with whatever channels are
  populated.
- Loses the ability to group phones and emails separately, but nobody
  wanted that anyway.

---

## ADR-002: Fixed vocabulary of 9 social platforms

**Date**: 2026-07-17 · **Status**: Accepted

**Context**: Social platforms proliferate. Without a fixed list, the LLM
invents "mastodon" for one venue, "vero" for another, etc.

**Decision**: Fixed list of 9: facebook, instagram, twitter, tiktok,
youtube, linkedin, reddit, threads, bluesky. Every venue's `socials`
object contains all 9 keys, always. Blanks are `""`, never `null` or
missing.

**Consequences**:
- Predictable schema for the frontend.
- Adding a platform means updating `SOCIAL_PLATFORMS` in both
  `enrich-venues.py` AND `match-venues.py` (they must stay in lockstep),
  plus this doc.
- Prompt is shorter (LLM is constrained to the enum).

---

## ADR-001: Static site, no framework

**Date**: 2026-04-24 · **Status**: Foundational

**Context**: Could have used Next.js, Astro, Eleventy, etc.

**Decision**: One `index.html` file. Vanilla JS. CSS custom properties.
Served from GitHub Pages. No build step.

**Consequences**:
- Trivially embeddable in any host page.
- No dependency hell, no CVE churn, no build breakage.
- File is now ~1600 lines and inching toward hard to maintain — worth
  reconsidering if it hits ~3000 lines OR if we need real interactivity
  the current architecture can't handle (offline mode, PWA, etc.).
- Deploy is `git push`.
