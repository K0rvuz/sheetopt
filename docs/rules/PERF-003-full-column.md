# PERF-003 — Repeated full-column references

Detects ranges such as `A:A` or `Dados!F:F` used repeatedly.

A full-column reference is not inherently wrong. The finding becomes more relevant when the same large range is scanned by many formulas. v0.1 therefore reports weighted occurrences instead of declaring every full-column reference an error.
