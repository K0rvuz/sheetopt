from sheetopt.analysis.analyzer import analyze_snapshot
from sheetopt.models import FormulaCell, WorkbookSnapshot


def test_repeated_sumifs_rule_and_full_column_rule():
    formulas = [
        FormulaCell(
            sheet="Dashboard",
            row=row,
            column=2,
            a1=f"Dashboard!B{row}",
            formula=f"=SUMIFS(Dados!F:F,Dados!A:A,A{row})",
        )
        for row in range(2, 302)
    ]
    snapshot = WorkbookSnapshot(
        spreadsheet_id="test",
        title="test",
        sheets=["Dados", "Dashboard"],
        formulas=formulas,
    )
    report = analyze_snapshot(snapshot)
    ids = {finding.rule_id for finding in report.findings}
    assert "PERF-002" in ids
    assert "PERF-003" in ids
    assert report.pattern_count == 1
