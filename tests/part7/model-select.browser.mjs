// docs/specs/model-picker.md (AC-P1 to AC-P12) at 412x915 on the result harness (tests/part7/harness/result.html, the real
// replay fixture and the real compare.js, picker.js, import-dialog.js, catalog.js). The model server (library.json, api/models)
// is answered by page.route, and character.js / person-skin.js are replaced by small recorders so this test does not depend
// on the skin code lanes. Run: PLAYWRIGHT_DIR=<node_modules> scripts/with-browser-slot.sh node tests/part7/model-select.browser.mjs
// The skin pixels and the frame time with four skinned figures are proven by the integrated run, not here.
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { serveRoot } from "./serve_static.mjs";

const here = path.dirname(fileURLToPath(import.meta.url));
const req = createRequire(path.join(process.env.PLAYWRIGHT_DIR || path.resolve(here, "../../node_modules"), "x.js"));
const { chromium } = req("playwright");
let AXE = null;
try { AXE = fs.readFileSync(req.resolve("axe-core/axe.min.js"), "utf8"); } catch { AXE = null; }

const ID = "a".repeat(32);
const json = (route, status, body) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
const LIB = { schema: "simon.model-library.v1", models: [
  { id: "ual2-female", name: "Mannequin F", glb: "models/library/ual2-female/model.glb", manifest: "models/library/ual2-female/character.json", licence: { id: "CC0", attribution: null } },
  { id: "ual1-male", name: "Mannequin M", glb: "models/library/ual1-male/model.glb", manifest: "models/library/ual1-male/character.json", licence: { id: "CC0", attribution: null } },
  { id: "rigged-figure", name: "Rigged Figure", glb: "models/library/rigged-figure/model.glb", manifest: "models/library/rigged-figure/character.json",
    licence: { id: "CC-BY", attribution: "Khronos Group, CC-BY 4.0" } },
] };

// recorders for the skin modules
const CHARACTER_STUB = `export async function loadCharacter(entry) { (window.__skinLog ||= []).push("character:" + entry.id);
  return { kind: "character", id: entry.id, object3d: null, setPose() {}, setGhost() {}, dispose() { window.__skinLog.push("dispose:" + entry.id); }, stats() { return {}; } }; }`;
const PERSON_STUB = `export async function loadPersonSkin(job, person) { (window.__skinLog ||= []).push("person:" + job + ":" + person); return null; }`;

const { port } = await serveRoot();
const browser = await chromium.launch({ args: ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"] });
const failures = [];
let passed = 0;
const ok = (name) => { passed++; console.log(`ok - ${name}`); };

async function open(kase, { mine = [], post = null, withSkins = true, ctx = null, signedIn = false } = {}) {
  const context = ctx || await browser.newContext({ viewport: { width: 412, height: 915 }, reducedMotion: "reduce" });
  const page = await context.newPage();
  const bad = [];
  const state = { mine: [...mine], posts: [], profileGets: 0 };
  page.on("pageerror", (e) => bad.push(`pageerror ${e.message}`));
  page.on("requestfailed", (r) => bad.push(`failed ${r.url()}`));
  page.on("response", (r) => { if (r.status() >= 400 && r.request().method() === "GET" && !/\/api\/(client-log|models\/[0-9a-f]+)/.test(r.url()) && !r.url().endsWith("favicon.ico")) bad.push(`${r.status()} ${r.url()}`); });
  // signed out, as on staging: the picker may ask who is signed in, never the profile (model-default.md)
  await page.route("**/api/auth/me", (route) => json(route, 200, { available: true, signed_in: signedIn }));
  await page.route("**/api/me/profile", (route) => { state.profileGets++; return json(route, 401, { error: "not signed in" }); });
  await page.route("**/models/library/library.json", (route) => json(route, 200, LIB));
  await page.route(/\/api\/models(\?.*)?$/, (route) => {
    if (route.request().method() === "GET") return json(route, 200, { mine: state.mine });
    const url = new URL(route.request().url());
    state.posts.push({ query: Object.fromEntries(url.searchParams), origin: route.request().headers().origin || null });
    return post ? post(route, state) : json(route, 500, {});
  });
  if (withSkins) {
    await page.route("**/web/skin/character.js", (route) => route.fulfill({ contentType: "text/javascript", body: CHARACTER_STUB }));
    await page.route("**/web/skin/person-skin.js", (route) => route.fulfill({ contentType: "text/javascript", body: PERSON_STUB }));
  }
  await page.goto(`http://127.0.0.1:${port}/tests/part7/harness/result.html?case=${kase}`);
  await page.waitForFunction(() => window.__ready === true);
  return { page, bad, state, context };
}
const selectOf = (page, i) => page.getByTestId(`model-select-${i}`);
const optionValues = (page, i) => selectOf(page, i).locator("option").evaluateAll((os) => os.map((o) => o.value));
const optionTexts = (page, i) => selectOf(page, i).locator("option").evaluateAll((os) => os.map((o) => o.textContent));
const log = (page) => page.evaluate(() => window.__skinLog || []);
async function axe(page, selector) {
  if (!AXE) return [];
  await page.evaluate(AXE);
  const res = await page.evaluate((sel) => window.axe.run(document.querySelector(sel), { resultTypes: ["violations"] }), selector);
  return res.violations.filter((v) => ["serious", "critical", "moderate", "minor"].includes(v.impact)).map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(" | ")}`);
}
const MINE = [{ id: ID, name: "My figure", kind: "upload", glb: "g", manifest: "m", licence: { id: "own-work", attribution: null }, status: "ready" }];

try {
  // AC-P1: one select per figure, Person first and selected, the options in order (compare has two figures)
  {
    const { page, bad, state } = await open("ok", { mine: MINE });
    await selectOf(page, 1).waitFor();
    assert.equal(await page.locator("[data-testid^=model-select-]").count(), 2);
    assert.deepEqual(await optionValues(page, 0), ["person", "skeleton", "lib:ual2-female", "lib:ual1-male", "lib:rigged-figure", `up:${ID}`, "import"]);
    assert.deepEqual((await optionTexts(page, 1)).slice(0, 2), ["Person", "Skeleton"]);
    assert.equal((await optionTexts(page, 1)).at(-1), "Import a model…");
    assert.equal(await selectOf(page, 0).inputValue(), "person");
    assert.equal(await selectOf(page, 1).inputValue(), "person");
    assert.equal(await page.getByTestId("model-attribution").isVisible(), false);
    assert.deepEqual(bad, []);
    assert.equal(state.profileGets, 0, "negative: signed out, the picker never requests api/me/profile");
    ok("AC-P1 one select per figure, default Person, no failing request, no profile request signed out");

    // AC-P2: the follower picks a library model; the trainer keeps its choice; a reload restores it
    await selectOf(page, 1).selectOption("lib:ual2-female");
    await page.waitForFunction(() => (window.__skinLog || []).includes("character:ual2-female"), null, { timeout: 2000 });
    assert.equal(await selectOf(page, 0).inputValue(), "person");
    assert.equal(await page.evaluate(() => localStorage.getItem("simon.model.you")), "lib:ual2-female");
    assert.equal(await page.evaluate(() => localStorage.getItem("simon.model.trainer")), null);
    const skinId = await page.getByTestId("compare").getAttribute("data-skin-id");
    if (await page.evaluate(() => !!document.querySelector("[data-testid=compare]")) && skinId !== null) {
      // the stage reports skins (the viewer3d hook is integrated): the second figure carries the id
      if (skinId !== "-,-") assert.equal(skinId.split(",")[1], "ual2-female");
    }
    ok("AC-P2 the follower chooses a library model, the trainer keeps Person, the choice is saved");
    assert.equal(await page.getByTestId("model-body-note").textContent(), "", "negative: the harness result has no job, so no take to lack a body");

    await page.reload();
    await page.waitForFunction(() => window.__ready === true);
    await selectOf(page, 1).waitFor();
    await page.waitForFunction(() => document.querySelector("[data-testid=model-picker]")?.dataset.ready === "true");
    assert.equal(await selectOf(page, 1).inputValue(), "lib:ual2-female");
    assert.equal(await selectOf(page, 0).inputValue(), "person");
    await page.waitForFunction(() => (window.__skinLog || []).includes("character:ual2-female"));
    ok("AC-P2 a reload restores the saved choice");

    // AC-P3: Skeleton gives no skin and is remembered (negative: nothing is loaded for it)
    const before = (await log(page)).length;
    await selectOf(page, 1).selectOption("skeleton");
    await page.waitForFunction(() => document.querySelector("[data-testid=model-picker]").dataset.choices.endsWith("skeleton"));
    assert.equal((await log(page)).length, before);
    assert.equal(await page.evaluate(() => localStorage.getItem("simon.model.you")), "skeleton");
    const kind = await page.getByTestId("compare").getAttribute("data-skin-kind");
    if (kind !== null) assert.equal(kind.split(",")[1], "-");
    ok("AC-P3 Skeleton removes the skin and loads nothing");
    await page.context().close();
  }

  // AC-P4: a CC-BY model shows its credit line, a CC0 model shows none, and the credit goes when the model does
  {
    const { page } = await open("ok");
    await selectOf(page, 0).selectOption("lib:ual1-male");
    await page.waitForFunction(() => (window.__skinLog || []).includes("character:ual1-male"));
    assert.equal(await page.getByTestId("model-attribution").isVisible(), false);
    await selectOf(page, 1).selectOption("lib:rigged-figure");
    await page.waitForFunction(() => document.querySelector("[data-testid=model-attribution]").textContent.length > 0);
    assert.equal(await page.getByTestId("model-attribution").textContent(), "Rigged Figure: Khronos Group, CC-BY 4.0");
    await selectOf(page, 1).selectOption("skeleton");
    await page.waitForFunction(() => document.querySelector("[data-testid=model-attribution]").textContent === "");
    assert.equal(await page.getByTestId("model-attribution").isVisible(), false);
    ok("AC-P4 the credit line shows for CC-BY only, and leaves with the model");
    await page.context().close();
  }

  // AC-P5, AC-P6: import a rigged GLB with licence CC-BY; it joins the list and is chosen
  {
    const post = (route, state) => {
      const entry = { id: ID, name: "RiggedFigure", kind: "upload", glb: "g", manifest: "m", licence: { id: "CC-BY", attribution: "Khronos" }, status: "ready" };
      state.mine.push(entry);
      return json(route, 201, { id: ID, status: "ready", entry });
    };
    const { page, state, bad } = await open("ok", { post });
    await selectOf(page, 1).selectOption("import");
    const dlg = page.getByTestId("model-import-dialog");
    await dlg.waitFor();
    // negative: an empty form is refused before anything is sent
    await page.getByTestId("model-import-submit").click();
    assert.match(await page.getByTestId("model-import-error").textContent(), /Choose a file/);
    assert.equal(state.posts.length, 0);
    await page.getByTestId("model-import-file").setInputFiles({ name: "RiggedFigure.glb", mimeType: "model/gltf-binary", buffer: Buffer.from("glTF") });
    await page.getByTestId("model-import-licence").selectOption("CC-BY");
    await page.getByTestId("model-import-submit").click();
    assert.match(await page.getByTestId("model-import-error").textContent(), /credit line/i);
    assert.equal(state.posts.length, 0);
    await page.getByTestId("model-import-credit").fill("Khronos");
    await page.getByTestId("model-import-submit").click();
    await dlg.waitFor({ state: "detached" });
    assert.equal(state.posts.length, 1);
    assert.equal(state.posts[0].query.licence, "CC-BY");
    assert.equal(state.posts[0].query.attribution, "Khronos");
    assert.equal(state.posts[0].query.name, "RiggedFigure");
    assert.ok(state.posts[0].origin && state.posts[0].origin.startsWith("http://127.0.0.1"), "the browser sends Origin on the upload");
    await page.waitForFunction((id) => document.querySelector("[data-testid=model-select-1]").value === `up:${id}`, ID);
    assert.ok((await optionValues(page, 0)).includes(`up:${ID}`));
    await page.waitForFunction((id) => (window.__skinLog || []).includes(`character:${id}`), ID);
    assert.equal(await page.getByTestId("model-attribution").textContent(), "RiggedFigure: Khronos");
    assert.deepEqual(bad, []);
    ok("AC-P5 an imported CC-BY GLB joins the list, is chosen, and shows its credit");
    await page.context().close();
  }

  // AC-P6: a skinless GLB names the missing bones; the list is unchanged; Cancel leaves the previous choice
  {
    const post = (route) => json(route, 422, { error: "This model has no humanoid rig.", missing: ["hips", "leftUpperArm"] });
    const { page } = await open("ok", { post });
    await selectOf(page, 1).waitFor();
    const before = await optionValues(page, 0);
    await selectOf(page, 1).selectOption("import");
    await page.getByTestId("model-import-file").setInputFiles({ name: "flat.glb", mimeType: "model/gltf-binary", buffer: Buffer.from("glTF") });
    await page.getByTestId("model-import-submit").click();
    await page.getByTestId("model-import-error").waitFor({ state: "visible" });
    const text = await page.getByTestId("model-import-error").textContent();
    assert.match(text, /Missing bones: hips, leftUpperArm/);
    assert.deepEqual(await optionValues(page, 0), before);
    if (AXE) assert.deepEqual(await axe(page, "[data-testid=model-import-dialog]"), []);
    await page.getByTestId("model-import-cancel").click();
    await page.getByTestId("model-import-dialog").waitFor({ state: "detached" });
    assert.equal(await selectOf(page, 1).inputValue(), "person");
    ok("AC-P6 a skinless GLB shows the missing bones, adds nothing, Cancel keeps the choice (axe clean)");
    await page.context().close();
  }

  // AC-P7: a photo asks who is in it, and sends the answer; a conversion is waited for
  {
    let polls = 0;
    const post = (route) => json(route, 202, { id: ID, status: "queued" });
    const { page, state } = await open("ok", { post });
    await page.route(`**/api/models/${ID}`, (route) => {
      polls++;
      if (polls < 2) return json(route, 200, { id: ID, status: "converting" });
      state.mine.push({ id: ID, name: "me", kind: "upload", glb: "g", manifest: "m", licence: { id: "own-work", attribution: null }, status: "ready" });
      return json(route, 200, { id: ID, status: "ready" });
    });
    await selectOf(page, 0).selectOption("import");
    await page.getByTestId("model-import-file").setInputFiles({ name: "me.png", mimeType: "image/png", buffer: Buffer.from("png") });
    await page.getByTestId("model-import-consent").waitFor({ state: "visible" });
    await page.getByTestId("model-import-submit").click();
    assert.match(await page.getByTestId("model-import-error").textContent(), /who the photo shows/i);
    await page.getByTestId("model-import-consent").selectOption("self");
    await page.getByTestId("model-import-submit").click();
    await page.getByTestId("model-import-dialog").waitFor({ state: "detached", timeout: 15000 });
    assert.equal(state.posts[0].query.consent, "self");
    await page.waitForFunction((id) => document.querySelector("[data-testid=model-select-0]").value === `up:${id}`, ID);
    ok("AC-P7 a photo needs the consent answer, a queued model is waited for");
    await page.context().close();
  }

  // AC-P13: the import dialog shows a progress bar that advances through the server's real steps, with seconds so far
  for (const motion of ["reduce", "no-preference"]) {
    const ctx = await browser.newContext({ viewport: { width: 412, height: 915 }, reducedMotion: motion });
    const script = [
      { id: ID, status: "queued", step: "waiting", step_index: 2, step_count: 5, position: 1, waiting: "Waiting for the graphics card: a take is being analysed. Your model is next." },
      { id: ID, status: "converting", step: "skeleton", step_index: 3, step_count: 5 },
      { id: ID, status: "converting", step: "checking", step_index: 4, step_count: 5 },
      { id: ID, status: "ready" },
    ];
    let polls = 0;
    const post = (route) => json(route, 202, { id: ID, status: "queued", step: "waiting", step_index: 2, step_count: 5 });
    const { page, state } = await open("ok", { post, ctx });
    await page.route(`**/api/models/${ID}`, (route) => {
      const rec = script[Math.min(polls++, script.length - 1)];
      if (rec.status === "ready") state.mine.push({ id: ID, name: "me", kind: "upload", glb: "g", manifest: "m", licence: { id: "own-work", attribution: null }, status: "ready" });
      return json(route, 200, rec);
    });
    await page.evaluate(() => {  // record what the bar shows each time it changes
      window.__bar = [];
      const grab = () => {
        const b = document.querySelector("[data-testid=model-progress-bar]");
        if (!b) return;
        const row = { now: b.getAttribute("aria-valuenow"), role: b.getAttribute("role"), step: b.closest("[data-step]")?.getAttribute("data-step"),
          time: document.querySelector("[data-testid=model-progress-time]")?.textContent, text: b.getAttribute("aria-valuetext") };
        const last = window.__bar.at(-1);
        if (!last || last.now !== row.now || last.step !== row.step) window.__bar.push(row);
      };
      new MutationObserver(grab).observe(document.body, { subtree: true, attributes: true, childList: true });
    });
    await selectOf(page, 0).selectOption("import");
    await page.getByTestId("model-import-file").setInputFiles({ name: "me.png", mimeType: "image/png", buffer: Buffer.from("png") });
    await page.getByTestId("model-import-consent").selectOption("self");
    await page.getByTestId("model-import-submit").click();
    await page.waitForFunction(() => document.querySelector("link[data-simon-model-progress-css]")?.sheet); // the sheet loads after the click
    const spin = await page.getByTestId("model-progress-spin").evaluate((n) => getComputedStyle(n).animationName);
    assert.equal(spin, motion === "reduce" ? "none" : "msel-turn", `the ring ${motion === "reduce" ? "is still" : "turns"} (${motion})`);
    await page.getByTestId("model-import-dialog").waitFor({ state: "detached", timeout: 20000 });
    const seen = await page.evaluate(() => window.__bar);
    assert.ok(seen.every((r) => r.role === "progressbar"));
    const steps = seen.map((r) => r.step);
    for (const want of ["waiting", "skeleton", "checking", "ready"]) assert.ok(steps.includes(want), `the bar passed through ${want}: ${steps}`);
    assert.ok(steps.indexOf("waiting") < steps.indexOf("skeleton") && steps.indexOf("skeleton") < steps.indexOf("checking") && steps.indexOf("checking") < steps.indexOf("ready"), "in order");
    const values = seen.filter((r) => r.now !== null).map((r) => Number(r.now));
    assert.deepEqual([...values].sort((a, b) => a - b), values, "aria-valuenow never goes back");
    assert.equal(values.at(-1), 100);
    assert.ok(values.includes(20) && values.includes(40) && values.includes(60), `real step values: ${values}`);
    assert.ok(seen.every((r) => /so far$/.test(r.time || "")), "seconds so far are shown");
    assert.ok(seen.some((r) => /Step 3 of 5: Adding the skeleton/.test(r.text || "")));
    assert.equal(await page.getByTestId("model-progress-bar").count(), 0, "negative: the bar leaves with the dialog");
    await ctx.close();
  }
  ok("AC-P13 the import progress bar advances through the real steps (waiting, skeleton, checking, ready); the ring is still under reduced motion");

  // AC-P13 (docs/specs/image3d-intake.md AC-I15 to AC-I18): one picture asks what is in it. A character or object sends
  // kind=object with no consent, waits for the model and picks it; a person keeps the consent question; several photos
  // do not ask. Two witnesses: the request the server gets, and the model the figure ends up wearing.
  {
    let polls = 0;
    const post = (route) => json(route, 202, { id: ID, status: "queued" });
    const { page, state } = await open("ok", { post, signedIn: true });
    await page.route(`**/api/models/${ID}`, (route) => {
      polls++;
      if (polls < 2) return json(route, 200, { id: ID, status: "converting" });
      state.mine.push({ id: ID, name: "armour", kind: "generated", glb: "g", manifest: "m", licence: { id: "own-work", attribution: null }, status: "ready" });
      return json(route, 200, { id: ID, status: "ready" });
    });
    await selectOf(page, 0).selectOption("import");
    const file = page.getByTestId("model-import-file");
    await file.setInputFiles({ name: "armour.png", mimeType: "image/png", buffer: Buffer.from("png") });
    const group = page.getByTestId("model-import-picture");
    await group.waitFor({ state: "visible" });
    assert.match(await group.textContent(), /What is in the picture\?/);
    assert.match(await group.textContent(), /A real person \(a plain skin-coloured body\)/);
    assert.match(await group.textContent(), /A character or object \(a textured model with a skeleton\)/);
    assert.equal(await page.getByTestId("model-import-picture-person").isChecked(), true, "person is the default");
    assert.equal(await page.getByTestId("model-import-consent").isVisible(), true, "a person is asked for consent");
    assert.equal(await page.getByTestId("model-import-look-field").isVisible(), false, "negative: no face copy before the answer");
    await page.getByTestId("model-import-consent").selectOption("self");
    await page.getByTestId("model-import-look-field").waitFor({ state: "visible" }); // face copy, for a signed-in person's photo
    await page.getByTestId("model-import-consent").selectOption("");
    await page.getByTestId("model-import-picture-object").check();
    assert.equal(await page.getByTestId("model-import-consent").isVisible(), false, "negative: no consent question for an object");
    if (AXE) assert.deepEqual(await axe(page, "[data-testid=model-import-dialog]"), []);
    await page.getByTestId("model-import-submit").click();   // consent left empty on purpose
    await page.getByTestId("model-import-dialog").waitFor({ state: "detached", timeout: 15000 });
    assert.equal(state.posts.length, 1);
    assert.equal(state.posts[0].query.kind, "object");
    assert.equal(state.posts[0].query.consent, undefined, "negative: no consent is sent for an object");
    await page.waitForFunction((id) => document.querySelector("[data-testid=model-select-0]").value === `up:${id}`, ID);
    ok("AC-P13 one picture asks what is in it; a character or object sends kind=object with no consent and is picked when ready");
    await page.context().close();
  }
  {
    const { page, state } = await open("ok", { signedIn: true, post: (route) => json(route, 415, { error: "Making a 3D model from a picture of a character or object is not available here." }) });
    await selectOf(page, 0).selectOption("import");
    await page.getByTestId("model-import-file").setInputFiles({ name: "a.png", mimeType: "image/png", buffer: Buffer.from("png") });
    await page.getByTestId("model-import-picture-object").check();
    await page.getByTestId("model-import-submit").click();
    await page.getByTestId("model-import-error").waitFor({ state: "visible" });
    assert.match(await page.getByTestId("model-import-error").textContent(), /not available here/);
    assert.equal(await page.getByTestId("model-import-dialog").isVisible(), true, "the dialog stays open on a refusal");
    assert.equal(await page.getByTestId("model-import-submit").isEnabled(), true);
    // back to a person: the consent question returns and a send without it is stopped before any request
    await page.getByTestId("model-import-picture-person").check();
    assert.equal(await page.getByTestId("model-import-consent").isVisible(), true);
    const sent = state.posts.length;
    await page.getByTestId("model-import-submit").click();
    assert.match(await page.getByTestId("model-import-error").textContent(), /photo|who|agreed/i);
    assert.equal(state.posts.length, sent, "negative: a person picture without consent sends nothing");
    // several pictures do not ask what is in them
    await page.getByTestId("model-import-file").setInputFiles([
      { name: "a.png", mimeType: "image/png", buffer: Buffer.from("png") }, { name: "b.png", mimeType: "image/png", buffer: Buffer.from("png") }]);
    assert.equal(await page.getByTestId("model-import-picture").isVisible(), false);
    assert.equal(await page.getByTestId("model-import-consent").isVisible(), true);
    // a model file does not ask either
    await page.getByTestId("model-import-file").setInputFiles({ name: "m.glb", mimeType: "model/gltf-binary", buffer: Buffer.from("glTF") });
    assert.equal(await page.getByTestId("model-import-picture").isVisible(), false);
    ok("AC-P14 a refusal keeps the dialog open; person keeps the consent question; several pictures and model files do not ask");
    await page.context().close();
  }

  // TICKET-318b (image3d-intake.md AC-I35): signed out, a character or object picture says "Sign in" and sends nothing; a
  // session that ended after the page loaded gets the server's 401 in the same words and the dialog stays open
  {
    const { page, state } = await open("ok", { post: (route) => json(route, 202, { id: ID, status: "queued" }) }); // signed out (the default)
    await selectOf(page, 0).selectOption("import");
    await page.getByTestId("model-import-file").setInputFiles({ name: "armour.png", mimeType: "image/png", buffer: Buffer.from("png") });
    await page.getByTestId("model-import-picture-object").check();
    assert.match(await page.getByTestId("model-import-photo-hint").textContent(), /Sign in to make a 3D model from a picture/);
    await page.getByTestId("model-import-submit").click();
    await page.getByTestId("model-import-error").waitFor({ state: "visible" });
    assert.match(await page.getByTestId("model-import-error").textContent(), /Sign in to make a 3D model from a picture/);
    assert.equal(state.posts.length, 0, "negative: nothing is uploaded signed out");
    assert.equal(await page.getByTestId("model-import-dialog").isVisible(), true);
    // a person photo signed out is not blocked: it goes up as the grey body
    await page.getByTestId("model-import-picture-person").check();
    assert.doesNotMatch(await page.getByTestId("model-import-photo-hint").textContent(), /Sign in/);
    await page.context().close();
  }
  {
    const { page, state } = await open("ok", { signedIn: true, post: (route) => json(route, 401, { error: "Sign in to make a 3D model from a picture." }) });
    await selectOf(page, 0).selectOption("import");
    await page.getByTestId("model-import-file").setInputFiles({ name: "armour.png", mimeType: "image/png", buffer: Buffer.from("png") });
    await page.getByTestId("model-import-picture-object").check();
    await page.getByTestId("model-import-submit").click();
    await page.getByTestId("model-import-error").waitFor({ state: "visible" });
    assert.match(await page.getByTestId("model-import-error").textContent(), /Sign in to make a 3D model from a picture/);
    assert.equal(state.posts.length, 1, "the server was asked and refused");
    assert.equal(await page.getByTestId("model-import-dialog").isVisible(), true);
    assert.equal(await page.getByTestId("model-import-submit").isEnabled(), true);
    ok("TICKET-318b a signed-out character or object picture is blocked before the upload; a 401 from the server shows the same sentence");
    await page.context().close();
  }

  // AC-P15 (TICKET-375): a real take (harness case orphan-present, job e700387c7a1c) whose person skin has no body (the
  // stub resolves null): the line names who still shows Person, Skeleton or a model clears it for that figure
  {
    const { page } = await open("orphan-present");
    await page.waitForFunction(() => document.querySelector("[data-testid=model-picker]")?.dataset.ready === "true", null, { timeout: 20000 });
    const bodyNote = page.getByTestId("model-body-note");
    assert.deepEqual((await log(page)).filter((l) => l.startsWith("person:")).sort(), ["person:e700387c7a1c:trainer", "person:e700387c7a1c:you"]);
    assert.equal(await bodyNote.textContent(), "No 3D body for the trainer and you in this take, so Person shows the stick figures.");
    await page.getByText("3D", { exact: true }).first().click();   // this case opens on the Videos view
    assert.equal(await bodyNote.isVisible(), true);
    assert.ok((await bodyNote.boundingBox()).width > 100, "the line is shown at its full width, not the empty live region's 1 px");
    assert.equal(await bodyNote.getAttribute("role"), "status");
    assert.deepEqual(await axe(page, "[data-testid=model-picker]"), [], "axe with the line shown");
    await selectOf(page, 1).selectOption("lib:ual2-female");
    await page.waitForFunction(() => document.querySelector("[data-testid=model-body-note]")?.textContent.includes("the trainer in"), null, { timeout: 2000 });
    assert.equal(await bodyNote.textContent(), "No 3D body for the trainer in this take, so Person shows the stick figure.");
    await selectOf(page, 0).selectOption("skeleton");
    await page.waitForFunction(() => document.querySelector("[data-testid=model-body-note]")?.textContent === "", null, { timeout: 2000 });
    assert.ok((await bodyNote.boundingBox()).width <= 1, "negative: nobody shows Person, no line on screen");
    assert.equal(await bodyNote.getAttribute("role"), "status", "the empty live region stays in the page for the next announcement");
    ok("AC-P15 Person with no body on a real take says who; a model or Skeleton clears it for that figure");
    await page.context().close();
  }

  // AC-P8: Watch (mountViewer, one figure, no job): the picker is there, Person is the stick figure, nothing is requested
  {
    const { page, bad } = await open("viewer");
    await selectOf(page, 0).waitFor();
    assert.equal(await page.locator("[data-testid^=model-select-]").count(), 1);
    assert.equal(await selectOf(page, 0).inputValue(), "person");
    assert.deepEqual((await log(page)).filter((l) => l.startsWith("person:")), []);   // no job: the person skin is never asked for
    assert.ok(await page.locator("canvas").count() > 0);
    assert.deepEqual(bad, []);
    ok("AC-P8 Watch shows the picker; Person is the stick figure with no request");
    await page.context().close();
  }

  // AC-P9: no model server at all (library and api fail): Person and Skeleton still work
  {
    const context = await browser.newContext({ viewport: { width: 412, height: 915 }, reducedMotion: "reduce" });
    const page = await context.newPage();
    await page.route("**/models/library/library.json", (route) => route.fulfill({ status: 404, body: "no" }));
    await page.route(/\/api\/models(\?.*)?$/, (route) => route.fulfill({ status: 500, body: "no" }));
    await page.goto(`http://127.0.0.1:${port}/tests/part7/harness/result.html?case=ok`);
    await page.waitForFunction(() => window.__ready === true);
    await selectOf(page, 0).waitFor();
    assert.deepEqual(await optionValues(page, 0), ["person", "skeleton", "import"]);
    ok("AC-P9 with no catalog the picker still offers Person, Skeleton and Import");
    await context.close();
  }

  // AC-P10: a character that cannot load keeps the last look and says so
  {
    const { page } = await open("ok", { withSkins: false });
    await page.route("**/web/skin/character.js", (route) => route.fulfill({ contentType: "text/javascript", body: "export async function loadCharacter() { throw new Error('bad'); }" }));
    await page.route("**/web/skin/person-skin.js", (route) => route.fulfill({ contentType: "text/javascript", body: PERSON_STUB }));
    await page.reload();
    await page.waitForFunction(() => window.__ready === true);
    await selectOf(page, 1).waitFor();
    await page.waitForFunction(() => document.querySelector("[data-testid=model-picker]")?.dataset.ready === "true");
    await selectOf(page, 1).selectOption("lib:ual2-female");
    await page.getByTestId("model-choice-note").filter({ hasText: "could not be shown" }).waitFor();
    assert.equal(await selectOf(page, 1).inputValue(), "person");
    assert.equal(await page.evaluate(() => localStorage.getItem("simon.model.you")), null);
    ok("AC-P10 a model that cannot load leaves the figure as it was and says so");
    await page.context().close();
  }

  // AC-P11: multi-compare: a trainer row and one row per person; each person has their own choice
  {
    const { page, bad } = await open("ok");
    await page.evaluate(async () => {
      const replay = await fetch("../../../fixtures/input/replay.json").then((r) => r.json());
      const mod = await import("../../../web/multi-compare.js");
      const host = document.createElement("div");
      host.id = "multi";
      document.body.append(host);
      window.__multi = await mod.mountMultiCompare(host, [{ id: "p1", label: "Ann", replay, job: "g1" }, { id: "p2", label: "Bo", replay, job: "g1" }]);
    });
    const multi = page.locator("#multi");
    await multi.locator("[data-testid=model-select-2]").waitFor();
    assert.equal(await multi.locator("[data-testid^=model-select-]").count(), 3);
    await multi.locator("[data-testid=model-select-1]").selectOption("lib:ual2-female");
    await multi.locator("[data-testid=model-select-2]").selectOption("lib:rigged-figure");
    await page.waitForFunction(() => ["character:ual2-female", "character:rigged-figure"].every((s) => (window.__skinLog || []).includes(s)));
    assert.equal(await page.evaluate(() => localStorage.getItem("simon.model.p1")), "lib:ual2-female");
    assert.equal(await page.evaluate(() => localStorage.getItem("simon.model.p2")), "lib:rigged-figure");
    const seen = await log(page);
    assert.ok(seen.includes("person:g1:trainer"));
    assert.ok(!seen.some((l) => l.startsWith("person:") && l !== "person:g1:trainer"), "a group person has no mesh of their own: Person stays sticks");
    assert.deepEqual(bad, []);
    // TICKET-375: the trainer row asks (group job, trainer) and the stub has no body: only the trainer is named; the people
    // have no take of their own (job null), so Person is their stick figure by design and the line leaves them out
    assert.equal(await multi.getByTestId("model-body-note").textContent(), "No 3D body for the trainer in this take, so Person shows the stick figure.");
    ok("AC-P11 multi-compare keeps a choice per person, keyed by person id");
    await page.context().close();
  }

  // AC-P12: axe on the picker
  {
    const { page } = await open("ok", { mine: MINE });
    await selectOf(page, 0).waitFor();
    const v = await axe(page, "[data-testid=model-picker]");
    assert.deepEqual(v, []);
    ok(`AC-P12 axe reports nothing on the picker${AXE ? "" : " (axe-core not installed: skipped)"}`);
    await page.context().close();
  }
} catch (err) {
  failures.push(err);
  console.error(err);
}
await browser.close();
console.log(`${passed} passed, ${failures.length} failed`);
process.exit(failures.length ? 1 : 0);
