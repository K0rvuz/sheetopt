# PERF-002 — Repeated SUMIFS aggregation

Detects a copied `SUMIFS`/`SOMASES` structure repeated across many rows.

Possible optimization strategies include a grouped `QUERY`, a pre-aggregated helper table, and a lookup over the aggregation.

## Not safe to blindly rewrite

Future auto-fix logic must explicitly handle or reject cases involving:

- wildcard criteria;
- date and locale semantics;
- blank/error behavior;
- dynamic references such as `INDIRECT`/`OFFSET`;
- irregular source ranges.

Any rewrite must be applied to a clone and validated against original outputs before merge.
