# REGRET

REGRET is a counterfactual autonomous paper-trading research system.

The Day 31 decision path is:

`CandidateTrade -> Azure primary analyst -> NVIDIA Kimi K3 adversarial critic -> deterministic consensus -> deterministic risk -> ACCEPT/REJECT`

ACCEPT and REJECT are research decisions only. The backend contains no order submission, cancellation, replacement, or position-closing path. Alpaca is constructed with `paper=True` and is used for market/account reads.

Run provider-independent tests:

```powershell
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider
```

Run analysis-only provider smoke tests when credentials are configured:

```powershell
.\.venv\Scripts\python.exe -m backend.scripts.test_azure_ai
.\.venv\Scripts\python.exe -m backend.scripts.test_nvidia_kimi
```

Day 31 endpoints:

- `POST /api/candidates/{id}/analyze`
- `GET /api/decisions`
- `GET /api/decisions/{id}`
