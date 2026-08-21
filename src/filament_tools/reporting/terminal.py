from __future__ import annotations

import json
from io import StringIO
from typing import Any, Sequence

from rich.console import Console
from rich.table import Table

from filament_tools.model import ComparisonReport, OverrideReport, ValidationIssue


def display(value: Any, present: bool | None = None) -> str:
    if present is False:
        return "∅"
    if value is None:
        return "null" if present else "∅"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def comparison_text(report: ComparisonReport, show_source: bool = False) -> str:
    stream = StringIO()
    console = Console(file=stream, force_terminal=False, color_system=None, width=180)
    table = Table(show_lines=False)
    table.add_column("Parameter", style="bold")
    for label in report.labels:
        table.add_column(label)
    for row in report.rows:
        table.add_row(row.key, *[display(cell.value, cell.present) for cell in row.cells])
        if show_source:
            table.add_row("  source", *[cell.source or "" for cell in row.cells], style="dim")
    console.print(table)
    return stream.getvalue().rstrip()


def overrides_text(reports: Sequence[OverrideReport]) -> str:
    stream = StringIO()
    console = Console(file=stream, force_terminal=False, color_system=None, width=180)
    for report in reports:
        console.print(f"[bold]Profile:[/bold] {report.label}")
        console.print(f"[bold]Parent:[/bold] {report.parent_status}")
        table = Table()
        for heading in ("Parameter", "Explicit", "Parent effective", "Difference", "Parent source"):
            table.add_column(heading)
        for row in report.rows:
            table.add_row(
                row.key,
                display(row.explicit_value),
                display(row.parent_value),
                row.difference,
                row.parent_source or "",
            )
        console.print(table)
    return stream.getvalue().rstrip()


def issues_text(issues: Sequence[ValidationIssue]) -> str:
    if not issues:
        return "valid"
    return "\n".join(
        f"{issue.severity.value.upper()} {issue.code}"
        f"{f' [{issue.key}]' if issue.key else ''}: {issue.message}"
        for issue in issues
    )
