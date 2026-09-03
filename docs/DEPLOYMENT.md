# REGRET public demo deployment

This runbook prepares a read-only public jury dashboard backed by an autonomous
OBSERVE worker. It does not deploy resources, enable paper order submission, or
support live-money trading.

## Architecture

```text
Public browser
  -> Vercel (Next.js, frontend/)
  -> Railway FastAPI service
       -> Railway PostgreSQL <- Railway autonomous worker
       -> Alpaca PAPER / Azure OpenAI / NVIDIA NIM (server-side only)
```

The FastAPI service and worker must receive the same `DATABASE_URL`. Only
`NEXT_PUBLIC_API_BASE_URL` belongs in Vercel; brokerage, model-provider, and
database credentials must never be configured as `NEXT_PUBLIC_*` values.

## A. Railway

1. Create one Railway project and provision PostgreSQL.
2. Add a backend service from this repository. Keep the repository root as the
   service root.
3. Use build command `pip install -r requirements.txt`.
4. On the backend service only, use pre-deploy command
   `python -m backend.scripts.init_db`. It calls SQLAlchemy `create_all`, which
   creates missing tables and indexes but never drops or recreates data.
5. Use start command
   `uvicorn backend.app.main:app --host 0.0.0.0 --port $PORT`.
6. Set the health-check path to `/health`.
7. Add a second service from the same repository for the worker, again using
   the repository root and `pip install -r requirements.txt`.
8. Use worker start command
   `python -m backend.scripts.run_autonomous_agent`.
9. Attach both services to the same PostgreSQL `DATABASE_URL`. Configure the
   same Alpaca PAPER, Azure, NVIDIA, and autonomous settings in both services.
   Do not expose these variables through Vercel.

Use this public OBSERVE profile for both server roles:

```dotenv
ALPACA_PAPER=true
AUTONOMOUS_AGENT_ENABLED=true
AUTONOMOUS_NEW_ENTRIES_ENABLED=true
PAPER_EXECUTION_ENABLED=false
PUBLIC_AGENT_TRIGGER_ENABLED=false
PUBLIC_WRITE_API_ENABLED=false
AUTONOMOUS_CYCLE_SECONDS=300
AUTONOMOUS_STALE_CYCLE_SECONDS=900
DATABASE_URL=<railway-postgres-url>
```

Copy the existing Azure/NVIDIA/Alpaca variable names from `.env.example` into
Railway's secret settings. Never commit their values. The worker is the only
recurring scheduler; do not add an autonomous startup hook to FastAPI.

## B. Vercel

1. Import the same repository in Vercel.
2. Set **Root Directory** to `frontend`.
3. Keep the standard Next.js build command (`npm run build`).
4. Configure exactly one public backend setting:

   ```dotenv
   NEXT_PUBLIC_API_BASE_URL=https://<railway-backend-domain>
   ```

5. Deploy only after the Railway backend has a stable HTTPS URL.

`NEXT_PUBLIC_*` values are embedded into browser JavaScript at build time.
Never place Alpaca, Azure, NVIDIA, or PostgreSQL credentials in them.

## C. CORS

After Vercel assigns the frontend URL, configure the Railway backend with a
comma-separated list of exact origins:

```dotenv
CORS_ALLOWED_ORIGINS=https://<frontend-domain>
```

For a temporary local plus hosted test, use:

```dotenv
CORS_ALLOWED_ORIGINS=http://localhost:3000,http://127.0.0.1:3000,https://<frontend-domain>
```

Do not use `*`. Restart the backend after changing CORS settings.

## D. Verified demo data migration

The migration is intentional and one-time; it never runs during application
startup. It copies persisted records without recomputing decisions or outcomes.

1. Export the local SQLite dataset to a secure location outside the repository:

   ```powershell
   $env:DATABASE_URL = "sqlite:///./regret.db"
   .\.venv\Scripts\python.exe -m backend.scripts.export_demo_data `
     --output "$env:TEMP\regret-demo-verified.json"
   ```

2. Inspect the JSON before transfer. It should contain only the documented
   database tables and no credentials. Keep it private even though it contains
   no API secrets, because it is execution evidence.
3. Transfer it through a secure administrative channel to a one-time Railway
   shell/job with the same `DATABASE_URL` as the application.
4. Initialize the target schema, then import:

   ```text
   python -m backend.scripts.init_db
   python -m backend.scripts.import_demo_data --input /secure/path/regret-demo-verified.json
   ```

The importer validates format, table/column compatibility, IDs, datetimes, and
existing rows. Matching records are skipped on repeat runs; conflicts fail and
roll back the transaction. PostgreSQL ID sequences are advanced after explicit
primary-key import. Delete the transferred JSON after validation according to
the platform's secure file-handling workflow.

## E. Validation

Before sharing the public URL, verify:

```text
GET https://<backend-domain>/health
GET https://<backend-domain>/api/agent/status
GET https://<backend-domain>/api/regret/metrics
GET https://<backend-domain>/api/executions
GET https://<backend-domain>/api/exits
POST https://<backend-domain>/api/agent/run-once  -> 403
POST https://<backend-domain>/api/scout/run      -> 403
```

Then open the Vercel URL and check:

- `AGENT ACTIVE · OBSERVE`
- TSLA TRADE replay with confirmed BUY, `TIME_EXIT`, SELL, realized P&L, and
  `BAD_EXECUTION`
- DUO `AVOIDED_LOSS` replay
- BIAF `MISSED_ALPHA` replay
- EN -> ID -> EN, API health, metrics, and the audit trail

No judge action or new order is required to understand the project.

## F. Final safety values

Re-check these exact Railway values after every configuration change:

```dotenv
ALPACA_PAPER=true
PAPER_EXECUTION_ENABLED=false
PUBLIC_AGENT_TRIGGER_ENABLED=false
PUBLIC_WRITE_API_ENABLED=false
AUTONOMOUS_AGENT_ENABLED=true
AUTONOMOUS_NEW_ENTRIES_ENABLED=true
AUTONOMOUS_CYCLE_SECONDS=300
AUTONOMOUS_STALE_CYCLE_SECONDS=900
```

With this profile, fresh autonomous analysis continues, rejected decisions can
produce shadow outcomes, and genuine accepts are recorded as execution-held.
No new Alpaca PAPER BUY is submitted. Live-money trading is unsupported.

## Public API audit

The dashboard calls GET endpoints only. `/health` is constant-time and invokes
no database write, Scout, LLM, autonomous cycle, or Alpaca client.

| Endpoint class | Classification | Public OBSERVE behavior |
| --- | --- | --- |
| GET API endpoints | Read-only; account/mover reads may call Alpaca | Dashboard uses persisted read endpoints |
| `POST /api/agent/run-once` | Expensive and state-changing | Requires both write API and manual-agent gates; hosted profile returns 403 |
| `POST /api/scout/run` | Market-data call and database mutation | Blocked with 403 by `PUBLIC_WRITE_API_ENABLED=false` |
| `POST /api/candidates/{id}/analyze` | LLM-expensive and database mutation | Blocked with 403 by `PUBLIC_WRITE_API_ENABLED=false` |
| `POST /api/decisions/{id}/route` | Execution-sensitive | Blocked with 403 by the write gate; execution kill switch remains a second defense |
| Execution sync/outcome evaluation POSTs | Read-only against Alpaca, but update persisted state | Blocked with 403 by `PUBLIC_WRITE_API_ENABLED=false` |

CORS permits browser GETs only, but CORS is not authentication. The application
therefore rejects every HTTP `POST`, `PUT`, `PATCH`, and `DELETE` below `/api`
while `PUBLIC_WRITE_API_ENABLED=false`, before route dependencies or services
run. This guard does not affect the Railway worker because it calls Python
services directly. Keep authenticated administration in front of these routes
if remote write access is intentionally enabled later.
