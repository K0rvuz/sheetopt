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
6. Enable **Google Sheets API** and **Google Drive API** in your own Google Cloud project. For personal access, create an OAuth client (Web Application recommended), download its `client_secret_*.json`, and upload it under **Minha conta Google (OAuth 2.0)**. Desktop OAuth JSON is also accepted for localhost deployments.
7. For a **Web Application** OAuth client, add `http://localhost:8080/auth/google/callback` to **Authorized redirect URIs** in Google Cloud. If running behind HTTPS, set `SHEETOPT_PUBLIC_BASE_URL=https://your.domain.example` in `.env`, and register `https://your.domain.example/auth/google/callback`. For a **Desktop** client the callback uses `http://127.0.0.1:8080/auth/google/callback`. Desktop clients only work with local loopback deployments.
8. Click **Conectar com Google**, authorize Google in the new browser window, close it after confirmation, and confirm that **OAuth conectado** appears. Paste a spreadsheet link and analyze.
9. Alternatively, upload a **Service Account** JSON. Share the spreadsheet with its service email. Creating Drive copies with Service Accounts may require an appropriate Shared Drive / storage ownership configuration. Formula-free spreadsheets are reported without copying.

For remote installation use HTTPS and authentication at the reverse proxy. By default Compose listens only on 127.0.0.1, **not** publicly on the network. This release supports **one installation administrator**, not multi-user access.

### Security

- Admin operations require `Authorization: Bearer SHEETOPT_ADMIN_TOKEN` (minimum 32 characters).
- Google OAuth client secret, OAuth refresh/access tokens, Service Account JSON and optional AI key are encrypted at rest with Fernet using `SHEETOPT_ENCRYPTION_KEY`, stored in a persistent Docker volume. Credentials remain on the user's instance.
- The token remains in browser memory, not in localStorage. The browser must send it again after page reload. Google OAuth browser callbacks do not contain admin tokens, and Docker's Uvicorn access log is disabled to avoid logging OAuth authorization codes.
- Saving a different OAuth client clears existing OAuth tokens. Disconnect deletes local tokens; revoke access separately in your Google account settings. Keep backups of your encryption key.
- The OAuth flow uses an unpredictable one-time, 10-minute state and PKCE (S256), uses Google's HTTPS token endpoint and persists refresh tokens encrypted. OAuth authorization callback doesn't require the admin header, but starting the OAuth flow does.
- The authorization scopes are `spreadsheets.readonly` and `drive` (full Drive scope), so the user can submit an arbitrary spreadsheet URL and create a copy. The full Drive scope is restricted by Google and public distribution may require OAuth verification/security review. A future Google Picker + `drive.file` approach can reduce privileges. OAuth credentials belong to each user's own Google Cloud project, not the SheetOpt developer.
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

API endpoints: `GET /health`, `GET /v1/settings`, `PUT /v1/settings/google`, `PUT /v1/settings/google/oauth-client`, `POST /v1/google/oauth/start`, `DELETE /v1/settings/google/oauth`, `PUT /v1/settings/ai`, `POST /v1/analyze` (read-only), and `POST /v1/workbooks/analyze` (diagnose and optionally clone when formulas exist). All API routes except `/health` and the one-time `GET /auth/google/callback` require the admin token.

## Rules and roadmap

Current read-only findings: PERF-001 (repeated formulas), PERF-002 (repeated SUMIFS), PERF-003 (full-column scans), PERF-004 (duplicate IMPORTRANGE). These are **diagnostics, not safe rewrite algorithms**.

Milestones:
1. ✅ Self-hosted web interface, encrypted credentials and access control.
2. ✅ Formula detection, diagnostics, full-file clone (Service Account where permissions permit).
3. ⬜ Formula parser/AST, dependency graph, safe rewrite rule engine.
4. ⬜ Snapshot comparison of values/types/formats and mutation-based tests.
5. ⬜ Performance evaluation, approved patch diff, conflict-aware batch merge.
6. ✅ Google OAuth (Web client and localhost Desktop client) and Google Service Account authentication.
7. ⬜ Google Picker, optional AI for proposal generation and curated training dataset.

Never accept LLM output as a validated rewrite. Optimization must be demonstrated independently.

License: Apache-2.0.


## Large Google Sheets and Drive copy timeouts

Google Drive `files.copy` can take longer for large sheets than default HTTP timeouts.
Set `SHEETOPT_GOOGLE_COPY_TIMEOUT_SECONDS=180` (default) in your `.env` (allowed
15–600 seconds) to change the Drive HTTP read timeout, then rebuild with
`docker compose up -d --build`.

If Google does not respond before the timeout, SheetOpt **keeps the diagnostic
report** and reports `clone_timeout` rather than returning HTTP 500. A
timed-out request has an **unknown outcome**: Google may still have created
the copy. Check your Drive for a `[SheetOpt]` copy before issuing another
copy request. SheetOpt never automatically retries timed-out `files.copy`
requests to avoid accidental duplicate files.

Use **Somente diagnosticar (sem cópia)** when you want the existing report
without copying again. The project does not rewrite formulas yet.

## Diagnostic dashboard and exports

The results panel displays a compact summary, severity breakdown, collapsible
groups by rule and filters for severity/text. It intentionally does not mount
hundreds of individual findings until a group is expanded. A collapsible
execution record shows per-stage durations for read, diagnosis and copy
(available only after the API returns; this is not live progress tracking).

You can download a complete structured **PDF** or **JSON** of the report
without reading Google Sheets again. The PDF includes totals, findings by
severity and rule, frequently used functions, available execution timings,
locations and rule recommendations. Exports are generated from the
in-memory report returned to the browser and do **not** apply any changes.
The export endpoint is authenticated, does not save a PDF server-side and
rejects unreasonably large payloads. Treat downloads as potentially
confidential because they may include spreadsheet names, references and
pieces of formulas.

All findings are diagnostic only. Performance improvement and safe
formula rewrites must be validated and measured in later work.

## Experimental clone-only optimization (OPT-LET-001)

The analysis now discovers up to five **very conservatively matched** scalar
formulas with the form `=SUMIFS(...)+SUMIFS(...)` (or the supported simple
SUM/COUNT/AVERAGEIF variants) where both function calls are identical. The
experimental rewrite uses Google's `LET` to cache the shared calculation
without replacing addition by multiplication. Nested functions and uncertain
syntax are intentionally excluded. See Google's LET documentation for its
evaluate-once behavior.

After **Analisar e criar cópia**, expand **Otimizações experimentais na cópia**
to review candidates. With explicit confirmation the backend:

1. Checks that the clone ID and candidate were generated and saved by SheetOpt.
2. Reads the original and cloned *target cell* and verifies the formula, values,
   types, displayed value, relevant formatting and validation metadata match.
3. Writes **one formula to the clone only** using Google Sheets batchUpdate.
4. Re-reads the clone target cell and compares with the baseline. On mismatch,
   it attempts to restore the old formula in the clone.
5. Reports `validated_cell_only`, `rejected`, `reverted`, or
   `manual_review_required` if rollback or write outcome cannot be confirmed.

Successful local verification is **not** an optimization performance
measurement nor proof of full-workbook equivalence. Downstream dependents,
recalculation timing, named-range collisions, volatility triggered by
dependencies, concurrent editors, locale restrictions, and future input
changes require more work. The original is never modified and merge remains
disabled. Changes on the clone can be inspected manually. There is no
automatic retry after an ambiguous write. This is an experimental foundation,
not a general purpose correction of PERF-003 findings.
