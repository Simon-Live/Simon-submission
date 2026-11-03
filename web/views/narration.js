// Plain elements for the teacher's words under one fault row, styled by theme/narration.css. No fetch, no storage.

/** The play button and caption for a cue that has the trainer's own recording. `play(url)` starts the sound. */
function voice(line, { url, who }, play) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "nr-play";
  button.setAttribute("data-testid", "narration-play");
  button.textContent = "Hear it";
  button.addEventListener("click", () => play(url));
  const caption = document.createElement("span");
  caption.className = "nr-who";
  caption.setAttribute("data-testid", "narration-who");
  caption.textContent = `${who}, in their own voice`;
  line.append(button, caption);
}

/** A `div` holding one `p` per line; `lines` are `{ at, text, audio? }` with `audio` `{ url, who }` when the trainer's recording exists. */
export function narrationBox(testid, lines, play = (url) => new Audio(url).play().catch(() => {})) {
  const box = document.createElement("div");
  box.className = "nr";
  box.setAttribute("data-testid", testid);
  for (const { at, text, audio } of lines) {
    const line = document.createElement("p");
    line.className = "nr-line";
    line.setAttribute("data-testid", "narration-cue");
    line.setAttribute("data-cue-at-s", String(at));
    line.textContent = text;
    if (audio) voice(line, audio, play);
    box.append(line);
  }
  return box;
}
