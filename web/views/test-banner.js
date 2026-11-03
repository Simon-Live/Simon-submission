// The persistent "you are on a test server" banner in the header. View only: model/test-server.js decides.
import { h } from "../ui.js";

export function renderTestBanner(header, text) {
  const existing = header.querySelector("[data-testid=test-server-banner]");
  if (existing) return existing;
  const el = h("div", { class: "test-banner", role: "alert", "data-testid": "test-server-banner", text });
  header.append(el);
  return el;
}
