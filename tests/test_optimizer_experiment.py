from __future__ import annotations

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from sheetopt import api
from sheetopt.config import settings
from sheetopt.models import FormulaCell, WorkbookSnapshot
from sheetopt.optimizer import validate
from sheetopt.optimizer.let_cache import find_candidates, propose_let_cache
from sheetopt.secrets_store import put_secret

FORMULA = '=SUMIFS(VENDAS!$A:$A,VENDAS!$C:$C,"OK")+SUMIFS(VENDAS!$A:$A,VENDAS!$C:$C,"OK")'


def test_let_candidate_caches_identical_aggregates():
    result = propose_let_cache(FORMULA, "Painel!B2")
    assert result is not None
    assert result.startswith("=LET(sheetoptcache")
    assert result.count("SUMIFS(") == 1
    assert result.count("sheetoptcache") == 3
    cells = [
        FormulaCell(sheet="Painel", row=2, column=2, a1="Painel!B2", formula=FORMULA),
        FormulaCell(sheet="Painel", row=3, column=2, a1="Painel!B3", formula="=SUM(A1:A5)"),
    ]
    candidates = find_candidates(cells)
    assert len(candidates) == 1
    assert candidates[0]["after"] == result
    assert find_candidates(cells, limit=0) == []


def test_let_candidate_rejects_unsafe_and_ambiguous_grammar():
    bad = [
        "=SUM(A1:A5)", "=SUM(A1:A5)+SUM(A1:A6)",
        "=SUM(INDIRECT(\"A:A\"))+SUM(INDIRECT(\"A:A\"))",
        "=SUM(A1+(B1))+SUM(A1+(B1))",
        "=SUM(A1:A5)*SUM(A1:A5)",
        "=SUM(A1:A5)+SUM(A1:A5)+1",
        "=RAND()+RAND()", "=SUM(A1:A5)+SOMME(A1:A5)",
        "=SUM(A1:A5)+SUM(A1:A5) & \"x\"",
    ]
    for item in bad:
        assert propose_let_cache(item) is None, item


def _cell(formula: str, value: float = 7.0) -> dict:
    return {
        "userEnteredValue": {"formulaValue": formula},
        "effectiveValue": {"numberValue": value},
        "formattedValue": "7",
        "userEnteredFormat": {"numberFormat": {"type": "NUMBER", "pattern": "0"}},
        "effectiveFormat": {"numberFormat": {"type": "NUMBER", "pattern": "0"}},
    }


def _candidate():
    rewritten = propose_let_cache(FORMULA, "Painel!B2")
    assert rewritten is not None
    return {
        "rule_id": "OPT-LET-001", "before": FORMULA, "after": rewritten,
        "sheet": "Painel", "a1": "Painel!B2",
    }


def test_clone_only_validation_passes_without_original_write(monkeypatch):
    candidate = _candidate()
    original_id = "O" * 30
    clone_id = "C" * 30
    current = {original_id: _cell(FORMULA), clone_id: _cell(FORMULA)}
    writes: list[tuple[str, str]] = []

    def fake_read(_service, file_id, _sheet, _address):
        return current[file_id]

    def fake_write(_service, file_id, _sheet, _address, formula):
        writes.append((file_id, formula))
        current[file_id] = _cell(formula)

    monkeypatch.setattr(validate, "read_cell", fake_read)
    monkeypatch.setattr(validate, "write_formula", fake_write)
    result = validate.test_candidate_on_clone(
        object(), original_id=original_id, clone_id=clone_id, candidate=candidate
    )
    assert result["status"] == "validated_cell_only"
    assert result["merge_available"] is False
    assert result["performance_measured"] is False
    assert writes == [(clone_id, candidate["after"])]
    assert current[original_id]["userEnteredValue"]["formulaValue"] == FORMULA


def test_clone_only_reverts_when_calculation_differs(monkeypatch):
    candidate = _candidate()
    current = {"o": _cell(FORMULA), "c": _cell(FORMULA)}
    writes: list[str] = []

    def fake_write(_service, file_id, _sheet, _address, formula):
        assert file_id == "c"
        writes.append(formula)
        current[file_id] = _cell(formula, 8.0 if formula == candidate["after"] else 7.0)

    monkeypatch.setattr(validate, "read_cell", lambda _s, f, _sh, _a: current[f])
    monkeypatch.setattr(validate, "write_formula", fake_write)
    monkeypatch.setattr(validate.time, "sleep", lambda _: None)
    result = validate.test_candidate_on_clone(
        object(), original_id="o", clone_id="c", candidate=candidate
    )
    assert result["status"] == "reverted"
    assert writes == [candidate["after"], FORMULA]
    assert current["o"]["effectiveValue"] == current["c"]["effectiveValue"]


def test_clone_rejects_modified_original_or_modified_copy(monkeypatch):
    candidate = _candidate()
    current = {"o": _cell("=SUM(A1)"), "c": _cell(FORMULA)}
    monkeypatch.setattr(validate, "read_cell", lambda _s, f, _sh, _a: current[f])
    monkeypatch.setattr(validate, "write_formula", lambda *_: (_ for _ in ()).throw(AssertionError))
    result = validate.test_candidate_on_clone(
        object(), original_id="o", clone_id="c", candidate=candidate
    )
    assert result["status"] == "rejected"
    current["o"] = _cell(FORMULA)
    current["c"] = _cell(FORMULA, 8.0)
    result = validate.test_candidate_on_clone(
        object(), original_id="o", clone_id="c", candidate=candidate
    )
    assert result["status"] == "rejected"


def test_server_endpoint_requires_managed_clone_and_consumes_once(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    monkeypatch.setattr(settings, "encryption_key", Fernet.generate_key().decode())
    monkeypatch.setattr(settings, "admin_token", "a" * 48)
    client = TestClient(api.app)
    headers = {"Authorization": "Bearer " + "a" * 48}
    cid = "C" * 30
    candidate = _candidate()
    candidate["id"] = "a" * 24
    payload = {"clone_id": cid, "candidate_id": candidate["id"]}
    assert client.post("/v1/optimizations/test", json=payload).status_code == 401
    assert client.post("/v1/optimizations/test", json=payload, headers=headers).status_code == 404
    put_secret("optimizer-plan-" + cid, {
        "clone_id": cid, "original_id": "O" * 30, "candidates": [candidate], "tested": [],
    })
    put_secret("google_auth_mode", {"mode": "oauth"})
    monkeypatch.setattr(api, "oauth_credentials", lambda: object())
    monkeypatch.setattr(api, "persist_oauth_credentials", lambda _c: None)
    monkeypatch.setattr(api, "sheets_service", lambda _c: object())
    observed = []

    def fake_test(_service, *, original_id, clone_id, candidate):
        observed.append((original_id, clone_id, candidate["id"]))
        return {"status": "validated_cell_only", "merge_available": False}

    monkeypatch.setattr(api, "test_candidate_on_clone", fake_test)
    result = client.post("/v1/optimizations/test", json=payload, headers=headers)
    assert result.status_code == 200
    assert observed == [("O" * 30, cid, "a" * 24)]
    assert client.post("/v1/optimizations/test", json=payload, headers=headers).status_code == 409


def test_workflow_exposes_candidates_only_after_clone(monkeypatch):
    from sheetopt import workflow

    snapshot = WorkbookSnapshot(
        spreadsheet_id="O" * 30, title="Report", sheets=["Painel"],
        formulas=[
            FormulaCell(sheet="Painel", row=2, column=2, a1="Painel!B2", formula=FORMULA)
        ],
    )
    monkeypatch.setattr(workflow, "credentials_from_info", lambda _: object())
    monkeypatch.setattr(workflow, "sheets_service", lambda _: object())
    monkeypatch.setattr(workflow, "read_workbook", lambda *args, **kwargs: snapshot)
    monkeypatch.setattr(workflow, "drive_service", lambda _: object())
    monkeypatch.setattr(workflow, "clone_spreadsheet", lambda *_: {
        "id": "C" * 30, "url": "https://docs.google.com/spreadsheets/d/" + "C" * 30 + "/edit",
    })
    result = workflow.inspect_and_clone("O" * 30, None, credentials=object())
    assert result["status"] == "cloned_not_optimized"
    assert len(result["optimization_candidates"]) == 1
    assert result["merge_available"] is False
    no_copy = workflow.inspect_and_clone("O" * 30, None, credentials=object(), make_clone=False)
    assert no_copy["optimization_candidates"] == []
