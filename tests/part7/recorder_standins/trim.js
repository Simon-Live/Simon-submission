// TEST HELPER ONLY (TICKET-052): stand-in for the EDIT lane's web/trim.js. Never copied into web/.
// Contract: openTrimEditor(root, {blob|file, source, countdownUsed, manual}) -> {start_ms, end_ms} | null.
export function openTrimEditor(root, opts) {
  return new Promise((resolve) => {
    window.__trimCall = { source: opts.source, countdownUsed: opts.countdownUsed, manual: opts.manual, size: (opts.blob || opts.file).size };
    const box = document.createElement("div");
    box.setAttribute("data-testid", "trim");
    box.innerHTML = '<p>Trim stand-in</p><button type="button" data-testid="trim-continue">Continue</button><button type="button" data-testid="trim-back">Record again</button>';
    box.querySelector('[data-testid="trim-continue"]').onclick = () => resolve({ start_ms: 0, end_ms: 4000 });
    box.querySelector('[data-testid="trim-back"]').onclick = () => resolve(null);
    root.append(box);
  });
}
