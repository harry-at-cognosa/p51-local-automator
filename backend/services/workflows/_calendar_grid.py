"""Matplotlib renderer for the Calendar Digest with Context (type 9) PNG.

Output: a single PNG with two stacked panels.

Top panel — the time grid:
- Columns are days (1..7); two-line header per column (date over weekday)
- Rows are a continuous time axis from 7am to 8pm with labeled rows at
  9 / 11 / 1 / 3 / 5 / 7 plus stub bands above 7am ("before 7") and
  below 8pm ("later") for clipped events
- Each event is a colored block. NO TITLE TEXT inside the block —
  instead, a small numeric badge in the top-left corner refers to the
  legend below.
- Block fill color is assigned per calendar (stable order from the
  workflow's calendars list, so Work is always blue, Family always
  green, etc. across runs).
- Importance: saturated fill + thick border in the calendar color
- Tentative: dashed outline
- Reminder: thin colored vertical mark (no block)

Bottom panel — the legend:
- One row per event in chronological order across the entire window
- Format: number  swatch  date+time  title  tags  calendar
"""
from __future__ import annotations

import re
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

# Per-calendar color palette: (dark_edge, pale_fill, text_on_dark).
# Assigned by calendar's position in the workflow's configured
# calendars list so colors stay stable run to run.
CALENDAR_COLORS: list[tuple[str, str, str]] = [
    ("#1d4ed8", "#dbeafe", "#ffffff"),  # blue
    ("#15803d", "#dcfce7", "#ffffff"),  # green
    ("#c2410c", "#ffedd5", "#ffffff"),  # orange
    ("#7e22ce", "#f3e8ff", "#ffffff"),  # purple
    ("#be123c", "#ffe4e6", "#ffffff"),  # rose
    ("#0e7490", "#cffafe", "#ffffff"),  # cyan
]
DEFAULT_COLOR = ("#525b6a", "#e8edf3", "#ffffff")  # gray fallback

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
    calendars_order: Sequence[str] | None = None,
) -> None:
    """Render the time grid + legend as a single PNG to output_path.

    `days` clamps to [1, 7]. `calendars_order` controls the color-by-calendar
    assignment; pass the workflow's configured calendars list so colors
    stay stable across runs. If None, derives order from first appearance.
    """
    days = max(1, min(7, days))
    sorted_events = sorted(events, key=lambda e: e.start_dt)
    indexed = list(enumerate(sorted_events, start=1))  # [(1, ev), (2, ev), ...]

    cal_order = _resolve_cal_order(calendars_order, sorted_events)
    colors = _assign_calendar_colors(cal_order)

    # Compute figure dimensions. Grid height is fixed; legend height
    # scales with event count so rows aren't squished.
    n_events = len(sorted_events)
    legend_rows = max(1, n_events)
    legend_h = 0.5 + 0.25 * legend_rows + 0.4   # row height + padding for header/footer
    grid_h = 6.5
    fig_w = max(8.0, 1.5 + 1.4 * days)
    fig_h = grid_h + legend_h + 0.5

    fig = plt.figure(figsize=(fig_w, fig_h), dpi=120, constrained_layout=True)
    gs = fig.add_gridspec(
        2, 1,
        height_ratios=[grid_h, legend_h],
    )
    ax_grid = fig.add_subplot(gs[0])
    ax_legend = fig.add_subplot(gs[1])

    _draw_day_columns(ax_grid, start_date, days)
    _draw_time_axis(ax_grid, days)

    # Bucket events by day, then pack each day's overlapping events into
    # side-by-side columns so no two boxes stack on top of each other.
    by_day: dict[int, list[tuple[int, GridEvent]]] = {i: [] for i in range(days)}
    for render_id, ev in indexed:
        day_idx = (ev.start_dt.date() - start_date).days
        if 0 <= day_idx < days:
            by_day[day_idx].append((render_id, ev))

    for day_idx, items in by_day.items():
        packed = _pack_day(items)
        for render_id, ev, col_idx, n_cols in packed:
            _draw_event(ax_grid, day_idx, render_id, ev, colors, col_idx, n_cols)

    ax_grid.set_xlim(-0.5, days - 0.5)
    ax_grid.set_ylim(Y_BOTTOM, Y_TOP)  # inverted: early times at top
    ax_grid.set_xticks([])
    ax_grid.set_yticks([])
    for s in ax_grid.spines.values():
        s.set_visible(False)

    _draw_legend(ax_legend, indexed, colors)

    if attribution_text:
        fig.text(
            0.99, 0.005, attribution_text,
            ha="right", va="bottom",
            fontsize=6, color="#888",
        )

    fig.savefig(output_path, dpi=120, bbox_inches="tight")
    plt.close(fig)


def _resolve_cal_order(
    explicit: Sequence[str] | None,
    sorted_events: Sequence[GridEvent],
) -> list[str]:
    """Use the explicit order if given; else derive from event appearance."""
    if explicit:
        out = [c for c in explicit if c]
    else:
        out = []
    seen = set(out)
    for ev in sorted_events:
        if ev.calendar and ev.calendar not in seen:
            out.append(ev.calendar)
            seen.add(ev.calendar)
    return out


def _assign_calendar_colors(
    calendar_names: Sequence[str],
) -> dict[str, tuple[str, str, str]]:
    """Returns calendar_name -> (edge_color, fill_color, text_on_dark)."""
    out: dict[str, tuple[str, str, str]] = {}
    for i, name in enumerate(calendar_names):
        out[name] = CALENDAR_COLORS[i] if i < len(CALENDAR_COLORS) else DEFAULT_COLOR
    return out


def _calendar_color(
    ev: GridEvent,
    colors: dict[str, tuple[str, str, str]],
) -> tuple[str, str, str]:
    return colors.get(ev.calendar, DEFAULT_COLOR)


def _draw_day_columns(ax, start_date: date, days: int) -> None:
    """Column backgrounds with the date-over-weekday header above each."""
    for i in range(days):
        d = start_date + timedelta(days=i)
        if i % 2 == 0:
            ax.add_patch(mpatches.Rectangle(
                (i - 0.5, Y_TOP), 1.0, Y_BOTTOM - Y_TOP,
                facecolor="#fafbfc", edgecolor="none", zorder=0,
            ))
        ax.plot(
            [i + 0.5, i + 0.5], [Y_TOP, Y_BOTTOM],
            color="#dde2ea", lw=0.6, zorder=1,
        )
        # Date on top (small y), weekday below.
        ax.text(
            i, Y_TOP - 1.1, str(d.day),
            ha="center", va="bottom", fontsize=14, fontweight="bold",
        )
        ax.text(
            i, Y_TOP - 0.15, d.strftime("%a"),
            ha="center", va="bottom", fontsize=10, color="#555",
        )


def _draw_time_axis(ax, days: int) -> None:
    x_left = -0.5
    x_right = days - 0.5
    for y in STUB_LINES:
        ax.plot([x_left, x_right], [y, y], color="#aab0bd", lw=0.8, zorder=1)
    for y in HOUR_GRID_LINES:
        ax.plot(
            [x_left, x_right], [y, y],
            color="#e6eaf1", lw=0.5, zorder=1,
        )
    for y, label in ROW_LABELS:
        ax.text(
            x_left - 0.05, y, label,
            ha="right", va="center", fontsize=9, color="#444",
        )


def _pack_day(
    items: list[tuple[int, GridEvent]],
) -> list[tuple[int, GridEvent, int, int]]:
    """Greedy column packing for events in one day.

    Returns (render_id, event, col_index, n_cols) — col_index is the
    event's horizontal slot in the day column; n_cols is the day-wide
    max-overlap width so all events in the same day get uniform widths.
    Reminders are still packed so their number badges don't collide.
    """
    if not items:
        return []
    sorted_items = sorted(items, key=lambda t: t[1].start_dt)
    columns: list[datetime] = []  # end time per column
    assignments: list[int] = []

    for _render_id, ev in sorted_items:
        end = ev.end_dt if (ev.end_dt and ev.end_dt > ev.start_dt) else ev.start_dt
        placed = -1
        for i, col_end in enumerate(columns):
            if ev.start_dt >= col_end:
                columns[i] = end
                placed = i
                break
        if placed == -1:
            columns.append(end)
            placed = len(columns) - 1
        assignments.append(placed)

    n_cols = max(1, len(columns))
    return [
        (rid, ev, col, n_cols)
        for (rid, ev), col in zip(sorted_items, assignments)
    ]


def _draw_event(
    ax,
    day_idx: int,
    render_id: int,
    ev: GridEvent,
    colors: dict[str, tuple[str, str, str]],
    col_idx: int = 0,
    n_cols: int = 1,
) -> None:
    """Render an event as a colored block (or a slim reminder line)."""
    edge_color, fill_color, _ = _calendar_color(ev, colors)

    y_start = _dt_to_y(ev.start_dt)
    if ev.end_dt is not None and ev.end_dt > ev.start_dt:
        y_end = _dt_to_y(ev.end_dt)
    else:
        y_end = y_start + 0.25

    y_start_clip = max(Y_TOP, min(Y_BOTTOM, y_start))
    y_end_clip = max(Y_TOP, min(Y_BOTTOM, y_end))
    if y_end_clip <= y_start_clip:
        return

    # Day column spans x = day_idx - 0.4 → day_idx + 0.4 (width 0.8).
    # Each event in a packed day gets 1/n_cols of that width.
    full_left = day_idx - 0.40
    full_width = 0.80
    slot_width = full_width / n_cols
    x_left = full_left + col_idx * slot_width
    x_right = x_left + slot_width
    x_center = (x_left + x_right) / 2

    if ev.is_reminder:
        # Slim vertical line at the slot's center, in the calendar color.
        ax.plot(
            [x_center, x_center],
            [y_start_clip, y_end_clip if y_end_clip > y_start_clip + 0.1 else y_start_clip + 0.25],
            color=edge_color, lw=2.5, solid_capstyle="round", zorder=3,
        )
        ax.text(
            x_center + 0.04, y_start_clip + 0.15, _badge_label(render_id, ev),
            fontsize=7, color=edge_color, fontweight="bold",
            va="top", ha="left", zorder=4,
        )
        return

    # Solid box. Importance toggles fill (pale ↔ saturated) + line weight.
    if ev.importance == "important":
        face = edge_color
        edge = edge_color
        lw = 1.8
        text_color = "#ffffff"
    else:
        face = fill_color
        edge = edge_color
        lw = 1.0
        text_color = edge_color
    linestyle = TENTATIVE_LINESTYLE if ev.tentative else "-"

    height = y_end_clip - y_start_clip
    ax.add_patch(mpatches.Rectangle(
        (x_left, y_start_clip), slot_width, height,
        facecolor=face, edgecolor=edge, linewidth=lw, linestyle=linestyle, zorder=2,
    ))

    # Number badge + short prefix in the top-left of the box, sized down a
    # hair when packed.
    badge_fs = 9 if n_cols == 1 else max(7, 9 - (n_cols - 1))
    ax.text(
        x_left + 0.03, y_start_clip + 0.08, _badge_label(render_id, ev),
        fontsize=badge_fs, color=text_color, fontweight="bold",
        va="top", ha="left", zorder=4,
    )


def _draw_legend(
    ax,
    indexed: list[tuple[int, GridEvent]],
    colors: dict[str, tuple[str, str, str]],
) -> None:
    """Render the legend as a clean text table below the grid.

    Layout: # | swatch | When | Event (title + inline tags) | Calendar.
    """
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.set_xticks([])
    ax.set_yticks([])
    for s in ax.spines.values():
        s.set_visible(False)

    if not indexed:
        ax.text(
            0.5, 0.5, "No events in this window.",
            ha="center", va="center", fontsize=10, color="#888",
        )
        return

    # Column x-positions in axes coords (axis is [0,1] wide).
    COL_NUM = 0.005
    COL_SWATCH = 0.025
    COL_WHEN = 0.07
    COL_EVENT = 0.27
    COL_CAL = 0.84

    # Header row
    header_y = 0.96
    for x, label in [
        (COL_NUM, "#"),
        (COL_WHEN, "When"),
        (COL_EVENT, "Event"),
        (COL_CAL, "Calendar"),
    ]:
        ax.text(
            x, header_y, label,
            fontsize=8, color="#888", fontweight="bold", va="top", ha="left",
        )
    # Underline header
    ax.plot(
        [0.005, 0.99], [header_y - 0.04, header_y - 0.04],
        color="#ccc", lw=0.5,
    )

    n = len(indexed)
    top = 0.86
    bottom = 0.04
    available = top - bottom
    row_h = min(0.08, available / n) if n > 0 else available

    for i, (render_id, ev) in enumerate(indexed):
        y = top - i * row_h
        edge_color, fill_color, _ = _calendar_color(ev, colors)

        # # column
        ax.text(
            COL_NUM, y, str(render_id),
            fontsize=9, color="#222", fontweight="bold", va="center", ha="left",
        )

        # Swatch — same styling as the box in the grid (saturated for
        # important, dashed border for tentative).
        swatch_h = row_h * 0.55
        swatch_w = 0.025
        swatch_face = edge_color if ev.importance == "important" else fill_color
        ax.add_patch(mpatches.Rectangle(
            (COL_SWATCH, y - swatch_h / 2), swatch_w, swatch_h,
            facecolor=swatch_face, edgecolor=edge_color, linewidth=0.9,
            linestyle=TENTATIVE_LINESTYLE if ev.tentative else "-",
        ))

        # When
        ax.text(
            COL_WHEN, y, _format_when(ev),
            fontsize=8, color="#222", va="center", ha="left",
        )

        # Event: title + inline tags
        tags: list[str] = []
        if ev.importance == "important":
            tags.append("important")
        if ev.tentative:
            tags.append("tentative")
        if ev.is_reminder:
            tags.append("reminder")
        if ev.also_on:
            tags.append("also on " + ", ".join(ev.also_on))
        title_str = ev.title
        ax.text(
            COL_EVENT, y, title_str,
            fontsize=8, color="#222", va="center", ha="left",
        )
        if tags:
            # Place tags after the title, separated by " · "; use a slightly
            # offset y so they read as secondary info.
            ax.text(
                COL_CAL - 0.005, y, " · ".join(tags),
                fontsize=7, color="#666", va="center", ha="right", style="italic",
            )

        # Calendar column
        ax.text(
            COL_CAL, y, ev.calendar or "(unspecified)",
            fontsize=8, color=edge_color, va="center", ha="left", fontweight="bold",
        )


def _format_when(ev: GridEvent) -> str:
    date_str = ev.start_dt.strftime("%a %b %d")
    start_str = ev.start_dt.strftime("%H:%M")
    if ev.end_dt and ev.end_dt > ev.start_dt:
        end_str = ev.end_dt.strftime("%H:%M")
        return f"{date_str}  {start_str}–{end_str}"
    return f"{date_str}  {start_str}"


_WORD_RE = re.compile(r"[\w']+")
_PREFIX_MAX = 8


def _short_prefix(title: str) -> str:
    """First word of `title` (stops at whitespace or punctuation), max 8 chars.

    Used for the in-box hint after the badge number. Users tune their event
    titles so the first word is the meaningful code (e.g. "Coffee with X" →
    "Coffee", "Clint/Dan/Harry" → "Clint").
    """
    if not title:
        return ""
    m = _WORD_RE.match(title.strip())
    if not m:
        return title.strip()[:_PREFIX_MAX]
    return m.group(0)[:_PREFIX_MAX]


def _badge_label(render_id: int, ev: GridEvent) -> str:
    """'<n> - <prefix>' or just '<n>' if title has no word characters."""
    prefix = _short_prefix(ev.title)
    return f"{render_id} - {prefix}" if prefix else str(render_id)


def _dt_to_y(dt: datetime) -> float:
    return dt.hour + dt.minute / 60.0 + dt.second / 3600.0
