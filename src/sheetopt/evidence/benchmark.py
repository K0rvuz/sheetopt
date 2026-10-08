"""Pure benchmark gate for *future* measured compute-time evidence.

Do not feed untrusted manually submitted timings into the official trial log.
Actual Sheets recalculation timing is not instrumented in this milestone.
"""
from __future__ import annotations

from statistics import median


def assess_repeated_measurements(
    baseline_ms: list[float], optimized_ms: list[float], *, equivalent: bool
) -> dict[str, float | str | bool | None]:
    if len(baseline_ms) < 5 or len(optimized_ms) < 5:
        raise ValueError("At least five independent runs per version are required.")
    for seq in (baseline_ms, optimized_ms):
        if len(seq) > 40 or any(not 0 < val < 1_000_000 for val in seq):
            raise ValueError("Invalid benchmark timings.")
    before = median(baseline_ms)
    after = median(optimized_ms)
    delta = round(100 * (before - after) / before, 2)
    return {
        "median_baseline_ms": round(before, 3),
        "median_optimized_ms": round(after, 3),
        "observed_delta_percent": delta,
        "equivalent": equivalent,
        "verdict": "candidate_improvement" if equivalent and delta > 5 else "not_proven",
        "performance_measured": True,
        "full_workbook_verified": False,
        "merge_available": False,
    }
