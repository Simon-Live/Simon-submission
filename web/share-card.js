// The share card: a 1080 x 1350 PNG drawn on a canvas, and how it leaves the phone (docs/specs/challenges.md).
// `layoutCard` is pure (it takes a text measuring function) so the layout is unit tested without a browser.
import { tokenValue } from "./theme-colors.js";

export const CARD_W = 1080;
export const CARD_H = 1350;
export const PAD = 80;
const FONT = '"SF Pro Display", "Helvetica Neue", system-ui, sans-serif';
// grade colours from the theme: lime for A and B, pink below (theme/tokens.css); the literals are harness fallbacks
const GRADE_TOKENS = { A: "--color-accent", B: "--color-accent", C: "--color-bad", D: "--color-bad", F: "--color-bad" };
const GRADE_FALLBACK = { A: "#c6f35a", B: "#c6f35a", C: "#ff2d95", D: "#ff2d95", F: "#ff2d95" };
const gradeColorOf = (g) => (GRADE_TOKENS[g] && tokenValue(GRADE_TOKENS[g])) || GRADE_FALLBACK[g];

/** Wrap `text` to `maxWidth` using `measure(text)`; a word wider than the line is broken by characters; at most `maxLines`. */
export function wrapText(measure, text, maxWidth, maxLines = 99) {
  const lines = [];
  let line = "";
  const push = () => { if (line) lines.push(line); line = ""; };
  for (const word of String(text || "").split(/\s+/).filter(Boolean)) {
    const next = line ? `${line} ${word}` : word;
    if (measure(next) <= maxWidth) { line = next; continue; }
    push();
    let rest = word;
    while (measure(rest) > maxWidth) {
      let n = rest.length;
      while (n > 1 && measure(rest.slice(0, n)) > maxWidth) n--;
      lines.push(rest.slice(0, n));
      rest = rest.slice(n);
    }
    line = rest;
  }
  push();
  if (lines.length > maxLines) {
    const kept = lines.slice(0, maxLines);
    let last = kept[maxLines - 1];
    while (last.length > 1 && measure(`${last}...`) > maxWidth) last = last.slice(0, -1);
    kept[maxLines - 1] = `${last}...`;
    return kept;
  }
  return lines;
}

/**
 * The drawing of a card as a list of operations `{type: "rect"|"text", ...}` in canvas pixels.
 * @param model {movement, score, grade, strongest, challenger, title, url, sponsor}
 * @param measure (font, text) => width in px
 */
export function layoutCard(model, measure) {
  const ops = [{ type: "rect", x: 0, y: 0, w: CARD_W, h: CARD_H, fill: "#0f141b" }, { type: "rect", x: 0, y: 0, w: CARD_W, h: 14, fill: "#8aa4ff" }];
  const inner = CARD_W - PAD * 2;
  let y = 150;
  const text = (str, size, weight, fill, extra = {}) => {
    const font = `${weight} ${size}px ${FONT}`;
    const lines = wrapText((s) => measure(font, s), str, extra.maxWidth ?? inner, extra.maxLines ?? 2);
    for (const line of lines) {
      ops.push({ type: "text", text: line, x: extra.x ?? PAD, y, font, fill, align: extra.align ?? "left" });
      y += Math.round(size * 1.2);
    }
    return lines.length;
  };
  text(model.movement || "A Simon movement", 72, 700, "#ffffff", { maxLines: 2 });
  y += 14;
  text(`${model.challenger || "Someone"} scored`, 44, 500, "#9aa7b8", { maxLines: 1 });
  y += 200;
  const scoreText = String(model.score);
  const scoreFont = `800 300px ${FONT}`;
  ops.push({ type: "text", text: scoreText, x: PAD, y, font: scoreFont, fill: "#ffffff", align: "left" });
  const scoreW = measure(scoreFont, scoreText);
  const gradeColor = gradeColorOf(String(model.grade || "").charAt(0)) || "#9aa7b8";
  const pillX = Math.min(PAD + scoreW + 50, CARD_W - PAD - 150);
  ops.push({ type: "rect", x: pillX, y: y - 190, w: 150, h: 150, fill: gradeColor, radius: 36 });
  ops.push({ type: "text", text: String(model.grade || "-"), x: pillX + 75, y: y - 80, font: `800 96px ${FONT}`, fill: "#0f141b", align: "center" });
  y += 70;
  if (model.strongest) text(`Strongest: ${model.strongest}`, 44, 600, "#e9eef6", { maxLines: 2 });
  y = Math.max(y + 60, 880);
  text("Can you beat it?", 92, 800, "#ffffff", { maxLines: 2 });
  y += 10;
  if (model.title) text(model.title, 40, 500, "#9aa7b8", { maxLines: 2 });
  y = Math.max(y + 30, 1130);
  text(model.url || "", 34, 500, "#8aa4ff", { maxLines: 3 });
  if (model.sponsor) {
    ops.push({ type: "text", text: wrapText((s) => measure(`600 32px ${FONT}`, s), `Sponsored by ${model.sponsor}`, inner, 1)[0], x: PAD, y: CARD_H - 50, font: `600 32px ${FONT}`, fill: "#ffc83d", align: "left" });
  }
  return ops;
}

/** Draw `ops` on a 2D context. */
export function drawOps(ctx, ops) {
  for (const op of ops) {
    if (op.type === "rect") {
      ctx.fillStyle = op.fill;
      if (op.radius && ctx.roundRect) { ctx.beginPath(); ctx.roundRect(op.x, op.y, op.w, op.h, op.radius); ctx.fill(); } else ctx.fillRect(op.x, op.y, op.w, op.h);
    } else {
      ctx.font = op.font;
      ctx.fillStyle = op.fill;
      ctx.textAlign = op.align;
      ctx.textBaseline = "alphabetic";
      ctx.fillText(op.text, op.x, op.y);
    }
  }
}

/** Render the card on a new canvas; resolves `{canvas, blob}` (a PNG). */
export async function renderCard(model, doc = document) {
  const canvas = doc.createElement("canvas");
  canvas.width = CARD_W;
  canvas.height = CARD_H;
  const ctx = canvas.getContext("2d");
  if (!ctx) throw new Error("This browser cannot draw the card.");
  drawOps(ctx, layoutCard(model, (font, s) => { ctx.font = font; return ctx.measureText(s).width; }));
  const blob = await new Promise((resolve) => canvas.toBlob(resolve, "image/png"));
  if (!blob) throw new Error("The card could not be saved as a picture.");
  return { canvas, blob };
}

/** Copy `text`: the clipboard API, else a hidden textarea and execCommand. Resolves true when copied. */
export async function copyText(text, win = globalThis) {
  try {
    if (win.navigator?.clipboard?.writeText) { await win.navigator.clipboard.writeText(text); return true; }
  } catch { /* fall through to the textarea */ }
  try {
    const doc = win.document;
    const area = doc.createElement("textarea");
    area.value = text;
    area.setAttribute("readonly", "");
    area.style.cssText = "position:fixed;left:-9999px;top:0";
    doc.body.append(area);
    area.select();
    const done = doc.execCommand("copy");
    area.remove();
    return !!done;
  } catch { return false; }
}

/** Save the PNG through a download link. */
/** The blob as a data: URL. A preview <img> uses it because a data: URL has no lifetime to revoke (TICKET-096). */
export function blobToDataUrl(blob) {
  return new Promise((resolve, reject) => {
    const r = new FileReader();
    r.onload = () => resolve(String(r.result));
    r.onerror = () => reject(r.error || new Error("The picture could not be read."));
    r.readAsDataURL(blob);
  });
}

export function downloadBlob(blob, filename, win = globalThis) {
  const url = win.URL.createObjectURL(blob);
  const a = win.document.createElement("a");
  a.href = url;
  a.download = filename;
  a.rel = "noopener";
  win.document.body.append(a);
  a.click();
  a.remove();
  win.setTimeout(() => win.URL.revokeObjectURL(url), 10000);
}

/**
 * Send the card out. With the share sheet (files supported): `{mode: "shared"}`, or `{mode: "cancelled"}` when the
 * person closes it. Otherwise the PNG downloads and the link is copied: `{mode: "download", copied}`.
 */
export async function shareCard({ blob, url, text, filename = "simon-challenge.png" }, win = globalThis) {
  const nav = win.navigator;
  const file = typeof win.File === "function" ? new win.File([blob], filename, { type: "image/png" }) : null;
  const data = { files: file ? [file] : [], url, text, title: "Simon challenge" };
  if (file && typeof nav?.share === "function" && typeof nav.canShare === "function" && nav.canShare({ files: [file] })) {
    try {
      await nav.share(data);
      return { mode: "shared" };
    } catch (err) {
      if (err && err.name === "AbortError") return { mode: "cancelled" };
    }
  }
  downloadBlob(blob, filename, win);
  return { mode: "download", copied: await copyText(url, win) };
}

/** Share only the link (the board's Share button): the share sheet, else copy. */
export async function shareLink({ url, text }, win = globalThis) {
  const nav = win.navigator;
  if (typeof nav?.share === "function") {
    try { await nav.share({ url, text, title: "Simon challenge" }); return { mode: "shared" }; } catch (err) {
      if (err && err.name === "AbortError") return { mode: "cancelled" };
    }
  }
  return { mode: "copy", copied: await copyText(url, win) };
}
