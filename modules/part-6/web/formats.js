// Format adapters for keyframes, skeleton and animation files (docs/specs/formats.md).
//
// The same semantics as part6/formats.py, held to the same golden suite
// (fixtures/conformance/formats/cases.json). One small reader per file kind turns any known shape
// into one normalized form; the player only ever sees that form. Detection is by version field
// first, then by shape. A file no reader accepts throws a FormatError whose message names the file
// and the field in plain words, byte for byte the message the Python readers raise.
//
// Pure: no I/O, no DOM, no clock, no imports. Data is untrusted JSON, so every field is read as an
// own property and joints only by the 17 fixed names, never by a key that came from the data.

export const KINDS = Object.freeze(['keyframes', 'skeleton', 'animation']);
export const FORMATS = Object.freeze({
  animation: Object.freeze(['simon.animation/1', 'simon.animation.v1']),
  skeleton: Object.freeze(['simon.skeleton/1', 'simon.skeleton.v1']),
  keyframes: Object.freeze(['simon.keyframes/part1', 'simon.keyframes.v1']),
});
export const PRODUCER = Object.freeze({
  'simon.animation/1': 6, 'simon.animation.v1': 4, 'simon.skeleton/1': 3,
  'simon.skeleton.v1': 4, 'simon.keyframes/part1': 1, 'simon.keyframes.v1': 4,
});
export const PLAY_FPS = 30;
export const MAX_TIME_S = 7200; // two hours: no time a reader derives may be above this (E16)
export const JOINTS = Object.freeze([
  'nose', 'left_eye', 'right_eye', 'left_ear', 'right_ear',
  'left_shoulder', 'right_shoulder', 'left_elbow', 'right_elbow', 'left_wrist', 'right_wrist',
  'left_hip', 'right_hip', 'left_knee', 'right_knee', 'left_ankle', 'right_ankle',
]);

const [A1, AV1] = FORMATS.animation;
const [S1, SV1] = FORMATS.skeleton;
const [K1, KV1] = FORMATS.keyframes;
const ID_KIND = new Map(KINDS.flatMap((kind) => FORMATS[kind].map((id) => [id, kind])));
const NAME_KINDS = [['keyframe', 'keyframes'], ['skeleton', 'skeleton'], ['animation', 'animation']];
const EPS = 1e-6; // absorbs Part 3's three-decimal t_ms rounding (AC-F07)

/** A file no reader accepts. `message` is the plain-words text; `code` is its id (E1..E16). */
export class FormatError extends Error {
  constructor(message, code) {
    super(message);
    this.name = 'FormatError';
    this.code = code;
  }
}

const fail = (code, message) => new FormatError(message, code);
const has = (o, k) => o !== null && typeof o === 'object' && Object.prototype.hasOwnProperty.call(o, k);
const get = (o, k) => (has(o, k) ? o[k] : undefined);
const isObj = (v) => v !== null && typeof v === 'object' && !Array.isArray(v);
const isNum = (v) => typeof v === 'number' && Number.isFinite(v);
const obj = (v) => (isObj(v) ? v : {});
const frameIndex = (t, fps) => Math.floor(t * fps + 0.5);
const SHOWN_MAX = 60; // an E2 value longer than this is cut to its first 57 characters plus "..."

/** The frame of a mark at `t` seconds on a clock of `fps`: floor(t * fps + 0.5). */
export function markFrame(t, fps) {
  return frameIndex(t, fps);
}

// ---- detection ------------------------------------------------------------------------------

// The known id named by `format`, else by `schema`, or null (AC-F02). A string field decides: a
// known id of this kind is used, another kind's id is E3, anything else is E2 even when the other
// field is known. An unknown version is never read by a guess.
function byVersion(kind, data, file) {
  for (const field of ['format', 'schema']) {
    const v = get(data, field);
    if (typeof v === 'string') {
      if (!ID_KIND.has(v)) {
        const ids = FORMATS[kind].join(', ');
        const chars = Array.from(v); // code points, as Python counts them
        const shown = chars.length <= SHOWN_MAX ? v : `${chars.slice(0, SHOWN_MAX - 3).join('')}...`;
        throw fail('E2', `${file}: ${field} "${shown}" is not a version Part 6 reads (it reads ${ids})`);
      }
      const other = ID_KIND.get(v);
      if (other !== kind) throw fail('E3', `${file}: holds ${v}, which belongs in ${other}.json, not ${kind}.json`);
      return v;
    }
  }
  return null;
}

const outOfRange = (file, where) => fail('E16', `${file}: ${where}: time must be from 0 to two hours`);

// `t` seconds, or E16 unless it is from 0 to two hours (this bounds a held skeleton's frames).
function inLimit(t, file, where) {
  if (!(t >= 0 && t <= MAX_TIME_S)) throw outOfRange(file, where);
  return t;
}

// Plain string sort by code point, the order Python's sorted() gives (not UTF-16 unit order).
function byCodePoint(a, b) {
  const x = Array.from(a, (c) => c.codePointAt(0));
  const y = Array.from(b, (c) => c.codePointAt(0));
  const n = Math.min(x.length, y.length);
  for (let i = 0; i < n; i += 1) if (x[i] !== y[i]) return x[i] - y[i];
  return x.length - y.length;
}

function start(kind, data, file) {
  const name = file || `${kind}.json`;
  if (!isObj(data)) throw fail('E1', `${name}: is not a JSON object`);
  return [name, byVersion(kind, data, name)];
}

const noReader = (kind, file) =>
  fail('E4', `${file}: has no format or schema field and its shape matches no ${kind} reader`);

const isKeyList = (v) => Array.isArray(v) && v.length > 0 && isObj(v[0]) && has(v[0], 'joints');

/** The kind of an imported file: version id, then file name, then shape (AC-F03). */
export function detectKind(data, fileName) {
  const name = typeof fileName === 'string' && fileName ? fileName : 'file';
  if (!isObj(data)) throw fail('E1', `${name}: is not a JSON object`);
  for (const field of ['format', 'schema']) {
    const v = get(data, field);
    if (typeof v === 'string' && ID_KIND.has(v)) return ID_KIND.get(v);
  }
  const low = name.toLowerCase();
  for (const [needle, kind] of NAME_KINDS) if (low.includes(needle)) return kind;
  if (has(data, 'frames')) return has(data, 'fps') ? 'animation' : 'skeleton';
  if (isKeyList(get(data, 'keyframes'))) return 'skeleton';
  if (has(data, 'people') || has(data, 'keyframes')) return 'keyframes';
  throw fail('E4', `${name}: has no format or schema field and its shape matches no reader`);
}

// ---- joints and persons ---------------------------------------------------------------------

function vec(v) {
  let parts = null;
  if (Array.isArray(v)) parts = v.length >= 3 ? [v[0], v[1], v[2]] : null;
  else if (isObj(v)) parts = [get(v, 'x'), get(v, 'y'), get(v, 'z')];
  return parts && parts.every(isNum) ? parts : null;
}

function readJoints(src, file, where) {
  const from = isObj(src) ? src : {};
  const out = {};
  for (const name of JOINTS) {
    if (!has(from, name)) throw fail('E7', `${file}: ${where}.joints.${name}: missing`);
    const v = vec(from[name]);
    if (v === null) throw fail('E8', `${file}: ${where}.joints.${name}: needs three finite numbers`);
    out[name] = v;
  }
  return out;
}

function pickPerson(people) {
  if (!Array.isArray(people) || people.length === 0) return null;
  const i = people.findIndex((p) => isObj(p) && isNum(get(p, 'id')) && p.id === 0);
  return i < 0 ? 0 : i;
}

function personJoints(people, p, file, where) {
  return readJoints(get(obj(people[p]), 'joints'), file, `${where}.people[${p}]`);
}

// ---- animation ------------------------------------------------------------------------------

function animationShape(data, file) {
  const frames = get(data, 'frames');
  if (has(data, 'fps') && Array.isArray(frames) && frames.length > 0 && isObj(frames[0])) {
    if (has(frames[0], 'people')) return A1;
    if (has(frames[0], 'joints')) return AV1;
  }
  throw noReader('animation', file);
}

function a1Frame(fr, i, fps, file) {
  const where = `frames[${i}]`;
  const tms = get(fr, 't_ms');
  const t = inLimit(isNum(tms) ? tms / 1000 : i / fps, file, where);
  const people = get(fr, 'people');
  const p = pickPerson(people);
  if (p === null) throw fail('E9', `${file}: ${where}: has no person`);
  return [t, personJoints(people, p, file, where)];
}

function v1Frame(fr, i, fps, file) {
  const tt = get(fr, 't');
  const index = get(fr, 'index');
  let t = i / fps;
  if (isNum(tt)) t = tt;
  else if (isNum(index)) t = index / fps;
  const where = `frames[${i}]`;
  return [inLimit(t, file, where), readJoints(get(fr, 'joints'), file, where)];
}

export function readAnimation(data, file = 'animation.json') {
  const [name, id] = start('animation', data, file);
  const format = id === null ? animationShape(data, name) : id;
  const by = id === null ? 'shape' : 'version';
  const fps = get(data, 'fps');
  if (!isNum(fps) || !(fps > 0)) throw fail('E5', `${name}: fps: must be a number above 0`);
  const frames = get(data, 'frames');
  if (!Array.isArray(frames) || frames.length === 0) {
    throw fail('E6', `${name}: frames: must be a non-empty list`);
  }
  const readFrame = format === A1 ? a1Frame : v1Frame;
  const out = [];
  let prev = null;
  for (let i = 0; i < frames.length; i += 1) {
    const fr = obj(frames[i]);
    const [t, joints] = readFrame(fr, i, fps, name);
    if (prev !== null && !(t > prev)) {
      throw fail('E10', `${name}: frames[${i}]: time must be later than the frame before`);
    }
    out.push({ t, interpolated: get(fr, 'interpolated') === true, joints });
    prev = t;
  }
  return {
    kind: 'animation', format, detected_by: by, source_kind: 'animation', fps, frames: out, held: false,
  };
}

// ---- skeleton -------------------------------------------------------------------------------

// [path prefix, key list] of the skeleton key poses, or null: a top-level `keyframes` list whose
// items carry `joints`, else the first top-level object field in sorted key order (plain string
// sort, so both readers agree) whose `format` is simon.skeleton.v1 and which holds such a list
// (Part 3 `--view part4`).
function keyBlock(data) {
  if (isKeyList(get(data, 'keyframes'))) return ['keyframes', data.keyframes];
  for (const field of Object.keys(data).sort(byCodePoint)) {
    const val = data[field];
    if (isObj(val) && get(val, 'format') === SV1 && isKeyList(get(val, 'keyframes'))) {
      return [`${field}.keyframes`, val.keyframes];
    }
  }
  return null;
}

function skeletonShape(data, file) {
  const frames = get(data, 'frames');
  if (!has(data, 'fps') && Array.isArray(frames) && frames.length > 0 && isObj(frames[0])
      && has(frames[0], 'people')) return S1;
  if (isKeyList(get(data, 'keyframes'))) return SV1;
  throw noReader('skeleton', file);
}

function skeletonFrames(data, file) {
  const frames = get(data, 'frames');
  if (!Array.isArray(frames) || frames.length === 0) return null;
  const out = [];
  for (let i = 0; i < frames.length; i += 1) {
    const fr = obj(frames[i]);
    const tms = get(fr, 't_ms');
    const tt = get(fr, 't');
    let t;
    if (isNum(tms)) t = tms / 1000;
    else if (isNum(tt)) t = tt;
    else throw fail('E11', `${file}: frames[${i}]: needs t_ms or t`);
    inLimit(t, file, `frames[${i}]`);
    const people = get(fr, 'people');
    const p = pickPerson(people);
    out.push({ t, joints: p === null ? null : personJoints(people, p, file, `frames[${i}]`) });
  }
  return out;
}

function skeletonKeys(block, file) {
  if (block === null) return null;
  const [prefix, items] = block;
  const out = [];
  for (let i = 0; i < items.length; i += 1) {
    const item = obj(items[i]);
    const where = `${prefix}[${i}]`;
    const tt = get(item, 't');
    const index = get(item, 'index');
    let t;
    if (isNum(tt)) t = tt;
    else if (isNum(index)) t = index / PLAY_FPS;
    else throw fail('E11', `${file}: ${where}: needs t or index`);
    inLimit(t, file, where);
    const name = has(item, 'name') ? item.name : '';
    if (typeof name !== 'string') throw fail('E15', `${file}: ${where}.name: must be a string`);
    out.push({ t, name, joints: readJoints(get(item, 'joints'), file, where) });
  }
  return out;
}

export function readSkeleton(data, file = 'skeleton.json') {
  const [name, id] = start('skeleton', data, file);
  const format = id === null ? skeletonShape(data, name) : id;
  const by = id === null ? 'shape' : 'version';
  const frames = skeletonFrames(data, name);
  const keys = skeletonKeys(keyBlock(data), name);
  const present = (frames || []).some((f) => f.joints !== null);
  if (!present && !(keys && keys.length > 0)) {
    throw fail('E9s', `${name}: no frame has a person and there are no key poses`);
  }
  return { kind: 'skeleton', format, detected_by: by, frames, keys };
}

/** A skeleton played as its own animation: 30 fps, each pose held, never blended (AC-F07). */
export function animationFromSkeleton(skeleton) {
  const frames = skeleton.frames || [];
  let samples = frames.filter((f) => f.joints !== null);
  if (samples.length === 0) samples = (skeleton.keys || []).slice();
  if (samples.length === 0) {
    throw fail('E9s', 'skeleton.json: no frame has a person and there are no key poses');
  }
  samples = samples.slice().sort((a, b) => a.t - b.t);
  const count = Math.max(1, frameIndex(samples[samples.length - 1].t, PLAY_FPS) + 1);
  const exact = new Set(samples.map((s) => frameIndex(s.t, PLAY_FPS)));
  const out = [];
  let j = 0;
  for (let k = 0; k < count; k += 1) {
    const limit = k / PLAY_FPS + EPS;
    while (j + 1 < samples.length && samples[j + 1].t <= limit) j += 1;
    out.push({ t: k / PLAY_FPS, interpolated: !exact.has(k), joints: samples[j].joints });
  }
  return {
    kind: 'animation', format: skeleton.format, detected_by: skeleton.detected_by,
    source_kind: 'skeleton', fps: PLAY_FPS, frames: out, held: true,
  };
}

/** The animation when there is one, else the skeleton played as an animation (E12 for neither). */
export function playable(animation, skeleton) {
  if (animation !== undefined && animation !== null) return animation;
  if (skeleton !== undefined && skeleton !== null) return animationFromSkeleton(skeleton);
  throw fail('E12', 'nothing to play: add an animation.json or a skeleton.json');
}

// ---- keyframes ------------------------------------------------------------------------------

function keyframesShape(data, file) {
  if (Array.isArray(get(data, 'people'))) return K1;
  const list = get(data, 'keyframes');
  if (Array.isArray(list) && !isKeyList(list)) return KV1;
  throw noReader('keyframes', file);
}

// `fps` as a number, null when the file has none; E5 when it is there and not above 0.
function clockFps(data, file) {
  const fps = get(data, 'fps');
  if (fps === undefined || fps === null) return null;
  if (!isNum(fps) || !(fps > 0)) throw fail('E5', `${file}: fps: must be a number above 0`);
  return fps;
}

function markName(item, file, where) {
  const name = get(item, 'name');
  if (typeof name !== 'string') throw fail('E15', `${file}: ${where}.name: must be a string`);
  return name;
}

function part1Time(item, fps, file, where) {
  const tms = get(item, 't_ms');
  const frame = get(item, 'frame');
  if (isNum(tms) && tms >= 0) return inLimit(tms / 1000, file, where);
  if (fps !== null && isNum(frame)) return inLimit(frame / fps, file, where);
  if (isNum(tms)) throw outOfRange(file, where); // a negative t_ms with no frame clock to use
  throw fail('E14', `${file}: ${where}: needs t_ms, or frame with fps`);
}

function part1Marks(data, fps, file) {
  const people = get(data, 'people');
  if (!Array.isArray(people)) throw fail('E13', `${file}: people: must be a list`);
  const p = pickPerson(people);
  if (p === null) return [];
  const person = obj(people[p]);
  const base = `people[${p}]`;
  const reps = get(person, 'repetitions');
  if (!Array.isArray(reps)) throw fail('E13', `${file}: ${base}.repetitions: must be a list`);
  const pid = isNum(get(person, 'id')) ? person.id : p;
  const marks = [];
  for (let r = 0; r < reps.length; r += 1) {
    const rep = obj(reps[r]);
    const rbase = `${base}.repetitions[${r}]`;
    const items = get(rep, 'keyframes');
    if (!Array.isArray(items)) throw fail('E13', `${file}: ${rbase}.keyframes: must be a list`);
    const number = isNum(get(rep, 'rep')) ? rep.rep : r + 1;
    for (let k = 0; k < items.length; k += 1) {
      const item = obj(items[k]);
      const where = `${rbase}.keyframes[${k}]`;
      const name = markName(item, file, where);
      marks.push({ name, t: part1Time(item, fps, file, where), rep: number, person: pid });
    }
  }
  return marks;
}

function v1Time(item, fps, file, where) {
  const tt = get(item, 't');
  const index = get(item, 'index');
  if (isNum(tt)) return inLimit(tt, file, where);
  if (fps !== null && isNum(index)) return inLimit(index / fps, file, where);
  throw fail('E14', `${file}: ${where}: needs t, or index with fps`);
}

function v1Marks(data, fps, file) {
  const items = get(data, 'keyframes');
  if (!Array.isArray(items)) throw fail('E13', `${file}: keyframes: must be a list`);
  const marks = [];
  for (let k = 0; k < items.length; k += 1) {
    const item = obj(items[k]);
    const where = `keyframes[${k}]`;
    const name = markName(item, file, where);
    marks.push({ name, t: v1Time(item, fps, file, where), rep: null, person: null });
  }
  return marks;
}

export function readKeyframes(data, file = 'keyframes.json') {
  const [name, id] = start('keyframes', data, file);
  const format = id === null ? keyframesShape(data, name) : id;
  const by = id === null ? 'shape' : 'version';
  const fps = clockFps(data, name);
  const marks = (format === K1 ? part1Marks : v1Marks)(data, fps, name);
  marks.sort((a, b) => a.t - b.t); // Array.prototype.sort is stable
  return { kind: 'keyframes', format, detected_by: by, clock_fps: fps, marks };
}

// ---- dispatch and summary -------------------------------------------------------------------

const READERS = { keyframes: readKeyframes, skeleton: readSkeleton, animation: readAnimation };

/** The reader of `kind` applied to `data`; `file` defaults to `<kind>.json`. */
export function read(kind, data, file) {
  if (!has(READERS, kind)) {
    throw new FormatError(`${kind}: is not a file kind Part 6 reads (it reads ${KINDS.join(', ')})`);
  }
  return READERS[kind](data, file || `${kind}.json`);
}

function summaryAnimation(n) {
  const frames = n.frames;
  return {
    kind: 'animation', format: n.format, detected_by: n.detected_by, source_kind: n.source_kind,
    fps: n.fps, frame_count: frames.length, duration_s: frames[frames.length - 1].t,
    interpolated_count: frames.filter((f) => f.interpolated).length, held: n.held,
    nose_first: frames[0].joints.nose.slice(),
    left_ankle_mid: frames[Math.floor(frames.length / 2)].joints.left_ankle.slice(),
    right_wrist_last: frames[frames.length - 1].joints.right_wrist.slice(),
  };
}

function summarySkeleton(n) {
  const frames = n.frames || [];
  const keys = n.keys || [];
  return {
    kind: 'skeleton', format: n.format, detected_by: n.detected_by, frame_count: frames.length,
    present_count: frames.filter((f) => f.joints !== null).length, key_count: keys.length,
    key_names: keys.map((k) => k.name),
  };
}

function summaryKeyframes(n) {
  return {
    kind: 'keyframes', format: n.format, detected_by: n.detected_by, clock_fps: n.clock_fps,
    mark_count: n.marks.length, marks: n.marks.map((m) => [m.name, m.t]),
    frames_at_30: n.marks.map((m) => markFrame(m.t, PLAY_FPS)),
  };
}

/** The comparable digest of a normalized result (AC-F10); one definition for both runners. */
export function summary(normalized) {
  if (normalized.kind === 'animation') return summaryAnimation(normalized);
  if (normalized.kind === 'skeleton') return summarySkeleton(normalized);
  return summaryKeyframes(normalized);
}

// ---- strict JSON (docs/specs/formats.md "Error Cases") --------------------------------------

/**
 * The browser's twin of part6/validate.py parse_json, and the one place a browser reads a JSON file:
 * the Import screen, the player and the golden runner all call it. Takes the file's bytes (an
 * ArrayBuffer or a typed array), never throws, and returns {ok: true, data, text} (`text` is the
 * decoded text without the byte order mark: what a caller that must send the file sends) or
 * {ok: false} for bytes that are not valid UTF-8, text that is not JSON, and a number that is not
 * finite (JSON.parse turns 1e400 into Infinity, which the server refuses too).
 */
export function parseStrictJson(bytes) {
  let text;
  let data;
  try {
    // fatal: a byte sequence that is not valid UTF-8 throws instead of becoming U+FFFD; one leading
    // byte order mark is dropped, as the server's utf-8-sig does. A fresh decoder keeps no state.
    text = new TextDecoder('utf-8', { fatal: true }).decode(bytes);
    data = JSON.parse(text);
  } catch (error) {
    return { ok: false };
  }
  return holdsNonFinite(data) ? { ok: false } : { ok: true, data, text };
}

/**
 * True when a parsed JSON value holds a number that is not finite. JSON.parse turns 1e400 into
 * Infinity, and the server refuses such a file as not valid JSON (part6/validate.py parse_json),
 * so every browser read of a JSON file refuses it too (parseStrictJson). Iterative, so a deeply
 * nested file cannot run out of stack.
 */
export function holdsNonFinite(value) {
  if (typeof value === 'number') return !Number.isFinite(value);
  if (value === null || typeof value !== 'object') return false;
  const pending = [value];
  while (pending.length > 0) {
    const node = pending.pop();
    for (const child of Array.isArray(node) ? node : Object.values(node)) {
      if (typeof child === 'number') {
        if (!Number.isFinite(child)) return true;
      } else if (child !== null && typeof child === 'object') {
        pending.push(child);
      }
    }
  }
  return false;
}
