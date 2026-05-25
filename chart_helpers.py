"""
chart_helpers.py — inline SVG chart primitives for the dashboard pages.

Design goals:
  - Zero JS dependencies; charts render with the HTML.
  - Match the existing dark-gold dashboard theme (gold-on-near-black).
  - Crisp typography via the JetBrains Mono / Fraunces stack already loaded
    by the storefront. Pages that don't already load Fraunces fall back
    cleanly to the system stack — these charts never block on fonts.
  - Accessible: aria-labels, deterministic colors, no color-only encoding
    for status (red/yellow/green bands also carry text labels).

All public functions return a string of SVG/HTML.
"""
from __future__ import annotations

import html as _h
from typing import Iterable, Sequence


# Theme tokens — keep in sync with storefront_agent.STOREFRONT_CSS.
GOLD        = "#c9a542"
GOLD_BRIGHT = "#f0d27a"
GOLD_DIM    = "#8a7521"
INK         = "#f1efe9"
MUTE        = "#9a9388"
FAINT       = "#5d5852"
SURFACE     = "#141414"
SURFACE_2   = "#1c1c1c"
EDGE        = "rgba(201,165,66,0.18)"
RED         = "#d35a5a"
AMBER       = "#e0a647"
GREEN       = "#5fb874"
GRID        = "rgba(255,255,255,0.05)"

_BUCKET_COLORS = {
    "red":   RED,
    "amber": AMBER,
    "yellow": AMBER,
    "green": GREEN,
    "ok":    GREEN,
    "good":  GREEN,
    "severe": RED,
    "poor":  AMBER,
    "blocked": MUTE,
    "dead-zone": MUTE,
    "apply": GOLD_BRIGHT,
}

_FONT_STACK = "'JetBrains Mono', ui-monospace, Menlo, monospace"
_LABEL_STACK = "'Familjen Grotesk', system-ui, sans-serif"
_DISPLAY_STACK = "'Fraunces', Georgia, serif"


def _fmt_money(v: float) -> str:
    # Edge: negatives are rare here but should render with a sign rather than collapse to $0.
    if v is None:
        return "$0"
    try:
        v = float(v)
    except (TypeError, ValueError):
        return "$0"
    neg = v < 0
    a = abs(v)
    # >= $10k: drop the fractional decimal entirely ($12k); >= $1k: one decimal ($1.2k).
    if a >= 10000:
        s = f"${a/1000:.0f}k"
    elif a >= 1000:
        s = f"${a/1000:.1f}k"
    elif a >= 100:
        # Whole dollars look cleaner once amounts are >= $100.
        s = f"${a:.0f}"
    else:
        # Sub-$100 keeps cents so $42.50 doesn't render the same as $43.
        s = f"${a:.2f}"
    return ("-" + s) if neg else s


def _fmt_int(v: float) -> str:
    try:
        return f"{int(round(float(v))):,}"
    except (TypeError, ValueError):
        return "0"


def card_wrapper(title: str, subtitle: str, body_html: str, *, accent: str = GOLD_BRIGHT) -> str:
    """Reusable framed container so every chart sits in the same kind of card."""
    return f'''
<figure class="ch-card" style="
  background:{SURFACE};border:1px solid {EDGE};border-radius:4px;
  padding:1.1rem 1.3rem 1.2rem;margin:0 0 1.2rem;
  box-shadow:0 14px 40px -22px rgba(0,0,0,0.8);">
  <figcaption style="display:flex;align-items:baseline;justify-content:space-between;gap:1rem;margin-bottom:0.85rem;border-bottom:1px solid {EDGE};padding-bottom:0.5rem;">
    <span style="font-family:{_DISPLAY_STACK};font-style:italic;font-weight:500;font-size:18px;color:{INK};">{_h.escape(title)}</span>
    <span style="font-family:{_FONT_STACK};font-size:10px;letter-spacing:0.16em;text-transform:uppercase;color:{accent};">{_h.escape(subtitle)}</span>
  </figcaption>
  {body_html}
</figure>
'''.strip()


def bar_chart_vertical(
    rows: Sequence[tuple[str, float]],
    *,
    width: int = 760,
    height: int = 220,
    value_fmt=_fmt_money,
    bar_color: str = GOLD,
    accent_color: str = GOLD_BRIGHT,
    accent_index: int | None = None,
    y_label: str = "",
) -> str:
    """Daily/weekly bar chart. rows = [(label, value), …]."""
    if not rows:
        return f'<div style="color:{MUTE};font-family:{_LABEL_STACK};padding:1rem 0;">No data yet.</div>'

    pad_l, pad_r, pad_t, pad_b = 44, 14, 14, 32
    inner_w = width - pad_l - pad_r
    inner_h = height - pad_t - pad_b
    n = len(rows)
    gap = max(2, inner_w // (n * 8))
    bar_w = max(2, (inner_w - gap * (n - 1)) / n)

    # All-zero rows: show an empty-state instead of an axis with a single "$0" tick.
    # Rows may be 2-tuple (label, value) or 3-tuple (label, value, tooltip).
    raw_vmax = max((r[1] for r in rows), default=0)
    if not raw_vmax or raw_vmax <= 0:
        return (f'<div style="color:{MUTE};font-family:{_LABEL_STACK};'
                f'padding:1.4rem 0 1.2rem;text-align:center;">'
                f'No activity in this window.</div>')

    vmax = raw_vmax
    # Round vmax up to a "nice" tick. The mag exponent must be safe for any
    # vmax >= 1 — the previous `log10 - 1` underflowed for vmax in [1, 9].
    import math
    if vmax >= 10:
        mag = 10 ** max(0, int(math.log10(vmax)) - 1)
    elif vmax >= 1:
        # $2 max: tick on $0.50; $5 max: tick on $1.25 → round up to $2 quarters.
        mag = 0.5
    else:
        # Sub-$1 (cents) — quarter-dollar grid keeps labels readable.
        mag = 0.25
    tick = max(mag, math.ceil(vmax / mag / 4) * mag)
    nice_max = tick * 4 if tick * 4 >= vmax else tick * 5

    # Gridlines
    grid_lines = []
    y_labels = []
    for i in range(5):
        y = pad_t + (inner_h * i / 4)
        v = nice_max * (1 - i / 4)
        grid_lines.append(f'<line x1="{pad_l}" y1="{y:.1f}" x2="{pad_l+inner_w}" y2="{y:.1f}" stroke="{GRID}" stroke-width="1"/>')
        y_labels.append(f'<text x="{pad_l-6}" y="{y+3.5:.1f}" text-anchor="end" fill="{FAINT}" font-family="{_FONT_STACK}" font-size="9.5">{value_fmt(v)}</text>')

    bars = []
    xlabels = []
    for i, row in enumerate(rows):
        # Accept either (label, value) or (label, value, tooltip_label) so
        # callers can render a compact axis tick but a rich hover tooltip.
        if len(row) == 3:
            label, val, tip_label = row
        else:
            label, val = row
            tip_label = label
        x = pad_l + i * (bar_w + gap)
        h = inner_h * (val / nice_max) if nice_max else 0
        y = pad_t + (inner_h - h)
        col = accent_color if (accent_index is not None and i == accent_index) else bar_color
        bars.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_w:.1f}" height="{h:.1f}" fill="{col}" opacity="{0.95 if col == accent_color else 0.85}" rx="1"><title>{_h.escape(str(tip_label))}: {value_fmt(val)}</title></rect>')
        if n <= 14 or i % max(1, n // 8) == 0:
            xlabels.append(f'<text x="{x + bar_w/2:.1f}" y="{height - 10}" text-anchor="middle" fill="{MUTE}" font-family="{_FONT_STACK}" font-size="9">{_h.escape(str(label))}</text>')

    yl = f'<text x="{pad_l-30}" y="{pad_t-4}" fill="{FAINT}" font-family="{_FONT_STACK}" font-size="9" letter-spacing="0.1em">{_h.escape(y_label)}</text>' if y_label else ""
    return f'''<svg viewBox="0 0 {width} {height}" width="100%" height="auto" role="img" aria-label="{_h.escape(y_label or 'bar chart')}" style="display:block;max-width:100%">
  {yl}
  {''.join(grid_lines)}
  {''.join(bars)}
  {''.join(y_labels)}
  {''.join(xlabels)}
</svg>'''


def bar_chart_horizontal(
    rows: Sequence[tuple[str, float, str | None]],
    *,
    width: int = 720,
    row_height: int = 28,
    value_fmt=_fmt_int,
    default_color: str = GOLD,
) -> str:
    """Horizontal bars. rows = [(label, value, color_or_None), …]."""
    if not rows:
        return f'<div style="color:{MUTE};font-family:{_LABEL_STACK};padding:1rem 0;">No data yet.</div>'
    label_w = 150
    value_w = 70
    pad_l = 12
    pad_r = 12
    bar_x = pad_l + label_w
    bar_max = width - bar_x - value_w - pad_r
    vmax = max((v for _, v, _ in rows), default=0) or 1
    height = row_height * len(rows) + 18

    parts = []
    for i, (label, val, color) in enumerate(rows):
        y = 9 + i * row_height
        bw = bar_max * (val / vmax)
        col = color or default_color
        parts.append(
            f'<text x="{pad_l}" y="{y + row_height/2 + 3.5:.1f}" fill="{INK}" font-family="{_LABEL_STACK}" font-size="12">{_h.escape(label)}</text>'
            f'<rect x="{bar_x}" y="{y + 4:.1f}" width="{bar_max:.1f}" height="{row_height - 12:.1f}" fill="{GRID}" rx="2"/>'
            f'<rect x="{bar_x}" y="{y + 4:.1f}" width="{bw:.1f}" height="{row_height - 12:.1f}" fill="{col}" rx="2"><title>{_h.escape(label)}: {value_fmt(val)}</title></rect>'
            f'<text x="{width - pad_r}" y="{y + row_height/2 + 3.5:.1f}" text-anchor="end" fill="{GOLD_BRIGHT}" font-family="{_FONT_STACK}" font-size="11" font-weight="600">{value_fmt(val)}</text>'
        )
    return f'''<svg viewBox="0 0 {width} {height}" width="100%" height="auto" role="img" style="display:block;max-width:100%">
  {''.join(parts)}
</svg>'''


def sparkline(values: Sequence[float], *, width: int = 240, height: int = 56, color: str = GOLD_BRIGHT, fill: str = "rgba(240,210,122,0.18)") -> str:
    if not values:
        return (f'<div style="color:{MUTE};font-family:{_LABEL_STACK};font-size:12px;'
                f'padding:0.3rem 0;">No trend data.</div>')
    n = len(values)
    vmax = max(values)
    vmin = min(values)
    rng = (vmax - vmin) or 1
    pts = []
    for i, v in enumerate(values):
        # Single-point sparkline: anchor the dot at the right edge instead of dividing by zero.
        x = (i / max(1, n - 1)) * (width - 4) + 2 if n > 1 else (width - 4)
        y = height - 4 - ((v - vmin) / rng) * (height - 8)
        pts.append(f"{x:.1f},{y:.1f}")
    last_x, last_y = pts[-1].split(",")
    if n == 1:
        # Single data point — render just a dot + baseline tick, no path/area.
        baseline_y = height - 4
        return f'''<svg viewBox="0 0 {width} {height}" width="100%" height="auto" role="img" aria-label="trend (single point)" style="display:block;max-width:{width}px">
  <line x1="2" y1="{baseline_y}" x2="{width-2}" y2="{baseline_y}" stroke="{GRID}" stroke-width="1"/>
  <circle cx="{last_x}" cy="{last_y}" r="3.0" fill="{color}"/>
</svg>'''
    path = "M " + " L ".join(pts)
    area = f"{path} L {width-2},{height-2} L 2,{height-2} Z"
    return f'''<svg viewBox="0 0 {width} {height}" width="100%" height="auto" role="img" aria-label="trend" style="display:block;max-width:{width}px">
  <path d="{area}" fill="{fill}" stroke="none"/>
  <path d="{path}" fill="none" stroke="{color}" stroke-width="1.6" stroke-linejoin="round" stroke-linecap="round"/>
  <circle cx="{last_x}" cy="{last_y}" r="2.6" fill="{color}"/>
</svg>'''


def stacked_proportion_bar(
    segments: Sequence[tuple[str, float, str]],
    *,
    width: int = 760,
    height: int = 36,
) -> str:
    """Single stacked bar showing share of total. segments=[(label, value, color), …]."""
    raw_total = sum(v for _, v, _ in segments)
    if not segments or raw_total <= 0:
        # All-zero (or empty) segments — show an explicit empty-state rather
        # than dividing by 1 and silently rendering a slim invisible bar.
        return (f'<div style="color:{MUTE};font-family:{_LABEL_STACK};'
                f'padding:0.8rem 0;text-align:center;">'
                f'No listings in any bucket yet.</div>')
    total = raw_total
    x = 0
    parts = []
    legend = []
    for label, val, color in segments:
        w = (val / total) * width
        parts.append(f'<rect x="{x:.1f}" y="0" width="{w:.1f}" height="{height}" fill="{color}"><title>{_h.escape(label)}: {_fmt_int(val)} ({val/total*100:.0f}%)</title></rect>')
        if w > 38:
            parts.append(f'<text x="{x + w/2:.1f}" y="{height/2 + 4:.1f}" text-anchor="middle" fill="#0a0a0a" font-family="{_FONT_STACK}" font-size="11" font-weight="700">{_fmt_int(val)}</text>')
        legend.append(f'<span style="display:inline-flex;align-items:center;gap:0.4rem;margin-right:1.1rem;font-family:{_FONT_STACK};font-size:10.5px;color:{MUTE};letter-spacing:0.08em;text-transform:uppercase;"><span style="display:inline-block;width:10px;height:10px;background:{color};border-radius:1px;"></span>{_h.escape(label)} · <span style="color:{INK};">{_fmt_int(val)}</span></span>')
        x += w
    return (
        f'<svg viewBox="0 0 {width} {height}" width="100%" height="auto" style="display:block;max-width:100%;border-radius:2px;overflow:hidden">'
        + ''.join(parts) + '</svg>'
        + f'<div style="margin-top:0.55rem;display:flex;flex-wrap:wrap;">{"".join(legend)}</div>'
    )


def bucket_color(name: str) -> str:
    """Resolve a status-bucket name (red/amber/green/severe/poor/ok/good/…) to a color."""
    return _BUCKET_COLORS.get((name or "").lower(), GOLD)
