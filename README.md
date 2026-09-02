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

Outcome evaluation, the Regret Engine, and the frontend are intentionally outside this milestone.
