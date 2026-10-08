from __future__ import annotations

import json

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from sheetopt import api
from sheetopt.config import settings
from sheetopt.context.engine import (
    build_report_context,
    build_workbook_context,
    select_context_packet,
)
from sheetopt.google.sheets import read_workbook
from sheetopt.models import AnalysisReport, Finding, FormulaCell, WorkbookSnapshot


def _report() -> AnalysisReport:
    return AnalysisReport(
        spreadsheet_id="fake-id", title="Dashboard",
        sheet_count=4, formula_count=6, pattern_count=3,
        function_counts={"SUMIFS": 5, "INDIRECT": 1},
        findings=[
            Finding(
                rule_id="PERF-003", title="Full columns", severity="high",
                message="Several references",
                locations=["Dash!A1", "Dash!A2"],
                evidence={"reference": "Data!A:A", "weighted_occurrences": 42},
            ),
        ],
    )


def _snapshot() -> WorkbookSnapshot:
    formulas = [
        FormulaCell(sheet="Data", row=2, column=1, a1="Data!A2", formula="=SUM(1;2)"),
        FormulaCell(
            sheet="Dash", row=1, column=1, a1="Dash!A1",
            formula="=SUM(Data!A:A)+COUNTIF('Input Data'!$B$2:$B$20;\"x\")",
        ),
        FormulaCell(
            sheet="Dash", row=2, column=1, a1="Dash!A2",
            formula='="Data!Z100"&Data!B2+Data!$C:$C',
        ),
        FormulaCell(
            sheet="Dash", row=3, column=1, a1="Dash!A3",
            formula='=INDIRECT("Data!A1")',
        ),
        FormulaCell(
            sheet="Dash", row=4, column=1, a1="Dash!A4",
            formula="=SUM(Missing!A2)",
        ),
        FormulaCell(
            sheet="Dash", row=5, column=1, a1="Dash!A5",
            formula="=SUM('O''Brien'!B2)",
        ),
    ]
    return WorkbookSnapshot(
        spreadsheet_id="fake-id", title="Dashboard",
        sheets=["Data", "Dash", "Input Data", "O'Brien"],
        sheet_headers={"Data": ["Date", "Product", "Revenue"]},
        formulas=formulas,
    )


def test_full_sheet_graph_and_dynamic_counters():
    context = build_workbook_context(_snapshot(), _report())
    assert context["coverage"] == "formula_snapshot"
    assert context["formula_count"] == 6
    edges = {
        (item["from_sheet"], item["depends_on_sheet"]): item["formula_cells"]
        for item in context["edges"]
    }
    assert edges == {
        ("Dash", "Data"): 2,
        ("Dash", "Input Data"): 1,
        ("Dash", "O'Brien"): 1,
    }
    assert context["dynamic_formula_count"] == 1
    assert context["unknown_references"] == 1
    assert next(item for item in context["sheets"] if item["name"] == "Data") == {
        "name": "Data", "formula_count": 1,
        "possible_headers": ["Date", "Product", "Revenue"],
        "dynamic_formula_count": 0,
    }
    assert context["hotspots"][0]["estimated_occurrences"] == 42
    assert context["ai"]["data_sent"] is False
    assert context["edges_truncated"] is False


def test_context_omits_raw_formulas_and_string_literals():
    snapshot = _snapshot()
    snapshot.formulas[0].formula = '="SENSITIVE_SECRET_997"&SUM(1;2)'
    result = build_workbook_context(snapshot, _report())
    serialized = json.dumps(result)
    assert "SENSITIVE_SECRET_997" not in serialized
    assert "Data!Z100" not in serialized
    assert "Missing!A2" not in serialized
    assert "=" not in serialized


def test_context_limits_edges_and_reports_truncation():
    result = build_workbook_context(_snapshot(), _report(), max_edges=2)
    assert len(result["edges"]) == 2
    assert result["edge_count_total"] == 3
    assert result["edges_truncated"] is True
    assert result["dependency_granularity"] == "explicit_cross_sheet_references_only"


def test_diagnostic_only_context_does_not_fabricate_full_graph():
    context = build_report_context(_report())
    assert context["coverage"] == "diagnostic_only"
    assert context["sheets"][0]["name"] == "Dash"
    assert context["sheets"][0]["formula_count"] is None
    assert context["edges"] == []
    assert context["edge_count_total"] is None
    assert context["dynamic_formula_count"] is None
    assert "JSON antigo" in context["limitations"][-1]


def test_context_packet_scope_and_reject_unknown_sheet():
    context = build_workbook_context(_snapshot(), _report())
    packet = select_context_packet(context, sheet_name="Dash")
    assert packet["ai_request_sent"] is False
    assert packet["sheets"][0]["name"] == "Dash"
    assert all(
        edge["from_sheet"] == "Dash" or edge["depends_on_sheet"] == "Dash"
        for edge in packet["edges"]
    )
    with pytest.raises(ValueError, match="not available"):
        select_context_packet(context, sheet_name="Unknown")
    assert len(select_context_packet(context)["sheets"]) == 4


def test_context_on_workflow_without_cloning(monkeypatch):
    from sheetopt import workflow

    monkeypatch.setattr(workflow, "read_workbook", lambda *_a, **_kw: _snapshot())
    monkeypatch.setattr(workflow, "sheets_service", lambda _credential: object())

    def forbid_drive(*_a, **_kw):
        raise AssertionError("No Drive request is allowed")

    monkeypatch.setattr(workflow, "drive_service", forbid_drive)
    result = workflow.inspect_and_clone("fake-id", None, credentials=object(), make_clone=False)
    assert result["context"]["coverage"] == "formula_snapshot"
    assert len(result["context"]["edges"]) == 3
    assert result["events"][-2]["stage"] == "context"
    assert result["events"][-1]["status"] == "skipped"
    assert result["clone"] is None
    assert result["merge_available"] is False


def test_offline_context_endpoint_requires_auth_and_google_is_not_called(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    monkeypatch.setattr(settings, "encryption_key", Fernet.generate_key().decode())
    monkeypatch.setattr(settings, "admin_token", "a" * 48)
    client = TestClient(api.app)
    payload = {"report": _report().model_dump()}
    assert client.post("/v1/optimizations/plan", json=payload).status_code == 401
    response = client.post(
        "/v1/optimizations/plan", json=payload,
        headers={"Authorization": "Bearer " + "a" * 48},
    )
    assert response.status_code == 200
    assert response.json()["context"]["coverage"] == "diagnostic_only"
    assert response.json()["context"]["edges"] == []


def test_google_reader_samples_only_bounded_possible_headers():
    class FakeSheets:
        def spreadsheets(self):
            return self

        def get(self, **_kwargs):
            self.is_metadata = True
            return self

        def values(self):
            return self

        def batchGet(self, **_kwargs):
            self.is_metadata = False
            return self

        def execute(self):
            if self.is_metadata:
                return {
                    "properties": {"title": "Small"},
                    "sheets": [{"properties": {"title": "Data"}}],
                }
            return {
                "valueRanges": [
                    {"values": [
                        ["Date", "Revenue", "Owner@example.com", "https://secret.example"],
                        ["2026-01-01", "=SUM(A2:A3)"],
                    ]}
                ]
            }

    result = read_workbook("A" * 30, service=FakeSheets())
    assert result.sheet_headers["Data"] == ["Date", "Revenue"]
    assert result.formula_count == 1
    assert result.formulas[0].a1 == "Data!B2"
