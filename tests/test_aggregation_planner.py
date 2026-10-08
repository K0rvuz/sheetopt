from __future__ import annotations

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from sheetopt import api
from sheetopt.config import settings
from sheetopt.models import AnalysisReport, Finding, FormulaCell
from sheetopt.optimizer.aggregation_planner import _extract_groups, plan_aggregations
from sheetopt.optimizer.let_cache import propose_let_cache


def report_with_patterns(*items: tuple[str, int]) -> AnalysisReport:
    return AnalysisReport(
        spreadsheet_id="test-file-id", title="Synthetic workbook",
        sheet_count=2, formula_count=3000, pattern_count=len(items),
        function_counts={"SUMIFS": 3000},
        findings=[
            Finding(
                rule_id="PERF-002", title="Repeated SUMIFS aggregation",
                severity="medium", message="Synthetic repeated aggregation",
                locations=[f"Overview!B{index + 2}"],
                evidence={"occurrences": count, "normalized_formula": formula},
            )
            for index, (formula, count) in enumerate(items)
        ],
    )


def test_semicolon_query_planning_groups_shared_dimensions():
    first = '=SUMIFS(Data!$E:$E;Data!$A:$A;B{ROW};Data!$C:$C;"Search")'
    second = '=SUMIFS(Data!$E:$E;Data!$A:$A;B{ROW};Data!$C:$C;"Pmax")'
    third = '=SUMIFS(Data!$D:$D;Data!$A:$A;B{ROW};Data!$C:$C;"Search")'
    planned = plan_aggregations(report_with_patterns(
        (first, 1800), (second, 2500), (third, 1200)
    ))
    assert len(planned) == 2
    top = planned[0]
    assert top["source_sheet"] == "Data"
    assert top["measure_column"] == "E"
    assert top["group_columns"] == ["A", "C"]
    assert top["delimiter"] == ";"
    assert top["estimated_pattern_occurrences"] == 4300
    assert top["pattern_count"] == 2
    assert top["query_shape"] == "SELECT A, C, SUM(E) GROUP BY A, C"
    assert top["status"] == "review_only"
    assert top["requires_validation"]
    assert "Data!" not in top["query_shape"]
    assert planned[1]["measure_column"] == "D"


def test_quoted_sheet_and_formula_wrappers():
    formula = (
        "=IFERROR(SUMIFS('Finance Data'!$H:$H;"
        "'Finance Data'!$A:$A;C{ROW};"
        "'Finance Data'!$F:$F;\"Paid\");0)"
    )
    groups = _extract_groups(formula)
    assert groups == {("Finance Data", "H", ("A", "F"), ";")}


def test_mask_literals_and_mixed_separators():
    formula = (
        '=IF("SUMIFS(Fake!A:A;Fake!B:B;1)"="text";'
        'SUMIFS(Data!C:C;Data!A:A;"OK");0)'
    )
    groups = _extract_groups(formula)
    assert groups == {("Data", "C", ("A",), ";")}
    assert _extract_groups('=SUMIFS(Data!E:E;Data!A:A,"X")') == set()
    assert _extract_groups('=SUMIFS(Data!E:E;Other!A:A;"X")') == set()
    assert _extract_groups('=SUMIFS(Data!E:E;Data!E:E;"X")') == set()


def test_multiple_calls_same_family_not_double_counted():
    formula = (
        '=SUMIFS(Data!E:E;Data!A:A;"A")+'
        'SUMIFS(Data!E:E;Data!A:A;"B")'
    )
    plan = plan_aggregations(report_with_patterns((formula, 1000)))
    assert len(plan) == 1
    assert plan[0]["pattern_count"] == 1
    assert plan[0]["estimated_pattern_occurrences"] == 1000


def test_no_findings_returns_no_plans():
    report = report_with_patterns()
    assert plan_aggregations(report) == []
    assert plan_aggregations(report_with_patterns(
        ('=SUM(A1:A3)', 1200)
    ), limit=0) == []


def test_api_plan_from_json_is_authenticated_and_read_only(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    monkeypatch.setattr(settings, "encryption_key", Fernet.generate_key().decode())
    monkeypatch.setattr(settings, "admin_token", "a" * 48)
    client = TestClient(api.app)
    headers = {"Authorization": "Bearer " + "a" * 48}
    report = report_with_patterns(
        ('=SUMIFS(Data!E:E;Data!A:A;"Search")', 1500)
    )
    payload = {"report": report.model_dump()}
    assert client.post("/v1/optimizations/plan", json=payload).status_code == 401
    response = client.post("/v1/optimizations/plan", json=payload, headers=headers)
    assert response.status_code == 200
    assert response.json()["aggregation_opportunities"][0]["source_sheet"] == "Data"


def test_semicolon_let_rewrite_with_identical_aggregates():
    formula = (
        '=SUMIFS(Data!E:E;Data!A:A;"Search")+'
        'SUMIFS(Data!E:E;Data!A:A;"Search")'
    )
    rewritten = propose_let_cache(formula, "Overview!B2")
    assert rewritten is not None
    assert rewritten.startswith("=LET(sheetoptcache")
    assert rewritten.count("SUMIFS(") == 1
    assert rewritten.count(";") == 4  # 2 in cached SUMIFS, 2 in LET
    assert ";sheetoptcache" in rewritten
    bad = '=SUMIFS(Data!E:E;Data!A:A;"Search")+SUMIFS(Data!E:E,Data!A:A,"Search")'
    assert propose_let_cache(bad) is None


def test_planner_does_not_use_raw_cells_or_edit_files():
    formula = (
        '=SUMIFS(Data!$F:$F;Data!$A:$A;B{ROW};Data!$D:$D;"active")'
    )
    report = report_with_patterns((formula, 300))
    planned = plan_aggregations(report)
    assert len(planned) == 1
    assert "before" not in planned[0]
    assert "after" not in planned[0]
    assert "rewrite" not in planned[0]
    assert planned[0]["status"] == "review_only"
    # An ordinary FormulaCell is intentionally not modified by the planner.
    cell = FormulaCell(sheet="Overview", row=2, column=2, a1="Overview!B2", formula=formula)
    assert cell.formula == formula
