import test from "node:test";
import assert from "node:assert/strict";
import { angle, compareAngles, cueFor, outOfView, liveJoints, animationJoints, MP } from "../../web/live-check.js";
test("angle: straight 180, right angle 90", () => {
  assert.equal(Math.round(angle({x:0,y:1,z:0},{x:0,y:0,z:0},{x:0,y:-1,z:0})), 180);
  assert.equal(Math.round(angle({x:1,y:0,z:0},{x:0,y:0,z:0},{x:0,y:1,z:0})), 90);
});
const body = (kneeBend) => ({ left_hip:{x:0.1,y:0,z:0,v:1}, left_knee:{x:0.1,y:-0.45,z:0,v:1}, left_ankle:{x:0.1,y:-0.9,z:kneeBend,v:1},
  right_hip:{x:-0.1,y:0,z:0,v:1}, right_knee:{x:-0.1,y:-0.45,z:0,v:1}, right_ankle:{x:-0.1,y:-0.9,z:0,v:1} });
test("a knee bent much more than the trainer's is flagged, mirrored sides swap", () => {
  const live = body(-0.45), ref = body(0);
  const miss = compareAngles(live, ref, false);
  assert.equal(miss.length, 1); assert.equal(miss[0].label, "left knee"); assert.ok(miss[0].diff < -25);
  assert.equal(cueFor(miss[0]), "Straighten your left knee");
  assert.equal(compareAngles(live, body(0), true).at(0).label, "left knee"); // mirrored: compared with the trainer's right knee (straight)
});
test("out of view names what is missing", () => {
  const pts = Array.from({length:33}, () => ({x:0.5,y:0.5,visibility:1}));
  assert.equal(outOfView(pts), "");
  pts[MP.left_ankle] = {x:0.5,y:1.05,visibility:0.2};
  assert.match(outOfView(pts), /feet is out of view/);
  assert.equal(outOfView([]), "No one in view");
});
test("live joints flip y up; animation picks the frame at t", () => {
  const w = Array.from({length:33}, (_, i) => ({x:i, y:2, z:0, visibility:1}));
  assert.equal(liveJoints(w).left_knee.y, -2);
  const anim = { fps: 30, frames: [0,1,2].map(i => ({ people: [{ joints: { nose: {x:i,y:0,z:0} } }] })) };
  assert.equal(animationJoints(anim, 1/30).nose.x, 1);
  assert.equal(animationJoints(anim, 9).nose.x, 2);
  const v1 = { fps: 30, frames: [{ joints: { nose: [0.1, 0.6, 0.1] } }] };
  assert.deepEqual(animationJoints(v1, 0).nose, { x: 0.1, y: 0.6, z: 0.1 });
});
