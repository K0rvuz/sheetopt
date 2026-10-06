# PERF-004 — Duplicate IMPORTRANGE

Detects the same normalized `IMPORTRANGE` structure more than once.

The preferred architecture is usually to import an external source once into a staging sheet and reuse that local result, reducing repeated external fetches.
