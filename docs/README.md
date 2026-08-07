# Events Hub — Documentation Index

This directory is the durable specification and design record for the Raleigh
Weekend Events Hub. It exists so a new collaborator — human or AI — can be
productive on this codebase **without any conversational context**. Everything
that matters lives here or in the code it references.

## Reading order for a new agent

If you are an AI assistant picking up this codebase for the first time, read in
this order:

1. **[architecture.md](architecture.md)** — system overview, data flow diagram,
   and the file/directory contract. Start here.
2. **[data-model.md](data-model.md)** — canonical schemas for `events.json`,
   `venues.json`, the archive manifest, and raw newsletter dumps. All field
   semantics, invariants, and gotchas.
3. **[weekly-workflow.md](weekly-workflow.md)** — the exact command sequence to
   ingest, enrich, and ship a new week. Copy-pasteable. This is the single most
   common operation.
4. **[pipeline-scripts.md](pipeline-scripts.md)** — deep dive on each script in
   `scripts/`: inputs, outputs, flags, timeouts, failure modes.
5. **[venue-registry.md](venue-registry.md)** — how venues are matched,
   auto-created, enriched, and geocoded. The registry is the most subtle piece
   of the system.
6. **[enrichment-flows.md](enrichment-flows.md)** — prompts, models, timeouts,
   and the blanks-only philosophy behind both event and venue enrichment.
7. **[frontend.md](frontend.md)** — how `index.html` consumes the data files,
   filter state model, URL sync, week picker, sharing.
8. **[agent-playbook.md](agent-playbook.md)** — the operating manual for AI
   agents working on this codebase. Conventions, invariants, common mistakes,
   how to add features safely.
9. **[evolution.md](evolution.md)** — history of the project: what shipped
   when, why, and what prompts drove the changes. Preserves the user's voice
   and the reasoning behind decisions that are no longer visible in the code.
10. **[decision-log.md](decision-log.md)** — short-form ADRs (architecture
    decision records) for choices that could otherwise get re-litigated:
    place_id vs osm_id, hard-caps vs retries, retiring seed-venues, etc.

## Quick links

- **Live site**: <https://weekend.brewideas.net/>
- **Repo**: <https://github.com/bkibbey/events-hub>
- **Source newsletter**: <https://www.thingstodo919.com>
- **Deploy**: GitHub Pages from `main`, single static `index.html` + JSON data
- **Owner contact**: bkibbey@gmail.com (US/Eastern)

## Design principles (in priority order)

1. **Static site, no build step.** The site is a single `index.html` that
   fetches JSON at boot. There is no bundler, no framework, no server. Every
   change ships by committing to `main`.
2. **Additive data, never lossy.** Enrichment fills blanks; it never overwrites
   existing values. Every past week is preserved verbatim in
   `data/archive/events-YYYY-MM-DD.json`.
3. **Hard timeouts, no retries.** Every external call has a per-call ceiling
   (15s for event enrichment, 45s for venue enrichment). `max_retries=0`. One
   slow row doesn't block a batch.
4. **Idempotent scripts.** Re-running a script with the same inputs produces
   the same outputs (modulo LLM non-determinism). No side effects beyond
   writing to files listed in the docstring.
5. **The newsletter is the source of truth for what's happening.** We enrich,
   we don't invent. If Things To Do 919 doesn't list it, it's not on the site.

## What this project is not

- Not a general-purpose events aggregator. It is a specific downstream of one
  newsletter, for one metro area, on a weekly cadence.
- Not a real-time system. Events are frozen at Friday-morning ingest.
- Not a database-backed app. There is no server, no auth, no user accounts.
- Not a scraper of primary sources. The AI enrichment step consults the web
  (via Perplexity's `sonar` model), but the event list itself is exactly what
  the newsletter published.
