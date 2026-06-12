"""Matplotlib renderer for the Calendar Digest with Context (type 9) PNG.

Output is a single PNG: columns are days (1..7), rows are a continuous
time axis from 7am to 8pm with labeled rows at 9 / 11 / 1 / 3 / 5 / 7
(odd hours) plus stub bands above 7am ("before 7") and below 8pm ("later")
for clipped events.

Each event renders as a rectangle spanning its actual start→end time:
- normal: light gray fill, thin border
- important: pale-yellow fill, thick border
- tentative: dashed outline (combinable with important)
- reminder: drawn as a slim vertical line (or short tick at the start),
  ignoring duration emphasis — these are point-in-time signals

The renderer is intentionally simple — no overlap-aware horizontal packing
within a single column for now. Multiple events in the same time slot
overlap visually, which is the desired signal (the reader sees the
conflict).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Sequence

import matplotlib
matplotlib.use("Agg")  # headless
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches


# Y-axis layout. Hours are floats — 13.5 means 1:30 PM.
Y_TOP = 5.0           # visible top edge (in hour units)
Y_MAIN_TOP = 7.0      # top of main band — events earlier clip into stub above
Y_MAIN_BOTTOM = 20.0  # bottom of main band — events later clip into stub below
Y_BOTTOM = 21.0       # visible bottom edge

ROW_LABELS = [
    (6.0, "before 7"),  # stub center
    (9.0, "9"),
    (11.0, "11"),
    (13.0, "1"),
    (15.0, "3"),
    (17.0, "5"),
    (19.0, "7"),
    (20.5, "later"),    # stub center
]
HOUR_GRID_LINES = [9.0, 11.0, 13.0, 15.0, 17.0, 19.0]
STUB_LINES = [Y_MAIN_TOP, Y_MAIN_BOTTOM]  # band boundaries

# Event styling
COLOR_NORMAL_FILL = "#e8edf3"
COLOR_NORMAL_EDGE = "#4a5b76"
COLOR_IMPORTANT_FILL = "#fff4c2"
COLOR_IMPORTANT_EDGE = "#a07a00"
COLOR_REMINDER = "#7c5cd6"
TENTATIVE_LINESTYLE = (0, (3, 2))  # dashed


@dataclass
class GridEvent:
    """Curated event passed to the renderer. Times are local datetimes."""
    start_dt: datetime
    end_dt: datetime | None
    title: str
    calendar: str
    importance: str = "normal"   # "important" | "normal"
    tentative: bool = False
    is_reminder: bool = False
    also_on: tuple[str, ...] = ()


def render_grid(
    events: Sequence[GridEvent],
    start_date: date,
    days: int,
    output_path: str,
    attribution_text: str = "",
) -> None:
    """Render the time grid as a PNG to output_path.

    `days` is clamped to [1, 7]. `events` whose dates fall outside the
    visible window are dropped (they shouldn't be in the input anyway —
    the runner is expected to fetch only the visible range).
    """
    days = max(1, min(7, days))

    # Figure size: ~1.4" per day column + 1.5" for the y-axis labels;
    # ~6" tall regardless of column count.
    fig_w = 1.5 + 1.4 * days
    fig_h = 6.5
    fig, ax = plt.subplots(figsize=(fig_w, fig_h), dpi=120)

    # Draw the day-column backgrounds and the time axis first so events
    # paint on top of them.
    _draw_day_columns(ax, start_date, days)
    _draw_time_axis(ax, days)

    # Bucket events by day index (0..days-1).
    by_day: dict[int, list[GridEvent]] = {i: [] for i in range(days)}
    for ev in events:
        day_idx = (ev.start_dt.date() - start_date).days
        if 0 <= day_idx < days:
            by_day[day_idx].append(ev)

    for day_idx, evs in by_day.items():
        # Chronological order matters only for text-stacking; overlapping
        # boxes will still overlap on the canvas regardless.
        evs.sort(key=lambda e: e.start_dt)
        for ev in evs:
            _draw_event(ax, day_idx, ev)

    # Bounds + titling
    ax.set_xlim(-0.5, days - 0.5)
    ax.set_ylim(Y_BOTTOM, Y_TOP)  # inverted: early times at top
    ax.set_xticks([])
    ax.set_yticks([])
    for s in ax.spines.values():
        s.set_visible(False)

    fig.suptitle(
        f"Calendar grid — {start_date.isoformat()} through "
        f"{(start_date + timedelta(days=days - 1)).isoformat()}",
        y=0.97, fontsize=11,
    )

    if attribution_text:
        fig.text(
            0.99, 0.01, attribution_text,
            ha="right", va="bottom",
            fontsize=6, color="#888",
        )

    fig.tight_layout(rect=(0, 0.02, 1, 0.94))
    fig.savefig(output_path, dpi=120, bbox_inches="tight")
    plt.close(fig)


def _draw_day_columns(ax, start_date: date, days: int) -> None:
    """Column backgrounds with the date-over-weekday header above each."""
    for i in range(days):
        d = start_date + timedelta(days=i)
        # Alternating-shade columns help the eye scan.
        if i % 2 == 0:
            ax.add_patch(mpatches.Rectangle(
                (i - 0.5, Y_TOP), 1.0, Y_BOTTOM - Y_TOP,
                facecolor="#fafbfc", edgecolor="none", zorder=0,
            ))
        # Vertical separator between columns.
        ax.plot(
            [i + 0.5, i + 0.5], [Y_TOP, Y_BOTTOM],
            color="#dde2ea", lw=0.6, zorder=1,
        )
        # Two-line header above the column. The y axis is inverted, so a
        # smaller y value renders higher on screen — date on top (line 1),
        # weekday name below (line 2).
        ax.text(
            i, Y_TOP - 1.1, str(d.day),
            ha="center", va="bottom", fontsize=14, fontweight="bold",
        )
        ax.text(
            i, Y_TOP - 0.15, d.strftime("%a"),
            ha="center", va="bottom", fontsize=10, color="#555",
        )


def _draw_time_axis(ax, days: int) -> None:
    """Time row labels down the left edge + hour gridlines across all days."""
    x_left = -0.5
    x_right = days - 0.5

    # Stub-band separators.
    for y in STUB_LINES:
        ax.plot([x_left, x_right], [y, y], color="#aab0bd", lw=0.8, zorder=1)

    # Hour gridlines.
    for y in HOUR_GRID_LINES:
        ax.plot(
            [x_left, x_right], [y, y],
            color="#e6eaf1", lw=0.5, zorder=1,
        )

    # Row labels (left of the grid).
    for y, label in ROW_LABELS:
        ax.text(
            x_left - 0.05, y, label,
            ha="right", va="center", fontsize=9, color="#444",
        )


def _draw_event(ax, day_idx: int, ev: GridEvent) -> None:
    """Render a single event as a rectangle (or a thin reminder line)."""
    # Map datetimes to y-coordinates (hours since midnight, float).
    y_start = _dt_to_y(ev.start_dt)
    if ev.end_dt is not None and ev.end_dt > ev.start_dt:
        y_end = _dt_to_y(ev.end_dt)
    else:
        # Point-in-time event: tiny vertical extent so it's still visible.
        y_end = y_start + 0.25

    # Clip to visible window.
    y_start_clip = max(Y_TOP, min(Y_BOTTOM, y_start))
    y_end_clip = max(Y_TOP, min(Y_BOTTOM, y_end))
    if y_end_clip <= y_start_clip:
        return  # entirely outside (shouldn't happen given upstream filtering)

    x_center = day_idx
    if ev.is_reminder:
        # Slim vertical line at the event time(s).
        ax.plot(
            [x_center, x_center],
            [y_start_clip, y_end_clip if y_end_clip > y_start_clip + 0.1 else y_start_clip + 0.25],
            color=COLOR_REMINDER, lw=2.0, solid_capstyle="round", zorder=3,
        )
        # Title goes to the right of the line, small.
        ax.text(
            x_center + 0.05, (y_start_clip + y_end_clip) / 2,
            _truncate(ev.title, 22),
            fontsize=7, color="#333", va="center", ha="left", zorder=4,
        )
        return

    # Box rectangle. Importance + tentative are independent styles.
    if ev.importance == "important":
        face = COLOR_IMPORTANT_FILL
        edge = COLOR_IMPORTANT_EDGE
        lw = 1.6
    else:
        face = COLOR_NORMAL_FILL
        edge = COLOR_NORMAL_EDGE
        lw = 0.9
    linestyle = TENTATIVE_LINESTYLE if ev.tentative else "-"

    x_left = x_center - 0.40
    width = 0.80
    height = y_end_clip - y_start_clip
    ax.add_patch(mpatches.Rectangle(
        (x_left, y_start_clip), width, height,
        facecolor=face, edgecolor=edge, linewidth=lw, linestyle=linestyle, zorder=2,
    ))

    # Title text inside (or just below if box is too short).
    label = _truncate(ev.title, 24)
    if ev.also_on:
        label += f"  (+{len(ev.also_on)})"
    if height >= 0.6:
        ax.text(
            x_center, y_start_clip + 0.15, label,
            fontsize=8, ha="center", va="top", color="#222", zorder=4,
        )
    else:
        # Short box — title floats just below.
        ax.text(
            x_center, y_end_clip + 0.05, label,
            fontsize=7, ha="center", va="top", color="#222", zorder=4,
        )


def _dt_to_y(dt: datetime) -> float:
    """Convert a datetime to its y-coordinate (hour of day as float)."""
    return dt.hour + dt.minute / 60.0 + dt.second / 3600.0


def _truncate(s: str, n: int) -> str:
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"
