# PERF-001 — Repeated formula pattern

Detects one normalized formula structure repeated many times.

This is a **smell**, not an automatic proof that the formula is wrong. Repetition can indicate an opportunity for `ARRAYFORMULA`, a helper table, or a set-based calculation.

v0.1 only reports the pattern. It does not rewrite it.
