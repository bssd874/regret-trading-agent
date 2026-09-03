# REGRET

REGRET is a counterfactual autonomous paper-trading research system built for the Alpaca AI Trading Agents Hackathon.

## Day 01 architecture

```text
Alpaca market data
  -> Market Scout
  -> Azure GPT-4.1-mini primary analyst
  -> NVIDIA NIM moonshotai/kimi-k3 primary critic
     -> Azure GPT-4.1-mini critic fallback (availability failures only)
  -> deterministic consensus
  -> deterministic Risk Engine (final authority)
     -> ACCEPT -> execution kill switch -> Alpaca PAPER execution
     -> REJECT -> ShadowTrade
```

The Azure critic fallback is used only for NVIDIA timeouts, connection failures, HTTP 429 responses, and provider 5xx responses. Invalid or schema-invalid Kimi content fails closed as `CRITIC_FAILED`; it does not trigger fallback. The selected critic provider and model are persisted and exposed by the decision API, with `degraded_mode=true` for fallback reviews.

## Safety guarantees

- REGRET is paper-only. Configuration rejects `ALPACA_PAPER=false`, and every trading client is constructed with `paper=True`.
- `PAPER_EXECUTION_ENABLED` defaults to `false`. An `ACCEPT` cannot submit while the kill switch is off.
- Only the deterministic Risk Engine can produce `ACCEPT` or `REJECT`. Neither LLM can approve or submit an order.
- `REJECT` creates an idempotent shadow trade and never calls paper execution.
- `ACCEPT` reserves one unique execution record before submission. Replays return that record and never retry an order, including after an uncertain submission failure.
- Order creation and submission are isolated to `backend/app/services/paper_execution_service.py`.
- Execution synchronization only retrieves an existing Alpaca order and persists its latest status and fill fields.

## Configuration

Copy `.env.example` to `.env` and provide paper-account and provider credentials. Keep these defaults unless deliberately running a tightly controlled paper integration:

```dotenv
ALPACA_PAPER=true
PAPER_EXECUTION_ENABLED=false
EXECUTION_POSITION_PCT=0.02
NVIDIA_TIMEOUT_SECONDS=60
NVIDIA_MAX_TOKENS=512
NVIDIA_REASONING_EFFORT=low
```

`.env` and local SQLite databases are ignored by Git.

## Tests

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests -v -p no:cacheprovider
```

Provider smoke tests are analysis-only and can be run when credentials are configured:

```powershell
.\.venv\Scripts\python.exe -m backend.scripts.test_azure_ai
$env:NVIDIA_TIMEOUT_SECONDS = "60"
$env:NVIDIA_MAX_TOKENS = "512"
.\.venv\Scripts\python.exe -m backend.scripts.test_nvidia_kimi
.\.venv\Scripts\python.exe -m backend.scripts.test_azure_critic_fallback
```

## API

Existing endpoints:

- `GET /health`
- `GET /api/account`
- `POST /api/scout/run`
- `GET /api/candidates`
- `POST /api/candidates/{id}/analyze`
- `GET /api/decisions`
- `GET /api/decisions/{id}`

Day 01 routing endpoints:

- `POST /api/decisions/{decision_id}/route`
- `GET /api/executions`
- `GET /api/executions/{execution_id}`
- `POST /api/executions/{execution_id}/sync`
- `GET /api/shadow-trades`
- `GET /api/shadow-trades/{shadow_id}`

## Day 02 outcome and regret layer

```text
ExecutedTrade + ShadowTrade
  -> read-only Alpaca evaluation price
  -> deterministic Outcome Engine
  -> OutcomeSnapshot
  -> deterministic Regret Engine
  -> RegretEvent + Decision Value
```

Day 02 measures what happened after each decision without changing the original decision or performing any trading mutation. Shadow outcomes use the hypothetical entry and notional. Executed outcomes require a genuine completed fill and use its actual average fill price and quantity. Evaluation is due-time gated and idempotent: each source can have at most one outcome, and each outcome can have at most one regret event.

Classifications:

- `MISSED_ALPHA`: a rejected trade would have made money.
- `AVOIDED_LOSS`: a rejected trade would not have made money.
- `CORRECT_EXECUTION`: an accepted and executed trade made or preserved money.
- `BAD_EXECUTION`: an accepted and executed trade lost money.

For accepted trades, Decision Value equals realized outcome P&L. For rejected trades, it is the negative of hypothetical P&L. A positive value means the decision added or protected value; a negative value means it destroyed or missed value.

Day 02 endpoints:

- `POST /api/outcomes/evaluate-due`
- `POST /api/shadow-trades/{shadow_id}/evaluate`
- `POST /api/executions/{execution_id}/evaluate`
- `GET /api/outcomes`
- `GET /api/outcomes/{outcome_id}`
- `GET /api/regret-events`
- `GET /api/regret-events/{event_id}`
- `GET /api/regret/metrics`

The repository currently makes no claim of a live executed-trade evaluation; that requires a genuine filled paper execution. Outcome evaluation is read-only against Alpaca, and `PAPER_EXECUTION_ENABLED=false` remains the default and required Day 02 operating state.

## REGRET Autonomous Loop

The autonomous loop is a thin scheduler around the existing production pipeline. At the start of each cycle it read-only reconciles non-terminal paper executions through the existing `ExecutionSyncService`, then evaluates due outcomes, runs Market Scout, processes only candidates returned by that cycle, calls the existing Decision Pipeline, and routes only the persisted RiskDecision. It does not add a strategy, model, risk formula, or trading path.

Two safety-derived modes are available:

- **OBSERVE** — `AUTONOMOUS_AGENT_ENABLED=true` and `PAPER_EXECUTION_ENABLED=false`. Scouting, analysis, criticism, consensus, risk decisions, rejected-trade shadow routing, and due-outcome evaluation run automatically. A genuine `ACCEPT` is preserved unchanged and recorded in its cycle as `EXECUTION_HELD` with reason `PAPER_EXECUTION_DISABLED`; it is not routed, rejected, shadowed, or executed later.
- **AUTONOMOUS PAPER** — `AUTONOMOUS_AGENT_ENABLED=true` and `PAPER_EXECUTION_ENABLED=true`. Only a genuine `ACCEPT` created by the current cycle may pass to the existing DecisionRouter and Alpaca paper execution. Historical accepts are never scanned or automatically executed.

A newly submitted current-cycle paper order receives one immediate read-only status synchronization attempt. If it remains `new`, `accepted`, pending, or partially filled, later cycles synchronize it again. Known terminal states (`filled`, `canceled`, `expired`, and `rejected`) are not polled again. Genuine fill quantity and average price are persisted by the existing sync service, allowing the unchanged Outcome Engine to evaluate a filled execution when its horizon is due. One lookup failure is isolated to that execution and does not stop the cycle.

Autonomy defaults off, and paper execution independently defaults off:

```dotenv
ALPACA_PAPER=true
PAPER_EXECUTION_ENABLED=false
AUTONOMOUS_AGENT_ENABLED=false
AUTONOMOUS_CYCLE_SECONDS=300
AUTONOMOUS_MAX_CANDIDATES_PER_CYCLE=2
AUTONOMOUS_STALE_CYCLE_SECONDS=900
```

Each scheduled or manual cycle is persisted as an `AgentCycle`, including its mode, heartbeat, terminal status, counts, candidate actions, and safe error metadata. Backward-compatible reconciliation counts (`executions_synced` and `executions_filled`) are stored in its `summary_json` and exposed by the agent status and cycle APIs. A recent `RUNNING` heartbeat blocks overlap with `AGENT_CYCLE_ALREADY_RUNNING`; a heartbeat older than the configured stale window is marked `ABANDONED` before a new cycle is claimed.

Run the three processes separately from the repository root:

```powershell
# FastAPI
uvicorn backend.app.main:app --reload

# Frontend
cd frontend
npm run dev

# Recurring autonomous worker (from the repository root)
python -m backend.scripts.run_autonomous_agent
```

The terminal remains the read-only observability and audit interface for the autonomous agent. It is not a manual trading dashboard and provides no buy, sell, execute, or close controls.

Autonomous observability endpoints:

- `GET /api/agent/status`
- `GET /api/agent/cycles`
- `GET /api/agent/cycles/{cycle_id}`
- `POST /api/agent/run-once`

Manual run-once is available for a controlled test or demo even when the recurring worker is disabled. It runs one normal cycle and honors all paper-only and execution kill switches.

## Day 03 decision dashboard and replay

The Next.js dashboard turns the decision ledger into an evidence-first review surface. It shows aggregate Decision Value, avoided loss, missed alpha, evaluation counts, the honest execution count, full analyst/critic reasoning, deterministic risk output, and a two-point counterfactual replay built only from recorded entry and evaluation prices. The dashboard is read-only: it contains no order, routing, scouting, analysis, or evaluation controls.

The API permits browser reads only from `http://localhost:3000` and `http://127.0.0.1:3000`. Frontend configuration contains only the public backend location; provider and brokerage credentials stay in the backend environment.

### Run locally

Keep the backend safety switch disabled:

```dotenv
PAPER_EXECUTION_ENABLED=false
```

In one PowerShell terminal, run the API from the repository root:

```powershell
.\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```

In a second terminal, run the dashboard:

```powershell
cd frontend
Copy-Item .env.example .env.local
npm install
npm run dev
```

Open `http://127.0.0.1:3000`. The default `NEXT_PUBLIC_API_BASE_URL` already targets `http://127.0.0.1:8000`.

### Recommended demo sequence

1. Establish safety: point out the `PAPER MODE` badge, zero submitted orders, and absence of execution controls.
2. Read the scorecard: compare Decision Value, avoided loss, and missed alpha.
3. Select an evaluated decision from the feed and trace Scout → Analyst → Critic → Risk → Outcome.
4. Call out `Fallback Critic` when degraded mode is recorded; the UI never presents fallback as primary NVIDIA review.
5. Press **Replay** and compare the exact recorded entry and evaluation prices with the regret classification and Decision Value.

### Frontend verification

```powershell
cd frontend
npm run lint
npm test
npm run build
```
