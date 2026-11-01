// The only module with colour literals outside theme/tokens.css. They are harness fallbacks: used where the tokens
// stylesheet is not loaded (test pages, the standalone mesh demo) so three.js still has a colour to draw with. In the
// app every value is read from the token of the same role (theme-colors.js, mesh-view.js cssColor). Do not add a colour
// here that has no token; tests/part7/theme_rules.unit.test.mjs keeps the other drawing files free of literals.

/** `--3d-*` tokens as 0xRRGGBB numbers (viewer3d.js, compare.js). */
export const FALLBACK_3D = {
  "--3d-trainer": 0x8aa4ff,
  "--3d-you": 0x3ddc97,
  "--3d-grid": 0x3a4658,
  "--3d-grid-center": 0x232c3a,
  "--3d-hot": 0xffc83d,
  hotGlow: 0xffa400, // the hot joint's emissive tone
  skyLight: 0xdfe8ff, // the viewer's hemisphere light, sky side
  groundLight: 0x1a2230, // and ground side
  keyLight: 0xffffff,
};

/** `--mesh-*` tokens as CSS colour strings (mesh-view.js). */
export const FALLBACK_COLORS = {
  "--mesh-trainer": "rgb(138, 164, 255)", // the compare's trainer colour
  "--mesh-you": "rgb(61, 220, 151)", // the compare's "you" colour
  "--mesh-fault": "rgb(255, 77, 77)",
  "--mesh-light": "rgb(255, 255, 255)",
  "--mesh-ground": "rgb(51, 68, 85)",
};
