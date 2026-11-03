// Browser drive at 412x915 of the signed-in devices card against the REAL app (tests/part7/real_app.py: real sign-in, real
// sessions, real web/; only Part 6 is a stub and mail goes to the file outbox). Cases: signedout, endone, others,
// twoaccounts, keyboard. No --case runs all. Every browser context is a separate "device" with its own User-Agent.
//   /home/gingy/claude-template/scripts/with-browser-slot.sh node tests/part7/devices.browser.mjs [--case endone]
// Screenshots (not committed): SHOTS_DIR or demos/rubric/TICKET-235/.
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const req = createRequire(path.join(process.env.PLAYWRIGHT_DIR || path.resolve(here, "../../node_modules"), "x.js"));
const { chromium } = req("playwright");
const SHOTS = process.env.SHOTS_DIR || path.resolve(here, "../../demos/rubric/TICKET-235");
fs.mkdirSync(SHOTS, { recursive: true });
const only = process.argv.includes("--case") ? process.argv[process.argv.indexOf("--case") + 1] : null;

const PORT = 7900 + Math.floor(Math.random() * 40) * 2;
const BASE = `http://127.0.0.1:${PORT}/simon-part-7`;
const HELPER = `http://127.0.0.1:${PORT + 1}`;
const server = spawn("uv", ["run", "python", path.join(here, "real_app.py"), String(PORT), String(PORT + 1)], { stdio: ["ignore", "pipe", "inherit"] });
await new Promise((resolve, reject) => {
  server.stdout.on("data", (d) => { if (String(d).includes("ready")) resolve(); });
  server.on("exit", (code) => reject(new Error(`real_app exited ${code}`)));
  setTimeout(() => reject(new Error("real_app did not start")), 60000);
});

const UA = {
  chrome: "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
  firefoxAndroid: "Mozilla/5.0 (Android 14; Mobile; rv:126.0) Gecko/126.0 Firefox/126.0",
  safariIphone: "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1",
  edgeWindows: "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36 Edg/126.0.0.0",
};
const browser = await chromium.launch();
const newCtx = (userAgent = UA.chrome) => browser.newContext({ viewport: { width: 412, height: 915 }, deviceScaleFactor: 2, hasTouch: true, userAgent });
const errors = [];
let passed = 0;
const ok = (name) => { passed++; console.log(`ok - ${name}`); };
const tid = (page, id) => page.getByTestId(id);
const shot = (page, name) => page.screenshot({ path: path.join(SHOTS, name), fullPage: true });
const EXPECTED = /status of (401|404)/; // a signed-out session and an unknown id are normal answers here

async function open(ctx, hash = "") {
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
  const { code } = await (await fetch(`${HELPER}/code?email=${encodeURIComponent(email)}`)).json();
  assert.match(code, /^\d{6}$/);
  await tid(page, "auth-code").fill(code);
  await tid(page, "auth-verify").tap();
  await tid(page, "me-email").waitFor();
}

/** A new device (own context and User-Agent) signed in as `email`. */
async function device(email, userAgent) {
  const page = await open(await newCtx(userAgent));
  await signIn(page, email);
  return page;
}

async function openDevices(page) {
  await page.evaluate(() => { location.hash = "#/profile"; });
  await tid(page, "devices-list").waitFor();
}

const apiList = (page) => page.evaluate(async () => { const r = await fetch("api/me/sessions"); return { status: r.status, body: await r.json() }; });
const names = async (page) => (await page.locator('[data-testid^="device-name-"]').allInnerTexts());

const cases = {
  async signedout() {
    const page = await open(await newCtx(), "#/profile");
    await tid(page, "me-signed-out").waitFor(); // #/profile opens the Me page: its account card says to sign in
    assert.equal(await tid(page, "devices").count(), 0, "negative: no devices card when signed out");
    assert.equal((await apiList(page)).status, 401, "the list answers 401 signed out");
    assert.equal(/Signed-in devices/.test(await page.locator("#app").innerText()), false, "negative: no trace of the feature in the page");
    await shot(page, "1-signed-out.png");
    ok("signed out: no devices card, no words of it on the page, the list route answers 401");
  },

  async endone() {
    const a = await device("ann@example.com", UA.chrome);
    const b = await device("ann@example.com", UA.firefoxAndroid);
    await openDevices(a);
    assert.deepEqual((await names(a)).sort(), ["Chrome on Linux", "Firefox on Android"]);
    assert.equal(await tid(a, "devices-title").innerText(), "Signed-in devices");
    const current = a.locator('[data-current="true"]');
    assert.equal(await current.count(), 1);
    assert.match(await current.innerText(), /Chrome on Linux[\s\S]*This device/, "this browser is marked");
    assert.equal(await current.getByRole("button").count(), 0, "negative: this device has no Sign out button");
    const row = a.locator('[data-current="false"]');
    assert.match(await row.innerText(), /Firefox on Android/);
    assert.match(await row.innerText(), /Last active around/);
    await shot(a, "2-two-devices.png");

    // B is signed in right now (witness 1: its own page shows the signed-in Me page)
    await b.reload();
    await tid(b, "me-email").waitFor();

    await row.getByRole("button", { name: "Sign out Firefox on Android" }).tap();
    await a.waitForFunction(() => document.querySelector('[data-testid="devices-note"]')?.textContent === "Signed out.");
    assert.deepEqual(await names(a), ["Chrome on Linux"]);
    assert.equal(await tid(a, "devices-end-others").count(), 0, "negative: no Sign out everywhere else with one device");
    assert.equal(await tid(a, "devices-empty").innerText(), "No other devices are signed in.");
    assert.equal(await a.evaluate(() => document.activeElement?.getAttribute("data-testid")), "devices-title", "focus stays in the card");
    await shot(a, "3-after-sign-out.png");

    // witness 1: B's next request is refused and its page is the signed-out page
    assert.equal((await apiList(b)).status, 401, "negative: the ended session gets 401 on its next request");
    await b.reload();
    await b.evaluate(() => { location.hash = "#/profile"; });
    await tid(b, "me-signed-out").waitFor(); // #/profile opens the Me page: its account card says to sign in
    assert.equal(await tid(b, "profile-form").count(), 0);
    // witness 2: A's own list, read from the server, holds one session and it is A's
    const list = await apiList(a);
    assert.equal(list.status, 200);
    assert.equal(list.body.length, 1);
    assert.equal(list.body[0].current, true);
    ok("end one: A lists both devices, ends B, B is signed out on its next request and reload, A keeps its own");
  },

  async others() {
    const a = await device("cy@example.com", UA.chrome);
    const b = await device("cy@example.com", UA.firefoxAndroid);
    const c = await device("cy@example.com", UA.edgeWindows);
    await openDevices(a);
    assert.equal((await names(a)).length, 3);
    await shot(a, "4-three-devices.png");
    await tid(a, "devices-end-others").tap();
    await a.waitForFunction(() => document.querySelector('[data-testid="devices-note"]')?.textContent === "Signed out 2 devices.");
    assert.deepEqual(await names(a), ["Chrome on Linux"]);
    for (const other of [b, c]) {
      assert.equal((await apiList(other)).status, 401, "negative: each ended session gets 401 on its next request");
      await other.reload();
      await other.evaluate(() => { location.hash = "#/profile"; });
      await tid(other, "me-signed-out").waitFor(); // #/profile opens the Me page: its account card says to sign in
    }
    assert.equal((await apiList(a)).status, 200, "A is still signed in");
    await a.reload();
    await tid(a, "devices-list").waitFor();
    ok("sign out everywhere else: both other devices are refused at once, this one stays");
  },

  async twoaccounts() {
    const ann = await device("dee@example.com", UA.chrome);
    const bob = await device("eli@example.com", UA.safariIphone);
    await openDevices(ann);
    await openDevices(bob);
    assert.deepEqual(await names(ann), ["Chrome on Linux"]);
    assert.deepEqual(await names(bob), ["Safari on iPhone"]);
    assert.equal((await ann.content()).includes("Safari on iPhone"), false, "negative: the other account's device is not on this page");
    assert.equal(JSON.stringify((await apiList(ann)).body).includes("Safari"), false, "negative: nor in the list the server sent");
    // A cannot end B's session by guessing: the id is only in B's list, and a made-up id is a 404
    const bobId = (await apiList(bob)).body[0].id;
    const tried = await ann.evaluate(async (id) => {
      const r = await fetch(`api/me/sessions/${id}/end`, { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
      return r.status;
    }, bobId);
    assert.equal(tried, 404, "another account's session answers 404, not 403");
    assert.equal((await apiList(bob)).status, 200, "negative: B is still signed in");
    await shot(ann, "5-own-device-only.png");
    ok("two accounts: each list holds only its own device; ending the other's id answers 404 and ends nothing");
  },

  async keyboard() {
    await device("fay@example.com", UA.firefoxAndroid);
    const a = await device("fay@example.com", UA.chrome);
    await openDevices(a);
    await tid(a, "devices-title").focus();
    await a.keyboard.press("Tab"); // the next stop after the heading is the first Sign out button
    assert.equal(await a.evaluate(() => document.activeElement?.getAttribute("data-testid")), "device-end-1");
    const outline = await a.evaluate(() => getComputedStyle(document.activeElement).outlineStyle);
    assert.notEqual(outline, "none", "the focused button shows an outline");
    await a.keyboard.press("Enter");
    await a.waitForFunction(() => document.querySelector('[data-testid="devices-note"]')?.textContent === "Signed out.");
    assert.equal(await a.evaluate(() => document.activeElement?.getAttribute("data-testid")), "devices-title");
    ok("keyboard: Sign out works with Enter, the focus ring shows, focus moves to the card heading");
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
