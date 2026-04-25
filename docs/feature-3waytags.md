# Feature: Three-State Tag Selection

**Status**: Proposed
**Date drafted**: 2026-04-25

## Summary

Allow tags to cycle through three states instead of the current two:

- **Neutral** — tag is ignored (default)
- **Include** — event must have this tag (current "is-active" behavior)
- **Exclude** — event must NOT have this tag (new)

Cycle on click: `neutral → include → exclude → neutral`. The same cycle works on dropdown pills and card chips, and they stay in sync.

## State Model

Replace `state.activeTags: Set<string>` with two sets:

```js
state.includeTags: Set<string>
state.excludeTags: Set<string>
```

A tag can only be in one set at a time. Cycle logic moves a tag from one set to the next, removing from the prior set.

## Filter Logic (`applyFilters`)

```js
// Include: AND — event must have every included tag
for (const t of includeTags) if (!et.has(t)) return false;
// Exclude: event must have NONE of the excluded tags
for (const t of excludeTags) if (et.has(t)) return false;
```

## Visual Design

Three distinct states for both pill (`#tagPills .pill`) and card chip (`.card-tag`):

| State | Background | Text | Border | Glyph |
|---|---|---|---|---|
| Neutral | `--color-surface-offset` | muted | transparent | none |
| Include | `--color-primary-soft` (teal) | `--color-primary` | `--color-primary` | none |
| Exclude | rose/red-soft | rose | rose | `−` prefix or strikethrough |

Add CSS classes `.is-include` / `.is-exclude` (replacing the single `.is-active`).

Use a `−` glyph or strikethrough on excluded tags so the state is legible without relying on color alone (red/green colorblind accessibility).

Add `aria-pressed` and `title` attributes:

- Neutral: `title="Click to include"`
- Include: `title="Click to exclude"`
- Exclude: `title="Click to remove filter"`

## UI Affordances

1. **Tags dropdown badge** — show combined count, e.g. compact `+2 −1`, or "2 included, 1 excluded".
2. **Active filter chips** (top bar, `buildActiveChips`) — included render as green chips, excluded render as rose chips prefixed with `−`. Click removes (returns tag to neutral).
3. **Popover footer "Clear"** — clears both sets.
4. **Tooltip on hover** — `title` attribute explains the next action in the cycle.

## Edge Cases

- **`TAG_EXCLUDE` constant rename**: rename to `TAG_HIDDEN` to avoid naming collision with the new "exclude" semantics (the `'free'` tag is handled by a dedicated toggle).
- **Card chip click**: cycles the same way as dropdown pills. Keep `stopPropagation` so it doesn't open the event card.
- **"Clear all" / "Reset filters"**: clears both `includeTags` and `excludeTags`.
- **Pill counts**: per-tag event count display is unaffected.

## Shared URL Encoding

Current shareable URL likely encodes tags as `tags=a,b`. Recommended encoding for backward compatibility:

**Prefix syntax** — single param, mixed include/exclude: `tags=a,b,-c,-d`

- Bare names = include
- `-` prefix = exclude
- Old links with only `tags=a,b` continue to work as include-only.

Update both encode and decode paths.

## Implementation Steps

1. Refactor state: split `activeTags` into `includeTags` + `excludeTags`.
2. Replace `toggleTag(tag)` with `cycleTag(tag)`.
3. Update `applyFilters` for include-AND + exclude-NONE.
4. Update `syncTagPillState` to apply `.is-include` / `.is-exclude` to both `#tagPills .pill` and `.card-tag`.
5. Add CSS for `.is-exclude` (rose tones + `::before` minus glyph).
6. Update `buildActiveChips` to label excluded chips as `−tag` with rose styling.
7. Update Tags dropdown badge to show combined count.
8. Update share URL encode/decode to support `-tag` prefix.
9. Update "Clear" handlers to clear both sets.
10. Test in Playwright:
    - Cycle a tag through all 3 states from dropdown
    - Cycle a tag through all 3 states from a card chip
    - Verify card chip ↔ dropdown sync
    - Verify filter results for include-only, exclude-only, and mixed
    - Verify shared URL roundtrip with mix of include/exclude
    - Verify legacy `tags=a,b` URLs still load as include-only

## Optional Polish (Decide Before Implementing)

- **Right-click to exclude directly** (skip the include step). Power-user shortcut; discoverability is poor. Skip unless explicitly desired.
- **Long-press on mobile** for the same shortcut. Same discoverability concern.

## Risks / Considerations

- **Color accessibility**: rose + green can be tricky for red-green colorblind users. The `−` prefix / strikethrough is the real signal; color is secondary.
- **Visual noise**: tag cloud can get noisy with two colored states active simultaneously. Worth previewing before locking in final colors.
- **Open questions**:
  - Should card chips also cycle 3-state, or stay 2-state (include-only) and let exclusions happen only from the dropdown?
  - Final color choice for exclude state.
  - Final URL param format (prefix syntax vs separate `xtags=` param).

## Files Likely Touched

- `index.html` — state, filter logic, render functions, CSS, URL builder.
- `README.md` — brief mention in features section if user-facing behavior is documented there.
