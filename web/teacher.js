// The teacher page at `#/teacher/<entry>` (docs/specs/teacher-dashboard.md): glue between the API, the model and the view.
import { getEntry } from "./api.js";
import { h } from "./ui.js";
import { teacherUrl, teacherView } from "./model/teacher.js";
import { renderTeacher, renderTeacherError } from "./views/teacher.js";

async function load(entryId) {
  let res;
  try {
    res = await fetch(teacherUrl(entryId), { expectStatus: [404] }); // an unknown movement is shown, not reported
  } catch {
    return { status: 0 };
  }
  let body = null;
  try { body = await res.json(); } catch { body = null; }
  return { status: res.status, body };
}

/** @returns cleanup */
export function mountTeacher(container, entryId) {
  let live = true;
  const screen = h("section", { class: "screen" }, h("p", { "data-testid": "loading", text: "Loading the takes" }));
  container.append(screen);
  (async () => {
    const [res, entry] = await Promise.all([load(entryId), getEntry(entryId).catch(() => null)]);
    if (!live) return;
    if (res.status === 200 && res.body && typeof res.body === "object") renderTeacher(screen, teacherView(res.body, entry, entryId));
    else renderTeacherError(screen, res.status === 404);
  })();
  return () => { live = false; };
}
