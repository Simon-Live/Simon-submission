// "How this was made" (docs/specs/result-redesign-additions.md R1, TICKET-142): the Meta models that ran for this take,
// each with its status (ran live, saved run reused, fallback, not used, no record), what it did and its time. View only:
// draws the panel that web/model/models-used.js `modelsPanel` builds from GET api/results/<job>/models.json; every
// colour comes from theme/results.css through class names and data attributes.
import { h } from "../ui.js";

export const TEXT = {
  eyebrow: "Meta AI",
  title: "How this was made",
  none: "No Meta model ran live for this take.",
  clip: { trainer: "The trainer's video", you: "Your video" },
};

function step(item) {
  return h("li", { class: "hm-step", "data-testid": `model-${item.id}`, "data-status": item.status, "data-tone": item.tone },
    h("span", { class: "hm-dot", "aria-hidden": "true" }),
    h("div", { class: "hm-body" },
      h("div", { class: "hm-line" },
        h("span", { class: "hm-model", text: item.model }),
        h("span", { class: "hm-pill", "data-testid": `model-${item.id}-status`, text: item.statusLabel }),
        item.time ? h("span", { class: "hm-time", "data-testid": `model-${item.id}-time`, text: item.time }) : null),
      item.task ? h("p", { class: "hm-task", text: item.task }) : null,
      item.detail ? h("p", { class: "hm-detail", "data-testid": `model-${item.id}-detail`, text: item.detail }) : null));
}

/**
 * Draw the panel into `root` (appended). `panel` is `modelsPanel(doc)`: {items, total, madeWith}. Returns the section.
 * Rows are grouped by clip (the trainer's video, then yours) in the order the server lists them.
 */
export function renderModelsUsed(root, panel) {
  const section = h("section", { class: "hm", "data-testid": "models-used", "aria-labelledby": "hm-title" });
  section.append(h("header", { class: "hm-head" },
    h("p", { class: "hm-eyebrow", text: TEXT.eyebrow }),
    h("h2", { id: "hm-title", class: "hm-title", text: TEXT.title }),
    h("p", { class: "hm-made", "data-testid": "models-made-with", text: panel.madeWith || TEXT.none })));
  for (const clip of ["trainer", "you"]) {
    const items = panel.items.filter((x) => x.clip === clip);
    if (!items.length) continue;
    section.append(h("div", { class: "hm-group", "data-clip": clip },
      h("h3", { class: "hm-clip", text: TEXT.clip[clip] }),
      h("ol", { class: "hm-steps" }, ...items.map(step))));
  }
  if (panel.total) section.append(h("p", { class: "hm-total", "data-testid": "models-total", text: panel.total }));
  root.append(section);
  return section;
}
