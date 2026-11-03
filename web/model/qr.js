// A QR code encoder (ISO/IEC 18004): byte mode, error correction level M, versions 1 to 10, the mask with the lowest
// penalty. Pure: text in, a square of booleans out (true is a dark module). No DOM. Written for the class handout
// (docs/specs/handout.md) because the repo and its node_modules hold no QR encoder; checked against python-qrcode
// (tests/part7/fixtures/qr/reference.json) and decoded back in tests/part7/qr.unit.test.mjs.

export const MAX_VERSION = 10;
export const QUIET = 4; // modules of light margin a reader needs around the code
export const MAX_BYTES = 213; // the longest text (UTF-8 bytes) version 10 at level M holds

// Per version: [error correction codewords per block, [blocks, data codewords per block], ...] at level M.
const BLOCKS_M = [null,
  [10, [1, 16]], [16, [1, 28]], [26, [1, 44]], [18, [2, 32]], [24, [2, 43]],
  [16, [4, 27]], [18, [4, 31]], [22, [2, 38], [2, 39]], [22, [3, 36], [2, 37]], [26, [4, 43], [1, 44]]];
const ALIGN = [null, [], [6, 18], [6, 22], [6, 26], [6, 30], [6, 34], [6, 22, 38], [6, 24, 42], [6, 26, 46], [6, 28, 50]];
const FORMAT_M = 0; // the two format bits of level M
const MASKS = [
  (x, y) => (x + y) % 2 === 0,
  (x, y) => y % 2 === 0,
  (x) => x % 3 === 0,
  (x, y) => (x + y) % 3 === 0,
  (x, y) => (Math.floor(x / 3) + Math.floor(y / 2)) % 2 === 0,
  (x, y) => ((x * y) % 2) + ((x * y) % 3) === 0,
  (x, y) => (((x * y) % 2) + ((x * y) % 3)) % 2 === 0,
  (x, y) => (((x + y) % 2) + ((x * y) % 3)) % 2 === 0,
];

export const sizeOf = (version) => 17 + 4 * version;
const bit = (value, i) => ((value >>> i) & 1) === 1;
const dataCodewords = (version) => BLOCKS_M[version].slice(1).reduce((sum, [n, k]) => sum + n * k, 0);
const countBits = (version) => (version <= 9 ? 8 : 16);

/** The smallest version that holds `length` bytes at level M; 0 when none up to MAX_VERSION does. */
export function versionFor(length) {
  for (let v = 1; v <= MAX_VERSION; v++) if (4 + countBits(v) + 8 * length <= dataCodewords(v) * 8) return v;
  return 0;
}

// ----- Reed-Solomon over GF(256), polynomial 0x11d ----------------------------------------------------------------
function gfMul(x, y) {
  let z = 0;
  for (let i = 7; i >= 0; i--) {
    z = (z << 1) ^ ((z >>> 7) * 0x11d);
    z ^= ((y >>> i) & 1) * x;
  }
  return z;
}

function rsDivisor(degree) {
  const out = new Array(degree).fill(0);
  out[degree - 1] = 1;
  let root = 1;
  for (let i = 0; i < degree; i++) {
    for (let j = 0; j < degree; j++) {
      out[j] = gfMul(out[j], root);
      if (j + 1 < degree) out[j] ^= out[j + 1];
    }
    root = gfMul(root, 2);
  }
  return out;
}

/** The error correction codewords of `data` for a divisor of `degree`. */
export function rsRemainder(data, degree) {
  const divisor = rsDivisor(degree);
  const out = new Array(degree).fill(0);
  for (const b of data) {
    const factor = b ^ out.shift();
    out.push(0);
    divisor.forEach((c, i) => { out[i] ^= gfMul(c, factor); });
  }
  return out;
}

// ----- data -------------------------------------------------------------------------------------------------------
function dataBits(bytes, version) {
  const bits = [];
  const push = (value, len) => { for (let i = len - 1; i >= 0; i--) bits.push(bit(value, i)); };
  push(4, 4); // byte mode
  push(bytes.length, countBits(version));
  for (const b of bytes) push(b, 8);
  const room = dataCodewords(version) * 8;
  push(0, Math.min(4, room - bits.length)); // terminator
  push(0, (8 - (bits.length % 8)) % 8);
  for (let pad = 0xec; bits.length < room; pad ^= 0xec ^ 0x11) push(pad, 8);
  const words = [];
  for (let i = 0; i < bits.length; i += 8) words.push(bits.slice(i, i + 8).reduce((acc, b) => (acc << 1) | (b ? 1 : 0), 0));
  return words;
}

/** The codewords in the order they are placed: data interleaved across blocks, then error correction likewise. */
export function codewords(bytes, version) {
  const [ec, ...groups] = BLOCKS_M[version];
  const words = dataBits(bytes, version);
  const blocks = [];
  let at = 0;
  for (const [n, k] of groups) {
    for (let b = 0; b < n; b++, at += k) blocks.push(words.slice(at, at + k));
  }
  const out = [];
  const longest = Math.max(...blocks.map((b) => b.length));
  for (let i = 0; i < longest; i++) for (const b of blocks) if (i < b.length) out.push(b[i]);
  const eccs = blocks.map((b) => rsRemainder(b, ec));
  for (let i = 0; i < ec; i++) for (const e of eccs) out.push(e[i]);
  return out;
}

// ----- the matrix -------------------------------------------------------------------------------------------------
function grid(size) {
  return { size, dark: Array.from({ length: size }, () => new Array(size).fill(false)), fixed: Array.from({ length: size }, () => new Array(size).fill(false)) };
}

function setFixed(m, x, y, dark) {
  m.dark[y][x] = dark;
  m.fixed[y][x] = true;
}

function drawFormat(m, mask) {
  const data = (FORMAT_M << 3) | mask;
  let rem = data;
  for (let i = 0; i < 10; i++) rem = (rem << 1) ^ ((rem >>> 9) * 0x537);
  const bits = ((data << 10) | rem) ^ 0x5412;
  const s = m.size;
  for (let i = 0; i <= 5; i++) setFixed(m, 8, i, bit(bits, i));
  setFixed(m, 8, 7, bit(bits, 6));
  setFixed(m, 8, 8, bit(bits, 7));
  setFixed(m, 7, 8, bit(bits, 8));
  for (let i = 9; i < 15; i++) setFixed(m, 14 - i, 8, bit(bits, i));
  for (let i = 0; i < 8; i++) setFixed(m, s - 1 - i, 8, bit(bits, i));
  for (let i = 8; i < 15; i++) setFixed(m, 8, s - 15 + i, bit(bits, i));
  setFixed(m, 8, s - 8, true); // the dark module
}

function drawVersion(m, version) {
  if (version < 7) return;
  let rem = version;
  for (let i = 0; i < 12; i++) rem = (rem << 1) ^ ((rem >>> 11) * 0x1f25);
  const bits = (version << 12) | rem;
  for (let i = 0; i < 18; i++) {
    const a = m.size - 11 + (i % 3);
    const b = Math.floor(i / 3);
    setFixed(m, a, b, bit(bits, i));
    setFixed(m, b, a, bit(bits, i));
  }
}

function drawPatterns(m, version) {
  const s = m.size;
  for (let i = 0; i < s; i++) {
    setFixed(m, 6, i, i % 2 === 0);
    setFixed(m, i, 6, i % 2 === 0);
  }
  for (const [cx, cy] of [[3, 3], [s - 4, 3], [3, s - 4]]) {
    for (let dy = -4; dy <= 4; dy++) {
      for (let dx = -4; dx <= 4; dx++) {
        const x = cx + dx;
        const y = cy + dy;
        const ring = Math.max(Math.abs(dx), Math.abs(dy));
        if (x >= 0 && x < s && y >= 0 && y < s) setFixed(m, x, y, ring !== 2 && ring !== 4);
      }
    }
  }
  const pos = ALIGN[version];
  const last = pos.length - 1;
  pos.forEach((cx, i) => pos.forEach((cy, j) => {
    if ((i === 0 && j === 0) || (i === 0 && j === last) || (i === last && j === 0)) return; // the finder corners
    for (let dy = -2; dy <= 2; dy++) for (let dx = -2; dx <= 2; dx++) setFixed(m, cx + dx, cy + dy, Math.max(Math.abs(dx), Math.abs(dy)) !== 1);
  }));
  drawFormat(m, 0); // reserves the format area; the real bits are drawn with the mask
  drawVersion(m, version);
}

function placeData(m, words) {
  const s = m.size;
  let i = 0;
  for (let right = s - 1; right >= 1; right -= 2) {
    if (right === 6) right = 5; // the vertical timing column is skipped
    const upward = ((right + 1) & 2) === 0;
    for (let vert = 0; vert < s; vert++) {
      const y = upward ? s - 1 - vert : vert;
      for (let j = 0; j < 2; j++) {
        const x = right - j;
        if (m.fixed[y][x] || i >= words.length * 8) continue;
        m.dark[y][x] = bit(words[i >>> 3], 7 - (i & 7));
        i++;
      }
    }
  }
}

function masked(m, mask) {
  const test = MASKS[mask];
  const out = { size: m.size, dark: m.dark.map((row) => row.slice()), fixed: m.fixed };
  for (let y = 0; y < m.size; y++) for (let x = 0; x < m.size; x++) if (!m.fixed[y][x] && test(x, y)) out.dark[y][x] = !out.dark[y][x];
  drawFormat(out, mask);
  return out;
}

// ----- mask penalty (ISO/IEC 18004 7.8.3) -------------------------------------------------------------------------
const FINDER_LIKE = [[true, false, true, true, true, false, true, false, false, false, false], [false, false, false, false, true, false, true, true, true, false, true]];

function lineScore(line) {
  let score = 0;
  let run = 1;
  for (let i = 1; i <= line.length; i++) {
    if (i < line.length && line[i] === line[i - 1]) { run++; continue; }
    if (run >= 5) score += 3 + (run - 5);
    run = 1;
  }
  for (let i = 0; i + 11 <= line.length; i++) {
    if (FINDER_LIKE.some((p) => p.every((v, k) => line[i + k] === v))) score += 40;
  }
  return score;
}

/** The penalty of a finished matrix; the encoder keeps the mask with the lowest. */
export function penalty(dark) {
  const s = dark.length;
  let score = 0;
  for (let i = 0; i < s; i++) score += lineScore(dark[i]) + lineScore(dark.map((row) => row[i]));
  for (let y = 0; y + 1 < s; y++) {
    for (let x = 0; x + 1 < s; x++) {
      const c = dark[y][x];
      if (c === dark[y][x + 1] && c === dark[y + 1][x] && c === dark[y + 1][x + 1]) score += 3;
    }
  }
  const darkCount = dark.reduce((sum, row) => sum + row.filter(Boolean).length, 0);
  return score + Math.floor(Math.abs((darkCount * 100) / (s * s) - 50) / 5) * 10;
}

/**
 * The QR code of `text` (UTF-8 bytes): `{version, size, mask, modules}` where `modules[y][x]` is true for dark.
 * `mask` forces one of the 8 masks (tests); otherwise the lowest penalty wins. Throws a RangeError past version 10.
 */
export function encodeQr(text, { mask } = {}) {
  const bytes = new TextEncoder().encode(String(text));
  const version = versionFor(bytes.length);
  if (!version) throw new RangeError("The text is too long for this code.");
  const base = grid(sizeOf(version));
  drawPatterns(base, version);
  placeData(base, codewords(bytes, version));
  const choices = Number.isInteger(mask) && mask >= 0 && mask < 8 ? [mask] : [0, 1, 2, 3, 4, 5, 6, 7];
  let best = null;
  for (const k of choices) {
    const m = masked(base, k);
    const p = choices.length === 1 ? 0 : penalty(m.dark);
    if (best === null || p < best.p) best = { k, m, p };
  }
  return { version, size: base.size, mask: best.k, modules: best.m.dark };
}

/** An SVG path of the dark modules, offset by the quiet zone, and the side of its square viewBox. */
export function qrPath(modules, quiet = QUIET) {
  const parts = [];
  modules.forEach((row, y) => row.forEach((dark, x) => { if (dark) parts.push(`M${x + quiet} ${y + quiet}h1v1h-1z`); }));
  return { d: parts.join(""), side: modules.length + 2 * quiet };
}

/** The text's code as `modules`, or null when it is longer than MAX_BYTES bytes (the AR page falls back to a shorter link). */
export function tryQr(text, options) {
  try {
    return encodeQr(text, options).modules;
  } catch (e) {
    if (e instanceof RangeError) return null;
    throw e;
  }
}

/** A standalone SVG string of `modules` with the quiet zone. Colours: the --qr-dark and --qr-light tokens (theme/tokens.css). Numbers and fixed attributes only. */
export function qrSvg(modules, { quiet = QUIET } = {}) {
  const { d, side } = qrPath(modules, quiet);
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${side} ${side}" shape-rendering="crispEdges">`
    + `<rect width="${side}" height="${side}" fill="var(--qr-light)"/><path d="${d}" fill="var(--qr-dark)"/></svg>`;
}
