// The Open-source notices page (web/notices.js): THIRD_PARTY_NOTICES.md, as GET api/notices serves it, cut into the
// few blocks it uses (headings, tables, fenced licence texts, paragraphs). Pure: words in, blocks out; nothing is
// ever treated as HTML.

export const NOTICES_TEXT = {
  title: "Open-source notices",
  lead: "The open-source components and AI models Simon uses, with their licences.",
  missing: "The notices are not in this build yet. Email hello@simon.live for the list.",
};

/** `md` as blocks: {kind: "h1"|"h2"|"h3", text} | {kind: "table", head, rows} | {kind: "code", text} | {kind: "p", text}. */
export function noticeBlocks(md) {
  if (typeof md !== "string") return [];
  const lines = md.replace(/\r\n/g, "\n").split("\n");
  const blocks = [];
  const cells = (line) => line.trim().replace(/^\||\|$/g, "").split("|").map((c) => c.trim());
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    if (!line.trim()) continue;
    const head = /^(#{1,3})\s+(.*)$/.exec(line);
    if (head) { blocks.push({ kind: `h${head[1].length}`, text: head[2] }); continue; }
    if (line.startsWith("```")) {
      const body = [];
      for (i++; i < lines.length && !lines[i].startsWith("```"); i++) body.push(lines[i]);
      blocks.push({ kind: "code", text: body.join("\n") });
      continue;
    }
    if (line.trim().startsWith("|")) {
      const rows = [];
      for (; i < lines.length && lines[i].trim().startsWith("|"); i++) rows.push(lines[i]);
      i--;
      const [first, , ...rest] = rows;   // the second row is the |---| divider
      blocks.push({ kind: "table", head: cells(first), rows: rest.map(cells) });
      continue;
    }
    const para = [line.trim()];
    for (; i + 1 < lines.length && lines[i + 1].trim() && !/^(#|```|\|)/.test(lines[i + 1].trim()); i++) para.push(lines[i + 1].trim());
    blocks.push({ kind: "p", text: para.join(" ") });
  }
  return blocks;
}
