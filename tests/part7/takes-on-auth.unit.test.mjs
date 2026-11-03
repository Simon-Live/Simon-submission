// TICKET-327 B1: sign-out and Delete my data clear the takes this browser remembered (web/auth.js mountMe).   node --test tests/part7/
import test from "node:test";
import assert from "node:assert/strict";
import { El, installDom, find } from "./fake-dom.mjs";

const { store } = installDom();
const cls = (el) => (el.attrs.class || "").split(/\s+/).filter(Boolean);
Object.defineProperty(El.prototype, "classList", { get() { return { add: (c) => { this.attrs.class = [...new Set([...cls(this), c])].join(" "); } }; } });
Object.defineProperty(El.prototype, "hidden", { get() { return "hidden" in this.attrs; }, set(v) { if (v) this.attrs.hidden = ""; else delete this.attrs.hidden; } });
globalThis.localStorage.removeItem = (k) => store.delete(k);
globalThis.window = new EventTarget();
globalThis.location = { hash: "#/me" };

const ANSWERS = {
  "api/auth/me": { available: true, signed_in: true, email: "a@b.co", user_id: "u1", retention: { opted_in: false } },
  "api/me/takes": { takes: [] },
  "api/auth/signout": {},
  "api/me/delete": { deleted: true, takes_removed: 0, entries_unlinked: 0 },
};
globalThis.fetch = async (url) => new Response(JSON.stringify(ANSWERS[String(url)] ?? {}), { status: ANSWERS[String(url)] ? 200 : 404, headers: { "content-type": "application/json" } });

const A = await import("../../web/auth.js");
const M = await import("../../web/model/takes-on.js");
const settle = async () => { for (let i = 0; i < 20; i += 1) await new Promise((r) => setImmediate(r)); };

async function mounted() {
  M.rememberTake("aaaaaaaaaaa1", "squat", "Squat");
  assert.equal(M.deviceTakes().length, 1);
  const el = new El("div");
  A.mountMe(el);
  await settle();
  return el;
}

test("sign-out removes simon.deviceTakes", async () => {
  const el = await mounted();
  find(el, "me-signout").dispatchEvent(new Event("click"));
  await settle();
  assert.equal(globalThis.localStorage.getItem(M.DEVICE_KEY), null);
  assert.equal(location.hash, "#/");
});

test("Delete my data removes simon.deviceTakes", async () => {
  const el = await mounted();
  find(el, "me-delete").dispatchEvent(new Event("click"));
  find(el, "me-delete-confirm").dispatchEvent(new Event("click"));
  await settle();
  assert.equal(globalThis.localStorage.getItem(M.DEVICE_KEY), null);
});
