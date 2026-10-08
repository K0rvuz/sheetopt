from __future__ import annotations

import json

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from sheetopt import api
from sheetopt.ai.packet import build_ai_packet
from sheetopt.config import settings
from sheetopt.evidence.benchmark import assess_repeated_measurements
from sheetopt.evidence.trials import list_trials, outcome_summary, record_trial
from sheetopt.knowledge.retrieval import all_documents, knowledge_for_diagnostic, search_knowledge
from sheetopt.models import AnalysisReport, Finding


def _report() -> AnalysisReport:
    return AnalysisReport(
        spreadsheet_id="private-spreadsheet-secret",
        title="Proprietary document",
        sheet_count=3, formula_count=10000, pattern_count=8,
        function_counts={"SUMIFS": 9000, "TODAY": 120},
        findings=[
            Finding(
                rule_id="PERF-003", title="Full columns", severity="high",
                message="Secret formula must stay private",
                locations=["PrivateSheet!A1"],
                evidence={"reference": "PrivateSheet!A:A", "weighted_occurrences": 3400},
            )
        ],
    )


def _context() -> dict:
    return {
        "schema_version": 1, "coverage": "formula_snapshot",
        "formula_count": 10000, "sheet_count": 3,
        "sheets": [
            {"name": "PrivateSheet", "formula_count": 100, "possible_headers": [],
             "dynamic_formula_count": 0},
            {"name": "Summary", "formula_count": 8000, "possible_headers": [],
             "dynamic_formula_count": 120},
            {"name": "Chart", "formula_count": 1900, "possible_headers": [],
             "dynamic_formula_count": 0},
        ],
        "edges": [
            {"from_sheet": "Summary", "depends_on_sheet": "PrivateSheet",
             "formula_cells": 7500},
            {"from_sheet": "Chart", "depends_on_sheet": "Summary",
             "formula_cells": 1200},
        ],
        "hotspots": [
            {"reference": "PrivateSheet!A:A", "estimated_occurrences": 3400}
        ],
        "limitations": ["Partial graph"],
    }


def _client(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    monkeypatch.setattr(settings, "encryption_key", Fernet.generate_key().decode())
    monkeypatch.setattr(settings, "admin_token", "a" * 48)
    client = TestClient(api.app)
    return client, {"Authorization": "Bearer " + "a" * 48}


def test_offline_knowledge_uses_curated_official_references():
    docs = all_documents()
    assert len(docs) >= 8
    assert len({doc["id"] for doc in docs}) == len(docs)
    result = search_knowledge("SUMIFS QUERY agrupamento intervalos")
    assert result
    assert all(
        doc["source_url"].startswith("https://support.google.com/docs/")
        or doc["source_url"].startswith("https://developers.google.com/")
        for doc in result
    )
    assert any(doc["source_id"] == "SHEETS-FUNC-QUERY" for doc in result)
    assert knowledge_for_diagnostic(
        {"SUMIFS": 9000}, {"PERF-003": 3}
    )
    assert search_knowledge("x" * 60) == []
    with pytest.raises(ValueError):
        search_knowledge("hello", limit=30)


def test_diagnostic_packet_contains_sources_and_anonymizes_names():
    report = _report()
    packet = build_ai_packet(report, context=_context())
    assert packet["knowledge_sources"]
    assert packet["investigation"] == "overview"
    assert packet["transmission_policy"]["raw_formulas_included"] is False
    text = json.dumps(packet)
    for forbidden in (
        "private-spreadsheet-secret", "Proprietary document", "PrivateSheet",
        "Secret formula must stay private",
    ):
        assert forbidden not in text


def test_directed_investigation_filters_upstream_and_downstream():
    report = _report()
    context = _context()
    upstream = build_ai_packet(
        report, context=context, focus_sheet="Summary",
        investigation="upstream",
    )
    assert upstream["investigation"] == "upstream"
    assert len(upstream["cross_sheet_edges"]) == 1
    assert upstream["cross_sheet_edges"][0]["formula_cells"] == 7500
    downstream = build_ai_packet(
        report, context=context, focus_sheet="Summary",
        investigation="downstream",
    )
    assert len(downstream["cross_sheet_edges"]) == 1
    assert downstream["cross_sheet_edges"][0]["formula_cells"] == 1200
    hotspots = build_ai_packet(
        report, context=context, investigation="hotspots"
    )
    assert hotspots["cross_sheet_edges"] == []
    with pytest.raises(ValueError, match="Choose a sheet"):
        build_ai_packet(report, context=context, investigation="upstream")


def test_investigation_api_never_contacts_ai_or_google(monkeypatch, tmp_path):
    client, headers = _client(monkeypatch, tmp_path)

    def refuse_network(*_args, **_kwargs):
        raise AssertionError("Offline investigative endpoint called AI")

    monkeypatch.setattr(api, "infer_suggestions", refuse_network)
    payload = {
        "report": _report().model_dump(), "context": _context(),
        "investigation": "downstream", "focus_sheet": "Summary",
    }
    assert client.post("/v1/ai/investigate", json=payload).status_code == 401
    response = client.post("/v1/ai/investigate", json=payload, headers=headers)
    assert response.status_code == 200
    assert response.json()["sent"] is False
    assert response.json()["writes_performed"] is False
    assert response.json()["sources"]
    assert response.json()["packet"]["investigation"] == "downstream"
    assert client.get("/v1/knowledge", headers=headers).json()["sources"]
    assert client.post(
        "/v1/knowledge/search", json={"query": "QUERY SUMIFS"},
        headers=headers,
    ).status_code == 200


def test_evidence_journal_is_encrypted_append_only_and_not_performance(monkeypatch, tmp_path):
    _client(monkeypatch, tmp_path)
    first = record_trial(
        clone_id="private_clone_id", candidate_id="private_candidate_id",
        rule_id="OPT-LET-001",
        result={"status": "validated_cell_only", "reason": "secret private formula"},
    )
    second = record_trial(
        clone_id="private_clone_id", candidate_id="other_private_id",
        rule_id="OPT-LET-001", result={"status": "reverted"},
    )
    assert first["event_id"] != second["event_id"]
    assert first["verification_scope"] == "target_cell_only"
    assert first["performance_measured"] is False
    assert first["baseline_ms"] is None
    records = list_trials(limit=10)
    assert len(records) == 2
    assert not any("private_clone_id" in json.dumps(item) for item in records)
    assert not any("secret private formula" in json.dumps(item) for item in records)
    summary = outcome_summary(records)
    assert summary["proven_speedups"] == 0
    assert summary["outcomes"]["reverted"] == 1
    with pytest.raises(ValueError):
        list_trials(limit=1000)


def test_evidence_history_is_admin_only(monkeypatch, tmp_path):
    client, headers = _client(monkeypatch, tmp_path)
    record_trial(
        clone_id="clone", candidate_id="candidate", rule_id="OPT-LET-001",
        result={"status": "request_failed_unknown"},
    )
    assert client.get("/v1/evidence/trials").status_code == 401
    response = client.get("/v1/evidence/trials", headers=headers)
    assert response.status_code == 200
    assert response.json()["summary"]["trial_count"] == 1
    assert response.json()["records"][0]["status"] == "request_failed_unknown"


def test_benchmark_gate_does_not_invent_full_workbook_equivalence():
    good = assess_repeated_measurements(
        [100.0, 101.0, 99.0, 100.0, 100.0],
        [80.0, 79.0, 81.0, 80.0, 80.0],
        equivalent=True,
    )
    assert good["observed_delta_percent"] == 20.0
    assert good["verdict"] == "candidate_improvement"
    assert good["full_workbook_verified"] is False
    assert good["merge_available"] is False
    bad = assess_repeated_measurements(
        [100.0] * 5, [80.0] * 5, equivalent=False,
    )
    assert bad["verdict"] == "not_proven"
    with pytest.raises(ValueError):
        assess_repeated_measurements([100.0], [80.0], equivalent=True)


def test_validator_calls_local_evidence_registry_for_actual_clone_trial(monkeypatch, tmp_path):
    client, headers = _client(monkeypatch, tmp_path)
    cid = "C" * 30
    candidate = {"id": "a" * 24, "rule_id": "OPT-LET-001"}
    from sheetopt.secrets_store import put_secret

    put_secret("optimizer-plan-" + cid, {
        "clone_id": cid, "original_id": "O" * 30,
        "candidates": [candidate], "tested": [],
    })
    put_secret("google_auth_mode", {"mode": "oauth"})
    monkeypatch.setattr(api, "oauth_credentials", lambda: object())
    monkeypatch.setattr(api, "persist_oauth_credentials", lambda *_a: None)
    monkeypatch.setattr(api, "sheets_service", lambda *_a: object())
    monkeypatch.setattr(api, "test_candidate_on_clone", lambda *_a, **_kw: {
        "status": "validated_cell_only", "merge_available": False,
    })
    response = client.post(
        "/v1/optimizations/test",
        json={"clone_id": cid, "candidate_id": candidate["id"]},
        headers=headers,
    )
    assert response.status_code == 200
    assert list_trials(limit=10)[0]["rule_id"] == "OPT-LET-001"
    assert list_trials(limit=10)[0]["performance_measured"] is False
