# REGRET public demo deployment

The public hackathon stack is a read-only Vercel dashboard backed by a
Back4App FastAPI container and persistent Neon PostgreSQL. It does not enable
paper order submission or live-money trading.

## Architecture

```text
Public browser
  -> Vercel (Next.js, frontend/)
  -> Back4App Container (FastAPI, repository root Dockerfile)
       -> Neon PostgreSQL
       -> Alpaca PAPER / Azure OpenAI / NVIDIA NIM (server-side only)
```

The infinite autonomous worker is intentionally not hosted in this first
stage and must never be embedded in FastAPI. The dashboard therefore reports
`AGENT OFFLINE` while retaining verified autonomous Alpaca PAPER evidence from
the persisted demo dataset.

## Safe public configuration

Configure these values in Back4App only:

```dotenv
ALPACA_PAPER=true
AUTONOMOUS_AGENT_ENABLED=false
AUTONOMOUS_NEW_ENTRIES_ENABLED=false
PAPER_EXECUTION_ENABLED=false
PUBLIC_AGENT_TRIGGER_ENABLED=false
PUBLIC_WRITE_API_ENABLED=false
AUTONOMOUS_CYCLE_SECONDS=300
AUTONOMOUS_STALE_CYCLE_SECONDS=900
AUTONOMOUS_MAX_CANDIDATES_PER_CYCLE=2
DATABASE_URL=<private-neon-postgresql-url>
CORS_ALLOWED_ORIGINS=https://<frontend-domain>
```

Use the existing `.env.example` names for Alpaca, Azure OpenAI, and NVIDIA
server credentials. Never put those values or `DATABASE_URL` in Vercel,
`NEXT_PUBLIC_*`, Git, Dockerfile, logs, or documentation.

## Container

Back4App uses the repository root as its build context and the root
`Dockerfile`. The image copies only the Python requirements and backend
application, runs as a non-root user, exposes TCP port `8000`, and starts one
FastAPI process:

```text
uvicorn backend.app.main:app --host 0.0.0.0 --port $PORT --workers 1
```

The command uses port `8000` only as a local fallback. It does not start
`backend.scripts.run_autonomous_agent`.

## Neon initialization and verified data

Neon requires an SSL/TLS PostgreSQL connection string; preserve all supplied
query parameters. Keep it in the process environment only.

Initialize a fresh database non-destructively:

```powershell
$env:DATABASE_URL = "<private-neon-postgresql-url>"
.\.venv\Scripts\python.exe -m backend.scripts.init_db
```

Export the verified local SQLite dataset to a temporary path:

```powershell
$env:DATABASE_URL = "sqlite:///./regret.db"
.\.venv\Scripts\python.exe -m backend.scripts.export_demo_data `
  --output "$env:TEMP\regret-demo-verified.json"
```

Then inject the Neon URL and import intentionally:

```powershell
$env:DATABASE_URL = "<private-neon-postgresql-url>"
.\.venv\Scripts\python.exe -m backend.scripts.import_demo_data `
  --input "$env:TEMP\regret-demo-verified.json"
```

The importer preserves IDs and relationships, skips exact records on repeat,
and rolls back on conflicts. Delete the temporary export after hosted data is
verified.

## Back4App Container

1. Connect the GitHub repository in Back4App Containers.
2. Select branch `feat/autonomous-agent-loop`.
3. Set the repository root as the root directory.
4. Keep automatic deployment off unless feature-branch pushes should redeploy.
5. Add the private server environment values and safe flags above.
6. Initially set `CORS_ALLOWED_ORIGINS=http://localhost:3000` if the Vercel URL
   is not known.
7. Create the free container and verify its generated HTTPS URL.

Validate before deploying the frontend:

```text
GET  https://<backend-domain>/health                   -> 200
GET  https://<backend-domain>/api/regret/metrics       -> 200
POST https://<backend-domain>/api/agent/run-once       -> 403
POST https://<backend-domain>/api/scout/run            -> 403
```

## Vercel

Deploy from the `frontend` directory or configure it as the Git project root.
The only public environment variable is:

```dotenv
NEXT_PUBLIC_API_BASE_URL=https://<back4app-backend-domain>
```

After Vercel assigns the production URL, set Back4App to its exact origin:

```dotenv
CORS_ALLOWED_ORIGINS=https://<frontend-domain>
```

Do not use a wildcard. Redeploy/restart the API and confirm browser requests
reach Back4App rather than localhost.

## Final validation

Verify the public terminal shows:

- `PAPER MODE`, `API HEALTHY`, and truthful `AGENT OFFLINE`
- persisted Decision Value and evaluated-decision metrics
- DUO `AVOIDED_LOSS` replay
- BIAF `MISSED_ALPHA` replay
- TSLA confirmed BUY, `TIME_EXIT`, confirmed SELL, realized P&L, and
  `BAD_EXECUTION`
- EN -> ID -> EN without layout errors
- no BUY, SELL, CLOSE, EXECUTE, or manual cycle controls

Check browser console/network for CORS errors, localhost calls, application
exceptions, and secret values. Recheck the safe public flags after every
provider-side configuration change. No recurring worker is part of this
deployment; a scheduled service-to-service runner is future work.
