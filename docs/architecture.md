# Architecture — v0.1

SheetOpt v0.1 is deliberately read-only and deterministic.

```text
Google Sheets / snapshot JSON
          |
          v
       Reader
          |
          v
 Formula normalizer
          |
          v
   Pattern grouping
          |
          v
     Rule registry
          |
          v
        Report
```

## Trust boundaries

- Google credentials are consumed only by the Google reader.
- The analysis core receives an internal workbook snapshot, not credentials.
- Rules do not mutate spreadsheets.
- There is no LLM dependency in v0.1.

## Planned layers

1. richer formula AST and dependency graph;
2. optimization strategy registry;
3. clone/branch executor using Google Drive;
4. deterministic output validator;
5. optional LLM planner through provider adapters;
6. merge/rollback workflow.
