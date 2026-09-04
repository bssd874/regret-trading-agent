# REGRET public deployment

The public hackathon stack uses two Vercel projects, one Neon PostgreSQL
database, and one scheduled GitHub Actions workflow:

```text
Browser -> Vercel Next.js (frontend/) -> Vercel FastAPI (app.py)
                                             |
                                             v
                                      Neon PostgreSQL
                                             ^
                                             |
                         GitHub Actions one-shot OBSERVE cycle
```

The dashboard is read-only. The scheduled workflow calls the existing Python
service directly; it does not call a public HTTP mutation endpoint. It runs
`python -m backend.scripts.run_autonomous_cycle_once` every 15 minutes and
exits after exactly one cycle. GitHub Actions concurrency prevents overlapping
workflow runs, and the persistent `AgentCycle` lock remains the database-level
guard.

## Safe hosted mode

Set these values in the Vercel API project and GitHub Actions workflow:

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
```

`AUTONOMOUS_STALE_CYCLE_SECONDS` is intentionally greater than the nominal
cycle interval because configuration validation rejects equal values. In this
mode, genuine current-cycle ACCEPT decisions become `EXECUTION_HELD`; no new
Alpaca PAPER order is submitted. `ALPACA_PAPER=false` remains invalid, and
live-money trading is unsupported.

## Neon

Create or reuse one free Neon project and keep its connection URI private. Run
the existing non-destructive schema initializer and one-time import locally
with `DATABASE_URL` injected into the process:

```bash
python -m backend.scripts.init_db
python -m backend.scripts.export_demo_data --help
python -m backend.scripts.import_demo_data --help
```

Use the scripts' displayed arguments. Do not commit the generated JSON file,
recompute history, or expose the database URI. The API project and scheduled
workflow must receive the same `DATABASE_URL`.

## Vercel FastAPI project

The deployed project is `regret-api` at <https://regret-api.vercel.app>, built
from the repository root with the **FastAPI** framework preset. Vercel detects
the exported FastAPI `app` in root `app.py`; `requirements.txt` contains the
Python dependencies and `.vercelignore` keeps the frontend, tests, docs, local
databases, and every `.env` file out of the function bundle.

Two properties keep the API serverless-safe. First, `app.py` imports the
existing application only; no worker thread, scheduler loop, or background task
is started. Second, `backend.app.main.bootstrap_schema` skips `create_all` when
the platform-provided `VERCEL` variable is present, because schema creation is
owned by `backend.scripts.init_db` and the scheduled one-shot agent. A cold
start therefore issues no DDL, and `/health` keeps answering even when the
database is momentarily unreachable. `build_engine` enables `pool_pre_ping` for
PostgreSQL and uses `NullPool` on Vercel so frozen invocations hold no
connections.

Configure server-side environment values:

- `DATABASE_URL`
- `ALPACA_API_KEY` and `ALPACA_SECRET_KEY`
- `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_ENDPOINT`, and
  `AZURE_OPENAI_DEPLOYMENT`
- `NVIDIA_API_KEY`
- all safe hosted-mode flags above
- initially, `CORS_ALLOWED_ORIGINS=http://localhost:3000`

Never prefix backend secrets with `NEXT_PUBLIC_`. Store `DATABASE_URL` and the
provider credentials as **Sensitive** values. Paste the Neon URI as a single
unquoted line; a stray quote character is silently accepted and then fails at
runtime as an unresolvable host.

Verify `/health`, the GET observability APIs, `POST /api/agent/run-once`
returning 403, and another mutation route returning 403.

## Vercel frontend project

The deployed project is `regret-terminal` at
<https://regret-terminal.vercel.app>, deployed from `frontend/` with the Next.js
preset. Its only deployment environment value is:

```dotenv
NEXT_PUBLIC_API_BASE_URL=https://regret-api.vercel.app
```

Because that value is inlined at build time, set it before building. After
Vercel assigns the frontend production URL, update the API project to the exact
frontend origins and redeploy the API:

```dotenv
CORS_ALLOWED_ORIGINS=https://regret-terminal.vercel.app,https://regret-terminal-<team>.vercel.app
```

Do not use a wildcard origin. A single Vercel project cannot serve both halves
here without the legacy `builds` configuration, because the Next.js application
lives in `frontend/` while the Python application resolves from the repository
root; two zero-config projects plus an explicit CORS allowlist is the smaller
and more reliable arrangement.

## Position-monitoring heartbeat

An open paper position is only safe while something re-evaluates it against its
recorded target, stop and horizon. That clock must be dependable.

GitHub's cron is not. In one observed window the schedule was active for about
five hours before its first run, produced a single run, then nothing for the
next several hours. Treat it as a fallback, never as the primary heartbeat.

The primary heartbeat is provider-neutral. Any dependable external scheduler —
a hosted cron service, an uptime monitor, a cloud scheduler, or a machine you
control — makes one authenticated call:

```text
POST https://<api>/api/internal/scheduled-cycle
X-Regret-Scheduler-Secret: <SCHEDULER_TRIGGER_SECRET>
```

Set `SCHEDULER_TRIGGER_SECRET` as a server-side value on the API project. While
it is unset the endpoint returns 503, so the heartbeat fails closed. A wrong or
absent secret returns 401. The secret is never sent to the browser and never
appears in a response.

The endpoint runs exactly one existing `AutonomousAgent` cycle and returns
`cycle_id`, `status`, `mode`, `trigger_source`, `started_at` and
`completed_at`. It holds no loop, thread, sleep or timer, so it is safe on an
ephemeral serverless runtime. It duplicates no trading logic.

### Two modes, chosen automatically

Because the heartbeat is meant to run often, it must not spend provider quota
discovering trades nobody authorised. It picks its mode from the persisted
runtime permission:

| Effective new-entry permission | Mode | What runs |
|---|---|---|
| ARMED | `FULL_CYCLE` | lifecycle, then scout → analyst → critic → risk gate, and at most one BUY |
| DISARMED, expired, or budget spent | `LIFECYCLE_ONLY` | reconciliation, exits and due outcomes only |

`LIFECYCLE_ONLY` never calls the market scout, the analyst or the critic, and
creates no candidate, risk decision or new ShadowTrade. It still reconciles
pending BUY and SELL orders, monitors open positions, fires
TAKE_PROFIT / STOP_LOSS / TIME_EXIT, submits the paper SELL, and resolves
already-existing ShadowTrades to AVOIDED_LOSS or MISSED_ALPHA.

When nothing at all is outstanding the tick returns `status: IDLE` without even
claiming an `AgentCycle`, so an always-on heartbeat over a quiet account costs
nothing. The idle check reads only the local database and mirrors the
pipeline's own predicates, so it cannot report idle while real work is waiting.

After a BUY spends the execution budget the runtime auto-disarms, so the very
next tick hands over to `LIFECYCLE_ONLY` and keeps monitoring that position to
its exit. The GitHub cron fallback follows the same rule. Only ARM & START, or
a still-effective arm, runs the full pipeline.

Each cycle records `cycle_mode` and `trigger_source` in its summary. The
persisted `trigger` column stays `SCHEDULED`, so no migration is needed.

The heartbeat never arms the agent. It reads the persisted runtime permission
only. While DISARMED it opens no new position and every exit path stays live,
so a scheduler tick can always close a stranded position. Concurrent ticks are
safe: the persistent `AgentCycle` lock is authoritative, and a second caller
receives `status: ALREADY_RUNNING` without submitting anything. A hosted run
whose `DATABASE_URL` is missing returns 503 rather than falling back to SQLite.

A recommended cadence is every 5 minutes while a position is open. Suggested
`AUTONOMOUS_CYCLE_SECONDS` remains the pipeline's own guidance, not the
scheduler's.

## GitHub Actions scheduled agent

The workflow is `.github/workflows/autonomous-observe.yml`. Add these encrypted
repository Actions secrets:

- `DATABASE_URL`
- `ALPACA_API_KEY`
- `ALPACA_SECRET_KEY`
- `AZURE_OPENAI_API_KEY`
- `AZURE_OPENAI_ENDPOINT`
- `AZURE_OPENAI_DEPLOYMENT`
- `NVIDIA_API_KEY`

The workflow uses a 15-minute UTC cron, a ten-minute job timeout, no retry loop,
and `cancel-in-progress: false`. Run one manual `workflow_dispatch` smoke test
after the secrets exist. A successful run must finish, persist one OBSERVE
`AgentCycle`, and submit zero Alpaca orders.

## Final verification

Check:

```text
GET  <api>/health
GET  <api>/api/agent/status
GET  <api>/api/regret/metrics
GET  <api>/api/exits
GET  <api>/api/regret-events
POST <api>/api/agent/run-once  -> 403
```

Then open the frontend and verify DUO `AVOIDED_LOSS`, BIAF `MISSED_ALPHA`, and
the persisted TSLA BUY -> `TIME_EXIT` -> SELL -> `BAD_EXECUTION` replay in EN
and ID. Confirm there are no manual BUY, SELL, or CLOSE controls, no localhost
API traffic, no CORS errors, and no client-visible secrets.
