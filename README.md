# Hermes Automation: LoadRunner CI/CD Pipeline — GitHub Actions

> Enterprise-grade performance testing pipeline for **Micro Focus LoadRunner** (API & Web HTTP protocols), with open-source observability dashboard and Dynatrace/AppDynamics integration.

---

## Architecture Overview

```
GitHub Actions
├── lr-api-performance.yml     — API Protocol test workflow
├── lr-web-performance.yml     — Web HTTP/HTML Protocol test workflow
└── publish-dashboard.yml      — Deploys dashboard to GitHub Pages (public)

Self-Hosted Windows Runner (LoadRunner installed)
└── Executes .lrs scenarios, exports results

Scripts (Python + PowerShell)
├── configure-api-scenario.ps1  — Patches LRS XML, injects creds
├── configure-web-scenario.ps1  — Web-specific config (browser, think time)
├── run-lr-scenario.ps1         — Executes LR Controller scenario
├── validate-sla.ps1            — Compares results against SLA JSON
├── parse_lr_results.py         — Parses LR CSV/XML exports
├── push_to_dynatrace.py        — MINT metrics + events to Dynatrace
├── push_to_appdynamics.py      — Custom metrics + events to AppDynamics
└── update_dashboard.py         — Appends run to dashboard/data.json

Dashboard (GitHub Pages — no login required)
└── dashboard/index.html        — Static HTML dashboard (Chart.js)
    dashboard/data.json         — Auto-updated after each test run
```

---

## Quick Start

### 1. Set up GitHub Secrets
See [`docs/SECRETS_SETUP.md`](docs/SECRETS_SETUP.md) for the full list.

**Minimum required secrets:**
```
LR_LICENSE_SERVER, LR_CONTROLLER_HOST
LR_SCRIPT_USERNAME, LR_SCRIPT_PASSWORD
DT_ENVIRONMENT_ID, DT_API_TOKEN
APPDYNAMICS_CONTROLLER_URL, APPDYNAMICS_ACCOUNT_NAME
APPDYNAMICS_API_KEY, APPDYNAMICS_APP_ID
TARGET_URL_STAGING
```

### 2. Register a self-hosted Windows runner
```powershell
# Labels required: self-hosted,loadrunner,windows
# See: Repo → Settings → Actions → Runners
```

### 3. Enable GitHub Pages
```
Repo → Settings → Pages → Source: gh-pages branch
```

### 4. Run a test
```
Actions → "LoadRunner API Performance Test" → Run workflow
```

---

## Individual User Credentials

For scripts requiring per-user sessions (OAuth, user-specific data), add secrets:
```
LR_USER_1_USERNAME / LR_USER_1_PASSWORD
LR_USER_2_USERNAME / LR_USER_2_PASSWORD
...
LR_USER_N_USERNAME / LR_USER_N_PASSWORD
```

These are injected into a LoadRunner **parameter file** at runtime, cycling across VUsers. If no per-user creds exist, falls back to the shared `LR_SCRIPT_USERNAME` service account.

---

## Observability Integration

### Dynatrace
- Custom metrics pushed via **Metrics API v2** (MINT format)
- Deployment events created at test start and end
- Metrics namespace: `performance.loadrunner.*`

**Required token scopes:** `metrics.ingest`, `events.ingest`

### AppDynamics
- Custom metrics pushed per test run
- Metric path: `Custom Metrics|LoadRunner|<PROTOCOL>|*`
- Custom events created for test lifecycle

---

## SLA Configuration

Edit `configs/sla-load.json` (and `sla-smoke.json`, `sla-stress.json` etc.) to set thresholds:
```json
{
  "thresholds": {
    "avg_response_time_ms":  { "warn": 1500, "fail": 2000 },
    "error_rate_percent":    { "warn": 0.5,  "fail": 1.0  },
    "throughput_tps":        { "warn_below": 20, "fail_below": 10 }
  }
}
```

The pipeline fails the job if `fail` thresholds are breached.

---

## Dashboard

The dashboard at `https://<org>.github.io/<repo>/` is **publicly accessible with no login**.

Features:
- Filter by protocol, environment, scenario, run count
- Trend charts: Response Time, Error Rate, Throughput, SLA Pass Rate
- Per-run history table with SLA pass/fail status
- Direct links to Dynatrace and AppDynamics dashboards
- Auto-refreshes every 5 minutes

---

## License
MIT — fork and adapt freely.
