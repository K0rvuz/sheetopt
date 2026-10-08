from __future__ import annotations

import json

import pytest

from sheetopt.ai.evidence_gate import review_ai_analysis
from sheetopt.ai.provider import AIAnalysis
from sheetopt.knowledge.rules import knowledge_rules, retrieve_rules
from sheetopt.parser.structure import inspect_formula_shape, split_top_level_arguments
from sheetopt.training.dataset import prepare_dataset
from sheetopt.training.train_lora import validate_training_inputs


def test_structural_parser_respects_strings_nesting_and_quoted_separators():
    parts = split_top_level_arguments('A:A;B:B;"sent;ok";C:C;IF(D1>0;E1;0)')
    assert parts == ["A:A", "B:B", '"sent;ok"', "C:C", "IF(D1>0;E1;0)"]
    assert split_top_level_arguments('A:A;B:B;"unfinished') is None
    assert split_top_level_arguments('A:A;B:B,(C1)') is None
    assert split_top_level_arguments('A:A;IF(B1>0;1;0') is None
    assert split_top_level_arguments('A:A;"ab""cd";C1') == [
        "A:A", '"ab""cd"', "C1",
    ]


def test_parser_extracts_real_functions_without_quoted_false_positives():
    shape = inspect_formula_shape(
        '=SUMIFS(REF_SHEET!$E:$E;REF_SHEET!$A:$A;AG3;'
        'REF_SHEET!$F:$F;"NOW();QUERY();VIP,VIP")'
    )
    assert shape.aggregate == "SUMIFS"
    assert shape.aggregate_argument_count == 5
    assert shape.aggregate_arity_valid is True
    assert "NOW" not in shape.functions
    assert "QUERY" not in shape.functions
    assert len(shape.open_ranges) == 3
    assert not shape.volatile_functions

    count = inspect_formula_shape('=COUNTIFS(A:A;"ok";B:B;IF(C3>0;1;0))')
    assert count.aggregate == "COUNTIFS"
    assert count.aggregate_argument_count == 4
    assert count.parsed_completely is True
    assert "IF" in count.functions
    assert inspect_formula_shape('=SUMIFS(A:A;B:B)').aggregate_arity_valid is False
    assert inspect_formula_shape('=NOW()').volatile_functions == ("NOW",)


def _packet(*, sample: bool) -> dict:
    return {
        "focus_sheet": "sheet_01",
        "sheets": [{"sheet": "sheet_01", "dynamic_formula_count": 1}],
        "cross_sheet_edges": [],
        "knowledge_sources": [
            {"source_id": "SHEETS-PERF-002"},
            {"source_id": "SHEETS-FUNC-SUMIFS"},
            {"source_id": "SHEETS-FUNC-QUERY"},
        ],
        "functions": {"NOW": 5000, "SUMIFS": 100000},
        "functions_scope": "whole_workbook_only_not_selected_sheet",
        "sampled_formula_examples": (
            [{
                "sheet": "sheet_01",
                "cell": "AL3",
                "formula_shape": '=SUMIFS(REF_SHEET!$E:$E;REF_SHEET!$A:$A;AG3;"<TEXT>")',
            }]
            if sample else []
        ),
    }


def _model(title: str, rationale: str, *, risk: str = "low",
           refs: list[str] | None = None) -> AIAnalysis:
    return AIAnalysis.model_validate({
        "summary": "Recomendações para investigação conservadora.",
        "proposals": [{
            "title": title,
            "rationale": rationale,
            "risk": risk,
            "impact": "unknown",
            "target_sheets": ["sheet_01"],
            "source_ids": refs or ["SHEETS-PERF-002"],
            "validation_steps": ["Comparar somente na cópia."],
        }],
        "missing_context": [],
    })


def test_global_now_count_never_supports_local_today_now_claim():
    analysis = _model(
        "Substituir TODAY/NOW por datas estáticas",
        "Voláteis distribuídas na aba; trocar por datas fixas.",
    )
    review_ai_analysis(analysis, _packet(sample=True))
    p = analysis.proposals[0]
    assert p.evidence_status == "needs_evidence"
    assert any("contagens globais" in x for x in p.evidence_reasons)
    assert any("Datas estáticas" in x for x in p.evidence_reasons)
    assert p.evidence_rules


def test_sumifs_to_query_always_requires_validation_and_high_risk():
    analysis = _model(
        "Migrar SUMIFS para QUERY",
        "Trocar a função SUMIFS por QUERY para agregação compartilhada.",
        risk="low",
    )
    review_ai_analysis(analysis, _packet(sample=True))
    p = analysis.proposals[0]
    assert p.risk == "high"
    assert p.evidence_status == "needs_evidence"
    assert any("equivalência não demonstrada" in r for r in p.evidence_reasons)
    assert "GS-QUERY-COLUMN-TYPES" in p.evidence_rules or p.evidence_rules


def test_uncited_or_unknown_local_claim_fails_closed():
    analysis = _model(
        "Criar cache automático",
        "Uma alteração arbitrária melhora todo o processo.",
        refs=["SHEETS-FUNC-QUERY"],
    )
    review_ai_analysis(analysis, _packet(sample=False))
    assert analysis.proposals[0].evidence_status == "needs_evidence"
    assert any("sinal técnico local" in x for x in analysis.proposals[0].evidence_reasons)


def test_official_rules_have_unique_sources_and_are_retrievable():
    rules = knowledge_rules()
    assert len(rules) >= 10
    assert len({r["id"] for r in rules}) == len(rules)
    matched = retrieve_rules({"QUERY", "SUMIFS", "types"}, limit=5)
    assert matched
    assert any(r["source_id"] == "SHEETS-FUNC-QUERY" for r in matched)
    assert all(r["url"].startswith("https://") and r["requires"] for r in rules)


def test_prepared_dataset_is_source_attributed_and_training_refuses_tiny_seed(tmp_path):
    manifest = prepare_dataset(tmp_path)
    assert manifest["training_executed"] is False
    assert manifest["weights_modified"] is False
    train = [json.loads(s) for s in (tmp_path / "train.jsonl").read_text().splitlines()]
    heldout = [json.loads(s) for s in (tmp_path / "eval.jsonl").read_text().splitlines()]
    assert len(train) + len(heldout) == len(knowledge_rules())
    assert {r["rule_id"] for r in train}.isdisjoint(
        {r["rule_id"] for r in heldout}
    )
    assert all(row["source_id"] and row["source_url"] for row in train + heldout)
    assert not any("Private Finance Ledger" in row["text"] for row in train + heldout)
    with pytest.raises(ValueError, match="insufficient"):
        validate_training_inputs(tmp_path)
