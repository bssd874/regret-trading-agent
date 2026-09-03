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
MARKET_SCOUT_MIN_PRICE=5.0
MARKET_SCOUT_MIN_PREVIOUS_DAILY_VOLUME=500000
MARKET_SCOUT_MAX_DAILY_CHANGE_PCT=25.0
NVIDIA_TIMEOUT_SECONDS=60
NVIDIA_MAX_TOKENS=512
NVIDIA_REASONING_EFFORT=low
```

`.env` and local SQLite databases are ignored by Git.

### Evidence calibration and candidate quality

The analyst is instructed to calibrate confidence across the full continuous `[0, 1]` range using only supplied evidence. It is not instructed to become bullish, meet the Risk Engine threshold, or round confidence into fixed buckets. The critic independently tests the thesis: `PASS` requires no material concern and an adjustment of exactly `0`; `CHALLENGE` requires at least one concrete concern grounded in supplied candidate or analysis fields and a strictly negative adjustment no lower than `-0.20`. NVIDIA Kimi and the availability-only Azure fallback receive the same prompt and strict schema.

Before any candidate reaches an LLM, Market Scout applies deterministic quality gates. An asset must be active US equity metadata on a supported US exchange, tradable, and fractionable. Identifiable warrants, units, and rights are excluded by asset name. The snapshot must have a price of at least `$5.00`, positive current volume, at least `500,000` shares in the previous completed daily bar, and a positive daily move no greater than `25%`. These bounds are configurable with the `MARKET_SCOUT_*` variables above. If the movers feed is unavailable or every mover fails the gates, the existing liquid `AAPL/MSFT/NVDA/AMD/AMZN/META/GOOGL/TSLA/SPY/QQQ` watchlist is screened through the same gates.

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

The autonomous loop is a thin scheduler around the existing production pipeline. Each cycle read-only reconciles non-terminal BUY and SELL orders, monitors filled paper positions against their original persisted thesis, evaluates realized execution and due shadow outcomes, and—only when the separate new-entry gate is enabled—runs Market Scout and the existing Decision Pipeline. It does not add a strategy, model, or risk formula.

Two safety-derived modes are available:

- **OBSERVE** — `AUTONOMOUS_AGENT_ENABLED=true` and `PAPER_EXECUTION_ENABLED=false`. Scouting, analysis, criticism, consensus, risk decisions, rejected-trade shadow routing, and due-outcome evaluation run automatically. A genuine `ACCEPT` is preserved unchanged and recorded in its cycle as `EXECUTION_HELD` with reason `PAPER_EXECUTION_DISABLED`; it is not routed, rejected, shadowed, or executed later.
- **AUTONOMOUS PAPER** — `AUTONOMOUS_AGENT_ENABLED=true` and `PAPER_EXECUTION_ENABLED=true`. Only a genuine `ACCEPT` created by the current cycle may pass to the existing DecisionRouter and Alpaca paper execution. Historical accepts are never scanned or automatically executed.

`AUTONOMOUS_NEW_ENTRIES_ENABLED=false` independently disables Scout, analysis, and new entry creation while retaining reconciliation, position monitoring, approved exits, and outcome evaluation for existing paper positions. Set it to `true` only when new autonomous entries are intentionally enabled.

A newly submitted current-cycle BUY receives one immediate read-only status synchronization attempt. If it remains `new`, `accepted`, pending, or partially filled, later cycles synchronize it again. Known terminal states (`filled`, `canceled`, `expired`, and `rejected`) are not polled again. Genuine fill quantity and average price are persisted from Alpaca. One lookup failure is isolated to that execution and does not stop the cycle.

Autonomy defaults off, and paper execution independently defaults off:

```dotenv
ALPACA_PAPER=true
PAPER_EXECUTION_ENABLED=false
AUTONOMOUS_AGENT_ENABLED=false
AUTONOMOUS_NEW_ENTRIES_ENABLED=false
AUTONOMOUS_CYCLE_SECONDS=300
AUTONOMOUS_MAX_CANDIDATES_PER_CYCLE=2
AUTONOMOUS_STALE_CYCLE_SECONDS=900
```

Each scheduled or manual cycle is persisted as an `AgentCycle`, including its mode, heartbeat, terminal status, counts, candidate actions, and safe error metadata. Backward-compatible BUY reconciliation and exit-lifecycle counts are stored in `summary_json` and exposed by the agent status and cycle APIs. A recent `RUNNING` heartbeat blocks overlap with `AGENT_CYCLE_ALREADY_RUNNING`; a heartbeat older than the configured stale window is marked `ABANDONED` before a new cycle is claimed.

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
- `GET /api/exits`
- `GET /api/exits/{exit_id}`

Manual run-once is available for a controlled test or demo even when the recurring worker is disabled. It runs one normal cycle and honors all paper-only and execution kill switches.

## Verified Autonomous Paper Execution

On September 3, 2026, REGRET completed its first verified end-to-end real autonomous Alpaca PAPER execution from market discovery through confirmed order fill. The `ACCEPT` was produced naturally by genuine autonomous AgentCycle #20: no historical decision was modified, no human selected TSLA for execution, and no human clicked BUY.

```text
Market Scout
→ Analyst
→ Adversarial Critic
→ Consensus
→ Risk Gate
→ ACCEPT
→ Alpaca Paper Order
→ Automatic Reconciliation
→ FILLED
```

| Field                | Value         |
| -------------------- | ------------- |
| Agent Cycle          | #20           |
| Candidate            | #49           |
| Symbol               | TSLA          |
| Risk Decision        | #24 — ACCEPT  |
| Executed Trade       | #1            |
| Order Submission     | Automatic     |
| Initial Status       | `pending_new` |
| Reconciliation       | Automatic     |
| Final Status         | `FILLED`      |
| Filled Quantity      | 0.26104187    |
| Filled Average Price | $383.042      |
| Human BUY Action     | None          |

This verifies that REGRET can autonomously discover an opportunity, analyze it, pass deterministic risk controls, submit an Alpaca Paper order, and reconcile the execution to a confirmed fill without a human selecting or buying the asset. The filled quantity and average price came from Alpaca.

> **Safety:** REGRET remains paper-only. `ALPACA_PAPER=true` is enforced, and live-money trading is not supported.

### Autonomous Paper Exit Lifecycle

The backend now implements and tests the deterministic lifecycle after a filled BUY:

```text
FILLED BUY
→ Position Monitoring
→ TAKE_PROFIT / STOP_LOSS / TIME_EXIT
→ Alpaca Paper SELL
→ Automatic Reconciliation
→ FILLED
→ Realized Execution P&L
→ CORRECT_EXECUTION / BAD_EXECUTION
→ Decision Value
```

Position monitoring uses only the original persisted `target_price`, `stop_loss`, and `horizon_minutes`; no LLM changes exit levels. A `TradeExit` is reserved before Alpaca is contacted, ambiguous submission failures are not retried automatically, and pending SELL orders are reconciled read-only in later cycles. An executed ACCEPT outcome remains `NOT_READY` with `POSITION_STILL_OPEN` until both BUY and SELL have genuine fills. Realized P&L then uses Alpaca's actual entry fill, exit fill, and closed quantity with `price_source=alpaca_exit_fill`.

The autonomous SELL lifecycle is implemented and covered by mocked integration tests, but it has **not** yet been verified by selling the existing real TSLA paper position. No real SELL should be run without explicit user approval.

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
