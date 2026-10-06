# SheetOpt

SheetOpt is an open-source static analyzer and optimization foundation for Google Sheets.

The project is built around one safety rule:

> **Detect deterministically, propose conservatively, mutate only after validation.**

## v0.1 scope

The first version does not require AI. It can:

- connect to a Google Sheet using a Service Account;
- read formulas without editing the workbook;
- normalize copied formulas into reusable patterns;
- group identical structural patterns;
- run deterministic performance rules;
- generate a human-readable or JSON report;
- analyze local JSON fixtures without Google credentials.

No optimization is applied in v0.1. This version is intentionally read-only.

## First rules

- `PERF-001` — repeated formula pattern;
- `PERF-002` — repeated `SUMIFS`/`SOMASES` aggregation;
- `PERF-003` — repeated full-column references;
- `PERF-004` — duplicate `IMPORTRANGE`.

Each rule is auditable and documented under `docs/rules/`.

## Install

```bash
python -m venv .venv
# Windows
.\.venv\Scripts\Activate.ps1
# Linux/macOS
source .venv/bin/activate

pip install -e ".[dev]"
```

## Google credentials

Create a Google Cloud Service Account with access to the Sheets API, download its JSON credential file and set:

```bash
SHEETOPT_GOOGLE_CREDENTIALS=/absolute/path/service-account.json
```

Share the target Google Sheet with the Service Account email as **Viewer** for analysis. Editor permission is not necessary in v0.1.

Never commit the credential JSON. `credentials/` and `.env` are ignored by Git.

## Analyze a Google Sheet

```bash
sheetopt analyze "https://docs.google.com/spreadsheets/d/SPREADSHEET_ID/edit"
```

JSON output:

```bash
sheetopt analyze "https://docs.google.com/spreadsheets/d/SPREADSHEET_ID/edit" --format json
```

## Offline analysis

```bash
sheetopt analyze-json examples/workbook.json
```

## API

```bash
uvicorn sheetopt.api:app --host 0.0.0.0 --port 8080
```

Then use `POST /v1/analyze` with:

```json
{
  "spreadsheet_url": "https://docs.google.com/spreadsheets/d/.../edit"
}
```

## Docker

```bash
docker compose up --build
```

## Architecture

```text
Google Sheet / JSON fixture
          |
          v
       Scanner
          |
          v
     Normalizer
          |
          v
    Pattern Grouper
          |
          v
      Rule Engine
          |
          v
       Report
```

Future releases add clone/branch execution, deterministic validation and optional LLM planning through local or API providers.

## License

Apache-2.0.
