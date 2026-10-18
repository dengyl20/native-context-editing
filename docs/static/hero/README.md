# hero-blocks — the hero's animated background

The context, as a ledger.

Blocks live in ruled columns. Each one is an addressable context block: an
address in the left margin, a hairline rule, a body with a type rail in its
role colour and a few lines of text. The columns drift upward at parallax
speeds — outer columns near and fast, the middle ones far and slow — and every
few seconds an edit lands:

- **rewrite** — amber. The card swells, gains a 2px amber frame and a soft
  halo, an amber band sweeps across it, its first line turns amber, and a
  `REWRITE` label is set in the corner. The mark stays on the card until it
  recycles;
- **drop** — red (`--chip-drop-fg`). The card is struck through in red, every
  line turns red, a `DROP` label appears, and it squashes upward and out while
  the column closes the gap, reflowing every block beneath it;
- **append** — green (`--chip-append-fg`). A card arrives with a green frame,
  wash, rail and lines, an `APPEND` label, and slides into the stack as the
  blocks below make room.

Edits fire roughly twice a second, staggered across columns, so a visitor does
not have to wait to see one — and the arrival, the strike and the reflow are
three different motions, which is what makes the grammar legible at a glance.

The reflow is the point. It is the one thing on the page that behaves like the
paper's subject rather than like decoration.

It is one procedurally drawn Canvas 2D file: no dependency, no build step, no
network request, ~100 blocks drawn fresh each frame.

---

## 1. Files

| File | What it is |
|---|---|
| `hero-blocks.js` | The renderer, 25 KB raw / 7.8 KB gzip. Exposes `HeroBlocks` and self-initialises every `<canvas data-hero-blocks>`. |
| `hero-blocks.css` | Page-side plumbing: layer stacking, the legibility scrim, the bottom fade, dark-theme and phone overrides. Namespaced under `.hero-bg` / `.hero--bg`. |
| `preview.html` | A local harness that rebuilds the hero with the background attached, plus a theme switch, a field-opacity control and a live fps read-out. Preview only — nothing on the site links to it. |
| `README.md` | This file. |

Nothing else is touched. `docs/index.html` and `docs/static/site.css` are left
alone; wiring them in is the four-line change below.

---

## 2. Wiring it in

### 2.1 `docs/index.html`

**(a)** In `<head>`, after the `site.css` link:

```html
<link rel="stylesheet" href="static/hero/hero-blocks.css">
```

**(b)** The hero section. Add the `hero--bg` class and the layer as its **first
child**; leave the existing `.shell` alone — the CSS lifts it above the canvas:

```html
<section class="hero hero--bg">
  <div class="hero-bg" aria-hidden="true">
    <canvas data-hero-blocks></canvas>
  </div>
  <div class="shell">
    … the existing logo, h1, authors, links …
  </div>
</section>
```

`aria-hidden` matters: the canvas is decoration and must not surface to a
screen reader.

**(c)** Just before `</body>`:

```html
<script src="static/hero/hero-blocks.js" defer></script>
```

The script self-initialises on `DOMContentLoaded`, so no inline call is needed.
Parameters may also be declared in the markup:

```html
<canvas data-hero-blocks data-alpha="0.9" data-columns="7" data-edits="1.2"></canvas>
```

### 2.2 Tuning without touching JS

The two things a designer is most likely to change are CSS custom properties on
`.hero-bg`:

```css
.hero-bg {
  --hero-field-opacity: 0.55;                    /* whole layer, 0 … 1         */
  --hero-veil-color: rgba(251, 250, 247, 0.74);  /* the wash behind the text   */
  --hero-veil-size: 62% 52%;                     /* its shape around the title */
  --hero-veil-fade: 58%;                         /* where the bottom fade starts */
}
```

`--hero-veil-color` is the single knob for text legibility: raise its alpha if
the headline ever competes with the ledger, lower it to let more through. It is
the page ground (`--paper`) at partial alpha, so it reads as paper rather than
a grey overlay. The dark value is set by `:root[data-theme="dark"]` and by the
OS preference.

### 2.3 Tuning in JS

```js
const hero = HeroBlocks.attach(document.querySelector("canvas[data-hero-blocks]"), {
  columns: 7,          // null = derive from width (one per ~200px)
  speed: 0.9,          // global time scale
  alpha: 0.95,         // overall field strength
  edits: 1.2,          // edit-event rate multiplier; 0 stops the grammar
  reducedMotion: "static"
});

hero.stats      // { frames, fps, cpuMs, blocks, cssSize } — live counters
hero.redraw()   // force a resize + repaint
hero.destroy()  // cancel rAF, drop every listener and observer
```

`attach()` is idempotent per canvas and returns a handle; the same handle is on
`canvas.__heroBlocks`.

---

## 3. Parameters

| Option | Default | Range that still looks right | What it does |
|---|---|---|---|
| `columns` | `null` | 3 – 8 | Column count. `null` derives it from width: one per ~200px, clamped to `minColumns`…`maxColumns`. |
| `minColumns` / `maxColumns` | `3` / `8` | — | Rails for very narrow or very wide canvases. Phones get 3. |
| `speed` | `1` | 0.6 – 1.4 | Multiplies drift. Columns travel at `7 + 17·depth` px/s × speed, so 8 px/s in the far middle and 24 px/s at the near edges. |
| `alpha` | `1` | 0.8 – 1 | Field opacity; same as `--hero-field-opacity`, but baked per instance. |
| `edits` | `1` | 0 – 2 | Edit-event rate multiplier. `0` freezes the grammar and leaves a pure drift. |
| `editEvery` | `[0.38, 0.62]` | 0.3 – 3 s | Seconds between edits, before `edits` divides it. The default is about 1.9 edits/s across all columns. |
| `reducedMotion` | `"static"` | `"static"` \| `"slow"` | `static` = one settled frame; `slow` = continuous at 30 % speed. |
| `stillTime` | `40` | 15 – 60 | Seconds of drift baked into the reduced-motion still, so it reads as a paused moment rather than a fresh scatter. |
| `dpr` | `2` | 1 – 3 | Cap on the backing-store pixel ratio. |
| `seed` | `20261017` | any int | Changes the layout. Same seed, same ledger. |

### Per-block irregularity

Blocks are not a uniform grid. Each new block rolls its own height and line
count: most are one line, about a third are two, and roughly one in seven is a
tall block with four or five lines. Column gutters are ~12px, and tall blocks
push everything below them down — that is why the columns read as a context
rather than a table.

### Per-theme values

There is no separate per-theme parameter block to edit. The palette is built
from the page's tokens at run time:

| Role | Light | Dark |
|---|---|---|
| card fill | `rgba(255,255,255,0.92)` | `rgba(19,28,47,0.70)` |
| card edge | `rgba(28,34,48,0.10)` | `rgba(141,180,240,0.16)` |
| rule | `rgba(36,80,138,0.085)` | `rgba(141,180,240,0.10)` |
| address | `rgba(28,34,48,0.40)` | `rgba(232,236,244,0.40)` |
| text bars | `rgba(28,34,48,0.26 / 0.11)` | `rgba(232,236,244,0.30 / 0.13)` |
| rails | `--block-system`, `--block-task`, `--series-tools`, `--block-note` | same tokens, dark values |
| rewrite | `--block-rewritten` (`#DFA032`) + `--chip-rewrite-bg` wash | same |
| drop | `--chip-drop-fg` (`#A1282A`) + `--chip-drop-bg` wash | `#F2958F` / `#4A1F22` |
| append | `--chip-append-fg` (`#2C6A3B`) + `--chip-append-bg` wash | `#8FD19E` / `#1F3D27` |

If those variables are missing the script falls back to hard-coded values in
`TYPE_FALLBACK` at the top of the file. `--block-tool` is used for the dark
rail but `--series-tools` for the light one: `--block-tool` is deliberately
pale for chip backgrounds and would disappear on paper.

### Recommended settings

| | light | dark |
|---|---|---|
| `--hero-veil-color` | `rgba(251, 250, 247, 0.74)` | `rgba(13, 20, 36, 0.68)` |
| `--hero-field-opacity` | `0.55` | `1` |
| `columns` | `null` (7 at 1440px) | `null` |
| `speed` | `1` | `1` |
| `edits` | `1` | `1` |

Phones (`≤ 40rem`) automatically get three columns, a full-width wash sized
for the stacked headline (`118% 78%`, veil `0.62`), and a field at 60 %
opacity, with a dark-theme veil of `0.74`.

---

## 4. Behaviour

- **Reduced motion** — `prefers-reduced-motion: reduce` renders exactly one
  frame, advanced `stillTime` seconds into the drift, and never starts the loop.
  Pass `reducedMotion: "slow"` for a slow continuous version (30 % speed). The
  preference is watched live.
- **Hidden tab** — the loop stops on `visibilitychange` to `hidden` and resumes
  without a time jump.
- **Off-screen** — an `IntersectionObserver` stops the loop while the canvas is
  scrolled out of view.
- **Theme** — the palette is rebuilt whenever `<html data-theme>` changes or the
  OS preference changes. No reload, no layout shift.
- **No canvas 2D** — the canvas hides itself, logs one warning, and the CSS
  scrim carries the background alone.
- **Print and forced-colors** — the whole layer is `display: none`.

---

## 5. Measured cost

Headless Chromium, WebGL through SwiftShader (software), so these are a
conservative floor rather than a GPU figure:

| Viewport | Blocks | Frame rate | Main-thread cost per frame |
|---|---|---|---|
| 1440×900, light | 105–113 | 60.0 fps | 0.86–0.94 ms |
| 1440×900, dark | 105 | 60.0 fps | 0.72 ms |
| 390×844, light | 44 | 60.0 fps | 0.37 ms |

Sustained over a 3-second window after warm-up, on the preview page. Around
1 ms of a 16.7 ms budget, most of it filling rounded rectangles and drawing the
mono addresses.

---

## 6. Previewing

```bash
source code/tools/web/env.sh
cd code/native-context-editing/docs
python3 -m http.server 8414 --bind 127.0.0.1
# → http://127.0.0.1:8414/static/hero/preview.html
```

The preview bar switches the theme (writing the same `data-theme` attribute and
`localStorage` key the site toggle uses) and drops the field opacity, so both
extremes are one click apart. It also shows the module's own fps and cpu
counters. Serve it over HTTP; opening it from disk mostly works but does not
match the site's loading behaviour exactly.

---

## 7. Notes for whoever wires it up

- `hero-blocks.js` references no file at all; `hero-blocks.css` references only
  page tokens. The preview's `../tokens.css` links are the only relative paths.
- `hero-blocks.css` styles only `.hero--bg`, `.hero-bg`, and the `::after`
  scrim. If the hero markup changes, the only requirement is that the canvas
  sits inside a positioned element at least as tall as the hero.
- `attach()` is keyed off the canvas, so including the script twice still
  attaches once.
- The card radius is 4px on purpose: it matches `--radius-chip`, so the
  background uses the same geometry as the token chips in the page's figures.
