# Frontend

The frontend is a single `index.html` (~1600 lines) that fetches JSON at boot
and renders a filterable, shareable event view. There is no build step, no
framework, no bundler. It's vanilla JS with a small amount of state, CSS
custom properties for theming, and inline SVG icons.

## What loads and when

```
index.html loads
        │
        ▼
   ┌──────────────────────────────────┐
   │ Boot: read URL params            │
   │   week?  →  archive mode         │
   │   selected? → shared-view mode   │
   │   view=map? → open map on load   │
   └──────────────────────────────────┘
        │
        ▼
   fetch('data/events.json')  ── or ── fetch('data/archive/events-{week}.json')
        │
        ▼
   fetch('data/venues.json')  (non-blocking, doesn't hold up render)
        │
        ▼
   fetch('data/archive/index.json')  (populates week picker)
        │
        ▼
   applyUrlParamsToState()  → seed filters from URL
        │
        ▼
   renderCards()           → paint the list
```

All three fetches use `{cache: 'no-cache'}` so a freshly-pushed weekly update
appears immediately (no CDN-forced stale reads).

## State model

Single `state` object, mutated in place:

```js
state = {
  allEvents:     [],     // events for the currently-viewed week
  visibleEvents: [],     // after filters
  venues:        {},     // dict-shaped venues.json (slug → venue-obj)
  activeDay:     'all',  // 'all' | 'Friday' | 'Saturday' | 'Sunday'
  activeCities:  new Set(),
  activeTags:    new Set(),
  freeOnly:      false,
  query:         '',
  sort:          'shuffle',   // 'shuffle' | 'az' | 'za'
  view:          'list',      // 'list' | 'map'
  sharedView:    false,       // true when ?selected=... is present
  selected:      new Set(),   // user picks for the "shareable link" feature
}
```

Plus a `sessionStorage`-backed sort preference at `events-hub:sort`.

## URL sync (bidirectional)

Filters mirror into the URL, and URL params seed filters on load. `syncUrl()`
runs after every state change; `applyUrlParamsToState()` runs once on boot.

| Param      | Values                        | Reset on week-change? |
|------------|-------------------------------|------------------------|
| `sort`     | `az` \| `za`                  | yes (back to shuffle) |
| `day`      | `friday` \| `saturday` \| `sunday` | yes |
| `cities`   | comma-list                    | yes |
| `tags`     | comma-list                    | yes |
| `free`     | `1`                           | yes |
| `q`        | search text                   | yes |
| `view`     | `map`                         | no  |
| `week`     | `YYYY-MM-DD`                  | (the switch itself)   |
| `selected` | comma-list of event IDs       | no — shared-view      |

**Shared-view mode** (`?selected=1,3,7`) suspends filter mirroring — that URL
is a permanent link to a hand-picked list of events for a specific week.

## Filter architecture

Every filter is a "dropdown" (`.filter-dd`) with:

- A `.filter-dd-btn` button showing the current selection + a badge for count
- A `.filter-dd-pop` popover with the option list
- Multi-select with checkbox rows for cities and tags
- Single-select for day
- A `data-clear` button that resets that one filter

Tag matching is **AND** (must have all selected tags). City matching is **OR**
(any selected city). Free toggle is a hard filter.

Search (`q`) matches across name, tagline, description, venue, city, tags
using case-insensitive substring.

Active filters render as dismissible chips in the second filter row.

## Sort mode: Shuffle

Default sort is a client-side Fisher-Yates shuffle seeded by
`Math.random()`. Re-shuffles on:

- Every page load (so a refresh gives a fresh order)
- Every tap on the "Shuffle" pill (even if already active)

The intent is to keep prominence rotating — a hidden gem at position #47
gets a chance to be seen at #3. If the shuffle is stable during a session,
it's because the pill wasn't re-tapped.

A/Z and Z/A sorts are alphabetical by event name (case-insensitive, en-US
collation).

## Week picker

Clicking the "Weekend of Aug 7, 2026" label opens a popover of every week
from `data/archive/index.json`, newest-first, with a *Current* badge on the
active one. Selecting a past week:

1. Sets `?week=YYYY-MM-DD` in the URL
2. Fetches `data/archive/events-YYYY-MM-DD.json`
3. Resets all filters (different weekends have different cities/tags)
4. Resets sort to Shuffle
5. Shows a "Back to current" banner

## Map view

Leaflet map with markers for every event whose venue has `lat` and `lng`
via its `venueId` lookup into `venues.json`. Markers cluster with
`Leaflet.markercluster`. Toggle button in the header (`?view=map` for a
sharable link).

Events without a matched or geocoded venue are silently omitted from the
map. They still appear in the list view.

## Shareable link (event picks)

When events are selected (checkbox on each card), a floating "Copy
shareable link" pill appears at the bottom of the screen. Clicking it
builds:

```
https://weekend.brewideas.net/?selected=1,3,7&week=2026-08-07
```

Opened by a friend, the site loads shared-view mode: only those events
appear, with an amber banner offering "Show all N events" to escape.

## Theme

CSS custom properties on `:root` with a `[data-theme="dark"]` override on
`<html>`. Toggle button in the header persists to `localStorage`. Auto-
detects `prefers-color-scheme` on first load.

Color tokens mirror the Things To Do 919 brand:

- Light: `--color-primary: #1f2bbf` (indigo) / `--color-accent: #a6e22e`
  (lime)
- Dark: `--color-primary: #7c84ff` / `--color-accent: #b8f03d`
- 3px lime accent stripe pinned to the top of the viewport

## Confetti / holidays

`assets/confetti.min.js` (vendored canvas-confetti) fires on specific dates.
See [feature-holidays.md](feature-holidays.md) for the full trigger list.

## The About modal

Circled **i** in the header fetches `README.md` at runtime and renders it
inline via a minimal Markdown parser. No jump to GitHub — the modal keeps
users on-site.

## Disclaimer banner

"Experimental" floating banner at the bottom credits Things To Do 919 and
warns that AI-enriched details should be double-checked. Dismissible per
session (no `localStorage` — reappears every reload). Lifts above the
share-pill when events are selected.

## Iframe embedding

The site is embed-safe: no `X-Frame-Options` denial, no frame-busting JS.
Full snippet is in the root [README.md](../README.md#embedding-the-site).
The `?selected=...` and filter params make it possible to embed a curated,
pre-filtered view.

## Incomplete features (as of 2026-08-07)

### Venue filter (single-select type-ahead)

**Status: markup + CSS in place; JS not wired.**

The intent: a "Venue" dropdown alongside Day/Cities/Tags, showing only
venues with at least one event this week, with a type-ahead search input.

Present in `index.html`:

- HTML: `#ddVenue`, `#venueSearchInput`, `#venueList`, `#venueCount`,
  `[data-clear="venue"]`
- CSS: `.venue-search-wrap`, `.venue-search-input`, `.venue-list`,
  `.venue-item`, `.venue-empty`

Missing:

- `state.activeVenue` (single string, slug or empty)
- `populateVenueList()` (derive candidates from
  `state.allEvents.map(e => e.venueId).filter(x => x)` de-duped, then
  render `.venue-item` for each with counts)
- Input handler on `#venueSearchInput` for type-ahead filtering
- Apply-filter integration in the main filter function
- URL sync (`?venue=<slug>`)
- Active-chip render in the chips row
- Clear-all wiring for `data-clear="venue"`
- Playwright test to verify behavior end-to-end

If this feature is not being resumed soon, the markup + CSS should be
stashed/reverted so the UI doesn't show a broken dropdown.
