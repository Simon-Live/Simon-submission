// Small, pure pixel checks: no camera, DOM, network, or pose model is needed by this module.
import { PRERECORD_THRESHOLDS as T, PRERECORD_CODES, QUALITY_TIPS } from "./quality-constants.js";

const luma = (data, i) => 0.2126 * data[i] + 0.7152 * data[i + 1] + 0.0722 * data[i + 2];
const round = (n) => Math.round(n * 10000) / 10000;

/** RGBA ImageData (or its plain equivalent) in, numeric readings out. No source pixels are returned. */
export function measurePreview(image, previous = null) {
  const { width, height, data } = image || {};
  if (!Number.isInteger(width) || !Number.isInteger(height) || width < 3 || height < 3 || !data || data.length < width * height * 4) return null;
  const gray = new Float64Array(width * height);
  const borderX = Math.max(1, Math.floor(width * T.border_fraction));
  const borderY = Math.max(1, Math.floor(height * T.border_fraction));
  const isBorder = (x, y) => x < borderX || x >= width - borderX || y < borderY || y >= height - borderY;
  const comparable = previous && previous.width === width && previous.height === height && previous.data?.length >= data.length;
  let sum = 0, clipped = 0, center = 0, center2 = 0, centerN = 0, border = 0, borderN = 0, difference = 0;
  for (let y = 0; y < height; y++) for (let x = 0; x < width; x++) {
    const p = y * width + x, value = luma(data, p * 4);
    gray[p] = value;
    sum += value;
    if (value >= T.clipped_luma) clipped++;
    if (isBorder(x, y)) {
      border += value;
      borderN++;
      if (comparable) difference += Math.abs(value - luma(previous.data, p * 4));
    } else {
      center += value;
      center2 += value * value;
      centerN++;
    }
  }
  let lap = 0, lap2 = 0, lapN = 0, edges = 0, edgeN = 0;
  for (let y = 1; y < height - 1; y++) for (let x = 1; x < width - 1; x++) {
    const p = y * width + x;
    if (isBorder(x, y)) {
      const gradient = Math.abs(gray[p + 1] - gray[p]) + Math.abs(gray[p + width] - gray[p]);
      if (gradient > T.border_edge_gradient) edges++;
      edgeN++;
    } else {
      const value = gray[p - 1] + gray[p + 1] + gray[p - width] + gray[p + width] - 4 * gray[p];
      lap += value;
      lap2 += value * value;
      lapN++;
    }
  }
  const centerMean = centerN ? center / centerN : sum / gray.length;
  return {
    mean_luma: round(sum / gray.length),
    center_luma: round(centerMean),
    border_luma: round(borderN ? border / borderN : centerMean),
    clipped_share: round(clipped / gray.length),
    sharpness: round(lapN ? Math.max(0, lap2 / lapN - (lap / lapN) ** 2) : 0),
    center_contrast: round(centerN ? Math.sqrt(Math.max(0, center2 / centerN - centerMean ** 2)) : 0),
    border_difference: round(comparable && borderN ? difference / borderN / 255 : 0),
    border_edge_density: round(edgeN ? edges / edgeN : 0),
  };
}

/** These are setup suggestions, never server quality issues or scoring decisions. */
export function previewCodes(readings) {
  if (!readings) return [];
  const r = readings, codes = [];
  if (r.mean_luma < T.dark_luma) codes.push("dark");
  if (r.border_luma - r.center_luma > T.backlit_difference && r.center_luma < T.backlit_center_luma_max) codes.push("backlit");
  if (r.clipped_share > T.clipped_share) codes.push("overexposed");
  if (r.border_difference > T.camera_border_difference) codes.push("camera_moving");
  // Flat walls and darkness do not contain enough detail to support an out-of-focus suggestion.
  if (r.sharpness < T.blurry_laplacian_variance && r.center_contrast >= T.blurry_min_contrast
      && r.mean_luma >= T.blurry_min_luma && r.clipped_share <= T.clipped_share) codes.push("blurry");
  if (r.border_edge_density > T.busy_border_edge_density) codes.push("busy_background");
  return codes;
}

/** Retain an active tip until two seconds of continuously good readings; never mutate caller state. */
export function updateTipState(state = {}, codes = [], nowMs = 0) {
  const next = {};
  for (const code of PRERECORD_CODES) {
    if (codes.includes(code)) next[code] = { clearSince: null };
    else if (state[code]) {
      const clearSince = state[code].clearSince ?? nowMs;
      if (nowMs - clearSince < T.clear_ms) next[code] = { clearSince };
    }
  }
  return next;
}

export function visibleTips(state = {}) {
  return PRERECORD_CODES.filter((code) => state[code]).slice(0, T.max_tips)
    .map((code) => ({ code, text: QUALITY_TIPS[code] }));
}
