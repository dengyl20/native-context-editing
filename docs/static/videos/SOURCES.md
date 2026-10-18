# SOURCES — media shipped with the project page

Every font, image and piece of audio bundled under `docs/` is recorded here with
its licence. Nothing on the page is fetched at runtime: no CDN, no remote font,
no analytics. The page and the film work offline.

## Fonts

Fully recorded, file by file, in [`fonts/SOURCES.md`](fonts/SOURCES.md) — twenty
`.woff2` faces with byte counts, content hashes and upstream, covering:

| Family | Use | Licence |
|---|---|---|
| Instrument Serif | display type | OFL 1.1 |
| Inter | body and interface | OFL 1.1 |
| JetBrains Mono | token chips and code | OFL 1.1 |

Each licence's full text ships in `fonts/OFL-*.txt`. The OFL permits
redistribution, including bundled with a web page.

## The film

`nce.mp4` is the project film: 130 seconds, 1920×1080 at 30 fps, rendered at 2×
and downsampled, encoded with H.264 at CRF 14. Every frame is generated from
code — the block fields, the light, the typography and the cuts — by a
deterministic renderer driven by the absolute time of the frame, so the film can
be re-rendered frame-for-frame.

Its soundtrack is built in two layers. The bed is Alexander Nakarada's
**"Novus Initium"**, released in the FreePD collection *Free Public Domain
Music* (Internet Archive item `freepd`), which dedicates its catalogue to the
public domain; it is used here under that dedication, with no attribution
required. The bed is cut on a bar line and shaped by a level curve — the arc of
the film — rather than re-composed.

On top of it sits a layer of designed accents — low hits, bright impacts,
bells tuned to the harmony underneath, air, a riser, and one tick per typed
token. Every accent is placed on a picture cut: the accents carry the sync,
the bed carries the sound. The bed is cut so that the track's own climax falls
under the results section rather than after the film ends, and its level is
shaped so the first half stays under the words while the second half opens out.

Measured with ffmpeg's BS.1770-4 implementation, the mix runs 130.0 s at
48 kHz stereo, −19.5 LUFS integrated, −1.2 dBTP true peak, with a 14 dB
rise from the opening to the results.

The build script and the cue table are `nce-pv/music/build_v5.py`; earlier
scores and their notes remain in `nce-pv/music/` as record.

The poster frame, `nce-poster.jpg`, is drawn by the same design system as the
film. Everything in it is generated procedurally; the only third-party asset is
the project's own LongCat wordmark.

## Images and marks

| File | Origin | Licence |
|---|---|---|
| `assets/longcat-logo.*`, `docs/assets/longcat-logo.*` | the authors' own project mark | © the authors |
| `docs/static/img/favicon.svg` | the project mark, reduced to its glyph | © the authors |
| `docs/static/img/teaser.svg`, `teaser.png` | drawn for this release | © the authors |

The LongCat wordmark is the project's own mark, shipped here so the page can
present the work; it is not third-party clip art. The favicon and the teaser are
derived from the same asset set. No other third-party imagery is used — the
icon glyphs in the page are inline SVG paths authored for it.

## Icons

The operator glyphs (drop, rewrite, append) are inline SVG paths drawn for this
release, in the style of the Lucide icon set (ISC). No icon file is bundled.

## nce-poster-play.jpg

Derived from `nce-poster.jpg`: the same frame with a play button composited
over it, used as the clickable thumbnail in `README.md`. It is generated, not
photographed: the overlay is an HTML page rendered headless at 1920x1080 and
saved as JPEG (quality 88), so the type in it is the site's own Inter.
