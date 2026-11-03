// A test-only QR reader for a clean module matrix (docs/specs/handout.md): format bits, unmask, codewords, a Reed-Solomon
// syndrome check, then the byte segment. Written apart from web/model/qr.js (regions instead of drawn patterns,
// syndromes instead of division), so a shared mistake is unlikely. Level M, byte mode, versions 1 to 10.

const BLOCKS_M = { 1: [10, [1, 16]], 2: [16, [1, 28]], 3: [26, [1, 44]], 4: [18, [2, 32]], 5: [24, [2, 43]], 6: [16, [4, 27]],
  7: [18, [4, 31]], 8: [22, [2, 38], [2, 39]], 9: [22, [3, 36], [2, 37]], 10: [26, [4, 43], [1, 44]] };
const CENTRES = { 2: [6, 18], 3: [6, 22], 4: [6, 26], 5: [6, 30], 6: [6, 34], 7: [6, 22, 38], 8: [6, 24, 42], 9: [6, 26, 46], 10: [6, 28, 50] };
const UNMASK = [(r, c) => (r + c) % 2 === 0, (r) => r % 2 === 0, (r, c) => c % 3 === 0, (r, c) => (r + c) % 3 === 0,
  (r, c) => (Math.floor(r / 2) + Math.floor(c / 3)) % 2 === 0, (r, c) => ((r * c) % 2) + ((r * c) % 3) === 0,
  (r, c) => (((r * c) % 2) + ((r * c) % 3)) % 2 === 0, (r, c) => (((r + c) % 2) + ((r * c) % 3)) % 2 === 0];

const EXP = new Array(512);
const LOG = new Array(256);
for (let i = 0, x = 1; i < 255; i++) { EXP[i] = x; LOG[x] = i; x <<= 1; if (x & 0x100) x ^= 0x11d; }
for (let i = 255; i < 512; i++) EXP[i] = EXP[i - 255];

function formatWord(data) { // BCH(15,5) by brute force over the 32 valid words
  let rem = data;
  for (let i = 0; i < 10; i++) rem = (rem << 1) ^ ((rem >> 9) & 1 ? 0x537 : 0);
  return ((data << 10) | (rem & 0x3ff)) ^ 0x5412;
}

function readFormat(get) {
  const cells = [[8, 0], [8, 1], [8, 2], [8, 3], [8, 4], [8, 5], [8, 7], [8, 8], [7, 8], [5, 8], [4, 8], [3, 8], [2, 8], [1, 8], [0, 8]];
  const word = cells.reduce((acc, [c, r], i) => acc | ((get(r, c) ? 1 : 0) << i), 0);
  for (let data = 0; data < 32; data++) if (formatWord(data) === word) return { level: data >> 3, mask: data & 7 };
  throw new Error("format bits do not match any valid word");
}

function isFunction(r, c, version, n) {
  if ((r < 9 && c < 9) || (r < 9 && c >= n - 8) || (r >= n - 8 && c < 9)) return true; // finders, separators, format
  if (r === 6 || c === 6) return true;
  if (version >= 7 && ((r < 6 && c >= n - 11 && c < n - 8) || (c < 6 && r >= n - 11 && r < n - 8))) return true;
  const centres = CENTRES[version] || [];
  for (const ar of centres) {
    for (const ac of centres) {
      const corner = (ar === 6 && ac === 6) || (ar === 6 && ac === centres[centres.length - 1]) || (ac === 6 && ar === centres[centres.length - 1]);
      if (!corner && Math.abs(r - ar) <= 2 && Math.abs(c - ac) <= 2) return true;
    }
  }
  return false;
}

function syndromesZero(block) { // block = data then ec, highest power first
  const ec = block.ecLen;
  for (let i = 0; i < ec; i++) {
    let s = 0;
    for (const b of block.all) s = (s === 0 ? 0 : EXP[LOG[s] + i]) ^ b;
    if (s !== 0) return false;
  }
  return true;
}

/** The text of a square matrix of booleans (true dark), with or without a quiet zone of `quiet` modules. */
export function decodeMatrix(rows, quiet = 0) {
  const n = rows.length - 2 * quiet;
  const get = (r, c) => rows[r + quiet][c + quiet] === true || rows[r + quiet][c + quiet] === 1 || rows[r + quiet][c + quiet] === "1";
  const version = (n - 17) / 4;
  if (!Number.isInteger(version) || !BLOCKS_M[version]) throw new Error(`unsupported size ${n}`);
  const { level, mask } = readFormat(get);
  if (level !== 0) throw new Error("not level M");
  const bits = [];
  let upward = true; // the first column pair is read bottom to top, then each pair turns
  for (let right = n - 1; right > 0; right -= 2, upward = !upward) {
    if (right === 6) right = 5; // the timing column
    for (let k = 0; k < n; k++) {
      const r = upward ? n - 1 - k : k;
      for (const c of [right, right - 1]) if (!isFunction(r, c, version, n)) bits.push(get(r, c) !== UNMASK[mask](r, c));
    }
  }
  const words = [];
  for (let i = 0; i + 8 <= bits.length; i += 8) words.push(bits.slice(i, i + 8).reduce((a, b) => (a << 1) | (b ? 1 : 0), 0));
  const [ec, ...groups] = BLOCKS_M[version];
  const sizes = groups.flatMap(([count, k]) => new Array(count).fill(k));
  const blocks = sizes.map((k) => ({ data: [], ecw: [], k }));
  let at = 0;
  for (let i = 0; i < Math.max(...sizes); i++) for (const b of blocks) if (i < b.k) b.data.push(words[at++]);
  for (let i = 0; i < ec; i++) for (const b of blocks) b.ecw.push(words[at++]);
  for (const b of blocks) if (!syndromesZero({ all: [...b.data, ...b.ecw], ecLen: ec })) throw new Error("error correction check failed");
  const data = blocks.flatMap((b) => b.data);
  let pos = 0;
  const take = (len) => { let v = 0; for (let i = 0; i < len; i++, pos++) v = (v << 1) | ((data[pos >> 3] >> (7 - (pos & 7))) & 1); return v; };
  if (take(4) !== 4) throw new Error("not byte mode");
  const length = take(version <= 9 ? 8 : 16);
  const bytes = Uint8Array.from({ length }, () => take(8));
  return { text: new TextDecoder("utf-8", { fatal: true }).decode(bytes), version, mask, data };
}

/** The matrix of an SVG path written by qrPath ("M<x> <y>h1v1h-1z" per dark module) over a square of `side`. */
export function matrixFromPath(d, side) {
  const rows = Array.from({ length: side }, () => new Array(side).fill(false));
  for (const m of d.matchAll(/M(\d+) (\d+)h1v1h-1z/g)) rows[Number(m[2])][Number(m[1])] = true;
  return rows;
}
