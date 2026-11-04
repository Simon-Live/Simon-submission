# Art direction and asset sources

Records the visual direction as the stylesheets and pages implement it, and the source and licence of every image, icon,
font, video, mesh and model that Simon ships. Read from `web/` at `b2df01fc` (lane `phf-records`). Where the code and
this page differ, the code is right. A source, author or licence that no file in the repository states is written
UNKNOWN; none was filled in from memory.

## Direction as implemented

One dark theme, no light mode (`color-scheme: dark`, `web/theme/tokens.css`). Every colour, face and size is a token in
that one file; the other stylesheets read the names (`theme/tokens.css` header comment).

| Part | What the code does |
|---|---|
| Palette | Near-black `#0a0a0a`, greys `#141414`, `#1c1c1c`, `#262626`, chalk white `#f4f4ef`. Lime `#c6f35a` is the only pop colour: primary buttons, the score, good states, the follower body. Pink `#ff2d95` is the only other colour: attention and faults, the header divider, the back layer. Amber `#ffc83d` appears only on the test-server banner. |
| Contrast fixes | Muted text is `#b4b4ac`, not the palette grey, after a 3.5:1 reading over the chalk and dot cards at 390 px. Warn and fault text on cards use lighter pinks (`#ff4fa6`, `#ff8fc4`) because the brand pink alone measured under 4.5:1 (comments in `tokens.css`, a11y go-live R18 and N4). |
| Type | Inter (sans) for all interface text, served from `web/vendor/inter/`; Sniglet Regular, the logo's face, for the grade letter, the score and the score pops (`--font-display`); the mono stack names Geist Mono, then SF Mono, then the system monospace. No Geist Mono file ships, so the system face shows. Sizes run 12, 13, 15, 22, 32, 64 px. |
| Back layer | Two chalk-powder textures (pink on black, screen-blended so the black drops out) at the top right and left centre, soft pink smoke gradients over them, pink halftone dots fading out of the smoke and lime halftone dots in two corners (`theme/base.css`, `body::before`, `body::after`). Fixed behind everything, never hit by a tap, hidden under `prefers-reduced-transparency`. |
| Cards | Outer cards carry a faint white halftone that fades into the grey toward the bottom right; inner cards are smooth with a soft sheen, so dots never sit on dots (`--card-fill`, `--card-fill-raised`). |
| Shape and space | Radii 10, 12, 14 px and pill; spacing 4, 8, 12, 16, 24 px; tap target 44 px, button height 48 px. The content column is 60% of the screen and never under 960 px on a wide one. |
| Header | Glass bar with a 2 px pink divider. The brand mark hangs below the bar. Exercise and Dance switch in the middle, a lime Record pill on the right. Under 480 px the row wraps: brand, switch and links stay on one line when they fit. |
| Mark | A line drawing of a dog holding a sign that says "simon": the full mark on the splash and landing, the head alone in the header and favicon (`web/views/logo.js`, `web/favicon.svg`). Outline in the accent, the dog in the chalk fill, the word in black on lime. |
| Landing | One line of copy, a 9:16 muted looping clip of a real result with the faults marked, one lime "Try it" link, and a pause button (`landing.html`, `theme/landing.css`). |
| 3D and charts | Trainer body white, your body lime, fault pink, ground greys (`--mesh-*`, `--3d-*`). The heat ramp is five cividis stops, chosen to stay apart for common colour blindness and to rise in lightness, so it reads in greyscale (`--palette-heat-0` to `-4`). |
| Loading | A trail of paw prints cut from one mask (`--paw-mask`), one footstep every 260 ms. |
| Motion | Transitions are 0.12 to 0.3 s. In the stylesheets under `web/` the listed transitions are on `transform` and `opacity` (progress fill, splash fade, lifts) or on `background` and `border-color` for buttons and cards (0.12 to 0.15 s). Ten stylesheets carry a `prefers-reduced-motion` block, and `impeccable detect` reports no `layout-transition` (`docs/prod-verify/records-h12-2.md`). The landing clip plays unless reduced motion is asked for and has a pause button (WCAG 2.2.2). |

How it was checked in a browser: 65 `tests/part7/*.browser.mjs` drive the app in Chromium; the written review of
2026-10-31 used 412x915 and 1280x800 (`docs/ui-review-2026-10-31.md`); the follow screen was captured at 320, 390,
844x390, 1024, 1280 and 1728 px wide (`demos/screenshots/follow-side-291/`). This page does not repeat those runs.

Known deviations, kept on purpose: `impeccable detect` flags Inter as an overused face (10 findings in
`theme/fonts.css`) and four one-sided accent borders (`theme/footer.css`, `theme/narration.css`, `skin/any-body.css`,
`skin/skin.css`). Inter is the face named in the brand design of 2026-10-31 (`tokens.css` header); the borders are listed in `docs/prod-verify/records-h12-2.md`.

## Inventory of what ships

Paths are relative to the repository root. The hash column is the first 12 hex digits of the file's SHA-256. "Stated
in" names the file that carries the claim; UNKNOWN means no file in the repository states it.

### Brand images and icons

| File | What it is | Source | Licence | Stated in |
|---|---|---|---|---|
| `web/favicon.svg` (`a6181565bda0`) | The dog's head on a rounded black square, SVG | Drawn from the logo below; commit `9ee3fa01`, 2026-11-01 | Owner's own mark; no licence text. Author UNKNOWN | commit message `9ee3fa01` |
| `web/icons/icon-16.png`, `icon-32.png`, `icon-48.png`, `icon-180.png`, `icon-192.png`, `icon-512.png` (`741ba48963de`, `0015a8377bc0`, `eba7a1016f61`, `50576a3acf3f`, `d6b2d70eacb1`, `167e474b8f96`) | Favicon and home-screen icons at six sizes | Rendered from the same mark | As above | commit `9ee3fa01` |
| `web/icons/og-image.png` (`360e8a3789ec`) | 1200x630 share image | Made from the same mark; the tool and any photo in it UNKNOWN | UNKNOWN | commit `9ee3fa01`; `publish/overrides.json` lists it |
| Mark paths inline in `web/views/logo.js` | The dog and sign, traced to vector | "from the Affinity export", file name `simon logo.svg` (comment in `logo.js`); commit `d398a335` calls the first version "Logo B (the team's golden over the simon sign)" | Owner's own mark; no licence text. Who drew the dog: UNKNOWN | `logo.js` header comment; commits `d398a335`, `9ee3fa01` |
| `--paw-mask`, `--icon-video` in `web/theme/tokens.css` | A paw print and a video-camera glyph as inline SVG shapes (a few polygons, a rect and a path) | Written in the stylesheet; no icon library is named anywhere in `web/`. Origin UNKNOWN | UNKNOWN | `tokens.css` lines for both names |

### Backdrop textures

| File | What it is | Source | Licence | Stated in |
|---|---|---|---|---|
| `web/theme/img/powder-a.jpg` (`08a018132698`, 71,759 bytes), `web/theme/img/powder-b.jpg` (`1a5b69557d93`, 68,679 bytes) | Pink chalk powder on black, the back layer | "Two generated textures (pink chalk powder on black; Muse Image, darkened so they recede)", commit `55de3acc`, 2026-11-01. Which service and terms applied: UNKNOWN | UNKNOWN. The Meta Model API terms (register LIC-H3) are the nearest unread item | commit `55de3acc`; `web/theme/tokens.css` comment |

### Media

| File | What it is | Source | Licence | Stated in |
|---|---|---|---|---|
| `web/media/landing-loop.mp4` (`3972517106cd`, 162,206 bytes), `web/media/landing-poster.jpg` (`1be30175cc0d`, 27,349 bytes) | 8 s, 360x640 loop and its poster on the landing page | Export frames of Simon job `5277380db1e1` (a follow, body squat, a real person's take) | The operator recorded a footage release for this person on 2026-11-01. The release document itself is not in the repository: UNKNOWN beyond that line | `docs/specs/landing.md` "Media"; `docs/submission.md` "Clearances" |

### Fonts

| File | What it is | Source | Licence | Stated in |
|---|---|---|---|---|
| `web/vendor/inter/inter-latin-{400,500,600,700,800}-normal.woff2`, `inter-latin-ext-{400,500,600,700,800}-normal.woff2` (10 files) | Inter 4, latin and latin-ext | npm `@fontsource/inter` 5.3.0, tarball SHA-256 `02034af8...8fd6`; per-file hashes in `web/vendor/README.md` | SIL Open Font License 1.1, copyright 2016 The Inter Project Authors; text in `web/vendor/inter/LICENSE` | `web/vendor/README.md`; `THIRD_PARTY_NOTICES.md` |
| `web/theme/fonts/sniglet-regular.woff2` (`ebc2d6698b62`, 14,496 bytes) | Sniglet Regular, basic Latin only | Sniglet; the subset's build record is not in the repository (commit `fb7f1bca` says "basic Latin, 14 KB, OFL"). Download URL UNKNOWN | SIL Open Font License 1.1; text and copyright holders (Haley Fiege, Brenda Gallo, Pablo Impallari) in `web/theme/fonts/Sniglet-OFL.txt` (`89418a3c7b57`) | `theme/base.css` comment; commit `fb7f1bca` |
| Geist Mono | Named first in `--font-mono` | Not shipped. No request leaves the site for it; the system monospace face shows | Not applicable | `tokens.css` |

### Meshes and 3D models

| File | What it is | Source | Licence | Stated in |
|---|---|---|---|---|
| `web/mesh-demo/trainer/mesh3d.bin` (`f596159c703a`), `mesh3d.json` | Decimated MHR mesh, 61 frames at 10 fps, 2427 vertices | SAM 3D Body run by Simon Part 2 on the first 6 s of Pexels clip 6326808, 2026-10-31 | SAM License for SAM 3D Body output, plus Apache-2.0 for the MHR body model; texts in `web/mesh-demo/LICENSE-SAM.txt` and `LICENSE-MHR-Apache-2.0.txt`. Clip: Pexels License, author not stated on the page | `web/mesh-demo/SOURCE.md`; `THIRD_PARTY_NOTICES.md` |
| `web/mesh-demo/follower/mesh3d.bin` (`ff5b8cf26063`), `mesh3d.json` | The same for the follower, 2431 vertices | Same run on Pexels clip 8026937 | Same | Same |
| `web/mesh-demo/faults.json` | Faults Part 5 measured on the follower clip | Simon check run `20261031T182615Z` | Simon's own data | `SOURCE.md` |
| `web/models/library/ual1-mannequin/model.glb` (`c6108517c7b8`, 614,264 bytes) | Mannequin | Universal Animation Library by Quaternius, animation clips removed | CC0 1.0; note in `LICENSE.txt` beside it | `library.json`; `LICENSE.txt` |
| `web/models/library/ual2-mannequin-f/model.glb` (`2ee6cc3fe888`, 1,442,824 bytes) | Mannequin (female) | Universal Animation Library 2 by Quaternius, animation clips removed | CC0 1.0 | `library.json`; `LICENSE.txt` |
| `web/models/library/rigged-figure/model.glb` (`a9d14f3d379a`, 27,680 bytes) | Rigged figure | Khronos glTF-Sample-Assets, `Models/RiggedFigure`, (c) 2017 Cesium; animation clip removed | CC BY 4.0, attribution required | `library.json`; `LICENSE.txt` |
| Per-user avatars from `part2 avatar` | Not shipped; made for the owner on request | MHR-derived geometry | SAM License plus MHR Apache-2.0 travel with any redistribution; kept private to the owner | `modules/part-2/README.md` "Models and licences" |

### Vendored runtime files

| File | What it is | Source | Licence | Stated in |
|---|---|---|---|---|
| `web/vendor/mediapipe/models/pose_landmarker_lite.task` (`59929e1d1ee9`, 5,777,746 bytes) | BlazePose GHUM 3D pose model, float16 v1 | Google model bucket (URL in `web/vendor/README.md`) | Apache-2.0 per its model card, read 2026-11-02 | `web/vendor/README.md`; `THIRD_PARTY_NOTICES.md` |
| `web/vendor/mediapipe/wasm/vision_wasm_internal.wasm` (`f82a8e6c05e0`), `vision_wasm_nosimd_internal.wasm` (`38b61feab2fd`), the two `.js` loaders, `vision_bundle.mjs` | MediaPipe Tasks Vision 0.10.14 | npm `@mediapipe/tasks-vision` | Apache-2.0 (package metadata; the package ships no LICENSE file) | `web/vendor/README.md` |
| `web/vendor/three/**` | three.js 0.170.0 | npm tarball | MIT, `web/vendor/three/LICENSE` | `web/vendor/README.md` |
| `web/vendor/mermaid/mermaid.min.js` | Mermaid 11.17.2, architecture page only | npm tarball | MIT plus bundled third-party licences listed in `THIRD_PARTY_NOTICES.md` | `web/vendor/README.md` |

### In the release tree but not served

| Path | What it is | Source and licence |
|---|---|---|
| `fixtures/input/*.json`, `fixtures/input/quality/*.json` | Analysis and skeleton data for tests. No image, font or mesh | Test data; origin per file UNKNOWN |
| `demos/**/*.png` (70 files) and the JSON beside them | Screenshots of the app taken during review | Simon's own captures. The frames inside them come from the clips in `videos/manifest.json` or from job footage; per-file origin UNKNOWN |
| `videos/manifest.json` | URL, hash and licence of four Pexels test clips; the clips are git-ignored and not redistributed | Pexels License; authors "not stated on the page" |
| `.claude/skills/ui-styling/canvas-fonts/*.ttf` (agent tooling, 81 tracked files with their `*-OFL.txt`) | Fonts for an agent skill, never linked from `web/` | Each family has an `-OFL.txt` beside it; not reviewed one by one here |

## Open items

- UNKNOWN: who drew the logo, the licence of the og-image, the origin of the paw and camera glyphs, the Sniglet
  download source, and the content of the footage release for job `5277380db1e1`.
- The Muse Image terms, which decide whether the two powder textures are cleared for commercial use (nearest register item LIC-H3).
- No row here replaces a lawyer's reading; it records what the repository says.
