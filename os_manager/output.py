"""Terminal formatting: colours, aligned tables, JSON dumps."""

import json

RED = "\033[91m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
BLUE = "\033[94m"
MAGENTA = "\033[95m"
BOLD = "\033[1m"
RESET = "\033[0m"

# Execution states worth colouring wherever they appear in a table.
STATUS_COLORS = {
    "failed": RED, "retrying": RED, "URGENT": RED,
    "running": YELLOW, "in_progress": YELLOW, "starting": YELLOW,
    "condition_not_met": YELLOW, "HIGH": YELLOW,
    "completed": GREEN, "success": GREEN, "ok": GREEN,
    "LOW": BLUE,
}


def paint(text, color):
    return f"{color}{text}{RESET}" if color else text


def show_json(data):
    print(json.dumps(data, indent=2))


def table(rows, columns, row_color=None, total=None):
    """Print rows as an aligned table.

    columns  - (header, key) pairs, in display order.
    row_color- optional row -> colour; colours the whole row.
    total    - noun for the trailing count line, omitted when None.
    """
    if not rows:
        return
    headers = [header for header, _ in columns]
    widths = [len(header) for header in headers]
    cells = []
    for row in rows:
        values = [_cell(row.get(key)) for _, key in columns]
        widths = [max(w, len(v)) for w, v in zip(widths, values)]
        cells.append(values)

    print("  ".join(h.ljust(w) for h, w in zip(headers, widths)))
    print("-" * (sum(widths) + 2 * (len(widths) - 1)))
    for row, values in zip(rows, cells):
        line = "  ".join(v.ljust(w) for v, w in zip(values, widths))
        print(paint(line, row_color(row) if row_color else None))

    if total:
        print(f"\nTotal: {len(rows)} {total}")


def _cell(value):
    return "-" if value is None or value == "" else str(value)


def format_bytes(value):
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024:
            return f"{value:.1f}{unit}"
        value /= 1024
    return f"{value:.1f}PB"


def format_duration(millis):
    """Compact duration: 750ms, 4.2s, 3m20s, 5h12m, 2d6h."""
    if millis is None:
        return "-"
    if millis < 1000:
        return f"{int(millis)}ms"
    seconds = millis / 1000
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes, seconds = divmod(int(seconds), 60)
    if minutes < 60:
        return f"{minutes}m{seconds}s"
    hours, minutes = divmod(minutes, 60)
    if hours < 24:
        return f"{hours}h{minutes}m"
    days, hours = divmod(hours, 24)
    return f"{days}d{hours}h"
