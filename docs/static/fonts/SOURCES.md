# Font sources and licensing

Every file here is used under the **SIL Open Font License 1.1**. Full license
texts are `OFL-InstrumentSerif.txt`, `OFL-Inter.txt`, `OFL-JetBrainsMono.txt`
in this directory (identical copies sit in `nce-pv/fonts/`).

Nothing is fetched at runtime: the site resolves these from disk, which is why
it renders with the network fully off.

## Web faces — `docs/static/fonts/files/` (woff2, self-hosted)

Served through `docs/static/fonts.css`, two `unicode-range` subsets per face.
Upstream: the `@fontsource/*` npm packages, which repackage the same upstream
sources as `ofl/` in google/fonts (v5.3.0).

| File | Bytes | sha256[:16] | Upstream |
|---|---:|---|---|
| `instrument-serif-latin-400-italic.woff2` | 22,128 | `5a51946dfffa8297` | [`files/instrument-serif-latin-400-italic.woff2`](https://www.npmjs.com/package/@fontsource/instrument-serif/v/5.3.0) |
| `instrument-serif-latin-400-normal.woff2` | 21,032 | `5eb09b5ac0e28b67` | [`files/instrument-serif-latin-400-normal.woff2`](https://www.npmjs.com/package/@fontsource/instrument-serif/v/5.3.0) |
| `instrument-serif-latin-ext-400-italic.woff2` | 12,384 | `d0014821252a8a77` | [`files/instrument-serif-latin-ext-400-italic.woff2`](https://www.npmjs.com/package/@fontsource/instrument-serif/v/5.3.0) |
| `instrument-serif-latin-ext-400-normal.woff2` | 11,604 | `290e6267dd833bf5` | [`files/instrument-serif-latin-ext-400-normal.woff2`](https://www.npmjs.com/package/@fontsource/instrument-serif/v/5.3.0) |
| `inter-latin-400-normal.woff2` | 23,664 | `8909904ab6c872eb` | [`files/inter-latin-400-normal.woff2`](https://www.npmjs.com/package/@fontsource/inter/v/5.3.0) |
| `inter-latin-500-normal.woff2` | 24,272 | `f3779f1efccc4bdc` | [`files/inter-latin-500-normal.woff2`](https://www.npmjs.com/package/@fontsource/inter/v/5.3.0) |
| `inter-latin-600-normal.woff2` | 24,452 | `f9a06e79cd3a2a20` | [`files/inter-latin-600-normal.woff2`](https://www.npmjs.com/package/@fontsource/inter/v/5.3.0) |
| `inter-latin-700-normal.woff2` | 24,356 | `6f56409fd3d64bb8` | [`files/inter-latin-700-normal.woff2`](https://www.npmjs.com/package/@fontsource/inter/v/5.3.0) |
| `inter-latin-800-normal.woff2` | 24,400 | `a7d0a50f15d389ca` | [`files/inter-latin-800-normal.woff2`](https://www.npmjs.com/package/@fontsource/inter/v/5.3.0) |
| `inter-latin-ext-400-normal.woff2` | 35,000 | `6744a7f509ebc6ab` | [`files/inter-latin-ext-400-normal.woff2`](https://www.npmjs.com/package/@fontsource/inter/v/5.3.0) |
| `inter-latin-ext-500-normal.woff2` | 36,024 | `2c6fbc42d315528b` | [`files/inter-latin-ext-500-normal.woff2`](https://www.npmjs.com/package/@fontsource/inter/v/5.3.0) |
| `inter-latin-ext-600-normal.woff2` | 36,260 | `e4bdf67b0cd15ca9` | [`files/inter-latin-ext-600-normal.woff2`](https://www.npmjs.com/package/@fontsource/inter/v/5.3.0) |
| `inter-latin-ext-700-normal.woff2` | 36,244 | `143f9504f1377012` | [`files/inter-latin-ext-700-normal.woff2`](https://www.npmjs.com/package/@fontsource/inter/v/5.3.0) |
| `inter-latin-ext-800-normal.woff2` | 36,128 | `eade55593308b9e4` | [`files/inter-latin-ext-800-normal.woff2`](https://www.npmjs.com/package/@fontsource/inter/v/5.3.0) |
| `jetbrains-mono-latin-400-normal.woff2` | 21,168 | `14425ba9c695763c` | [`files/jetbrains-mono-latin-400-normal.woff2`](https://www.npmjs.com/package/@fontsource/jetbrains-mono/v/5.3.0) |
| `jetbrains-mono-latin-500-normal.woff2` | 21,832 | `cb182feeed4d798f` | [`files/jetbrains-mono-latin-500-normal.woff2`](https://www.npmjs.com/package/@fontsource/jetbrains-mono/v/5.3.0) |
| `jetbrains-mono-latin-700-normal.woff2` | 21,908 | `d0d4e818808f2a0b` | [`files/jetbrains-mono-latin-700-normal.woff2`](https://www.npmjs.com/package/@fontsource/jetbrains-mono/v/5.3.0) |
| `jetbrains-mono-latin-ext-400-normal.woff2` | 7,336 | `505dfba8ecbe77e8` | [`files/jetbrains-mono-latin-ext-400-normal.woff2`](https://www.npmjs.com/package/@fontsource/jetbrains-mono/v/5.3.0) |
| `jetbrains-mono-latin-ext-500-normal.woff2` | 7,528 | `879df9319f1cbf63` | [`files/jetbrains-mono-latin-ext-500-normal.woff2`](https://www.npmjs.com/package/@fontsource/jetbrains-mono/v/5.3.0) |
| `jetbrains-mono-latin-ext-700-normal.woff2` | 7,472 | `45a606d88f72bc0a` | [`files/jetbrains-mono-latin-ext-700-normal.woff2`](https://www.npmjs.com/package/@fontsource/jetbrains-mono/v/5.3.0) |

## Video faces — `nce-pv/fonts/` (static TTF)

The renderer needs real outline fonts, so these are static TTFs. Instrument
Serif ships static upstream; Inter and JetBrains Mono ship as variable fonts,
so the five/named instances below were produced with `fontTools.varLib`
`instantiateVariableFont` (weight pinned per file, name table and
`OS/2.usWeightClass` normalised so a plain family name matches).

| File | Bytes | sha256[:16] | Upstream |
|---|---:|---|---|
| `InstrumentSerif-Italic.ttf` | 71,592 | `08939b8bdf534afe` | [https://github.com/google/fonts/blob/main/ofl/instrumentserif/InstrumentSerif-Italic.ttf](https://github.com/google/fonts/blob/main/ofl/instrumentserif/InstrumentSerif-Italic.ttf) |
| `InstrumentSerif-Regular.ttf` | 70,012 | `498efd461f6ddfcb` | [https://github.com/google/fonts/blob/main/ofl/instrumentserif/InstrumentSerif-Regular.ttf](https://github.com/google/fonts/blob/main/ofl/instrumentserif/InstrumentSerif-Regular.ttf) |
| `Inter-Bold.ttf` | 343,028 | `4f0398e5bdfa3183` | [ofl/inter/Inter[opsz,wght].ttf](https://github.com/google/fonts/blob/main/ofl/inter/Inter%5Bopsz%2Cwght%5D.ttf), instanced |
| `Inter-ExtraBold.ttf` | 343,952 | `d21eb2b39decf1a9` | [ofl/inter/Inter[opsz,wght].ttf](https://github.com/google/fonts/blob/main/ofl/inter/Inter%5Bopsz%2Cwght%5D.ttf), instanced |
| `Inter-Italic.ttf` | 344,788 | `7e78ac3651042149` | [ofl/inter/Inter[opsz,wght].ttf](https://github.com/google/fonts/blob/main/ofl/inter/Inter%5Bopsz%2Cwght%5D.ttf), instanced |
| `Inter-Medium.ttf` | 341,948 | `1c157c1a9c71233c` | [ofl/inter/Inter[opsz,wght].ttf](https://github.com/google/fonts/blob/main/ofl/inter/Inter%5Bopsz%2Cwght%5D.ttf), instanced |
| `Inter-Regular.ttf` | 341,356 | `1e56255a56b0d94f` | [ofl/inter/Inter[opsz,wght].ttf](https://github.com/google/fonts/blob/main/ofl/inter/Inter%5Bopsz%2Cwght%5D.ttf), instanced |
| `Inter-SemiBold.ttf` | 342,640 | `26a27f08af7df522` | [ofl/inter/Inter[opsz,wght].ttf](https://github.com/google/fonts/blob/main/ofl/inter/Inter%5Bopsz%2Cwght%5D.ttf), instanced |
| `JetBrainsMono-Bold.ttf` | 115,096 | `cb12213e4a8cff29` | [ofl/jetbrainsmono/JetBrainsMono[wght].ttf](https://github.com/google/fonts/blob/main/ofl/jetbrainsmono/JetBrainsMono%5Bwght%5D.ttf), instanced |
| `JetBrainsMono-Italic.ttf` | 117,988 | `702dc040bea16047` | [ofl/jetbrainsmono/JetBrainsMono[wght].ttf](https://github.com/google/fonts/blob/main/ofl/jetbrainsmono/JetBrainsMono%5Bwght%5D.ttf), instanced |
| `JetBrainsMono-Medium.ttf` | 115,204 | `b4c7560386c86fcf` | [ofl/jetbrainsmono/JetBrainsMono[wght].ttf](https://github.com/google/fonts/blob/main/ofl/jetbrainsmono/JetBrainsMono%5Bwght%5D.ttf), instanced |
| `JetBrainsMono-Regular.ttf` | 115,180 | `e4a8e52851ccafd6` | [ofl/jetbrainsmono/JetBrainsMono[wght].ttf](https://github.com/google/fonts/blob/main/ofl/jetbrainsmono/JetBrainsMono%5Bwght%5D.ttf), instanced |

## Licenses

| Family | Copyright | License |
|---|---|---|
| Instrument Serif | The Instrument Serif Project Authors | OFL 1.1 |
| Inter | The Inter Project Authors | OFL 1.1 |
| JetBrains Mono | The JetBrains Mono Project Authors | OFL 1.1 |

- `OFL-InstrumentSerif.txt` — 4,405 bytes, sha256[:16] `129ed76189597169`
- `OFL-Inter.txt` — 4,377 bytes, sha256[:16] `5b9321a4298cfeb6`
- `OFL-JetBrainsMono.txt` — 4,399 bytes, sha256[:16] `b2fe5e8987594e9f`

