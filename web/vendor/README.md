# Vendored browser dependencies

`three@0.170.0` is vendored unmodified from the npm registry tarball (never from another part's repo). `web/index.html` maps the bare specifiers `three` and `three/addons/` to these files with an import map, so `OrbitControls.js` resolves `three` without a build step.

| Field | Value |
|---|---|
| Package | `three` |
| Version | `0.170.0` |
| Tarball URL | `https://registry.npmjs.org/three/-/three-0.170.0.tgz` |
| Tarball SHA-1 | `6087f97aab79e9e9312f9c89fcef6808642dfbb7` |
| Tarball SHA-256 | `4a608a355dcaba72e0e5383cdc814303f5b6060b43c238cdf6932dceb699238d` |
| Licence | MIT (`web/vendor/three/LICENSE`) |

## Files

| Path | Source path in tarball | SHA-256 |
|---|---|---|
| `web/vendor/three/three.module.min.js` | `package/build/three.module.min.js` | `08fd7545d13d2c7fb65ab691530a802dafefd638596501854f267d0fb13c39e7` |
| `web/vendor/three/examples/jsm/controls/OrbitControls.js` | `package/examples/jsm/controls/OrbitControls.js` | `80efaadea4f8a636a65fb0bd08bfef62f3d93a0bb94e2e7500f23176c5c07f4e` |
| `web/vendor/three/examples/jsm/loaders/GLTFLoader.js` | `package/examples/jsm/loaders/GLTFLoader.js` | `45139faddd5aaf48ed2d62203d976e5cbd703db1a592de40527f9f6cf58abd44` |
| `web/vendor/three/examples/jsm/utils/BufferGeometryUtils.js` | `package/examples/jsm/utils/BufferGeometryUtils.js` | `c25b7930e570e9ec56173cd3b866ec8d2e10016630db3937efb439daf1cedbf6` |
| `web/vendor/three/examples/jsm/utils/SkeletonUtils.js` | `package/examples/jsm/utils/SkeletonUtils.js` | `ee412be1aa05f3051c2bda8ea89612c1ba70c5c87de62b56040282120d5eb991` |
| `web/vendor/three/LICENSE` | `package/LICENSE` | `4c40a1ef62450b857c3b2aaf294936304cd552d965fbcd9d32d4c5bcf4ba4454` |

`tests/part7/test_web_static.py` checks these hashes.

The three loader and utility files (`GLTFLoader.js`, `BufferGeometryUtils.js`, `SkeletonUtils.js`) load rigged character models (docs/specs/vendor-addons.md). They are the same MIT package, unmodified.

## Mermaid

`mermaid@11.17.2` is vendored unmodified from the npm registry tarball for the in-app architecture page, which is the
only page that loads it. Version 12.2.0 was not used: its single-file bundle, `dist/mermaid.min.js`, includes elkjs,
which is under the Eclipse Public License 2.0. The 11.17.2 bundle has no elkjs code.

| Field | Value |
|---|---|
| Package | `mermaid` |
| Version | `11.17.2` |
| Tarball URL | `https://registry.npmjs.org/mermaid/-/mermaid-11.17.2.tgz` |
| Tarball SHA-1 | `e3caf3717582c0e44e5d04cff043e025caec7cba` |
| Tarball SHA-256 | `6ad2f42c3fc26bbf9e45cbb6d11898972573ea52b33a5f4ff51952899f950ffd` |
| Licence | MIT (`web/vendor/mermaid/LICENSE`); bundled dependencies in `THIRD_PARTY_NOTICES.md` |

| Path | Source path in tarball | SHA-256 |
|---|---|---|
| `web/vendor/mermaid/mermaid.min.js` | `package/dist/mermaid.min.js` | `581ed7d74bd9048d0e3a91363927d72ef22942d7722546b27f7cc29e35390eb8` |
| `web/vendor/mermaid/LICENSE` | `package/LICENSE` | `ec9fb67dcb25eccc416ed56e1aab819222c805a2a4bfe4cb19e7556bf2ffde80` |

`mermaid.min.js` is a classic script that sets `globalThis.mermaid`; it is not an ES module.

## Inter (LEG-H2)

`@fontsource/inter@5.3.0` is vendored unmodified from the npm registry tarball: the latin and latin-ext `.woff2` files
of weights 400 to 800 and the licence. `web/theme/fonts.css` declares them; nothing loads from Google Fonts.

| Field | Value |
|---|---|
| Package | `@fontsource/inter` |
| Version | `5.3.0` |
| Tarball URL | `https://registry.npmjs.org/@fontsource/inter/-/inter-5.3.0.tgz` |
| Tarball SHA-1 | `866278dc2357659f8be1755c8b67f29d3697b440` |
| Tarball SHA-256 | `02034af8d41dcc67ac8eab88f642e129bb8a2e8922abf30229c32725f54d8fd6` |
| Licence | SIL Open Font License 1.1 (`web/vendor/inter/LICENSE`) |

| Path | Source path in tarball | SHA-256 |
|---|---|---|
| `web/vendor/inter/LICENSE` | `package/LICENSE` | `3b0a5fca3d17942cde889069889dedbbbd075e9b599968c82a95f4d944e9b345` |
| `web/vendor/inter/inter-latin-400-normal.woff2` | `package/files/inter-latin-400-normal.woff2` | `8909904ab6c872eb994093482a88a28eca2cd95912d7b6fecd72103b0dc07edc` |
| `web/vendor/inter/inter-latin-500-normal.woff2` | `package/files/inter-latin-500-normal.woff2` | `f3779f1efccc4bdcdf9c0a02ab95bf6bd092ed09c48c08cedc725889edd1d19f` |
| `web/vendor/inter/inter-latin-600-normal.woff2` | `package/files/inter-latin-600-normal.woff2` | `f9a06e79cd3a2a20951c0f0e28f66dd0e6d3fda73911d640a2125c8fcb78f21a` |
| `web/vendor/inter/inter-latin-700-normal.woff2` | `package/files/inter-latin-700-normal.woff2` | `6f56409fd3d64bb85f7d070bce20749db2d66b6d63cec586cc22d1c761be2491` |
| `web/vendor/inter/inter-latin-800-normal.woff2` | `package/files/inter-latin-800-normal.woff2` | `a7d0a50f15d389cad679238466bdb5fc9787aa0715719064ce25abaff042820d` |
| `web/vendor/inter/inter-latin-ext-400-normal.woff2` | `package/files/inter-latin-ext-400-normal.woff2` | `6744a7f509ebc6ab220a6cd4ea77e898adf014f03d88dcda5d45d8a9feefb4e9` |
| `web/vendor/inter/inter-latin-ext-500-normal.woff2` | `package/files/inter-latin-ext-500-normal.woff2` | `2c6fbc42d315528beb06c1096df45487bf4186c4b78b8111d12c9c951f8acca2` |
| `web/vendor/inter/inter-latin-ext-600-normal.woff2` | `package/files/inter-latin-ext-600-normal.woff2` | `e4bdf67b0cd15ca9e184509275be95db942195d3cc2b17f6a0452f2adf75d0bf` |
| `web/vendor/inter/inter-latin-ext-700-normal.woff2` | `package/files/inter-latin-ext-700-normal.woff2` | `143f9504f1377012aa3e39c90c4354ef429cb0494b9ac0e1437f1a81e5412236` |
| `web/vendor/inter/inter-latin-ext-800-normal.woff2` | `package/files/inter-latin-ext-800-normal.woff2` | `eade55593308b9e4916dd7f47826929ce3e40cad85a2b338d56e5fd1e7bf8e5e` |

## MediaPipe (LIC-H5)

`@mediapipe/tasks-vision@0.10.14` is vendored unmodified from the npm registry tarball for Live check
(`web/live-check.js`), with the pose landmarker model from Google's model bucket. Before this, Live check loaded both
from jsDelivr and Google Cloud Storage with no integrity check. The bundle's `sourceMappingURL` names a `.map` file
that is not vendored; only developer tools ask for it.

| Field | Value |
|---|---|
| Package | `@mediapipe/tasks-vision` |
| Version | `0.10.14` |
| Tarball URL | `https://registry.npmjs.org/@mediapipe/tasks-vision/-/tasks-vision-0.10.14.tgz` |
| Tarball SHA-1 | `16c5ddc513408f2a416ccc6ce8ccc797ee02da3b` |
| Tarball SHA-256 | `3122ba7a70d414ffbb3a1bd194c370594a1bf1c90e467c375a5b8bd25be2c004` |
| Licence | Apache-2.0 (`license` in the package's `package.json`; no LICENSE file in the package) |
| Model URL | `https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_lite/float16/1/pose_landmarker_lite.task` |
| Model licence | Apache-2.0 (model card "BlazePose GHUM 3D", read 2026-11-02) |

| Path | Source | SHA-256 |
|---|---|---|
| `web/vendor/mediapipe/vision_bundle.mjs` | `package/vision_bundle.mjs` | `e77f281f9619150d937023c355bae170e9120e3b9e43f1e23a2a7bee07197669` |
| `web/vendor/mediapipe/wasm/vision_wasm_internal.js` | `package/wasm/vision_wasm_internal.js` | `9440cf0cc0cea21800e31581ec32aeedcc5fbf9df4509796bbc7d3f99e52ab9c` |
| `web/vendor/mediapipe/wasm/vision_wasm_internal.wasm` | `package/wasm/vision_wasm_internal.wasm` | `f82a8e6c05e08a44cc9f9e7ec5f845935bcbb1b1500ebe8c2f4812fb4e2917dc` |
| `web/vendor/mediapipe/wasm/vision_wasm_nosimd_internal.js` | `package/wasm/vision_wasm_nosimd_internal.js` | `abe9b6fbeaf86fcb53a5edce3926c82ccb0619e18fed4d9d9ce561ee7f55e054` |
| `web/vendor/mediapipe/wasm/vision_wasm_nosimd_internal.wasm` | `package/wasm/vision_wasm_nosimd_internal.wasm` | `38b61feab2fd7934e05cbe9f68baa308978a5e3b7f85c1913bb8ae89b8ef8b97` |
| `web/vendor/mediapipe/models/pose_landmarker_lite.task` | the model URL above | `59929e1d1ee95287735ddd833b19cf4ac46d29bc7afddbbf6753c459690d574a` |

`tests/part7/test_web_static.py` checks the package file hashes and `tests/part7/test_prod_policy.py` the model hash.
