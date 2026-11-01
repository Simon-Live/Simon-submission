// Plain elements for the teacher's words under one fault row, styled by theme/narration.css. No fetch, no storage.

/** A `div` holding one `p` per line; `lines` are `{ at, text }`. */
export function narrationBox(testid, lines) {
  const box = document.createElement("div");
  box.className = "nr";
  box.setAttribute("data-testid", testid);
  for (const { at, text } of lines) {
    const line = document.createElement("p");
    line.className = "nr-line";
    line.setAttribute("data-testid", "narration-cue");
    line.setAttribute("data-cue-at-s", String(at));
    line.textContent = text;
    box.append(line);
  }
  return box;
}
