# REGRET public demo deployment

The public hackathon stack is a read-only Vercel dashboard backed by a
Northflank FastAPI service and Northflank PostgreSQL. A separate Northflank cron
job runs one bounded autonomous cycle every 15 minutes in OBSERVE mode. Alpaca
PAPER order submission and public mutation APIs remain disabled.

## Architecture

```text
Public browser
  -> Vercel (Next.js, frontend/)
  -> Northflank Web Service (FastAPI, repository-root Dockerfile)
       -> Northflank PostgreSQL addon
       -> Alpaca PAPER / Azure OpenAI / NVIDIA NIM (server-side only)

Northflank Cron Job
  -> python -m backend.scripts.run_autonomous_cycle_once
  -> same PostgreSQL addon and server-side provider secrets
```

The FastAPI process does not start a background worker. The cron image overrides
the Docker command, invokes the existing `AutonomousAgent` once, and exits.

## Safe hosted configuration

Apply these values to both the API and the scheduled job through Northflank
configuration/secret groups:

```dotenv
ALPACA_PAPER=true
AUTONOMOUS_AGENT_ENABLED=true
AUTONOMOUS_NEW_ENTRIES_ENABLED=true
PAPER_EXECUTION_ENABLED=false
PUBLIC_AGENT_TRIGGER_ENABLED=false
PUBLIC_WRITE_API_ENABLED=false
AUTONOMOUS_CYCLE_SECONDS=900
AUTONOMOUS_STALE_CYCLE_SECONDS=1800
AUTONOMOUS_MAX_CANDIDATES_PER_CYCLE=2
DATABASE_URL=<private-northflank-postgresql-uri>
```

`AUTONOMOUS_STALE_CYCLE_SECONDS` is intentionally greater than the cycle value,
as required by application validation. The cron schedule, rather than
`AUTONOMOUS_CYCLE_SECONDS`, controls hosted cadence.

Set the API's CORS value initially to `http://localhost:3000`, then replace it
with the exact Vercel production origin. Do not use a wildcard. The cron job
does not need CORS.

Keep Alpaca, Azure OpenAI, NVIDIA, and database values server-side only. Never
put them in Vercel, `NEXT_PUBLIC_*`, Git, the Dockerfile, logs, or documentation.

## Container commands

Northflank builds the repository-root `Dockerfile`. Its default command runs one
FastAPI process on `0.0.0.0` and the platform-provided `PORT`:

```text
uvicorn backend.app.main:app --host 0.0.0.0 --port $PORT --workers 1
```

Use command overrides for bounded jobs:

```text
Schema initialization: python -m backend.scripts.init_db
One autonomous cycle: python -m backend.scripts.run_autonomous_cycle_once
```

Never use `backend.scripts.run_autonomous_agent` as a cron command because it
contains the intentionally long-running worker loop.

## Northflank resources

Create or reuse project `REGRET` on the Developer Sandbox plan:

1. Create one free PostgreSQL addon without HA, replicas, or paid storage.
2. Link its normal application URI to a secret group as `DATABASE_URL`.
3. Add the required server-provider secrets and safe hosted values to the group.
4. Create `regret-api` from `bssd874/regret-trading-agent`, branch
   `feat/autonomous-agent-loop`, using `/Dockerfile`.
5. Expose only the HTTP container port and route `/` to it. Configure an HTTP
   readiness check on `/health`.
6. Create a temporary/manual schema job using the same source and
   `python -m backend.scripts.init_db`, then run it once.
7. Create `regret-agent-job` from the same branch and image. Override its command
   with `python -m backend.scripts.run_autonomous_cycle_once`.

Cron settings:

```text
Schedule: */15 * * * *
Concurrency: Forbid
Retry limit: 0
Time limit: 600 seconds
Run on source change: Never
```

Run the agent job manually once before enabling its schedule. A successful run
must create exactly one OBSERVE `AgentCycle`, then terminate. A REJECT may create
a `ShadowTrade`; a genuine ACCEPT must become `EXECUTION_HELD`. Neither path may
submit an order while `PAPER_EXECUTION_ENABLED=false`.

## Verified data migration

Export the verified local SQLite dataset to a temporary path:

```powershell
$env:DATABASE_URL = "sqlite:///./regret.db"
.\.venv\Scripts\python.exe -m backend.scripts.export_demo_data `
  --output "$env:TEMP\regret-demo-verified.json"
```

Initialize and import using a bounded Northflank job or a temporary Northflank
database proxy. The effective command is:

```text
python -m backend.scripts.import_demo_data --input <temporary-export-path>
```

The import is intentional, preserves IDs and relationships, skips identical
records on repeat, and rolls back on conflicts. Do not commit the export or
permanently expose PostgreSQL. Delete the temporary export after hosted API
verification succeeds.

## API validation

Before deploying the frontend, verify:

```text
GET  https://<northflank-api-domain>/health             -> 200
GET  https://<northflank-api-domain>/api/agent/status   -> OBSERVE
GET  https://<northflank-api-domain>/api/regret/metrics -> 200
POST https://<northflank-api-domain>/api/agent/run-once -> 403
POST https://<northflank-api-domain>/api/scout/run      -> 403
```

Blocked HTTP calls must not create an `AgentCycle`, invoke providers, or submit
orders. The scheduled job bypasses no safety checks; it calls Python services
directly and retains the persistent AgentCycle lock.

## Vercel

Deploy the current feature-branch working tree from `frontend/`. The only public
environment variable is:

```dotenv
NEXT_PUBLIC_API_BASE_URL=https://<northflank-api-domain>
```

After Vercel assigns the production URL, set the API to its exact origin:

```dotenv
CORS_ALLOWED_ORIGINS=https://<frontend-domain>
```

Redeploy/restart the API and verify browser requests reach Northflank rather
than localhost.

## Final validation

Verify the public terminal shows:

- `PAPER MODE`, `API HEALTHY`, and `AGENT ACTIVE · OBSERVE`
- persisted Decision Value and evaluated-decision metrics
- DUO `AVOIDED_LOSS` and BIAF `MISSED_ALPHA` replays
- TSLA confirmed BUY, `TIME_EXIT`, confirmed SELL, realized P&L, and
  `BAD_EXECUTION`
- EN -> ID -> EN without layout errors
- no BUY, SELL, CLOSE, EXECUTE, or manual cycle controls

Check browser console/network for CORS errors, localhost calls, application
exceptions, and secret values. Recheck the safe flags after every provider-side
configuration change. Live-money trading is unsupported.
