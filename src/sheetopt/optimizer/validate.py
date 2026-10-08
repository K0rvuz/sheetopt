"""Clone-only experimental formula validation.

Current scope: original target cell vs clone target cell. A successful result
DOES NOT certify dependent cells, future inputs, recalc time, or whole workbooks.
"""
from __future__ import annotations

import time
from typing import Any

from googleapiclient.discovery import Resource

from sheetopt.google.cell import comparable, read_cell, write_formula
from sheetopt.optimizer.let_cache import propose_let_cache


def test_candidate_on_clone(
    service: Resource,
    *,
    original_id: str,
    clone_id: str,
    candidate: dict[str, str],
) -> dict[str, Any]:
    if original_id == clone_id:
        raise ValueError("Original and clone must be different.")
    sheet = candidate["sheet"]
    address = candidate["a1"]
    original_formula = candidate["before"]
    rewritten = candidate["after"]
    if propose_let_cache(original_formula, address) != rewritten:
        raise ValueError("Candidate is no longer eligible for this rule.")

    source = read_cell(service, original_id, sheet, address)
    dest = read_cell(service, clone_id, sheet, address)
    if source.get("userEnteredValue", {}).get("formulaValue") != original_formula:
        return {"status": "rejected", "reason": "A fórmula original mudou.", "cell": address}
    if dest.get("userEnteredValue", {}).get("formulaValue") != original_formula:
        return {"status": "rejected", "reason": "A cópia foi modificada.", "cell": address}
    if comparable(source) != comparable(dest):
        return {
            "status": "rejected", "reason": "Valores ou formatação inicial diferem.",
            "cell": address,
        }
    baseline = comparable(source)
    # This is a one-cell-only experiment; never write to the original ID.
    write_formula(service, clone_id, sheet, address, rewritten)
    try:
        updated = {}
        for attempt in range(3):
            updated = read_cell(service, clone_id, sheet, address)
            if (
                updated.get("userEnteredValue", {}).get("formulaValue") == rewritten
                and comparable(updated) == baseline
            ):
                return {
                    "status": "validated_cell_only", "cell": address,
                    "rule_id": candidate["rule_id"],
                    "message": (
                        "A célula da cópia preservou valor, tipo e formatação. "
                        "Dependências e performance ainda não foram validadas."
                    ),
                    "merge_available": False,
                    "performance_measured": False,
                }
            if attempt < 2:
                time.sleep(1)
        reason = (
            "Resultado ou formatação divergente"
            if updated.get("userEnteredValue", {}).get("formulaValue") == rewritten
            else "Não foi possível confirmar a fórmula aplicada"
        )
    except (TimeoutError, OSError, ValueError, KeyError):
        reason = "Falha ao verificar resultado"
    # Failed verification: best-effort restore the original formula on clone.
    try:
        write_formula(service, clone_id, sheet, address, original_formula)
        restored = read_cell(service, clone_id, sheet, address)
        if restored.get("userEnteredValue", {}).get("formulaValue") != original_formula:
            raise RuntimeError("Rollback could not be confirmed.")
    except Exception as exc:  # noqa: BLE001 - critical rollback failure must be surfaced safely
        return {
            "status": "manual_review_required",
            "cell": address,
            "reason": f"{reason}; a reversão não pôde ser confirmada.",
            "merge_available": False,
            "error_type": type(exc).__name__,
        }
    return {
        "status": "reverted",
        "cell": address,
        "reason": f"{reason}; fórmula anterior restaurada na cópia.",
        "merge_available": False,
    }
