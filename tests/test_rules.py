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


def test_full_column_references_do_not_match_text_literals():
    from sheetopt.parser.formula import full_column_references

    formula = '=IF(A1="VENDAS!A:A",SUMIFS(VENDAS!$A:$A,VENDAS!$C:$C,"A:A"),0)'
    assert full_column_references(formula) == ["VENDAS!$A:$A", "VENDAS!$C:$C"]
    assert full_column_references('=QUERY(A1:A50,"select A where A = \'B:B\'")') == []
    assert full_column_references('="Foo!A:A"') == []
    assert full_column_references("=SUM('O''Brien'!C:C)") == ["'O''Brien'!C:C"]
    assert full_column_references("=SUM(WRONGA:AABB)") == []
    assert full_column_references("=SUM(A:A)") == ["A:A"]
