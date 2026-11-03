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
