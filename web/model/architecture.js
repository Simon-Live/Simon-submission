// The architecture page's words and view model (docs/specs/impact-page.md, "Architecture page"). The diagrams are the
// Mermaid blocks of docs/ARCHITECTURE.md, as `GET api/architecture` returns them. No DOM and no fetching here.

export const ARCH_PAGE = {
  title: "How Simon is built",
  lead: "Seven parts, each its own process, passing files. Each diagram comes from docs/ARCHITECTURE.md, where every box links to the code.",
  missing: "The architecture doc is not in this copy of the app.",
  failed: "This diagram did not draw. Its source is shown instead.",
  unreachable: "The diagrams did not load. Reload the page to try again.",
  back: "Who Simon is for",
};

export const MERMAID_SRC = "vendor/mermaid/mermaid.min.js";

/** The diagrams to draw, `[{id, title, source}]`; empty when the answer holds none. */
export function architectureView(doc) {
  const list = doc && Array.isArray(doc.diagrams) ? doc.diagrams : [];
  return list
    .filter((d) => d && typeof d.source === "string" && d.source.trim())
    .map((d, i) => ({ id: `arch-diagram-${i}`, title: typeof d.title === "string" && d.title ? d.title : `Diagram ${i + 1}`, source: d.source }));
}

/** Mermaid's theme variables from the brand tokens (`read(name)` returns a token's value; "" when unset). */
export function mermaidTheme(read) {
  const v = (name) => read(name) || undefined;
  return {
    startOnLoad: false,
    securityLevel: "strict",
    theme: "base",
    flowchart: { useMaxWidth: false }, // drawn at full size; a phone scrolls the diagram sideways in its own box
    sequence: { useMaxWidth: false },
    themeVariables: {
      background: v("--color-bg"),
      primaryColor: v("--color-raised"),
      primaryTextColor: v("--color-text"),
      primaryBorderColor: v("--color-accent"),
      lineColor: v("--color-text-muted"),
      secondaryColor: v("--color-surface"),
      tertiaryColor: v("--color-surface"),
      textColor: v("--color-text"),
      mainBkg: v("--color-raised"),
      nodeBorder: v("--color-accent"),
      clusterBkg: v("--color-surface"),
      clusterBorder: v("--color-line"),
      actorBkg: v("--color-raised"),
      actorBorder: v("--color-accent"),
      actorTextColor: v("--color-text"),
      signalColor: v("--color-text"),
      signalTextColor: v("--color-text"),
      noteBkgColor: v("--color-surface"),
      noteTextColor: v("--color-text"),
      fontFamily: v("--font"),
    },
  };
}
