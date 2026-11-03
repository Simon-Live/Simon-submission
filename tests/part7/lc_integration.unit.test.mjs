// The long-context integration glue (TICKET-175): routes, header link and the route attribute, read from the source
// because app.js needs a browser. The behaviour behind each line has its own tests (auth, history, clientlog).
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

const web = (f) => readFileSync(fileURLToPath(new URL(`../../web/${f}`, import.meta.url)), "utf8");

test("app.js routes sign-in, the account page and one movement's history, all loaded on first use", () => {
  const app = web("app.js");
  const me = web("me-page.js"); // the one Me page (docs/specs/me-page.md)
  for (const re of ["signin$", "signin\\/([^/]+)$", "me$", "me\\/([^/]+)$"]) assert.ok(app.includes(`[/^${re}/`), re);
  assert.match(app, /import\("\.\/auth\.js"\)/);
  assert.match(app, /import\("\.\/history\.js"\)/);
  assert.match(me, /import\("\.\/auth\.js"\)/);
  assert.match(me, /import\("\.\/history\.js"\)/);
  for (const src of [app, me]) assert.doesNotMatch(src, /^import .* from "\.\/(auth|history)\.js"/m, "negative: anonymous visitors download neither module at start");
  assert.match(me, /Your takes over time/, "#/me embeds the history list");
});

test("the route attribute keeps the route name only, never a sign-in token or job id", () => {
  const app = web("app.js");
  assert.match(app, /dataset\.route = routeName\(location\.hash\)/);
  assert.doesNotMatch(app, /dataset\.route = location\.hash/);
});

test("the header has the auth link slot after Record, hidden until auth.js decides", () => {
  assert.match(web("index.html"), /data-testid="nav-record">Record<\/a><span id="auth-link" hidden><\/span>/);
  assert.match(web("app.js"), /mountAuthLink\(document\.getElementById\("auth-link"\)\)/);
});

test("auth.js and history.js share one fetch helper, and the copy says what withdrawing does", () => {
  for (const f of ["auth.js", "history.js"]) {
    assert.match(web(f), /import \{ call \} from "\.\/me-api\.js"/, f);
    assert.doesNotMatch(web(f), /function call\(/, `negative: ${f} has no private copy of the helper`);
  }
  assert.doesNotMatch(web("model/me.js"), /const plural =/, "negative: one plural, from model/teacher.js");
  assert.match(web("views/history.js"), /From your latest take\./);
  assert.doesNotMatch(web("views/history.js"), /The teacher's own cue/);
});
