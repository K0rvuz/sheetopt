from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Literal

import typer

from sheetopt.analysis.analyzer import analyze_snapshot
from sheetopt.analysis.render import render_report
from sheetopt.google.sheets import read_workbook
from sheetopt.io import load_snapshot

app = typer.Typer(no_args_is_help=True, help="Analyze Google Sheets formula structure.")


def _emit(report, output_format: Literal["text", "json"]) -> None:
    if output_format == "json":
        typer.echo(json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2))
    else:
        render_report(report)


@app.command()
def analyze(
    spreadsheet: Annotated[str, typer.Argument(help="Google Sheets URL or spreadsheet ID")],
    format: Annotated[Literal["text", "json"], typer.Option("--format")] = "text",
) -> None:
    """Analyze a Google Sheet without modifying it."""
    snapshot = read_workbook(spreadsheet)
    _emit(analyze_snapshot(snapshot), format)


@app.command("analyze-json")
def analyze_json(
    path: Annotated[Path, typer.Argument(exists=True, dir_okay=False, readable=True)],
    format: Annotated[Literal["text", "json"], typer.Option("--format")] = "text",
) -> None:
    """Analyze an offline workbook snapshot."""
    _emit(analyze_snapshot(load_snapshot(path)), format)


if __name__ == "__main__":
    app()
