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
| `web/vendor/three/LICENSE` | `package/LICENSE` | `4c40a1ef62450b857c3b2aaf294936304cd552d965fbcd9d32d4c5bcf4ba4454` |

`tests/part7/test_web_static.py` checks these hashes.
