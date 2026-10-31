import test from "node:test";
import assert from "node:assert/strict";
import { measurePreview, previewCodes, updateTipState, visibleTips } from "../../web/quality-check.js";
import { PRERECORD_THRESHOLDS as T, QUALITY_TIPS } from "../../web/quality-constants.js";

export function picture(value, width = T.width, height = T.height) {
  const data = new Uint8ClampedArray(width * height * 4);
  for (let y = 0; y < height; y++) for (let x = 0; x < width; x++) {
    const i = (y * width + x) * 4;
    const v = typeof value === "function" ? value(x, y) : value;
    data[i] = data[i + 1] = data[i + 2] = v;
    data[i + 3] = 255;
  }
  return { width, height, data };
}

const inBorder = (x, y) => x < 24 || x >= 136 || y < 13 || y >= 77;

test("a good textured subject against a plain wall raises no tip", () => {
  const good = picture((x, y) => inBorder(x, y) ? 130 : 110 + ((x % 8 < 4) ? 25 : -25));
  assert.deepEqual(previewCodes(measurePreview(good, good)), []);
});

test("dark, bright and backlit pixels use the shared tip codes", () => {
  const dark = measurePreview(picture(25));
  assert.equal(dark.mean_luma, 25);
  assert.deepEqual(previewCodes(dark), ["dark"]);
  assert.deepEqual(previewCodes(measurePreview(picture(255))), ["overexposed"]);
  const backlit = measurePreview(picture((x, y) => inBorder(x, y) ? 220 : 80));
  assert.equal(backlit.border_luma - backlit.center_luma, 140);
  assert.ok(previewCodes(backlit).includes("backlit"));
});

test("smooth blurred detail is detected without treating a featureless wall as blur", () => {
  const blurred = measurePreview(picture((x, y) => 130 + 45 * Math.sin(x / 22) + 10 * Math.sin(y / 18)));
  assert.ok(blurred.sharpness < T.blurry_laplacian_variance);
  assert.ok(previewCodes(blurred).includes("blurry"));
  assert.deepEqual(previewCodes(measurePreview(picture(130))), []);
});

test("busy border and changed border produce separate, bounded numeric readings", () => {
  const noisy = picture((x, y) => inBorder(x, y) ? ((x + y) % 2 ? 210 : 40) : 130);
  const result = measurePreview(noisy, picture(130));
  assert.ok(previewCodes(result).includes("busy_background"));
  assert.ok(previewCodes(result).includes("camera_moving"));
  assert.equal(measurePreview(noisy, noisy).border_difference, 0);
  assert.ok(Object.values(result).every((value) => typeof value === "number" && Number.isFinite(value)));
});

test("center movement alone never triggers the camera-moving proxy", () => {
  const old = picture(130);
  const next = picture((x, y) => inBorder(x, y) ? 130 : 70);
  assert.equal(measurePreview(next, old).border_difference, 0);
  assert.ok(!previewCodes(measurePreview(next, old)).includes("camera_moving"));
});

test("tips need two continuously good seconds to clear and are capped at two", () => {
  let state = updateTipState({}, ["dark", "backlit", "busy_background"], 0);
  assert.deepEqual(visibleTips(state).map((tip) => tip.code), ["dark", "backlit"]);
  assert.equal(visibleTips(state)[0].text, QUALITY_TIPS.dark);
  state = updateTipState(state, [], 500);
  state = updateTipState(state, [], 2499);
  assert.equal(visibleTips(state).length, 2);
  state = updateTipState(state, [], 2500);
  assert.deepEqual(visibleTips(state), []);
  state = updateTipState({}, ["dark"], 0);
  state = updateTipState(state, [], 500);
  state = updateTipState(state, ["dark"], 2000);
  state = updateTipState(state, [], 2500);
  assert.equal(visibleTips(updateTipState(state, [], 4000)).length, 1);
});

test("measurements are deterministic and malformed or mismatched frames are safe", () => {
  const data = picture((x, y) => (x * 17 + y * 23) % 255);
  assert.deepEqual(measurePreview(data), measurePreview(data));
  assert.equal(measurePreview({ width: 1, height: 1, data: [] }), null);
  assert.equal(measurePreview(data, picture(1, 40, 30)).border_difference, 0);
  assert.deepEqual(previewCodes(null), []);
  assert.deepEqual(updateTipState({}, ["invented"], 0), {});
});
