# Vendored three.js r170

The 3D replay uses three.js r170, copied unchanged from the npm package `three@0.170.0`
(`npm pack three@0.170.0`, then the files below). It is never copied from another part's repo
and never loaded from a CDN at run time. The licence is MIT (`three/LICENSE`).

| File in `three/` | Taken from the package | sha256 |
| --- | --- | --- |
| `three.module.js` | `build/three.module.js` | `ce1fa418de16a19495a9f72495580e3015d7745c296d3ce0485897f902ddedfb` |
| `OrbitControls.js` | `examples/jsm/controls/OrbitControls.js` | `80efaadea4f8a636a65fb0bd08bfef62f3d93a0bb94e2e7500f23176c5c07f4e` |
| `LICENSE` | `LICENSE` | `4c40a1ef62450b857c3b2aaf294936304cd552d965fbcd9d32d4c5bcf4ba4454` |

`three.core.js` is not in this table because release 0.170.0 does not contain it: the split into
`three.module.js` and `three.core.js` arrived in r171, and in r170 `three.module.js` is
self-contained. If the library moves to r171 or later, add `build/three.core.js` and its hash here.

`index.html` maps the bare names `three` and `three/addons/` onto these files with an import map, so
`OrbitControls.js` finds the library without any change to either file.

`tests/test_web_vendor.py` checks every hash above against the files (AC-V12). To refresh, unpack
the new package version, copy the files, and update both the table and the version named above.
