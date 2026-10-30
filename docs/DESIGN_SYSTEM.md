# Mimi design system: "Deep water"

Mimi runs full screen on a 7-inch handheld held at arm's length and driven by a game
controller, and on phones over the local network. It may be used outdoors, at night,
or in an emergency. Those conditions set the rules below.

- **Source of truth:** [`ui/src/app.css`](../ui/src/app.css) (tokens and primitives) and
  the helpers in `ui/src/lib/` (`color`, `theme`, `motion`, `dialog`, `confirm`, `roving`).
- **Live reference:** `/dev/design` in the app renders every token and primitive from the
  real code and previews any theme. It is linked from Settings › System › About.
- **Enforcement:** `npm run check` runs the type checker and the contrast audit
  (`npm run contrast`).

## Principles

| | |
|---|---|
| **Calm** | One accent, quiet surfaces, motion only when something is happening. Status copy is literal ("Transcribing what you said…"), never a joke. |
| **Legible in the field** | Every text token meets WCAG AA (4.5:1) on every surface in every theme, and AAA (7:1) in high contrast. A script checks this; it is not a hope. |
| **Controller-first** | Every control is reachable with a D-pad, every dialog closes with B, and no reflexive A press can destroy anything. Keyboard, touch and screen readers get the same paths. |
| **Offline-honest** | Say what is local, what is waiting and what failed. Presence is shown by the Well, and it only moves when Mimi is actually doing something. |

## Tokens

Three tiers. Components use tiers 1 and 2 (or tier 3 primitives) and never hard-code a
color, size, radius, layer or duration.

1. **Scales**: type, space, controls, radius, elevation, layers, motion. Theme-free.
2. **Theme**: semantic colors, redefined per theme, contrast mode and Well style.
3. **Primitives**: `.btn`, `.icon-btn`, `.card`, `.input`, `.field`, `.chip`, `.tag`, `.sheet`, `.scrim`, `.orb`, `kbd`.

### Type

Inter for interface, Source Serif 4 for long reading, JetBrains Mono for addresses and
code. Sizes are in `rem`, so Settings › Text size scales the whole UI. Each size has its
own line-height token; use them as a pair.

| Token | Size | Line height | Use |
|---|---|---|---|
| `--fs-display` | 32–44px (fluid) | 1.1 | Greeting, hero |
| `--fs-4xl` | 36px | 1.1 | Pairing codes, timers |
| `--fs-3xl` | 30px | 1.2 | Step and page titles on the handheld |
| `--fs-2xl` | 24px | 1.25 | Section titles |
| `--fs-xl` | 20px | 1.35 | Dialog and card titles |
| `--fs-lg` | 18px | 1.5 | Lede, emphasized body |
| `--fs-base` | 16px | 1.55 | Body, inputs |
| `--fs-md` | 14px | 1.5 | Dense UI text, menus, buttons |
| `--fs-sm` | 13px | 1.45 | Hints, small buttons |
| `--fs-xs` | 12px | 1.4 | Captions, eyebrow labels |
| `--fs-2xs` | 11px | 1.3 | Rail and tab labels only |

Weights: `--fw-regular` 400, `--fw-medium` 550, `--fw-semibold` 600, `--fw-bold` 650.

### Space and controls

A 4px grid. Steps of 8px and up are multiplied by `--density`, so Settings › Density
(Comfortable / Compact = 1 / 0.8) tightens layouts without touching hairlines.

| Token | px | | Token | px |
|---|---|---|---|---|
| `--space-0-5` | 2 | | `--space-5` | 20 |
| `--space-1` | 4 | | `--space-6` | 24 |
| `--space-1-5` | 6 | | `--space-8` | 32 |
| `--space-2` | 8 | | `--space-10` | 40 |
| `--space-3` | 12 | | `--space-12` | 48 |
| `--space-4` | 16 | | `--space-16` | 64 |

Control heights: `--control-sm` 32, `--control-md` 40, `--control-lg` 48 (×0.9 when
compact). `--hit-min` is 44px: on coarse pointers every small control keeps its look but
gets an invisible 44px hit area (`.icon-btn`, `.chip`, `.btn-sm`, tabs, radios, or any
element with `.hit`). Density never shrinks a hit area.

### Radius

Concentric: something inside a padded container uses a smaller step than the container.

| `--radius-xs` | `--radius-sm` | `--radius-md` | `--radius-lg` | `--radius-xl` | `--radius-2xl` | `--radius-pill` | `--radius-round` |
|---|---|---|---|---|---|---|---|
| 6 | 8 | 12 | 16 | 20 | 28 | 999px | 50% |
| code, kbd | log panes | inputs, rows | toasts, tiles | cards | sheets, dialogs | buttons, chips | avatars, orbs |

### Elevation

`--elev-1` (resting controls), `--elev-2` (raised cards), `--elev-3` (sheets, dialogs,
toasts), `--elev-glow` (selected or "live" items: an accent hairline and halo). Each
theme defines its own shadow colors; light shadows are softer.

### Layers

Named, in paint order. A scrim and its panel share a layer; the panel comes later in the DOM.

| `--z-raised` | `--z-nav` | `--z-popover` | `--z-tabbar` | `--z-palette` | `--z-sheet` | `--z-fullscreen` | `--z-dialog` | `--z-toast` | `--z-system` |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 5 | 20 | 30 | 60 | 70 | 80 | 90 | 100 | 120 |

Toasts sit above dialogs on purpose: an Undo must stay reachable.

### Motion

| Duration | ms | Use | | Easing | Use |
|---|---|---|---|---|---|
| `--dur-instant` | 80 | press feedback | | `--ease-standard` | most movement |
| `--dur-fast` | 140 | hover, color | | `--ease-out` | entrances (arrive softly) |
| `--dur-base` | 200 | small enter/exit, toggles | | `--ease-in` | exits (leave quickly) |
| `--dur-slow` | 300 | sheets, dialogs, toasts | | `--ease-breathe` | ambient loops |
| `--dur-slower` | 480 | hero morphs | | | |

**Reduced motion** (the OS setting or Settings › Reduce motion) sets every `--dur-*` to
0. `#lib/motion` hands the same tokens to Svelte transitions and strips movement:

```svelte
<div transition:fly={motion({ y: 24, duration: 'slow' })}>   <!-- fades only, instantly, when reduced -->
el.scrollIntoView({ behavior: scrollBehavior() })             <!-- 'auto' when reduced -->
```

A global rule also stops keyframe loops, and the Well holds still.

## Color and theming

Themes are attribute selectors on `<html>`: `data-theme` (`dark` Deep water, `oled`
Midnight, `light` Daylight; `auto` follows the OS), `data-contrast`, `data-density`,
`data-well`, `data-motion`. Because tokens live on attribute selectors rather than only
`:root`, any subtree can preview another theme (onboarding swatches, `/dev/design`).

| Token | Role |
|---|---|
| `--bg`, `--bg-2` | App background, rails |
| `--surface`, `--surface-2`, `--surface-3` | Cards, fields, hover/selected |
| `--line`, `--line-2` | Hairlines, control borders |
| `--text`, `--text-2`, `--text-3` | Primary, secondary, tertiary text |
| `--accent`, `--accent-ink`, `--accent-soft`, `--accent-line` | Accent as text, ink on a filled accent, tint, border |
| `--ok`, `--warn`, `--danger` (+ `-soft`, `-line`, `--danger-ink`) | Status, deep enough to be text |
| `--scrim`, `--glass` | Modal backdrop, translucent bars |
| `--media-*`, `--qr-bg`, `--map-route-casing` | Fixed colors for camera, QR, map (not themed) |

**The accent is solved, not picked.** People choose any color. `applyTheme()` keeps its
hue and chroma and moves only its OKLab lightness, in 1% steps, until it reaches 4.5:1
(7:1 in high contrast) against every surface of the active theme *and* against its own
16% tint. `--accent-ink` is a deep shade of the same hue, or white if that can't reach
AA. Lagoon `#6EE7D2` stays itself on Deep water and becomes `#006959` on Daylight.

**First paint.** `app.html` reads a snapshot that `#lib/theme` saves on every change and
applies the theme, accent and Well colors before any script or stylesheet loads, so a
Daylight user never sees a dark flash.

## Accessibility commitments

- **Contrast, enforced.** `ui/scripts/contrast.mjs` parses `app.css`, resolves all six
  theme × contrast combinations, and checks every text token on every surface (and on
  translucent glass), status colors on their own tints, ink on fills, every accent
  preset plus hostile custom colors through the app's own solver, the focus ring at 3:1,
  and avatar initials: about 1,600 pairs. It exits non-zero on any failure. Before this
  system, Daylight's warning color was 1.6:1 and its tertiary text 3.1:1.
- **Focus.** One ring, an `outline` with offset, so it follows each element's radius (a
  round button keeps a round ring). It shows for keyboard, screen readers and programmatic
  focus, and always under the gamepad (3px).
- **Dialogs.** `use:dialog` gives every modal `role`, `aria-modal`, a name, initial focus,
  a Tab trap, Escape and controller-B to close, stacking, and focus restore.
- **Forms.** No placeholder-only fields: `.field` + `.field-label`, or a settings `Row`,
  which names its control (`aria-labelledby`) and describes it with its hint. Segmented
  controls and pickers are radio groups with one Tab stop and arrow-key selection.
- **Input-aware copy.** Controller hints appear only when a controller is in use; touch
  and keyboard get their own wording.
- **Touch.** 44px minimum hit areas on coarse pointers, at any density.

## Patterns

**Destructive actions.** One item, reversible: do it immediately and show an **Undo**
toast (`app.deferDelete`); the real delete runs when the toast goes, or when the page is
hidden. Many items, or irreversible: ask first with `confirmDialog()`: Mimi's own dialog
(never the browser's `confirm()`, which a controller can't reach in the kiosk shell),
Cancel focused, the confirm button armed after 600ms so a reflexive A can't fire it.

**Toasts** pause while hovered or focused; errors are announced assertively.

**Settings.** Nine sections from one list (`#lib/settings-sections`), with sub-section
anchors, per-group reset (confirmed), and redirects from every old URL.

## Components

| Primitive / component | Notes |
|---|---|
| `.btn` (`-primary`, `-ghost`, `-danger`, `-danger-solid`, `-sm`, `-lg`) | Pill; `aria-disabled="true"` styles like `disabled` but stays focusable |
| `.icon-btn` (`.sm`) | Round; always needs `aria-label` |
| `.chip` | Filters and toggles; state via `aria-pressed` |
| `.tag` (`.live`, `.err`) | Read-only status |
| `.input`, `.field`, `.field-label` | Visible labels above fields |
| `.card`, `.sheet`, `.scrim` | Surfaces; sheets for modals |
| `Row`, `Toggle`, `Segmented`, `Slider` | Settings controls (`#components/settings`) |
| `ConfirmDialog`, `Toasts` | Mounted once in the layout |
| `Well` | WebGL presence, see below |

## The Well: a presence system

Mimi has no spinners. Its state is shown by one living object, after Mímir's well: a
WebGL orb of flowing light that **breathes** when idle, **ripples** with the microphone
when listening, **swirls** while thinking and **pulses** as Mimi speaks. The rail mark is
the same water, small: it dims while a model wakes and grays out when Core can't be
reached, with the state also in its accessible name.

It is drawn from three tokens: `--well-a` (the light: the user's raw accent), `--well-b`
(the body) and `--well-c` (the depths), plus a derived `--orb` gradient for static uses
(rail mark, WebGL fallback, boot screen, previews). Well styles recolor it without
touching the accent: **Tide** (default), **Aurora** (violet depths), **Ember** (warm
firelight) and **Mono** (quiet grays, least distracting). It is decorative to assistive
technology (`aria-hidden`); every state it shows is also said in words. Under reduced
motion the water holds still. It renders at about 30 fps when idle because the GPU is
shared with the language model.

## Adding to the system

- Need a value that isn't a token? Use the nearest step. If none fits, add a token in
  `app.css`, document it here, and show it in `/dev/design`.
- `ui/scripts/tokenize.py` rewrites literal radii, font sizes, weights, layers,
  durations and spacing in a component's `<style>` to the nearest token step.
- New color token used for text? Add it to `TEXT` in `scripts/contrast.mjs`.
