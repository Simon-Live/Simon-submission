// Browser drive at 412x915 of the profile page in the real app against tests/part7/fake_profile.py (a fake of the
// profile routes with a SEEDED history list: invented rows, not a real account), on the Me page (#/me). Cases:
// signed-out (#/profile opens #/me), edit-reload-delete,
// two-accounts, my 3D model (fake web/skin/ modules), no model files, keyboard. No --case runs all.
//   /home/gingy/claude-template/scripts/with-browser-slot.sh node tests/part7/profile.browser.mjs [--case edit]
// Screenshots (not committed): SHOTS_DIR or demos/rubric/TICKET-231/.
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const req = createRequire(path.join(process.env.PLAYWRIGHT_DIR || path.resolve(here, "../../node_modules"), "x.js"));
const { chromium } = req("playwright");
const SHOTS = process.env.SHOTS_DIR || path.resolve(here, "../../demos/rubric/TICKET-231");
fs.mkdirSync(SHOTS, { recursive: true });
const only = process.argv.includes("--case") ? process.argv[process.argv.indexOf("--case") + 1] : null;

const PORT = 7800 + Math.floor(Math.random() * 90);
const BASE = `http://127.0.0.1:${PORT}`;
const server = spawn("python3", [path.join(here, "fake_profile.py"), String(PORT)], { stdio: "inherit" });
for (let i = 0; i < 50; i++) {
  try { if ((await fetch(`${BASE}/api/health`)).ok) break; } catch { await new Promise((r) => setTimeout(r, 100)); }
}

const browser = await chromium.launch();
const newCtx = () => browser.newContext({ viewport: { width: 412, height: 915 }, deviceScaleFactor: 2, hasTouch: true });
const errors = [];
let passed = 0;
const ok = (name) => { passed++; console.log(`ok - ${name}`); };
const getJson = async (p) => (await fetch(`${BASE}/${p}`)).json();
const reset = () => fetch(`${BASE}/__test/auth`, { method: "POST", body: JSON.stringify({ reset: true, available: true }) });
const tid = (page, id) => page.getByTestId(id);
const shot = (page, name) => page.screenshot({ path: path.join(SHOTS, name), fullPage: true });
// the share list reaches the profile page through web/share.js (mountProfileExtras gets its mount function)
const EXPECTED = /status of (400|401|404)|share-list\.js/;

async function open(ctx, hash = "/") {
  const page = await ctx.newPage();
  page.on("console", (m) => { if (m.type() === "error" && !EXPECTED.test(m.text())) errors.push(`${hash}: ${m.text()}`); });
  page.on("pageerror", (e) => errors.push(`${hash}: ${e.message}`));
  await page.goto(`${BASE}/${hash}`);
  return page;
}

async function signIn(page, email) {
  await page.evaluate(() => { location.hash = "#/signin"; });
  await tid(page, "auth-email").fill(email);
  await tid(page, "auth-send").tap();
  await tid(page, "auth-code").waitFor();
  const mail = (await getJson("__test/outbox")).outbox.filter((m) => m.email === email).at(-1);
  await tid(page, "auth-code").fill(mail.code);
  await tid(page, "auth-verify").tap();
  await tid(page, "me-email").waitFor();
}

const appText = (page) => page.locator("#app").innerText();

// Small fakes of the model-selection modules (web/skin/, lane/ms-integrate), served in place of the real files so the
// "My 3D model" section is driven the same way before and after that branch is merged. Test only.
const FAKE_SKIN = {
  "catalog.js": `const lib = [{ id: "ual1-mannequin", name: "Mannequin", kind: "library" }];
    export async function list() { return [...lib, ...JSON.parse(sessionStorage.getItem("fake-mine") || "[]")]; }`,
  "import-dialog.js": `export async function openImportDialog() {
    const id = "a".repeat(32);
    sessionStorage.setItem("fake-mine", JSON.stringify([{ id, name: "My upload", kind: "upload" }]));
    return { id };
  }`,
  "picker.js": `export const choiceIdOf = (e) => (e.kind === "library" ? "lib" : "up") + ":" + e.id;`,
};
const fakeSkin = (ctx) => ctx.route(/\/skin\/(catalog|import-dialog|picker)\.js$/, (r) =>
  r.fulfill({ contentType: "text/javascript", body: FAKE_SKIN[new URL(r.request().url()).pathname.split("/").pop()] }));

const cases = {
  async signedout() {
    await reset();
    const page = await open(await newCtx(), "#/profile");
    await tid(page, "me-signed-out").waitFor();
    assert.equal(await page.evaluate(() => location.hash), "#/me", "the old address opens the Me page");
    assert.equal(await tid(page, "profile-link").count(), 0, "negative: no Profile link in the header");
    assert.equal(await tid(page, "profile-form").count(), 0, "negative: no form when signed out");
    await page.evaluate(() => { location.hash = "#/"; });
    await tid(page, "me-link").tap(); // signed out, Me is one tap from the header, and Sign in stays beside it
    await page.waitForFunction(() => location.hash === "#/me");
    await tid(page, "me-signed-out").waitFor();
    assert.equal(await tid(page, "auth-link").innerText(), "Sign in");
    await page.evaluate(() => { location.hash = "#/"; });
    const before = await page.evaluate(() => history.length);
    await page.evaluate(() => { location.hash = "#/profile/anything"; });
    await page.waitForFunction(() => location.hash === "#/me");
    await tid(page, "me-signed-out").waitFor();
    assert.equal(await page.evaluate(() => history.length), before + 1, "negative: the redirect replaces the entry, it adds none");
    await page.goBack();
    await page.waitForFunction(() => location.hash === "#/");
    assert.equal(await page.evaluate(() => location.hash), "#/", "Back leaves the Me page, no loop through #/profile");
    await shot(page, "1-signed-out.png");
    ok("signed out: #/profile and #/profile/<x> open the Me page, which asks to sign in; no Profile link");
  },

  async edit() {
    await reset();
    const page = await open(await newCtx());
    await signIn(page, "sam@example.com");
    await page.evaluate(() => { location.hash = "#/"; });
    await tid(page, "auth-link").waitFor();
    assert.equal(await tid(page, "profile-link").count(), 0, "negative: one entry point, no second Profile link");
    await tid(page, "auth-link").tap();
    await tid(page, "profile-form").waitFor();
    assert.equal(await page.evaluate(() => location.hash), "#/me");
    await tid(page, "me-email").waitFor(); // the account card and the profile are one page
    assert.equal(await tid(page, "me-profile").locator("h1").count(), 0, "the profile section adds no h1 to the Me page");
    assert.equal(await tid(page, "profile-who").innerText(), "You", "a new account shows You");
    assert.equal(await page.getByLabel("Show my display name to other people").isChecked(), false);
    assert.equal(await page.getByLabel("Credit me as the trainer on movements I make").isChecked(), false);
    assert.match(await tid(page, "profile-movements-0").innerText(), /Lateral raise/);
    assert.match(await tid(page, "profile-summary").innerText(), /3 takes kept across 1 movement/);
    await shot(page, "2-empty-account.png");

    // a bad name is refused on the page and nothing reaches the server
    await page.getByLabel("Display name", { exact: true }).fill("sam@example.com");
    await tid(page, "profile-save").tap();
    assert.match(await tid(page, "profile-name-error").innerText(), /no @ sign/);
    assert.deepEqual(await getJson("__test/profiles"), {}, "negative: a refused name saves nothing");

    await page.getByLabel("Display name", { exact: true }).fill("Sam");
    await tid(page, "profile-avatar-tide").check({ force: true });
    await page.getByLabel("Dance", { exact: true }).check();
    await page.getByLabel("Learn the moves", { exact: true }).check();
    await page.getByLabel("Show my display name to other people").check();
    await tid(page, "profile-save").tap();
    await page.waitForFunction(() => document.querySelector('[data-testid="profile-save-note"]')?.textContent === "Saved.");
    await shot(page, "3-saved.png");
    const kept = (await getJson("__test/profiles"))["sam@example.com"];
    assert.deepEqual(kept, { public_name: "Sam", avatar: "tide", modes: ["dance"], goals: ["learn_the_moves"], show_name: true, credit_me_as_trainer: false, default_model_id: null, created_utc: null, updated_utc: null });

    // reload: what was saved is what comes back
    await page.reload();
    await tid(page, "profile-form").waitFor();
    assert.equal(await page.getByLabel("Display name", { exact: true }).inputValue(), "Sam");
    assert.equal(await tid(page, "profile-avatar-tide").isChecked(), true);
    assert.equal(await page.getByLabel("Dance", { exact: true }).isChecked(), true);
    assert.equal(await page.getByLabel("Show my display name to other people").isChecked(), true);
    assert.equal(await page.getByLabel("Credit me as the trainer on movements I make").isChecked(), false);
    assert.match(await tid(page, "profile-who").innerText(), /Sam/);

    // negative: the email is nowhere in the profile section; the account card names it once, to its owner
    const body = await tid(page, "me-profile").innerText();
    assert.equal(body.toLowerCase().includes("sam@example.com"), false, "negative: no email in the profile section");
    assert.doesNotMatch(body, /\S+@\S+\.\S+/);
    assert.equal((await tid(page, "me-profile").innerHTML()).includes("sam@example.com"), false, "negative: no email in its markup either");
    assert.equal((await appText(page)).split("sam@example.com").length - 1, 1, "the page names the email once, in the account card");

    // delete asks first
    await tid(page, "profile-delete").tap();
    await tid(page, "profile-delete-sure").waitFor();
    await tid(page, "profile-delete-no").tap();
    assert.equal(await tid(page, "profile-delete-sure").isVisible(), false);
    assert.equal((await getJson("__test/profiles"))["sam@example.com"].public_name, "Sam", "negative: Keep them deletes nothing");
    await tid(page, "profile-delete").tap();
    await shot(page, "4-delete-confirm.png");
    await tid(page, "profile-delete-yes").tap();
    await page.waitForFunction(() => document.querySelector('[data-testid="profile-delete-note"]')?.textContent === "Profile details deleted.");
    assert.deepEqual((await getJson("__test/profiles"))["sam@example.com"], { public_name: null, avatar: null, modes: [], goals: [], show_name: false, credit_me_as_trainer: false, default_model_id: null, created_utc: null, updated_utc: null });
    assert.equal(await tid(page, "profile-who").innerText(), "You");
    assert.equal(await page.getByLabel("Display name", { exact: true }).inputValue(), "");
    ok("edit: sign in, the Me link, bad name refused, save, reload keeps it, no email on the page, delete confirmed");
  },

  async twoaccounts() {
    await reset();
    const a = await open(await newCtx());
    await signIn(a, "ann@example.com");
    await a.evaluate(() => { location.hash = "#/profile"; });
    await tid(a, "profile-form").waitFor();
    await a.getByLabel("Display name", { exact: true }).fill("Ann Private");
    await tid(a, "profile-save").tap();
    await a.waitForFunction(() => document.querySelector('[data-testid="profile-save-note"]')?.textContent === "Saved.");
    const b = await open(await newCtx());
    await signIn(b, "bo@example.com");
    await b.evaluate(() => { location.hash = "#/profile"; });
    await tid(b, "profile-form").waitFor();
    assert.equal(await tid(b, "profile-who").innerText(), "You");
    assert.equal(await b.getByLabel("Display name", { exact: true }).inputValue(), "");
    assert.equal((await b.content()).includes("Ann Private"), false, "negative: another account's name is not on this page");
    ok("two accounts: the second account sees its own empty profile, never the first's name");
  },

  async mymodel() {
    await reset();
    const ctx = await newCtx();
    await fakeSkin(ctx);
    const page = await open(ctx);
    await signIn(page, "mo@example.com");
    await page.evaluate(() => { location.hash = "#/profile"; }); // the old address lands on the same page
    await tid(page, "my-model-select").waitFor();
    assert.equal(await tid(page, "my-model-device-only").count(), 0, "negative: signed in, the choice is not device only");
    assert.deepEqual(await page.locator('[data-testid="my-model-select"] option').evaluateAll((os) => os.map((o) => o.value)), ["person", "skeleton", "lib:ual1-mannequin"]);
    await tid(page, "my-model-select").selectOption("lib:ual1-mannequin");
    await tid(page, "my-model-save").tap();
    await page.waitForFunction(() => document.querySelector('[data-testid="my-model-note"]')?.textContent === "Saved. Your results open with this model.");
    assert.equal((await getJson("__test/profiles"))["mo@example.com"].default_model_id, "lib:ual1-mannequin", "witness: the server keeps it");
    assert.equal(await page.evaluate(() => localStorage.getItem("simon.model.you")), null, "negative: a signed-in default is not written to this device");
    await page.reload();
    await tid(page, "my-model-select").waitFor();
    assert.equal(await tid(page, "my-model-select").inputValue(), "lib:ual1-mannequin", "witness: the page shows it after a reload");
    // the preview: the real stage plays the built-in movement, Play and Pause toggle, a drag orbits
    const preview = page.locator('[data-testid="my-model-preview"]');
    await page.locator('[data-testid="my-model-preview"][data-motion="fixture"]').waitFor();
    await tid(page, "my-model-stage").locator("canvas").waitFor();
    await tid(page, "my-model-play").tap();
    assert.equal(await preview.getAttribute("data-playing"), "true");
    assert.equal(await tid(page, "my-model-play").innerText(), "Pause");
    const before = await preview.getAttribute("data-camera-azimuth");
    const box = await tid(page, "my-model-stage").boundingBox();
    await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
    await page.mouse.down();
    await page.mouse.move(box.x + box.width / 2 + 120, box.y + box.height / 2, { steps: 6 });
    await page.mouse.up();
    assert.notEqual(await preview.getAttribute("data-camera-azimuth"), before, "a drag turns the figure");
    await tid(page, "my-model-play").tap();
    assert.equal(await preview.getAttribute("data-playing"), "false", "negative: Pause stops it");
    await shot(page, "6-my-model.png");

    await tid(page, "my-model-upload").tap();
    await page.waitForFunction(() => document.querySelector('[data-testid="my-model-note"]')?.textContent?.startsWith("Model added and picked."));
    const up = `up:${"a".repeat(32)}`;
    assert.equal(await tid(page, "my-model-select").inputValue(), up, "the uploaded model is picked");
    await tid(page, "my-model-save").tap();
    await page.waitForFunction(() => document.querySelector('[data-testid="my-model-note"]')?.textContent === "Saved. Your results open with this model.");
    assert.equal((await getJson("__test/profiles"))["mo@example.com"].default_model_id, up);

    await tid(page, "profile-delete").tap();
    await tid(page, "profile-delete-yes").tap();
    await page.waitForFunction(() => document.querySelector('[data-testid="profile-delete-note"]')?.textContent === "Profile details deleted.");
    await page.waitForFunction(() => document.querySelector('[data-testid="my-model-select"]')?.value === "person");
    assert.equal((await getJson("__test/profiles"))["mo@example.com"].default_model_id, null, "deleting the profile details clears the default");
    ok("my 3D model: pick and save to the account, reload keeps it, upload picks the new model, delete clears it");

    const anon = await newCtx();
    await fakeSkin(anon);
    const out = await open(anon, "#/me");
    await tid(out, "me-signed-out").waitFor();
    await tid(out, "my-model-device-only").waitFor();
    await tid(out, "my-model-select").selectOption("skeleton");
    await tid(out, "my-model-save").tap();
    await out.waitForFunction(() => document.querySelector('[data-testid="my-model-note"]')?.textContent === "Saved on this device.");
    assert.equal(await out.evaluate(() => localStorage.getItem("simon.model.you")), "skeleton", "signed out, the picker's own key holds it");
    assert.equal(await tid(out, "profile-form").count(), 0, "negative: no profile form signed out");
    ok("my 3D model signed out: kept on this device under the picker's key, next to the unchanged sign-in prompt");

    // a result's own picker (the real web/skin/ files): signed in it says where the default is set; a pick there is kept
    // for that take on this device and survives a reload, signed in or out, and never becomes a default
    const youChoice = (p) => p.evaluate(() => document.querySelector('[data-testid="model-picker"]')?.dataset.choices?.split(",")[1]);
    const takeKeys = (p) => p.evaluate(() => Object.keys(localStorage).filter((k) => k.startsWith("simon.model.you.")).map((k) => [k, localStorage.getItem(k)]));
    const res = await open(await newCtx());
    await signIn(res, "ri@example.com");
    await res.evaluate(() => { location.hash = "#/result/fixture"; });
    await tid(res, "model-default-hint").waitFor();
    assert.equal(await tid(res, "model-default-hint").innerText(), "Your default is set on Me.");
    assert.equal(await tid(res, "model-default-hint-link").getAttribute("href"), "#/me");
    await tid(res, "model-select-1").selectOption("skeleton");
    await res.waitForFunction(() => document.querySelector('[data-testid="model-picker"]')?.dataset.choices?.endsWith(",skeleton"));
    await res.reload();
    await res.locator('[data-testid="model-picker"][data-ready="true"]').waitFor();
    assert.equal(await youChoice(res), "skeleton", "signed in: the pick survives a reload of that result");
    assert.deepEqual(await takeKeys(res), [["simon.model.you.fixture", "skeleton"]], "kept under the take's key");
    assert.equal((await getJson("__test/profiles"))["ri@example.com"]?.default_model_id ?? null, null, "negative: a pick on a result writes no account default");
    assert.equal(await res.evaluate(() => localStorage.getItem("simon.model.you")), null, "negative: nor the device default");
    const anonResult = await open(await newCtx(), "#/result/fixture");
    await anonResult.locator('[data-testid="model-picker"][data-ready="true"]').waitFor();
    assert.equal(await tid(anonResult, "model-default-hint").count(), 0, "negative: no hint signed out");
    await tid(anonResult, "model-select-1").selectOption("skeleton");
    await anonResult.waitForFunction(() => document.querySelector('[data-testid="model-picker"]')?.dataset.choices?.endsWith(",skeleton"));
    await anonResult.reload();
    await anonResult.locator('[data-testid="model-picker"][data-ready="true"]').waitFor();
    assert.equal(await youChoice(anonResult), "skeleton", "signed out: the pick survives a reload too");
    assert.equal(await anonResult.evaluate(() => localStorage.getItem("simon.model.you")), null, "negative: signed out it is not the device default either");
    ok("a result's picker: the hint signed in; a pick survives a reload of that take, signed in or out, and writes no default");

    // Person in the Me preview with the real catalog: the first built-in mannequin stands in, and a line says so
    const real = await open(await newCtx(), "#/me");
    await real.locator('[data-testid="my-model-preview"][data-model]:not([data-model=""])').waitFor({ timeout: 30000 });
    assert.equal(await tid(real, "my-model-select").inputValue(), "person");
    assert.equal(await real.locator('[data-testid="my-model-preview"]').getAttribute("data-model"), "ual2-mannequin-f", "the first built-in mannequin");
    assert.equal(await tid(real, "my-model-preview-status").innerText(), "Person shows you as filmed on a result. Here it uses the mannequin.");
    await real.getByTestId("splash").waitFor({ state: "detached" }); // the first-visit splash fades out first
    await tid(real, "my-model-stage").scrollIntoViewIfNeeded();
    await real.screenshot({ path: path.join(SHOTS, "7-person-mannequin.png") });
    ok("Me preview: Person with no mesh shows the first built-in mannequin and says so");
  },

  async nomodels() {
    await reset();
    const ctx = await newCtx();
    await ctx.route(/\/skin\/catalog\.js$/, (r) => r.fulfill({ status: 404, body: "" }));
    const page = await open(ctx, "#/me");
    await tid(page, "my-model-unavailable").waitFor();
    assert.equal(await tid(page, "my-model-unavailable").innerText(), "Choosing a 3D model is not available yet.");
    assert.equal(await tid(page, "my-model-select").count(), 0, "negative: nothing to press without the model files");
    ok("no model files: one short line, no controls");
  },

  async keyboard() {
    await reset();
    const page = await open(await newCtx());
    await signIn(page, "kay@example.com");
    await page.evaluate(() => { location.hash = "#/profile"; });
    await tid(page, "profile-form").waitFor();
    const order = [];
    await tid(page, "profile-title").focus(); // the section title (tabindex -1): Tab moves on into the form
    for (let i = 0; i < 12; i++) {
      await page.keyboard.press("Tab");
      order.push(await page.evaluate(() => document.activeElement?.getAttribute("data-testid") || document.activeElement?.tagName));
    }
    assert.equal(order[0], "profile-name", "first stop is the display name");
    assert.ok(order.indexOf("profile-save") === -1 || order.indexOf("profile-show-name") < order.indexOf("profile-save"), "privacy comes before Save");
    const outline = await page.evaluate(() => { const el = document.querySelector('[data-testid="profile-name"]'); el.focus(); return getComputedStyle(el).outlineStyle; });
    assert.notEqual(outline, "none", "the focused field shows an outline");
    await shot(page, "5-keyboard.png");
    ok("keyboard: tab order starts at the name, privacy before Save, focus outline shown");
  },
};

try {
  for (const [name, fn] of Object.entries(cases)) if (!only || only === name) await fn();
} finally {
  await browser.close();
  server.kill();
}
assert.deepEqual(errors, [], `console errors: ${errors.join(" | ")}`);
console.log(`${passed} browser checks passed`);
