# Feature: Holiday & Easter-Egg Confetti

**Status**: Shipped (commit `7d970e7`, 2026-04-25)
**Library**: [canvas-confetti](https://github.com/catdad/canvas-confetti) v1.9.3, vendored locally as `assets/confetti.min.js` (~10 KB)

## Overview

The site fires `canvas-confetti` animations in two scenarios:

1. **Easter eggs** — when the user types a trigger word in the search box.
2. **Holidays** — when the page loads on a recognized calendar date, once per browser session per holiday.

All effects respect the user's `prefers-reduced-motion` setting and silently no-op when reduced motion is requested.

## File Layout

| File | Purpose |
|---|---|
| `assets/confetti.min.js` | Vendored canvas-confetti, loaded with `defer` from `<head>`. |
| `index.html` | Defines `CONFETTI_EFFECTS`, `fireConfetti`, easter-egg wiring, and the holiday IIFE. |

Vendoring (rather than CDN) keeps the site self-contained and works offline / under strict CSPs.

## Effect Recipes (`CONFETTI_EFFECTS`)

A single map keyed by effect name. Every recipe guards `window.confetti` so missing-script failures are silent.

### Easter-egg effects

| Name | Used by | Description |
|---|---|---|
| `burst` | `bruce` | Single 120-particle burst from `y:0.7`, spread 70°, velocity 45. |
| `rain` | `kibbey` | 1.5s `requestAnimationFrame` loop, 4 particles per frame, full 360° spread, dropping from `y: -0.2..0`. |
| `blueGold` | `rotary` | Two simultaneous 80-particle bursts from bottom-left (`x:0,y:.7`, angle 60°) and bottom-right (`x:1,y:.7`, angle 120°). Colors `#1f4e9f`, `#f7a81b`, `#ffd966`, `#0a3a7a` (Rotary blue + gold). |

### Holiday effects

| Name | Used by | Description |
|---|---|---|
| `fireworks` | New Year's | 2.5s loop with two simultaneous bursts (left third, right third), 50 particles each, full 360° spread. |
| `hearts` | Valentine's | Single 50-particle burst using `confetti.shapeFromText('❤️')`, scalar 2, rose color palette. |
| `shamrocks` | St. Patrick's | 60-particle burst of `☘️` shapes, green palette. |
| `redWhiteBlue` | July 4 | 1.8s loop, 30 particles per frame from the top, red/white/blue palette (`#b22234`, `#ffffff`, `#3c3b6e`). |
| `halloween` | Halloween | 2.5s loop, 3 particles per frame cycling through `🎃 👻 🦇`, slow gravity 0.7, drifting from the top. |
| `leaves` | Thanksgiving | 3s loop, 2 particles per frame cycling `🍁 🍂`, very slow gravity 0.3 with horizontal drift 1, narrow 80° spread. |
| `snow` | Christmas Eve / Christmas | 4s loop of `❄️` shapes, gravity 0.4, gentle 120° spread, white color override. |

## `fireConfetti(name)`

```js
function fireConfetti(name){
  if(window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)').matches) return;
  const fn = CONFETTI_EFFECTS[name];
  if (fn) fn();
}
```

Single entry point — all triggers route through it so the reduced-motion check is centralized.

## Easter-Egg Triggers (`EGG_TRIGGERS`)

Defined in `index.html`:

```js
const EGG_TRIGGERS = [
  { word: 'bruce',  message: 'What a guy',         effect: 'burst' },
  { word: 'kibbey', message: 'What a family',      effect: 'rain' },
  { word: 'rotary', message: 'Service above self', effect: 'blueGold' },
];
```

Matching is **whole-word, case-insensitive**. The query is split on `/\W+/` and we check `tokens.includes(word)`, so `"brucellosis"` does NOT match `"bruce"`.

### Re-fire guard (`lastEggWord`)

To avoid firing on every keystroke, we record the last matched word. Confetti only fires on a transition INTO a new match. Clearing the input or switching to a different egg word resets the guard.

Behavior verified in Playwright:

- Typing `bruce` → 1 burst (120 particles)
- Typing `kibbey` → ~93 calls (rain loop)
- Typing `rotary` → 2 calls at `{x:0,y:.7}` and `{x:1,y:.7}`
- Appending `" club"` to `rotary` → no re-fire
- Clearing then re-typing `rotary` → re-fires
- Typing `brucellosis` → no fire (whole-word match works)

## Holiday Detector

A self-invoking IIFE near the bottom of the script section. It runs once per page load, checks today's local date against a static `HOLIDAYS` array, and fires the matching effect after a 900ms delay (so the page has settled).

### Calendar table

| Month/Day | Effect | Key | Display name |
|---|---|---|---|
| 1 / 1 | `fireworks` | `newyears` | New Year's |
| 2 / 14 | `hearts` | `valentines` | Valentine's Day |
| 3 / 17 | `shamrocks` | `stpatricks` | St. Patrick's Day |
| 7 / 4 | `redWhiteBlue` | `july4` | Independence Day |
| 10 / 31 | `halloween` | `halloween` | Halloween |
| 11 / 26 | `leaves` | `thanksgiving` | Thanksgiving (approx) |
| 12 / 24 | `snow` | `xmaseve` | Christmas Eve |
| 12 / 25 | `snow` | `christmas` | Christmas |

### Once-per-session-per-holiday

A `sessionStorage` flag named `holiday-fired-{key}-{year}` is set on first fire. Subsequent reloads in the same browser session see the flag and skip. Closing the tab clears it.

The `try/catch` around `sessionStorage` is defensive — Safari Private Mode and a few other contexts throw on writes. If storage fails, the effect still fires (and may re-fire on reload), which is preferable to silently failing.

### Timezone

Date checks use the browser's local timezone via `new Date()`. A traveler in `UTC-12` on Dec 25 may see Christmas confetti slightly earlier or later than someone in `UTC+12`, by their respective local clocks. This is the right behavior for a regional events site.

## Reduced Motion

The single check in `fireConfetti` covers everything:

```js
if (window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)').matches) return;
```

The site's general CSS also collapses transitions for reduced-motion users (`@media (prefers-reduced-motion: reduce)` in the stylesheet).

## Known Limitations / Future Ideas

1. **Thanksgiving is hard-coded** to Nov 26, which is approximate. A correct implementation would compute "fourth Thursday of November". Worth fixing if Thanksgiving lands on a non-26 date and the effect doesn't show up.
2. **Easter & Mother's / Father's Day** are floating dates not currently supported. Easter requires the [Computus algorithm](https://en.wikipedia.org/wiki/Date_of_Easter); Mother's Day is "second Sunday in May"; Father's Day is "third Sunday in June".
3. **Multi-day windows**: currently each holiday is a single calendar day. To extend (e.g., snow Dec 20–Jan 1), expand `HOLIDAYS` to multiple entries with the same `key`, or change the schema to `{m, dStart, dEnd}`.
4. **Per-session opt-out**: no UI exists for "no confetti, please" beyond the OS-level reduced-motion setting. Could add a toggle in the About modal that writes a `localStorage` flag checked alongside the media query.
5. **Triggering effects manually for QA**: there's no dev URL trick like `?confetti=fireworks`. Easy to add for testing without faking the date.
6. **Effect previews in About modal**: would be a nice touch — a small grid of buttons that fire each effect on demand.

## Adding a New Holiday

1. Add a recipe to `CONFETTI_EFFECTS` (or reuse an existing one).
2. Append a row to the `HOLIDAYS` array with `{m, d, effect, key, name}`. The `key` must be unique — it's part of the sessionStorage flag.
3. (Optional) Add a Playwright test that mocks `Date` to that day and asserts `window.confetti` was called.

## Adding a New Easter Egg

1. Add a recipe to `CONFETTI_EFFECTS`.
2. Append `{word, message, effect}` to `EGG_TRIGGERS`. `word` must be a single token — `/\W+/` splitting prevents multi-word phrases. For phrases, refactor the matcher to test substrings.

## Testing Notes

The Playwright pattern used during development:

- `js_repl` with `reset:true` for a fresh browser.
- `addInitScript` to wrap `window.confetti` with a spy BEFORE navigation, so the script's confetti calls are recorded.
- For holiday testing, mock `Date` via `addInitScript`:
  ```js
  const RealDate = Date;
  globalThis.Date = class extends RealDate {
    constructor(...args){ if(args.length===0) return new RealDate('2026-12-25T12:00:00'); return new RealDate(...args); }
    static now(){ return new RealDate('2026-12-25T12:00:00').getTime(); }
  };
  ```
- Clear `sessionStorage` between holiday tests, or change the year in the mock to bypass the fired flag.
