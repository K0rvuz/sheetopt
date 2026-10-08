"""Post-generation evidence gate; an LLM cannot approve its own proposals.

Pure, deterministic, read-only classification. This gate can detect missing
evidence; it CANNOT establish semantic equivalence or performance benefit.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any

from sheetopt.ai.provider import AIAnalysis, AIProposal
from sheetopt.knowledge.rules import retrieve_rules
from sheetopt.parser.structure import inspect_formula_shape


def _norm(text: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFKD", text.lower())
        if not unicodedata.combining(c)
    )


def _evidence_problems(proposal: AIProposal, packet: dict[str, Any]) -> tuple[list[str], list[str]]:
    problems: list[str] = []
    tokens: set[str] = set()
    details = _norm(proposal.title + " " + proposal.rationale)
    focus = packet.get("focus_sheet")
    target_names = set(proposal.target_sheets)
    samples = packet.get("sampled_formula_examples") or []
    local_samples = [
        sample for sample in samples if isinstance(sample, dict)
        and (focus is None or sample.get("sheet") == focus)
    ]
    structs = [
        inspect_formula_shape(str(s.get("formula_shape", "")))
        for s in local_samples
    ]
    allowed_sheets = {
        sheet.get("sheet") for sheet in packet.get("sheets", [])
        if isinstance(sheet, dict)
    }
    allowed_sheets |= {
        edge.get("source_sheet") for edge in packet.get("cross_sheet_edges", [])
        if isinstance(edge, dict)
    }
    allowed_sheets |= {
        edge.get("consumer_sheet") for edge in packet.get("cross_sheet_edges", [])
        if isinstance(edge, dict)
    }
    if not target_names:
        problems.append("A proposta não aponta uma aba verificável.")
    elif target_names - allowed_sheets:
        problems.append("A proposta cita abas não comprovadas pelo contexto selecionado.")

    has_volatile = bool(re.search(
        r"\b(today|now|rand|randbetween|volatil\w*|datas? estaticas?|datas? fixas?)\b",
        details,
    ))
    has_sumifs = "sumifs" in details or "soma.se.s" in details
    has_query = "query" in details
    has_open_ranges = any(
        word in details for word in (
            "intervalo aberto", "intervalos abertos", "coluna inteira",
            "colunas inteiras", "truncar intervalo", "limitar intervalo",
            "intervalo fechado", "intervalos fechados", "$a:$a"
        )
    )

    recognized_signal = has_volatile or has_sumifs or has_query or has_open_ranges
    if not recognized_signal:
        problems.append("Não há sinal técnico local reconhecido para fundamentar a hipótese.")

    if has_volatile:
        tokens.update({"volatile", "TODAY", "NOW"})
        if not any(s.volatile_functions for s in structs):
            problems.append(
                "Amostras da aba não comprovam TODAY/NOW/RAND; contagens globais "
                "não constituem evidência local."
            )
        if any(w in details for w in ("data estatica", "datas fixas", "substituir today")):
            problems.append(
                "Datas estáticas podem alterar a atualização; não são otimização equivalente."
            )
    if has_sumifs or has_query:
        tokens.update({"SUMIFS", "QUERY"})
        if not any(s.aggregate in {"SUMIFS", "COUNTIFS"} for s in structs):
            problems.append("Não há amostra local de agregação para fundamentar a proposta.")
        if has_query:
            problems.append(
                "Conversão para QUERY depende de tipos, critérios, nulos, "
                "datas e comparação na cópia; equivalência não demonstrada."
            )
    if has_open_ranges:
        tokens.update({"full-column", "range"})
        if not any(s.open_ranges for s in structs):
            problems.append(
                "Não há referência a coluna inteira confirmada nas amostras locais."
            )
        problems.append(
            "Limite de intervalo exige política para novas linhas e benchmark na cópia."
        )

    if any(re.search(r"source_ids\s*:\s*\[", step, re.IGNORECASE)
           for step in proposal.validation_steps):
        problems.append("Saída do modelo contém fragmento de JSON em etapa de validação.")

    source_ids = {
        source.get("source_id") for source in packet.get("knowledge_sources", [])
        if isinstance(source, dict)
    }
    if not proposal.source_ids or any(src not in source_ids for src in proposal.source_ids):
        problems.append("Documentação citada ausente ou não verificável no pacote.")

    # Never conflate rule retrieval with a claim that the model has been trained.
    matched_rules = retrieve_rules(tokens, limit=4) if tokens else []
    return problems, [r["id"] for r in matched_rules]


def review_ai_analysis(analysis: AIAnalysis, packet: dict[str, Any]) -> AIAnalysis:
    """Conservative output gate; does not override unverified ideas with approval."""
    for proposal in analysis.proposals:
        problems, rules = _evidence_problems(proposal, packet)
        proposal.evidence_rules = rules[:4]
        proposal.evidence_reasons = problems[:7]
        proposal.evidence_status = (
            "needs_evidence" if problems else "review_only"
        )
        # SUMIFS to QUERY may need extra tests even if some evidence exists.
        if "query" in _norm(proposal.title + " " + proposal.rationale):
            proposal.risk = "high"
    return analysis
