// TICKET-121: an object URL is revoked only once its media element stopped fetching, and after detaching it.
import test from "node:test";
import assert from "node:assert/strict";
import { releaseMediaUrl } from "../../web/media-url.js";

function fakeEl(networkState, readyState = 0) {
  const log = [];
  const handlers = {};
  return {
    networkState, readyState, log, handlers,
    pause: () => log.push("pause"),
    removeAttribute: (a) => log.push(`remove:${a}`),
    load: () => log.push("load"),
    addEventListener: (e, f) => { handlers[e] = f; },
    removeEventListener: (e) => { delete handlers[e]; },
  };
}

test("an idle element is detached, then the URL is revoked", () => {
  const el = fakeEl(1, 4);
  const order = [];
  releaseMediaUrl(el, "blob:a", { revoke: (u) => order.push(`revoke:${u}:${el.log.join(",")}`) });
  assert.deepEqual(order, ["revoke:blob:a:pause,remove:src,load"]);
});

test("a loading element keeps its URL until it settles", () => {
  const el = fakeEl(2, 1);
  const revoked = [];
  releaseMediaUrl(el, "blob:b", { revoke: (u) => revoked.push(u), setTimer: () => {} });
  assert.deepEqual(revoked, []);
  el.handlers.suspend();
  assert.deepEqual(revoked, ["blob:b"]);
  assert.equal(Object.keys(el.handlers).length, 0);
});

test("a loading element that never settles is released by the timeout, once", () => {
  const el = fakeEl(2, 0);
  const revoked = [];
  let timer;
  releaseMediaUrl(el, "blob:c", { revoke: (u) => revoked.push(u), setTimer: (f) => { timer = f; } });
  timer();
  timer();
  assert.deepEqual(revoked, ["blob:c"]);
});

test("no URL or no element is a safe no-op or a plain revoke", () => {
  const revoked = [];
  releaseMediaUrl(fakeEl(1), "", { revoke: (u) => revoked.push(u) });
  releaseMediaUrl(null, "blob:d", { revoke: (u) => revoked.push(u) });
  assert.deepEqual(revoked, ["blob:d"]);
});
