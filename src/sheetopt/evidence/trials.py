"""Append-only private evidence from SheetOpt's own clone-only trials.

This is NOT a benchmark history yet: actual computation latency isn't measured
by the current validator. Preserve negative outcomes and unknown states.
"""
from __future__ import annotations

import hashlib
import json
import time
import uuid
from typing import Any

from sheetopt.secrets_store import _cipher, _connect

_ALLOWED = {
    "validated_cell_only", "rejected", "reverted",
    "manual_review_required", "request_failed_unknown",
}


def record_trial(
    *,
    clone_id: str,
    candidate_id: str,
    rule_id: str,
    result: dict[str, Any],
) -> dict[str, Any]:
    status = str(result.get("status", "request_failed_unknown"))
    if status not in _ALLOWED:
        status = "request_failed_unknown"
    record = {
        "event_id": uuid.uuid4().hex,
        "timestamp": int(time.time()),
        "clone_fingerprint": hashlib.sha256(clone_id.encode()).hexdigest()[:16],
        "candidate_fingerprint": hashlib.sha256(candidate_id.encode()).hexdigest()[:16],
        "rule_id": rule_id[:64],
        "status": status,
        "verification_scope": "target_cell_only" if status == "validated_cell_only"
                              else "not_verified",
        "equivalence_proven": False,
        "performance_measured": False,
        "merge_available": False,
        "baseline_ms": None,
        "optimized_ms": None,
        "speedup_percent": None,
    }
    cipher = _cipher()
    encrypted = cipher.encrypt(json.dumps(record, sort_keys=True).encode("utf-8"))
    with _connect() as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS optimization_trials "
            "(event_id TEXT PRIMARY KEY, timestamp INTEGER NOT NULL, "
            "encrypted BLOB NOT NULL)"
        )
        conn.execute(
            "INSERT INTO optimization_trials(event_id, timestamp, encrypted) "
            "VALUES (?, ?, ?)",
            (record["event_id"], record["timestamp"], encrypted),
        )
    return record


def list_trials(*, limit: int = 50) -> list[dict[str, Any]]:
    if not 1 <= limit <= 100:
        raise ValueError("Invalid evidence page size.")
    cipher = _cipher()
    with _connect() as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS optimization_trials "
            "(event_id TEXT PRIMARY KEY, timestamp INTEGER NOT NULL, "
            "encrypted BLOB NOT NULL)"
        )
        rows = conn.execute(
            "SELECT encrypted FROM optimization_trials "
            "ORDER BY timestamp DESC, event_id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [json.loads(cipher.decrypt(row[0])) for row in rows]


def outcome_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Counts observations; NEVER infer benchmark improvements from them."""
    statuses: dict[str, int] = {}
    for record in records:
        status = str(record.get("status", "request_failed_unknown"))
        statuses[status] = statuses.get(status, 0) + 1
    return {
        "trial_count": len(records),
        "outcomes": statuses,
        "performance_benchmarks": 0,
        "proven_speedups": 0,
        "note": "Trial history contains cell-level checks, not performance measurements.",
    }
