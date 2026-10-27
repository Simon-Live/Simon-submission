# Vendored libraries

Served from this folder so the app makes no request outside its own origin.

| File | Source | Version | Licence | sha256 |
|---|---|---|---|---|
| `three/three.module.js` | npm `three`, `build/three.module.js` | 0.186.1 | MIT (`three/LICENSE`) | `9052042d676cb0fdc1ddfefe193053f34b7ac0513a616fdac4535d49987812ea` |
| `three/three.core.js` | npm `three`, `build/three.core.js` (imported by `three.module.js`) | 0.186.1 | MIT | `9edde002b066a9a05676a6127f67735b62baf399bdea529f2f7e31657da769e6` |
| `three/OrbitControls.js` | npm `three`, `examples/jsm/controls/OrbitControls.js` | 0.186.1 | MIT | `3d79d07ecb686b4e5d93232eedab255331c1beef711e13164eaa1f68655a5f2b` |
| `three/LICENSE` | npm `three`, `LICENSE` | 0.186.1 | | `8b378ebe60e2fe500158cb0ac71cb5e8b7d92953c2abcc63a0eb90499653b5bc` |

`OrbitControls.js` imports from the bare name `three`, so the page declares an import map:

```html
<script type="importmap">{"imports": {"three": "./vendor/three/three.module.js"}}</script>
```

Update: `npm pack three@<version>`, copy the four files, refresh this table.
