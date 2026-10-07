# SheetOpt

Open-source Google Sheets formula optimizer, currently at **v0.2 foundation**.

**Safety guarantee at this milestone:** SheetOpt diagnoses existing formulas and can create a complete Drive copy, but **never modifies formulas or merges changes into the original**. Proposals, semantic validation, benchmarks and incremental merge are future milestones; the UI calls these out explicitly.

## Docker quick start

1. Clone the repository and checkout `feature/web-google-clone-foundation`.
2. Copy `.env.example` to `.env`.
3. Generate unique secrets locally:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Install `cryptography` in your host Python if necessary, or generate the key in a throwaway Python container. Set `SHEETOPT_ADMIN_TOKEN` and `SHEETOPT_ENCRYPTION_KEY` in `.env`. **Keep both keys private and backed up.** Losing the encryption key prevents recovery of saved credentials.

4. Start:

```bash
docker compose up --build -d
```

5. Open **http://localhost:8080**, enter your admin token.
6. In Google Cloud enable **Google Sheets API** and **Google Drive API**, create a Service Account and download its JSON. Upload the JSON in **Credenciais Google**.
7. Share the selected spreadsheet with the Service Account email. To create a copy, it needs appropriate Drive permissions and **storage ownership/quota**, commonly via a Shared Drive or an appropriately configured Workspace environment. Service Accounts without storage quota may be unable to copy into My Drive; personal OAuth is a planned alternative.
8. Paste the spreadsheet URL into the Analyze form. If formulas are detected, SheetOpt creates a new unmodified copy and lists rule findings. Formula-free spreadsheets are reported without copying.

For remote installation use HTTPS and authentication at the reverse proxy. By default Compose listens only on 127.0.0.1, **not** publicly on the network. This release supports **one installation administrator**, not multi-user access.

### Security

- Admin operations require `Authorization: Bearer SHEETOPT_ADMIN_TOKEN` (minimum 32 characters).
- Google Service Account JSON and optional AI key are encrypted at rest with Fernet using `SHEETOPT_ENCRYPTION_KEY`, stored in a persistent Docker volume. Credentials remain on the user's instance.
- The token remains in browser memory, not in localStorage. The browser must send it again after page reload.
- Service Account has Drive write scope so it can copy files. The old standalone CLI remains read-only.
- AI configuration can be saved as disabled, external HTTPS, or local HTTP(S); **no LLM inference is performed yet**.
- No security guarantee can be provided for deployments with weak admin tokens, a compromised host, or plain HTTP over a network.

### CLI and API

```bash
pip install -e ".[dev]"
sheetopt analyze-json examples/workbook.json
sheetopt analyze "https://docs.google.com/spreadsheets/d/SPREADSHEET_ID/edit"
```

The legacy CLI still uses `SHEETOPT_GOOGLE_CREDENTIALS=/path/to/service-account.json` for read-only access.

API endpoints: `GET /health`, `GET /v1/settings`, `PUT /v1/settings/google`, `PUT /v1/settings/ai`, `POST /v1/analyze` (read-only), and `POST /v1/workbooks/analyze` (diagnose and optionally clone when formulas exist). All except `/health` require the admin token.

## Rules and roadmap

Current read-only findings: PERF-001 (repeated formulas), PERF-002 (repeated SUMIFS), PERF-003 (full-column scans), PERF-004 (duplicate IMPORTRANGE). These are **diagnostics, not safe rewrite algorithms**.

Milestones:
1. ✅ Self-hosted web interface, encrypted credentials and access control.
2. ✅ Formula detection, diagnostics, full-file clone (Service Account where permissions permit).
3. ⬜ Formula parser/AST, dependency graph, safe rewrite rule engine.
4. ⬜ Snapshot comparison of values/types/formats and mutation-based tests.
5. ⬜ Performance evaluation, approved patch diff, conflict-aware batch merge.
6. ⬜ Google OAuth and selectable files, optional AI for proposal generation and curated training dataset.

Never accept LLM output as a validated rewrite. Optimization must be demonstrated independently.

License: Apache-2.0.
