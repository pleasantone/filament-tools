from __future__ import annotations

import html
from pathlib import Path

from filament_tools.model import ComparisonReport
from filament_tools.reporting.terminal import display
from filament_tools.schema import GROUP_LABELS


def write_html(path: Path, report: ComparisonReport, show_source: bool = False) -> None:
    sections = []
    for slug, label in GROUP_LABELS.items():
        rows = [row for row in report.rows if row.group == slug]
        if not rows:
            continue
        body = []
        for row in rows:
            cells = [f"<th>{html.escape(row.key)}</th>"]
            for cell in row.cells:
                source = (
                    f'<small class="source">from {html.escape(cell.source or "")}</small>'
                    if show_source and cell.source
                    else ""
                )
                cells.append(
                    f"<td><code>{html.escape(display(cell.value, cell.present))}</code>{source}</td>"
                )
            body.append("<tr>" + "".join(cells) + "</tr>")
        headings = "".join(f"<th>{html.escape(value)}</th>" for value in report.labels)
        sections.append(
            f"<details open><summary>{html.escape(label)} ({len(rows)})</summary>"
            f"<table><thead><tr><th>Parameter</th>{headings}</tr></thead>"
            f"<tbody>{''.join(body)}</tbody></table></details>"
        )
    document = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Filament profile comparison</title>
<style>body{{font:14px system-ui;margin:2rem;color:#17202a;background:#f7f8fa}}details{{background:white;border:1px solid #ccd3dd;border-radius:8px;margin:1rem 0;overflow:auto}}summary{{font-weight:700;padding:1rem;cursor:pointer}}table{{border-collapse:collapse;width:100%}}th,td{{border-top:1px solid #dde2ea;border-right:1px solid #dde2ea;padding:.6rem;text-align:left;vertical-align:top}}th{{background:#f1f4f8;position:sticky;top:0}}code{{white-space:pre-wrap}}small{{display:block;color:#667085;margin-top:.25rem}}</style></head>
<body><h1>Filament profile comparison</h1><p>{html.escape(report.mode)} · {len(report.rows)} settings</p>{"".join(sections)}</body></html>"""
    try:
        with path.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(document)
    except FileExistsError as exc:
        raise ValueError(f"refusing to overwrite report: {path}") from exc
