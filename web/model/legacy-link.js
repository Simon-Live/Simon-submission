// Old links that carry a `mode` query on the hash (`#/?mode=dance`, `#/follow/x?mode=rehab`) still open: the header
// switch that the parameter belonged to is gone (TICKET-436), so the parameter is dropped and the rest of the route is
// kept (`#/me/recap?month=2026-10` keeps its month). Logic only, no DOM.

/** The hash without any `mode` query parameter; a hash with no query, or none named `mode`, comes back as it was. */
export function stripLegacyMode(hash) {
  const text = String(hash || "");
  const at = text.indexOf("?");
  if (at < 0) return text;
  const kept = text.slice(at + 1).split("&").filter((pair) => pair && pair.split("=")[0] !== "mode");
  const before = text.slice(0, at);
  return kept.length ? `${before}?${kept.join("&")}` : before;
}
