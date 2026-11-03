// Follow capture layout (docs/specs/follow-side-by-side.md, TICKET-291): the trainer and the camera side by side at the
// same height, both whole under the sticky header. No DOM: web/follow-side.js measures and applies.

/** In portrait, each column must keep at least this share of the screen's width, else the two boxes stack. A screen
 * wider than tall (desktop, tablet, phone landscape) always has room for two columns. */
export const MIN_SHARE = 0.4;
/** Space kept between the boxes and the screen's bottom edge. */
export const MARGIN = 16;
const MIN_BOX = 80;

/**
 * @param width, height the viewport in CSS px
 * @param rowWidth the row's content width; gap the space between the two boxes
 * @param headerH the sticky header's height; between what sits between the boxes when stacked (the title and buttons)
 * @returns {layout: "side"|"stack", boxH, aspect} where aspect is the box's width over height
 */
export function followLayout({ width, height, rowWidth, headerH = 0, gap = 8, between = 0 }) {
  const room = Math.max(MIN_BOX, height - headerH - MARGIN);
  const col = (rowWidth - gap) / 2;
  if (width > 0 && col > 0 && (width >= height || col / width >= MIN_SHARE)) {
    const aspect = width < height ? 3 / 4 : 4 / 3;
    return { layout: "side", aspect, boxH: Math.floor(Math.max(MIN_BOX, Math.min(col / aspect, room))) };
  }
  const aspect = 4 / 3;
  const half = (room - gap - between) / 2;
  return { layout: "stack", aspect, boxH: Math.floor(Math.max(MIN_BOX, Math.min(rowWidth / aspect, half))) };
}
