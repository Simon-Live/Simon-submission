// docs/specs/model-picker.md: the catalog calls, the chooser (choice, restore, race, failure), the credit line, the
// import form check and the draw-stats columns. No DOM and no three: node --test tests/part7/picker.unit.test.mjs
import test from "node:test";
import assert from "node:assert/strict";
import { listModels, list, uploadModel, waitReady, errorText, needsConsent, makesRig, toEntry, deleteModel } from "../../web/skin/catalog.js";
import { createChooser, resolveChoice, creditFor, choiceIdOf, entryFor, KEY_PREFIX, noBodyNote } from "../../web/skin/picker.js";
import { validateForm, MSG } from "../../web/skin/import-dialog.js";
import { writeDrawStats } from "../../web/compare.js";

const ID = "a".repeat(32);
const LIB = { schema: "simon.model-library.v1", models: [
  { id: "ual2-female", name: "Mannequin F", glb: "models/library/ual2-female/model.glb", manifest: "models/library/ual2-female/character.json", licence: { id: "CC0", attribution: null } },
  { id: "rigged-figure", name: "Rigged Figure", glb: "g", manifest: "m", licence: { id: "CC-BY", attribution: "Khronos Group, CC-BY 4.0" } },
  { id: "broken" },
] };
const MINE = { mine: [
  { id: ID, name: "Mine", kind: "upload", glb: "g", manifest: "m", licence: { id: "own-work", attribution: null }, status: "ready" },
  { id: "b".repeat(32), name: "Busy", kind: "upload", glb: "g", manifest: "m", licence: { id: "own-work" }, status: "queued" },
] };

const reply = (status, body) => ({ ok: status >= 200 && status < 300, status, json: async () => body });
const router = (routes) => async (url, init) => {
  const key = Object.keys(routes).find((k) => url.startsWith(k));
  if (!key) throw new Error(`no route ${url}`);
  const r = routes[key];
  return typeof r === "function" ? r(url, init) : r;
};
const catalogFetch = router({ "models/library/library.json": reply(200, LIB), "api/models": reply(200, MINE) });

test("listModels merges the library and the ready uploads, and drops unusable records", async () => {
  const { library, mine } = await listModels(catalogFetch);
  assert.deepEqual(library.map((e) => e.id), ["ual2-female", "rigged-figure"]);
  assert.deepEqual(mine.map((e) => e.id), [ID]);   // the queued one is not offered
  assert.equal(library[0].kind, "library");
  assert.equal(mine[0].kind, "upload");
  assert.equal((await list(catalogFetch)).length, 3);
});

test("listModels survives a failed library call and a failed models call", async () => {
  const down = async () => { throw new Error("offline"); };
  assert.deepEqual(await listModels(down), { library: [], mine: [] });
  const only = router({ "models/library": reply(200, LIB), "api/models": reply(500, null) });
  const got = await listModels(only);
  assert.equal(got.library.length, 2);
  assert.deepEqual(got.mine, []);
});

test("toEntry refuses a record without a name or files", () => {
  assert.equal(toEntry(null), null);
  assert.equal(toEntry({ id: "x", name: "n" }), null);
  assert.equal(toEntry({ id: "x", name: "n", glb: "g", manifest: "m" }).licence.id, "unknown");
});

test("uploadModel sends the raw file with the query, and returns the new id", async () => {
  let seen;
  const f = router({ "api/models": (url, init) => { seen = { url, init }; return reply(201, { id: ID, status: "ready", entry: MINE.mine[0] }); } });
  const file = { name: "Rigged.glb", type: "model/gltf-binary" };
  const res = await uploadModel(file, { licence: "CC-BY", attribution: "Khronos & friends", sourceUrl: "https://example.org/a" }, f);
  assert.equal(res.ok, true);
  assert.equal(res.id, ID);
  assert.equal(res.entry.id, ID);
  const q = new URL(seen.url, "http://x").searchParams;
  assert.equal(q.get("name"), "Rigged");
  assert.equal(q.get("licence"), "CC-BY");
  assert.equal(q.get("attribution"), "Khronos & friends");
  assert.equal(q.get("source_url"), "https://example.org/a");
  assert.equal(q.has("consent"), false);
  assert.equal(seen.init.method, "POST");
  assert.equal(seen.init.body, file);
  assert.equal(seen.init.headers["Content-Type"], "model/gltf-binary");
});

test("uploadModel passes consent and draft, and reports a 202 as queued", async () => {
  let url;
  const f = router({ "api/models": (u) => { url = u; return reply(202, { id: ID, status: "queued" }); } });
  const res = await uploadModel({ name: "me.png", type: "image/png" }, { consent: "self", draft: ID }, f);
  assert.equal(res.status, "queued");
  const q = new URL(url, "http://x").searchParams;
  assert.equal(q.get("consent"), "self");
  assert.equal(q.get("draft"), ID);
});

test("uploadModel turns a 422 into a sentence that names the missing bones (negative)", async () => {
  const f = router({ "api/models": reply(422, { error: "This model has no humanoid rig.", missing: ["hips", "leftFoot"] }) });
  const res = await uploadModel({ name: "flat.glb", type: "" }, {}, f);
  assert.equal(res.ok, false);
  assert.equal(res.httpStatus, 422);
  assert.match(res.error, /Missing bones: hips, leftFoot\./);
  assert.deepEqual(res.missing, ["hips", "leftFoot"]);
});

test("uploadModel handles offline, a bad id and every status the server can answer", async () => {
  const offline = await uploadModel({ name: "a.glb" }, {}, async () => { throw new Error("x"); });
  assert.equal(offline.httpStatus, 0);
  assert.match(offline.error, /could not be reached/);
  const bad = await uploadModel({ name: "a.glb" }, {}, router({ "api/models": reply(201, { id: "../etc", status: "ready" }) }));
  assert.equal(bad.ok, false);
  for (const s of [400, 403, 411, 413, 415, 422, 429, 500]) assert.ok(errorText(s, null).length > 10, String(s));
  assert.match(errorText(413, null), /85 MB/);
  assert.doesNotMatch(errorText(429, null), /limit|Delete one/);
});

test("waitReady polls until ready, reports failed with the missing bones, and times out", async () => {
  const states = [{ status: "queued" }, { status: "converting" }, { status: "ready" }];
  let n = 0;
  const f = router({ "api/models/": () => reply(200, states[Math.min(n++, 2)]) });
  const waits = [];
  const ok = await waitReady(ID, { fetchImpl: f, wait: async (ms) => waits.push(ms), intervalMs: 5, timeoutMs: 100 });
  assert.equal(ok.status, "ready");
  assert.deepEqual(waits, [5, 5]);
  const failed = await waitReady(ID, { fetchImpl: router({ "api/models/": reply(200, { status: "failed", error: "No humanoid rig.", missing: ["hips"] }) }), wait: async () => {} });
  assert.equal(failed.status, "failed");
  assert.match(failed.error, /Missing bones: hips/);
  const slow = await waitReady(ID, { fetchImpl: router({ "api/models/": reply(200, { status: "converting" }) }), wait: async () => {}, intervalMs: 10, timeoutMs: 30 });
  assert.equal(slow.status, "failed");
  assert.match(slow.error, /too long/);
});

test("deleteModel says true for 200, 204 and 404, false otherwise", async () => {
  assert.equal(await deleteModel(ID, router({ "api/models/": reply(200, { ok: true }) })), true);
  assert.equal(await deleteModel(ID, router({ "api/models/": reply(204, null) })), true);
  assert.equal(await deleteModel(ID, router({ "api/models/": reply(404, null) })), true);
  assert.equal(await deleteModel(ID, router({ "api/models/": reply(403, null) })), false);
  assert.equal(await deleteModel(ID, async () => { throw new Error("x"); }), false);
});

// staging: an unread answer body leaves the request open and the next reload reports it as net::ERR_ABORTED
test("deleteModel reads the answer body to its end, and a body that cannot be read does not change the answer", async () => {
  let read = 0;
  const answer = { ok: true, status: 200, text: async () => { read += 1; return "{}"; } };
  assert.equal(await deleteModel(ID, async () => answer), true);
  assert.equal(read, 1);
  const broken = { ok: true, status: 200, text: async () => { throw new Error("gone"); } };
  assert.equal(await deleteModel(ID, async () => broken), true);
});

test("needsConsent: photos yes; an OBJ or a GLB no (a mesh is rigged with no question); makesRig: photos and OBJ", () => {
  assert.equal(needsConsent({ name: "me.jpg", type: "image/jpeg" }), true);
  assert.equal(needsConsent({ name: "me.WEBP", type: "" }), true);
  assert.equal(needsConsent({ name: "body.obj", type: "" }), false);
  assert.equal(makesRig({ name: "body.obj", type: "" }), true);
  assert.equal(makesRig({ name: "a.glb", type: "" }), false);
  assert.equal(needsConsent({ name: "a.glb", type: "model/gltf-binary" }), false);
  assert.equal(needsConsent(null), false);
});

// ---- chooser ---------------------------------------------------------------------------------------------------------
const entries = async () => (await listModels(catalogFetch));
const memory = (init = {}) => { const m = { ...init }; return { getItem: (k) => (k in m ? m[k] : null), setItem: (k, v) => { m[k] = v; }, m }; };
const adapter = (id) => ({ id, disposed: false, dispose() { this.disposed = true; } });
function rig({ stored = {}, tracks, job = "j1", loadCharacter, loadPersonSkin } = {}) {
  const calls = [];
  const stage = { setSkin: (i, a) => calls.push([i, a && a.id]) };
  const storage = memory(stored);
  const deps = {
    storage,
    loadCharacter: loadCharacter || (async (e) => adapter(e.id)),
    loadPersonSkin: loadPersonSkin || (async (j, p) => adapter(`person-${j}-${p}`)),
  };
  return { calls, stage, storage, deps, tracks: tracks || [{ role: "trainer", label: "Trainer" }, { role: "you", label: "You" }], job };
}

test("the default is Person, and Person loads the person skin for the job and the role", async () => {
  const r = rig();
  const ch = createChooser({ stage: r.stage, tracks: r.tracks, job: r.job, entries: [], deps: r.deps });
  await ch.restore();
  assert.equal(ch.current(0), "person");
  assert.deepEqual(r.calls, [[0, "person-j1-trainer"], [1, "person-j1-you"]]);
  assert.deepEqual(r.storage.m, {});   // restoring never writes
});

test("Person with no job (Watch, reference) is the stick figure and loads nothing", async () => {
  const r = rig({ job: null, loadPersonSkin: async () => { throw new Error("must not be called"); } });
  const ch = createChooser({ stage: r.stage, tracks: r.tracks, job: null, entries: [], deps: r.deps });
  await ch.restore();
  assert.deepEqual(r.calls, [[0, null], [1, null]]);
});

test("Person falls back to the stick figure when the skin is missing or throws", async () => {
  for (const loadPersonSkin of [async () => null, async () => { throw new Error("x"); }]) {
    const r = rig({ loadPersonSkin });
    const ch = createChooser({ stage: r.stage, tracks: r.tracks, job: "j1", entries: [], deps: r.deps });
    const res = await ch.choose(1, "person");
    assert.equal(res.ok, true);
    assert.deepEqual(r.calls, [[1, null]]);
  }
});

// TICKET-375: Person with no body to show was the stick figure with no word on screen (staging take bea90704d96a)
test("picker_names_who_has_no_body_given_person_resolves_no_skin", async () => {
  const r = rig({ loadPersonSkin: async (j, p) => (p === "trainer" ? null : adapter(`person-${j}-${p}`)) });
  const ch = createChooser({ stage: r.stage, tracks: r.tracks, job: "j1", entries: [], deps: r.deps });
  await ch.restore();
  assert.deepEqual(ch.bodiless(), [0]);
  assert.equal(noBodyNote(r.tracks, ch.bodiless()), "No 3D body for the trainer in this take, so Person shows the stick figure.");
  const both = rig({ loadPersonSkin: async () => { throw new Error("x"); } });
  const ch2 = createChooser({ stage: both.stage, tracks: both.tracks, job: "j1", entries: [], deps: both.deps });
  await ch2.restore();
  assert.deepEqual(ch2.bodiless(), [0, 1]);
  assert.equal(noBodyNote(both.tracks, ch2.bodiless()), "No 3D body for the trainer and you in this take, so Person shows the stick figures.");
  assert.equal(noBodyNote([{ role: "trainer", label: "Your reference" }], [0]), "No 3D body for your reference in this take, so Person shows the stick figure.");
});

test("picker_says_nothing_about_a_body_given_skeleton_a_model_a_skin_or_no_job (negative)", async () => {
  const r = rig({ loadPersonSkin: async () => null });
  const ch = createChooser({ stage: r.stage, tracks: r.tracks, job: "j1", entries: [{ id: "m1", kind: "library", name: "M" }], deps: r.deps });
  await ch.restore();
  assert.deepEqual(ch.bodiless(), [0, 1]);
  await ch.choose(0, "skeleton");
  await ch.choose(1, "lib:m1");
  assert.deepEqual(ch.bodiless(), [], "Skeleton and a library model draw what was chosen");
  await ch.choose(0, "person");
  assert.deepEqual(ch.bodiless(), [0], "back to Person with no body: said again");
  assert.equal(noBodyNote(r.tracks, []), "");
  const skin = rig();
  const ok = createChooser({ stage: skin.stage, tracks: skin.tracks, job: "j1", entries: [], deps: skin.deps });
  await ok.restore();
  assert.deepEqual(ok.bodiless(), [], "a person skin is a body");
  for (const job of [null, "fixture"]) {   // Watch and the example result have no take to have a body of
    const w = rig({ job, loadPersonSkin: async () => null });
    const cw = createChooser({ stage: w.stage, tracks: w.tracks, job, entries: [], deps: w.deps });
    await cw.restore();
    assert.deepEqual(cw.bodiless(), [], `job ${job}`);
  }
});

test("picker_says_nothing_about_a_body_given_a_generated_avatar_or_an_uploaded_model (negative)", async () => {
  // a generated avatar shares the choice id "person" with the no-body state: it is a body, so no line
  const made = { id: "av", name: "av", kind: "generated", status: "ready", glb: "g", manifest: "m", licence: { id: "own-work" }, for: { job: "j1", person: "you" } };
  const up = { id: "u1", name: "Mine", kind: "upload", glb: "g", manifest: "m", licence: { id: "own-work" }, status: "ready" };
  const r = rig({ loadPersonSkin: async () => null });
  const ch = createChooser({ stage: r.stage, tracks: r.tracks, job: "j1", entries: [made, up], deps: r.deps });
  await ch.restore();
  assert.equal(ch.current(1), "person");
  assert.deepEqual(ch.bodiless(), [0], "the follower has the avatar; only the trainer lacks a body");
  await ch.choose(0, "up:u1");
  assert.deepEqual(ch.bodiless(), [], "an uploaded model is what was chosen");
  // the avatar fails to load: Person falls back to the person skin, which has no body either, so it is said
  const broken = rig({ loadCharacter: async () => { throw new Error("bad glb"); }, loadPersonSkin: async () => null });
  const ch2 = createChooser({ stage: broken.stage, tracks: broken.tracks, job: "j1", entries: [made], deps: broken.deps });
  await ch2.restore();
  assert.deepEqual(ch2.bodiless(), [0, 1]);
});

test("picker_keeps_the_later_choice_given_a_bodiless_person_load_is_superseded", async () => {
  let release;
  const slow = new Promise((res) => { release = res; });
  const r = rig({ loadPersonSkin: async () => { await slow; return null; } });
  const ch = createChooser({ stage: r.stage, tracks: r.tracks, job: "j1", entries: [], deps: r.deps });
  const first = ch.choose(1, "person");
  await ch.choose(1, "skeleton");
  release();
  await first;
  assert.deepEqual(ch.bodiless(), [], "the Person load that lost the race does not claim a missing body");
});

test("choosing a library model for one figure leaves the other alone, and remembers it", async () => {
  const { library, mine } = await entries();
  const r = rig();
  const ch = createChooser({ stage: r.stage, tracks: r.tracks, job: "j1", entries: [...library, ...mine], deps: r.deps });
  await ch.restore();
  r.calls.length = 0;
  const res = await ch.choose(1, "lib:ual2-female");
  assert.equal(res.ok, true);
  assert.deepEqual(r.calls, [[1, "ual2-female"]]);
  assert.equal(ch.current(0), "person");
  assert.equal(ch.current(1), "lib:ual2-female");
  assert.equal(r.storage.m[KEY_PREFIX + "you"], "lib:ual2-female");
  assert.equal(KEY_PREFIX + "trainer" in r.storage.m, false);
});

test("a reload restores the saved choice; a model that is gone falls back to Person", async () => {
  const { library, mine } = await entries();
  const r = rig({ stored: { [KEY_PREFIX + "you"]: "lib:ual2-female", [KEY_PREFIX + "trainer"]: "up:" + "c".repeat(32) } });
  const ch = createChooser({ stage: r.stage, tracks: r.tracks, job: "j1", entries: [...library, ...mine], deps: r.deps });
  await ch.restore();
  assert.equal(ch.current(1), "lib:ual2-female");
  assert.equal(ch.current(0), "person");
  assert.deepEqual(r.calls.sort(), [[0, "person-j1-trainer"], [1, "ual2-female"]]);
});

test("Skeleton removes the skin and is remembered (negative: nothing is loaded)", async () => {
  const r = rig({ loadCharacter: async () => { throw new Error("no"); }, loadPersonSkin: async () => { throw new Error("no"); } });
  const ch = createChooser({ stage: r.stage, tracks: r.tracks, job: "j1", entries: [], deps: r.deps });
  assert.equal((await ch.choose(0, "skeleton")).ok, true);
  assert.deepEqual(r.calls, [[0, null]]);
  assert.equal(r.storage.m[KEY_PREFIX + "trainer"], "skeleton");
  assert.deepEqual(ch.credits(), []);
});

test("a model that fails to load keeps the last look and says so", async () => {
  const { library } = await entries();
  const r = rig({ loadCharacter: async () => { throw new Error("bad glb"); } });
  const ch = createChooser({ stage: r.stage, tracks: r.tracks, job: "j1", entries: library, deps: r.deps });
  await ch.choose(0, "skeleton");
  r.calls.length = 0;
  const res = await ch.choose(0, "lib:ual2-female");
  assert.equal(res.ok, false);
  assert.match(res.error, /could not be shown/);
  assert.deepEqual(r.calls, []);
  assert.equal(ch.current(0), "skeleton");
  assert.equal(r.storage.m[KEY_PREFIX + "trainer"], "skeleton");
});

test("a choice that is not in the list, and a bad figure index, fail without touching the stage", async () => {
  const r = rig();
  const ch = createChooser({ stage: r.stage, tracks: r.tracks, job: "j1", entries: [], deps: r.deps });
  assert.equal((await ch.choose(0, "lib:nope")).ok, false);
  assert.equal((await ch.choose(5, "skeleton")).ok, false);
  assert.deepEqual(r.calls, []);
});

test("two quick choices for one figure: the later one wins and the earlier skin is disposed", async () => {
  const { library } = await entries();
  const gates = {};
  const made = [];
  const r = rig({ loadCharacter: (e) => new Promise((res) => { gates[e.id] = () => { const a = adapter(e.id); made.push(a); res(a); }; }) });
  const ch = createChooser({ stage: r.stage, tracks: r.tracks, job: "j1", entries: library, deps: r.deps });
  const first = ch.choose(0, "lib:ual2-female");
  const second = ch.choose(0, "lib:rigged-figure");
  gates["rigged-figure"]();
  gates["ual2-female"]();
  assert.equal((await second).ok, true);
  assert.equal((await first).superseded, true);
  assert.deepEqual(r.calls, [[0, "rigged-figure"]]);
  assert.equal(made.find((a) => a.id === "ual2-female").disposed, true);
  assert.equal(ch.current(0), "lib:rigged-figure");
});

test("storage that throws never breaks a choice", async () => {
  const r = rig();
  r.deps.storage = { getItem() { throw new Error("denied"); }, setItem() { throw new Error("denied"); } };
  const ch = createChooser({ stage: r.stage, tracks: r.tracks, job: "j1", entries: [], deps: r.deps });
  await ch.restore();
  assert.equal((await ch.choose(0, "skeleton")).ok, true);
});

test("a stage without setSkin (the skin code is not loaded) still records the choice", async () => {
  const r = rig();
  const ch = createChooser({ stage: {}, tracks: r.tracks, job: "j1", entries: [], deps: r.deps });
  assert.equal((await ch.choose(0, "skeleton")).ok, true);
  assert.equal(ch.current(0), "skeleton");
});

test("figures are keyed by role, so a multi-compare picker keeps one choice per person", async () => {
  const tracks = [{ role: "trainer", label: "Trainer", job: "g1", person: "trainer" }, { role: "p1", label: "Ann", job: "g1", person: "p1" }, { role: "p2", label: "Bo", job: "g1", person: "p2" }];
  const { library } = await entries();
  const r = rig({ tracks });
  const ch = createChooser({ stage: r.stage, tracks, job: null, entries: library, deps: r.deps });
  await ch.restore();
  await ch.choose(1, "lib:ual2-female");
  await ch.choose(2, "lib:rigged-figure");
  assert.equal(r.storage.m[KEY_PREFIX + "p1"], "lib:ual2-female");
  assert.equal(r.storage.m[KEY_PREFIX + "p2"], "lib:rigged-figure");
  assert.ok(r.calls.some(([i, id]) => i === 0 && id === "person-g1-trainer"));
});

test("credit line: shown for a CC-BY model on screen, not for CC0, gone once it is swapped out", async () => {
  const { library } = await entries();
  const r = rig();
  const ch = createChooser({ stage: r.stage, tracks: r.tracks, job: "j1", entries: library, deps: r.deps });
  await ch.choose(0, "lib:ual2-female");
  assert.deepEqual(ch.credits(), []);
  await ch.choose(1, "lib:rigged-figure");
  assert.deepEqual(ch.credits(), ["Rigged Figure: Khronos Group, CC-BY 4.0"]);
  await ch.choose(0, "lib:rigged-figure");
  assert.equal(ch.credits().length, 1);   // the same line once
  await ch.choose(0, "skeleton");
  await ch.choose(1, "skeleton");
  assert.deepEqual(ch.credits(), []);
});

test("creditFor, resolveChoice, entryFor and choiceIdOf", async () => {
  const { library, mine } = await entries();
  assert.equal(creditFor(null), "");
  assert.equal(creditFor({ name: "n", licence: { id: "CC-BY", attribution: null } }), "");
  assert.equal(creditFor({ name: "n", licence: { id: "CC0", attribution: "thanks" } }), "");
  assert.equal(resolveChoice("skeleton", []), "skeleton");
  assert.equal(resolveChoice(null, []), "person");
  assert.equal(resolveChoice("up:zzz", [...library, ...mine]), "person");
  assert.equal(choiceIdOf(library[0]), "lib:ual2-female");
  assert.equal(choiceIdOf(mine[0]), `up:${ID}`);
  assert.equal(entryFor(`lib:${ID}`, [...library, ...mine]), null);   // an upload is not a library model
  assert.equal(entryFor("garbage", []), null);
});

// ---- import form ------------------------------------------------------------------------------------------------------
test("validateForm: no file, no credit, no consent, too many photos, mixed files", () => {
  const glb = { name: "a.glb", type: "" };
  const png = (n) => ({ name: `${n}.png`, type: "image/png" });
  assert.equal(validateForm({ files: [], licence: "CC0" }), MSG.noFile);
  assert.equal(validateForm({ files: [glb], licence: "CC-BY", attribution: "  " }), MSG.noCredit);
  assert.equal(validateForm({ files: [glb], licence: "CC-BY", attribution: "Khronos" }), "");
  assert.equal(validateForm({ files: [glb], licence: "own-work" }), "");
  assert.equal(validateForm({ files: [png(1)], licence: "own-work" }), MSG.noConsent);
  assert.equal(validateForm({ files: [png(1)], licence: "own-work", consent: "self" }), "");
  assert.equal(validateForm({ files: [1, 2, 3, 4, 5].map(png), licence: "own-work", consent: "self" }), MSG.imageLimit);
  assert.equal(validateForm({ files: [png(1), glb], licence: "own-work", consent: "self" }), MSG.imageLimit);
});

const DASH = new RegExp(`[${String.fromCharCode(0x2013)}${String.fromCharCode(0x2014)}]`);
const DASH_OR_SPACED = new RegExp(` - |${DASH.source}`);
test("no user-facing string in the picker modules has a dash", async () => {
  const fs = await import("node:fs");
  for (const f of ["catalog.js", "picker.js", "import-dialog.js", "skin.css"]) {
    const text = fs.readFileSync(new URL(`../../web/skin/${f}`, import.meta.url), "utf8");
    assert.doesNotMatch(text, DASH, f);
  }
  for (const s of Object.values(MSG)) assert.doesNotMatch(s, DASH_OR_SPACED);
});

// ---- draw stats -------------------------------------------------------------------------------------------------------
test("writeDrawStats adds the skin columns, with a dash for a figure that has none", () => {
  const attrs = {};
  const wrap = { setAttribute: (k, v) => { attrs[k] = v; } };
  writeDrawStats(wrap, [
    { joints: 17, dimmed: 0, bones: 16, skin: null },
    { joints: 17, dimmed: 1, bones: 16, skin: { kind: "character", id: "ual2-female", segErrDeg: 3.456 } },
    null,
  ]);
  assert.equal(attrs["data-joints-drawn"], "17,17,-");
  assert.equal(attrs["data-skin-kind"], "-,character,-");
  assert.equal(attrs["data-skin-id"], "-,ual2-female,-");
  assert.equal(attrs["data-skin-err"], "-,3.5,-");
  writeDrawStats(wrap, [{ joints: 1, dimmed: 0, bones: 0 }]);   // a stage without the skin field
  assert.equal(attrs["data-skin-id"], "-");
});

test("uploadModel sends more, filename and the take a generated model is for", async () => {
  let url;
  const f = router({ "api/models": (u) => { url = u; return reply(202, { id: ID, status: "draft" }); } });
  await uploadModel({ name: "me.png", type: "image/png" }, { consent: "self", more: true, forJob: "job1", forPerson: "you" }, f);
  const q = new URL(url, "http://x").searchParams;
  assert.equal(q.get("more"), "1");
  assert.equal(q.get("filename"), "me.png");
  assert.equal(q.get("for_job"), "job1");
  assert.equal(q.get("for_person"), "you");
});

test("Person prefers a generated avatar made for that person of that take, else the rigid skin", async () => {
  const { generatedFor } = await import("../../web/skin/picker.js");
  const mk = (id, job, person, extra = {}) => ({ id, name: id, kind: "generated", status: "ready", glb: "g", manifest: "m", licence: { id: "own-work" }, for: { job, person }, ...extra });
  const entries = [mk("old", "j1", "you"), mk("new", "j1", "you"), mk("other", "j2", "you"), mk("busy", "j1", "trainer", { status: "queued" })];
  assert.equal(generatedFor(entries, "j1", "you").id, "new");
  assert.equal(generatedFor(entries, "j1", "trainer"), null);
  const r = rig();
  const ch = createChooser({ stage: r.stage, tracks: r.tracks, job: "j1", entries, deps: r.deps });
  await ch.restore();
  assert.deepEqual(r.calls, [[0, "person-j1-trainer"], [1, "new"]]);
  const broken = rig({ loadCharacter: async () => { throw new Error("bad glb"); } });
  const ch2 = createChooser({ stage: broken.stage, tracks: broken.tracks, job: "j1", entries, deps: broken.deps });
  await ch2.restore();
  assert.deepEqual(broken.calls, [[0, "person-j1-trainer"], [1, "person-j1-you"]]);
});

test("Person on the example result asks for no mesh: the fixture job has no files (staging verify 404 on api/results/fixture/mesh.json)", async () => {
  const asked = [];
  const deps = { loadPersonSkin: async (job, person) => { asked.push([job, person]); return null; }, loadCharacter: async () => null, storage: null };
  const stage = { setSkin() {} };
  const tracks = [{ role: "trainer", label: "Trainer" }, { role: "you", label: "You" }];
  const fixture = createChooser({ stage, tracks, job: "fixture", entries: [], deps });
  assert.deepEqual(await fixture.choose(1, "person"), { ok: true });
  assert.deepEqual(asked, [], "no Person skin load, so no mesh.json request");
  const real = createChooser({ stage, tracks, job: "abcdef123456", entries: [], deps });
  await real.choose(1, "person");
  assert.deepEqual(asked, [["abcdef123456", "you"]], "a real job still loads its Person skin");
});

// staging 2026-11-02: a generated model's credit was only the SAM/MHR line; the uploader's credit must stay beside it
test("a generated model's credit shows the uploader's credit and the generator notice; toEntry keeps both and the source", () => {
  const raw = { id: ID, name: "Ironman", kind: "generated", glb: "g", manifest: "m", licence: { id: "CC-BY", attribution: "By Ana" },
    generator_attribution: "SAM License; MHR Apache-2.0 notice", source: { note: "test", url: null } };
  const entry = toEntry(raw, "upload");
  assert.equal(entry.generator, "SAM License; MHR Apache-2.0 notice");
  assert.deepEqual(entry.source, { url: null, note: "test" });
  assert.equal(creditFor(entry), "Ironman: By Ana. SAM License; MHR Apache-2.0 notice");
  assert.equal(creditFor({ ...entry, licence: { id: "own-work", attribution: null } }), "Ironman: SAM License; MHR Apache-2.0 notice");
  const plain = toEntry({ ...raw, generator_attribution: undefined, source: {} }, "upload");
  assert.deepEqual([plain.generator, plain.source], [null, null], "negative: an upload invents no generator or source");
  assert.equal(creditFor(plain), "Ironman: By Ana");
});

test("a library model is loaded with the track's role, so the trainer is chalk and you are lime (TICKET-335)", async () => {
  const { library } = await entries();
  const seen = [];
  const r = rig({ stored: { [KEY_PREFIX + "trainer"]: "lib:ual2-female", [KEY_PREFIX + "you"]: "lib:ual2-female" },
    loadCharacter: async (e, opts) => { seen.push(opts && opts.role); return adapter(e.id); } });
  const ch = createChooser({ stage: r.stage, tracks: r.tracks, job: "j1", entries: library, deps: r.deps });
  await ch.restore();
  assert.deepEqual(seen.sort(), ["trainer", "you"]);
  // the same roles drive the tone: the real loader's colours for each role
  const { toneMaterial } = await import("../../web/skin/character.js");
  const THREE = await import("../../web/vendor/three/three.module.min.js");
  const tone = (role) => { const m = new THREE.MeshStandardMaterial({ color: 0x8844cc }); toneMaterial(m, role); return m.color.getHexString(); };
  assert.equal(tone("trainer"), "f4f4ef");
  assert.equal(tone("you"), "c6f35a");
});
