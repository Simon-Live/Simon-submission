// Labels for a trainer entry: tags (0 to 8 chips) and notes (0 to 280 characters). recorder.md "Labels".
import { h } from "./ui.js";

export const MAX_TAGS = 8;
export const MAX_TAG_LEN = 24;
export const MAX_NOTES = 280;
export const TAG_TEXT = {
  chars: "Tags use letters, digits and hyphens only.",
  long: "A tag is 24 characters at most.",
  many: "Eight tags at most.",
};

/** One typed tag to its stored form: {tag} or {error}. Empty input gives {tag: ""}. */
export function parseTag(raw) {
  const tag = String(raw || "").trim().toLowerCase();
  if (!tag) return { tag: "" };
  if (!/^[a-z0-9-]+$/.test(tag)) return { error: TAG_TEXT.chars };
  if (tag.length > MAX_TAG_LEN) return { error: TAG_TEXT.long };
  return { tag };
}

/** All labels, {entry_id: {tags, notes}}; empty when the server does not answer. */
export async function getLabels() {
  try {
    const res = await fetch("api/labels");
    if (!res.ok) return {};
    const body = await res.json();
    return body && typeof body === "object" ? body : {};
  } catch {
    return {};
  }
}

/**
 * One entry's {tags, notes}, or null when it has none. Read from the `api/labels` map, not from
 * `api/labels/<id>`, which answers 404 for an unlabelled entry and would log a console error.
 */
export async function getEntryLabels(id) {
  const found = (await getLabels())[id];
  const tags = Array.isArray(found && found.tags) ? found.tags : [];
  const notes = typeof (found && found.notes) === "string" ? found.notes : "";
  return tags.length || notes ? { tags, notes } : null;
}

/** Read-only chips for catalog rows and Watch. */
export function tagChips(tags, testid) {
  return h("ul", { class: "chips", "data-testid": testid }, tags.map((t) => h("li", { class: "chip", text: t })));
}

export function mountLabels(root) {
  const tags = [];
  const chips = h("ul", { class: "chips editable" });
  const input = h("input", {
    type: "text", class: "chip-input", id: "tag-input", "data-testid": "tag-input", autocomplete: "off",
    autocapitalize: "none", spellcheck: "false", enterkeyhint: "done", placeholder: "Add a tag", "aria-describedby": "tag-help",
  });
  const box = h("div", { class: "chip-box", "data-testid": "tags" }, chips, input);
  const help = h("p", { class: "hint", id: "tag-help", text: "Press Enter or comma after each tag. Letters, digits and hyphens, up to 8 tags." });
  const error = h("p", { class: "error", role: "alert", hidden: true });
  const notes = h("textarea", { class: "input notes", id: "notes", rows: 3, maxlength: MAX_NOTES, "data-testid": "notes", placeholder: "What to look for, equipment, cues" });
  const count = h("span", { class: "hint tnum" });

  root.append(
    h("div", { class: "field" }, h("label", { for: "tag-input", text: "Tags" }), box, help, error),
    h("div", { class: "field" }, h("label", { for: "notes", text: "Notes" }), notes, count));

  function show(msg) { error.hidden = !msg; error.textContent = msg; }
  function draw() {
    chips.replaceChildren(...tags.map((t) => h("li", { class: "chip" },
      h("span", { text: t }),
      h("button", {
        type: "button", class: "chip-x", "aria-label": `Remove tag ${t}`, "data-testid": "tag-remove", text: "×",
        onclick: () => { tags.splice(tags.indexOf(t), 1); draw(); input.focus(); },
      }))));
    count.textContent = `${notes.value.length}/${MAX_NOTES}`;
  }
  /** Commit the typed text as a tag; false when it was refused (the reason is shown). */
  function commit() {
    const r = parseTag(input.value);
    if (r.error) { show(r.error); return false; }
    if (!r.tag) { show(""); return true; }
    if (tags.includes(r.tag)) { input.value = ""; show(""); return true; }
    if (tags.length >= MAX_TAGS) { show(TAG_TEXT.many); return false; }
    tags.push(r.tag);
    input.value = "";
    show("");
    draw();
    return true;
  }
  input.addEventListener("input", () => {
    input.value = input.value.toLowerCase();
    if (/[,\s]$/.test(input.value)) {
      input.value = input.value.replace(/[,\s]+$/, "");
      commit();
    } else {
      show(parseTag(input.value).error || "");
    }
  });
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter") { e.preventDefault(); commit(); }
    else if (e.key === "Backspace" && !input.value && tags.length) { tags.pop(); draw(); }
  });
  input.addEventListener("blur", () => { if (input.value) commit(); });
  notes.addEventListener("input", draw);
  box.addEventListener("click", () => input.focus());
  draw();

  return {
    value: () => {
      const r = parseTag(input.value);
      const pending = r.tag && !tags.includes(r.tag) && tags.length < MAX_TAGS ? [r.tag] : [];
      return { tags: [...tags, ...pending], notes: notes.value.slice(0, MAX_NOTES) };
    },
    valid: () => {
      const r = parseTag(input.value);
      if (r.error) return false;
      return !(r.tag && !tags.includes(r.tag) && tags.length >= MAX_TAGS);
    },
  };
}
