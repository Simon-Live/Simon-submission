// Follow capture layout by viewport (docs/specs/follow-side-by-side.md, TICKET-291 AC-2): side by side on every real
// screen, stacked only when a portrait column would keep under 40% of the width; the boxes always fit under the header.
//   node --test tests/part7/follow-layout.unit.test.mjs
import test from "node:test";
import assert from "node:assert/strict";
import { followLayout, MIN_SHARE, MARGIN } from "../../web/model/follow-layout.js";

// rowWidth is about the content column the app gives at each size; header 94 px, the bar with
// the test-server banner
const at = (width, height, rowWidth, extra = {}) => followLayout({ width, height, rowWidth, headerH: 94, gap: 12, ...extra });

test("desktop, laptop and tablet: side by side, wide boxes, height from the column", () => {
  for (const [w, h, row] of [[1728, 925, 1006], [1280, 720, 928], [1024, 768, 928]]) {
    const out = at(w, h, row);
    assert.equal(out.layout, "side", `${w}x${h}`);
    assert.ok(out.aspect > 1, `${w}x${h}: a 4:3 box`);
    assert.equal(out.boxH, Math.floor(Math.min((row - 12) / 2 / (4 / 3), h - 94 - MARGIN)));
    assert.ok(out.boxH <= h - 94 - MARGIN, `${w}x${h}: fits under the header`);
  }
});

test("phone landscape: side by side, the height capped by the screen, not the column", () => {
  const out = at(844, 390, 812);
  assert.equal(out.layout, "side");
  assert.equal(out.boxH, 390 - 94 - MARGIN);
  assert.ok(out.boxH < (812 - 12) / 2 / (4 / 3), "the cap is what binds");
});

test("phone portrait: two tall columns while each keeps 40% of the width", () => {
  for (const [w, h, row] of [[390, 844, 358], [412, 915, 380], [360, 780, 328], [320, 568, 288]]) {
    const out = at(w, h, row);
    assert.equal(out.layout, "side", `${w}x${h}`);
    assert.ok((row - 12) / 2 / w >= MIN_SHARE, `${w}x${h}: each column over 40%`);
    assert.ok(out.aspect < 1, `${w}x${h}: a 3:4 box`);
    assert.equal(out.boxH, Math.floor(Math.min((row - 12) / 2 / (3 / 4), h - 94 - MARGIN)));
  }
});

test("a portrait screen too narrow for two usable columns stacks, each box in half the room", () => {
  const out = at(180, 640, 148, { between: 120 });
  assert.equal(out.layout, "stack");
  assert.equal(out.boxH, Math.floor(Math.min(148 / (4 / 3), (640 - 94 - MARGIN - 12 - 120) / 2)));
  // negative: the choice turns exactly at the 40% line
  assert.equal(followLayout({ width: 300, height: 600, rowWidth: 252, gap: 12 }).layout, "side"); // 120 / 300 = 0.4
  assert.equal(followLayout({ width: 300, height: 600, rowWidth: 250, gap: 12 }).layout, "stack");
});

test("a row with no width yet never claims side by side, and a box never goes under the floor", () => {
  assert.equal(followLayout({ width: 800, height: 600, rowWidth: 0 }).layout, "stack");
  assert.ok(followLayout({ width: 900, height: 100, rowWidth: 860, headerH: 94 }).boxH >= 80);
});
