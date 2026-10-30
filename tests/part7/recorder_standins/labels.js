// TEST HELPER ONLY (TICKET-052): stand-in for the EDIT lane's web/labels.js.
export function mountLabels(root) {
  root.append(Object.assign(document.createElement("div"), { textContent: "Labels stand-in" }));
  return { value: () => ({ tags: ["arms"], notes: "n" }), valid: () => true };
}
