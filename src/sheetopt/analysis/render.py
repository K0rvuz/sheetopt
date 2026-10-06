from __future__ import annotations

from rich.console import Console
from rich.table import Table

from sheetopt.models import AnalysisReport


def render_report(report: AnalysisReport, console: Console | None = None) -> None:
    console = console or Console()
    console.print(f"[bold]SheetOpt[/bold] — {report.title}")
    console.print(
        f"Sheets: {report.sheet_count} | Formulas: {report.formula_count:,} | "
        f"Patterns: {report.pattern_count:,}"
    )
    table = Table(show_header=True, header_style="bold")
    table.add_column("Severity")
    table.add_column("Rule")
    table.add_column("Finding")
    for finding in report.findings:
        table.add_row(finding.severity.upper(), finding.rule_id, finding.message)
    if report.findings:
        console.print(table)
    else:
        console.print("No findings triggered the current rule thresholds.")
