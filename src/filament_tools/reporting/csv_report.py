from __future__ import annotations

import csv
from pathlib import Path

from filament_tools.model import ComparisonReport
from filament_tools.reporting.terminal import display


def write_csv(path: Path, report: ComparisonReport, show_source: bool = False) -> None:
    with path.open("x", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        header = ["parameter"]
        for label in report.labels:
            header.append(label)
            if show_source:
                header.append(f"{label} source")
        writer.writerow(header)
        for row in report.rows:
            values = [row.key]
            for cell in row.cells:
                values.append(display(cell.value, cell.present))
                if show_source:
                    values.append(cell.source or "")
            writer.writerow(values)
