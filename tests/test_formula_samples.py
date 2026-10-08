from __future__ import annotations

import json

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from sheetopt import api
from sheetopt.ai.packet import build_ai_packet
from sheetopt.config import settings
from sheetopt.context.formula_samples import (
    candidate_cells,
    read_formula_examples,
    sanitise_formula,
)
from sheetopt.models import AnalysisReport, Finding


def _report() -> AnalysisReport:
    return AnalysisReport(
        spreadsheet_id="A" * 30,
        title="Synthetic private workbook",
        sheet_count=2, formula_count=3000, pattern_count=3,
        function_counts={"SUMIFS": 2500, "NOW": 250},
        findings=[
            Finding(
                rule_id="PERF-002", title="Repeated SUMIFS", severity="high",
                message="Synthetic private formula details",
                locations=["Sales Dashboard!C3", "Sales Dashboard!C4", "Other!A1"],
            ),
            Finding(
                rule_id="PERF-003", title="Whole columns", severity="high",
                message="Repeated full columns",
                locations=["Sales Dashboard!D9", "Sales Dashboard!C3", "Sales Dashboard!X99999999"],
            ),
        ],
    )


def _context() -> dict:
    return {
        "coverage": "formula_snapshot",
        "sheets": [
            {"name": "Sales Dashboard", "formula_count": 100,
             "dynamic_formula_count": 0, "possible_headers": []},
            {"name": "Other", "formula_count": 2900, "dynamic_formula_count": 250,
             "possible_headers": []},
        ],
        "edges": [], "hotspots": [], "schema_version": 1,
        "sheet_count": 2, "formula_count": 3000, "limitations": [],
    }


def _client(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    monkeypatch.setattr(settings, "encryption_key", Fernet.generate_key().decode())
    monkeypatch.setattr(settings, "admin_token", "a" * 48)
    client = TestClient(api.app)
    return client, {"Authorization": "Bearer " + "a" * 48}


def test_candidate_locations_are_limited_and_belong_to_selected_sheet():
    assert candidate_cells(_report(), "Sales Dashboard") == ["C3", "C4", "D9"]
    assert candidate_cells(_report(), "Other") == ["A1"]
    assert candidate_cells(_report(), "Unknown") == []
    with pytest.raises(ValueError):
        candidate_cells(_report(), "Other", limit=9)


def test_sanitised_formula_does_not_leak_literals_or_sheet_names():
    formula = (
        '=IFERROR(SUMIFS(\'Customer Private\'!$E:$E;'
        '\'Customer Private\'!$A:$A;"client@example.com";'
        '\'Customer Private\'!$C:$C;158239);MySecretNamedRange)'
    )
    shape = sanitise_formula(formula)
    for secret in ("Customer Private", "client@example.com", "158239", "MySecretNamedRange"):
        assert secret not in shape
    assert "SUMIFS" in shape
    assert "REF_SHEET!" in shape
    assert "$E:$E" in shape
    assert "<NUMBER>" in shape
    assert "<TEXT>" in shape
    assert "IDENTIFIER" in shape
    assert sanitise_formula(shape) == shape


def test_formula_read_only_sends_only_three_specific_cells_and_redacts():
    called = []

    class FakeService:
        def spreadsheets(self):
            return self

        def values(self):
            return self

        def batchGet(self, **kwargs):
            called.append(kwargs)
            return self

        def execute(self):
            return {"valueRanges": [
                {"values": [['=SUMIFS(\'Customer Private\'!E:E;A:A;"secret")']]},
                {"values": [["=NOW()"]]},
                {"values": [["plain cell value, not a formula"]]},
            ]}

    result = read_formula_examples(FakeService(), _report(), "Sales Dashboard")
    assert result["writes_performed"] is False
    assert called[0]["valueRenderOption"] == "FORMULA"
    assert called[0]["ranges"] == [
        "'Sales Dashboard'!C3", "'Sales Dashboard'!C4", "'Sales Dashboard'!D9"
    ]
    assert len(result["examples"]) == 2
    assert "secret" not in json.dumps(result)
    assert "Customer Private" not in json.dumps(result)
    assert result["examples"][0]["a1"] == "C3"
    assert "SUMIFS" in result["examples"][0]["formula_template"]


def test_packet_keeps_global_counts_separate_and_optin_samples_sanitised():
    report, context = _report(), _context()
    base = build_ai_packet(report, context=context, focus_sheet="Sales Dashboard")
    assert base["sampled_formula_examples"] == []
    assert base["functions_scope"] == "whole_workbook_only_not_selected_sheet"
    raw = '=SUMIFS(\'Client Notes\'!A:A;B:B;"private@example.com")'
    enriched = build_ai_packet(report, context=context, focus_sheet="Sales Dashboard",
        formula_samples=[{
            "sheet": "Sales Dashboard", "a1": "C3", "formula_template": raw,
        }]
    )
    assert enriched["sample_count"] == 1
    assert enriched["transmission_policy"]["redacted_formula_shapes_included"] is True
    text = json.dumps(enriched)
    assert "private@example.com" not in text
    assert "Client Notes" not in text
    assert "Sales Dashboard" not in text
    assert "NOW" in text  # global count remains global, never local
    assert enriched["sampled_formula_examples"][0]["sheet"] == enriched["focus_sheet"]
    with pytest.raises(ValueError):
        build_ai_packet(report, context=context, formula_samples=[
            {"sheet": "Sales Dashboard", "a1": "C3", "formula_template": raw}
        ])


def test_sampling_endpoint_requires_separate_consent_and_admin(monkeypatch, tmp_path):
    client, headers = _client(monkeypatch, tmp_path)
    req = {"report": _report().model_dump(), "context": _context(),
           "focus_sheet": "Sales Dashboard"}
    assert client.post("/v1/ai/formula-samples", json=req).status_code == 401
    assert client.post("/v1/ai/formula-samples", json=req, headers=headers).status_code == 403
    req["read_consent"] = True
    assert client.post("/v1/ai/formula-samples", json=req, headers=headers).status_code == 409

    from sheetopt.secrets_store import put_secret

    put_secret("google_auth_mode", {"mode": "oauth"})
    monkeypatch.setattr(api, "oauth_credentials", lambda: object())
    monkeypatch.setattr(api, "persist_oauth_credentials", lambda *_a: None)
    monkeypatch.setattr(api, "sheets_service", lambda *_a: object())
    seen = []

    def fake_read(service, report, sheet):
        seen.append((service, report.spreadsheet_id, sheet))
        return {"examples": [{"a1": "C3", "formula_template": "=SUMIFS(A:A;B:B;\"<TEXT>\")",
                              "functions": ["SUMIFS"]}],
                "candidate_count": 1}

    monkeypatch.setattr(api, "read_formula_examples", fake_read)
    monkeypatch.setattr(api, "infer_suggestions", lambda *_a: pytest.fail(
        "No model call allowed during formula sampling"
    ))
    ok = client.post("/v1/ai/formula-samples", json=req, headers=headers)
    assert ok.status_code == 200
    assert ok.json()["sent_to_ai"] is False
    assert ok.json()["writes_performed"] is False
    assert len(seen) == 1
    assert ok.headers["cache-control"] == "no-store, private"

    req["focus_sheet"] = "Arbitrary Other Sheet"
    assert client.post("/v1/ai/formula-samples", json=req, headers=headers).status_code == 422


def test_sample_added_after_preview_requires_a_new_hash(monkeypatch, tmp_path):
    client, headers = _client(monkeypatch, tmp_path)
    req = {"report": _report().model_dump(), "context": _context(),
           "focus_sheet": "Sales Dashboard"}
    preview = client.post("/v1/ai/preview", json=req, headers=headers)
    assert preview.status_code == 200
    old_hash = preview.json()["preview_hash"]
    req["formula_samples"] = [{
        "sheet": "Sales Dashboard", "a1": "C3",
        "formula_template": '=SUMIFS(A:A;B:B;"<TEXT>")',
    }]
    updated = client.post("/v1/ai/preview", json=req, headers=headers)
    assert updated.status_code == 200
    assert updated.json()["preview_hash"] != old_hash
    req["consent"] = True
    req["preview_hash"] = old_hash
    assert client.post("/v1/ai/suggest", json=req, headers=headers).status_code == 409

def test_compact_packet_prioritizes_real_examples_over_repeated_summaries():
    import json

    from sheetopt.ai.packet import LOCAL_FRIENDLY_PACKET_CHARS, build_ai_packet

    report = _report()
    context = _context()
    context["edges"] = [
        {"from_sheet": "Sales Dashboard", "depends_on_sheet": "Other",
         "formula_cells": 100 + i}
        for i in range(32)
    ]
    context["hotspots"] = [
        {"reference": "Other!A:A", "estimated_occurrences": 12000 + i}
        for i in range(30)
    ]
    samples = []
    shape = "=SUMIFS(A:A;B:B;\"<TEXT>\")" * 15
    for i in range(6):
        samples.append({
            "sheet": "Sales Dashboard", "a1": f"C{i + 3}",
            "formula_template": shape,
        })
    packet = build_ai_packet(
        report, context=context, focus_sheet="Sales Dashboard",
        formula_samples=samples,
        opportunities=[{
            "source_sheet": "Other",
            "measure_column": "A", "group_columns": ["B", "C", "D"],
            "estimated_pattern_occurrences": 12500,
        }] * 8,
    )
    encoded = json.dumps(packet, ensure_ascii=False)
    assert len(encoded) <= LOCAL_FRIENDLY_PACKET_CHARS
    assert packet["context_compacted"] is True
    assert packet["sample_count"] >= 1
    assert packet["transmission_policy"]["redacted_formula_shapes_included"] is True
    assert "Sales Dashboard" not in encoded
    assert packet["functions_scope"] == "whole_workbook_only_not_selected_sheet"
    assert any("sanitizada" in item or "redacted" in item for item in packet["limits"])


def test_small_packet_is_not_compacted_unnecessarily():
    from sheetopt.ai.packet import build_ai_packet

    packet = build_ai_packet(_report(), context=_context(),
                             focus_sheet="Sales Dashboard", opportunities=[])
    assert packet["context_compacted"] is False
    assert packet["sample_count"] == 0
