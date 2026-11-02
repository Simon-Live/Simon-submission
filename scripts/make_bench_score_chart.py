"""The dose-response chart of `make bench-score` as one SVG (docs/specs/scoring-validity.md AC-SV05).

    dose_response_svg(curves, fires, bands) -> str

`curves` is `{joint: [(planted_deg, mean value, min, max)]}` (`make_score_validity.mean_curves`), `fires` the per-joint summary
(`make_score_validity.fire_summary`: median, min, max first fire, takes, never) and `bands` the grade bands of the score
(`part5.score.BANDS`). The text is built from the numbers, so the title states what the data say. Dataviz rules applied: the
title is the finding; one line per joint, labelled at the line's end instead of a legend; colours from the Okabe-Ito
palette (safe for the common colour blindnesses) with a different marker shape and dash pattern per joint, so colour is
never the only channel; text at 12 px or more with a contrast of at least 4.5 to 1 on white; quiet grid; the axes carry
their units; the grade bands are reference lines; the first-fire rings differ in radius so ones at the same point stay
legible; a `<title>` and a `<desc>` say the same in words. Pure standard library: no plotting package, deterministic bytes.
"""
from html import escape

WIDTH, HEIGHT = 820, 548
LEFT, RIGHT, TOP, BOTTOM = 70, 150, 100, 150
FONT = "system-ui, -apple-system, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif"
INK, MUTED, GRID, BAND = "#1a1a1a", "#595959", "#e6e6e6", "#b3b3b3"
# joint -> (line colour, label colour with a contrast of 4.5 or more on white, marker, dash pattern, ring radius)
STYLE = {
    "knee": ("#0072B2", "#005A8D", "circle", "none", 7),
    "hip": ("#D55E00", "#9E4500", "square", "7 4", 10),
    "elbow": ("#009E73", "#006B4F", "triangle", "2 4", 13),
    "trunk": ("#CC79A7", "#9B4A78", "diamond", "9 3 2 3", 16),
}
MIN_LABEL_GAP = 16


def _n(x):
    """A number as the shortest stable text with one decimal at most."""
    return f"{x:.1f}".rstrip("0").rstrip(".")


def _marker(shape, x, y, colour):
    if shape == "circle":
        return f'<circle cx="{_n(x)}" cy="{_n(y)}" r="3.6" fill="{colour}"/>'
    if shape == "square":
        return f'<rect x="{_n(x - 3.4)}" y="{_n(y - 3.4)}" width="6.8" height="6.8" fill="{colour}"/>'
    if shape == "triangle":
        pts = f"{_n(x)},{_n(y - 4.4)} {_n(x + 4.2)},{_n(y + 3.2)} {_n(x - 4.2)},{_n(y + 3.2)}"
        return f'<polygon points="{pts}" fill="{colour}"/>'
    pts = f"{_n(x)},{_n(y - 4.6)} {_n(x + 4.2)},{_n(y)} {_n(x)},{_n(y + 4.6)} {_n(x - 4.2)},{_n(y)}"
    return f'<polygon points="{pts}" fill="{colour}"/>'


def _spread_labels(items, gap=MIN_LABEL_GAP):
    """Push end labels `[(y, key)]` apart so none is closer than `gap`; returns `{key: y}` in the input order of y."""
    placed, last = {}, None
    for y, key in sorted(items):
        y = y if last is None or y - last >= gap else last + gap
        placed[key], last = y, y
    return placed


def _at(series, deg):
    """The mean value of a `(deg, mean, lo, hi)` series at the grid angle `deg`, or None."""
    return next((m for d, m, _, _ in series if abs(d - deg) < 1e-9), None)


def headline(curves, fires):
    """The title: where the matching fault first fires, from the medians (a joint that never fires is named)."""
    firing = {j: fires[j]["median_low"] for j in curves if fires[j]["median_low"] is not None}
    if not firing:
        return "No matching fault fired on any joint up to the largest planted error"
    lo, hi = min(firing.values()), max(firing.values())
    if len(firing) < len(curves):
        silent = ", ".join(j for j in curves if j not in firing)
        return f"Faults first fire at {_n(lo)} to {_n(hi)} degrees of planted error; none for {silent}"
    return f"Faults first fire at {_n(lo)} to {_n(hi)} degrees of planted error"


def description(curves, fires):
    """The chart in words, for `<desc>`: first fire and the mean score at 0, 10, 20 and 30 degrees per joint."""
    parts = []
    for joint, series in curves.items():
        f = fires[joint]
        fire = f"first fires at {_n(f['median_low'])} degrees" if f["median_low"] is not None else "does not fire in the median take"
        marks = ", ".join(f"{_n(_at(series, d))} at {d} degrees" for d in (0, 10, 20, 30) if _at(series, d) is not None)
        parts.append(f"{joint}: {fire}; mean score {marks}")
    return "Mean score against planted joint-angle error. " + ". ".join(parts) + "."


def dose_response_svg(curves, fires, bands):
    """The chart as SVG text."""
    pw, ph = WIDTH - LEFT - RIGHT, HEIGHT - TOP - BOTTOM
    xmax = max(d for series in curves.values() for d, _, _, _ in series)
    low = min(m for series in curves.values() for _, m, _, _ in series)
    ymin = max(0, int(low // 10) * 10 - 10)
    sx, sy = (lambda d: LEFT + pw * d / xmax), (lambda v: TOP + ph * (100 - v) / (100 - ymin))
    n_takes = max(f["takes"] for f in fires.values())
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {WIDTH} {HEIGHT}" width="{WIDTH}" height="{HEIGHT}" '
           f'role="img" aria-labelledby="chart-title chart-desc" font-family="{FONT}">',
           f'<title id="chart-title">{escape(headline(curves, fires))}</title>',
           f'<desc id="chart-desc">{escape(description(curves, fires))}</desc>',
           f'<rect width="{WIDTH}" height="{HEIGHT}" fill="#ffffff"/>',
           f'<text x="{LEFT}" y="30" font-size="18" font-weight="600" fill="{INK}">{escape(headline(curves, fires))}</text>',
           f'<text x="{LEFT}" y="52" font-size="13" fill="{MUTED}">Score against planted joint-angle error: the mean of '
           f'{n_takes} clean seed 5 correct takes per joint, shipped score.</text>',
           f'<text x="{LEFT}" y="70" font-size="13" fill="{MUTED}">Rings mark where the matching fault first fires. '
           f'The vertical axis starts at {ymin}.</text>']
    edges = {lo for lo, _ in bands}
    for v in range(ymin, 101, 10):   # the y tick labels, and a grid line where no grade band line is drawn
        if v not in edges or v == ymin:
            out.append(f'<line x1="{LEFT}" y1="{_n(sy(v))}" x2="{LEFT + pw}" y2="{_n(sy(v))}" stroke="{GRID}" stroke-width="1"/>')
        out.append(f'<text x="{LEFT - 8}" y="{_n(sy(v) + 4)}" font-size="12" text-anchor="end" fill="{MUTED}">{v}</text>')
    tops = [100] + [lo for lo, _ in bands[:-1]]
    for (lo_edge, letter), top_edge in zip(bands, tops):   # grade bands: a reference line at each lower edge, the letter inside
        if ymin < lo_edge < 100:
            out.append(f'<line x1="{LEFT}" y1="{_n(sy(lo_edge))}" x2="{LEFT + pw}" y2="{_n(sy(lo_edge))}" stroke="{BAND}" '
                       f'stroke-width="1" stroke-dasharray="4 4"/>')
        if top_edge > ymin:
            mid = (top_edge + max(lo_edge, ymin)) / 2
            out.append(f'<text x="{LEFT + 6}" y="{_n(sy(mid) + 4)}" font-size="12" fill="{MUTED}">{escape(letter)}</text>')
    xs = [i * 5 for i in range(int(xmax // 5) + 1)]
    for d in xs:   # x ticks
        out.append(f'<line x1="{_n(sx(d))}" y1="{TOP + ph}" x2="{_n(sx(d))}" y2="{TOP + ph + 5}" stroke="{MUTED}"/>')
        out.append(f'<text x="{_n(sx(d))}" y="{TOP + ph + 20}" font-size="12" text-anchor="middle" fill="{MUTED}">{d}</text>')
    out.append(f'<line x1="{LEFT}" y1="{TOP + ph}" x2="{LEFT + pw}" y2="{TOP + ph}" stroke="{MUTED}"/>')
    out.append(f'<text x="{_n(LEFT + pw / 2)}" y="{TOP + ph + 42}" font-size="13" text-anchor="middle" fill="{INK}">'
               f'Planted joint-angle error (degrees)</text>')
    out.append(f'<text transform="translate(18 {_n(TOP + ph / 2)}) rotate(-90)" font-size="13" text-anchor="middle" '
               f'fill="{INK}">Score (0 to 100)</text>')
    ends = _spread_labels([(sy(series[-1][1]), joint) for joint, series in curves.items()])
    for joint, series in curves.items():   # one line per joint: path, markers, ring, end label
        line, label, shape, dash, radius = STYLE[joint]
        pts = " ".join(f"{_n(sx(d))},{_n(sy(m))}" for d, m, _, _ in series)
        out.append(f'<polyline points="{pts}" fill="none" stroke="{line}" stroke-width="2.2" stroke-dasharray="{dash}" '
                   f'stroke-linejoin="round"/>')
        out += [_marker(shape, sx(d), sy(m), line) for d, m, _, _ in series]
        fire = fires[joint]["median_low"]
        if fire is not None and _at(series, fire) is not None:
            x, y = sx(fire), sy(_at(series, fire))
            out.append(f'<line x1="{_n(x)}" y1="{_n(y + radius)}" x2="{_n(x)}" y2="{TOP + ph}" stroke="{line}" '
                       f'stroke-width="1" stroke-dasharray="1 3" opacity="0.7"/>')
            out.append(f'<circle cx="{_n(x)}" cy="{_n(y)}" r="{radius}" fill="none" stroke="{line}" stroke-width="1.6"/>')
        out.append(f'<text x="{LEFT + pw + 12}" y="{_n(ends[joint] + 4)}" font-size="13" font-weight="600" '
                   f'fill="{label}">{escape(joint)} {_n(series[-1][1])}</text>')
    notes = []
    for joint in curves:
        f, label = fires[joint], STYLE[joint][1]
        text = (f"{joint} {_n(f['median_low'])} (takes {_n(f['min'])} to {_n(f['max'])})" if f["max"] is not None
                else f"{joint} {_n(f['median_low']) if f['median_low'] is not None else 'none'} ({f['never']} of {f['takes']} takes never fire)")
        notes.append((label, text))
    out.append(f'<text x="{LEFT}" y="{TOP + ph + 70}" font-size="12" fill="{MUTED}">First fire in degrees, lower median of the takes '
               f'(smallest to largest):</text>')
    for i, (label, text) in enumerate(notes):
        out.append(f'<text x="{LEFT + (i % 2) * 330}" y="{TOP + ph + 90 + (i // 2) * 18}" font-size="12" fill="{label}" '
                   f'font-weight="600">{escape(text)}</text>')
    out.append("</svg>")
    return "\n".join(out) + "\n"
