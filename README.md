# Hermes Automation

> **Open-source LoadRunner CI/CD framework** — 25-parameter GitHub Actions workflows, 7-APM integration, AI-powered analysis, TPH-based SLA monitoring, and a live public dashboard. Designed for BFSI/Insurance workload patterns.

[![Live Dashboard](https://img.shields.io/badge/Live_Dashboard-GitHub_Pages-6c63ff?style=flat-square&logo=github)](https://niyartalukdar.github.io/Hermes-Automation/)
[![API Pipeline](https://github.com/NiyarTalukdar/Hermes-Automation/actions/workflows/lr-api-performance.yml/badge.svg)](https://github.com/NiyarTalukdar/Hermes-Automation/actions/workflows/lr-api-performance.yml)
[![Web Pipeline](https://github.com/NiyarTalukdar/Hermes-Automation/actions/workflows/lr-web-performance.yml/badge.svg)](https://github.com/NiyarTalukdar/Hermes-Automation/actions/workflows/lr-web-performance.yml)
[![Dashboard Deploy](https://github.com/NiyarTalukdar/Hermes-Automation/actions/workflows/publish-dashboard.yml/badge.svg)](https://github.com/NiyarTalukdar/Hermes-Automation/actions/workflows/publish-dashboard.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-green?style=flat-square)](https://github.com/NiyarTalukdar/Hermes-Automation/blob/main/LICENSE)
[![Made with](https://img.shields.io/badge/Made_with-PowerShell_·_Python_·_GitHub_Actions-blue?style=flat-square)](https://github.com/NiyarTalukdar/Hermes-Automation)

---

## Why I built this

At Chubb Insurance, performance testing had a real operational problem: test cycles took ~4 hours end-to-end, results lived in scattered Excel files, and APM data in AppDynamics had no programmatic connection to test execution. Every release required manual correlation between load test output and infrastructure metrics.

I built Hermes to solve that — a pipeline that triggers LoadRunner, configures the scenario at runtime, validates SLAs automatically, pushes annotated metrics to any APM tool, and publishes results to a live dashboard. No manual steps between "trigger test" and "see results with APM context."

The SLA thresholds, TPH targets, and test scenario designs reflect real BFSI non-functional requirements — authentication flows, policy management APIs, claims processing, and cloud migration workloads.

---

## What this achieves

| Metric | Before | After |
| --- | --- | --- |
| Test cycle time | ~4 hours (manual) | ~12 minutes (automated) |
| SLA reporting | Manual Excel | Auto-generated, per-run, in dashboard |
| APM correlation | Manual, post-hoc | Automated annotation at test start/end |
| Result visibility | Shared locally | Public dashboard, no login required |
| Workflow parameters | Fixed in .lrs file | 25 runtime-configurable inputs |

---

## Architecture

```
GitHub Actions (CI/CD Orchestration)
├── lr-api-performance.yml      — API protocol · 25 configurable inputs
├── lr-web-performance.yml      — Web HTTP/HTML protocol · 25 configurable inputs
└── publish-dashboard.yml       — Auto-deploys dashboard + fetches live APM metrics

Self-Hosted Windows Runner (LoadRunner Enterprise installed)
└── Executes .lrs scenarios via lr_batch.exe · exports CSV/HTML/XML results

scripts/
├── configure-api-scenario.ps1  — Patches .lrs XML: scheduler, think time,
│                                 pacing, browser, SSL, logging, error handling
├── configure-web-scenario.ps1  — Web-specific: browser emulation, network
│                                 speed sim, cache, non-HTML resources
├── run-lr-scenario.ps1         — Executes via lr_batch.exe · polls · computes
│                                 P90/P95/P98/P99 · writes summary.json
├── validate-sla.ps1            — Post-test SLA check: log_only / warn_and_log
│                                 / fail_job — test NEVER stopped mid-run
├── push_metrics.py             — Universal APM dispatcher (7 tools)
├── fetch_apm_metrics.py        — Fetches live metrics at dashboard deploy time
└── update_dashboard.py         — Appends run record (all percentiles + TPH)

configs/
├── project.json                — APM tool selection · default run settings
├── sla-load.json               — SLA thresholds: RT percentiles, error rate, TPH
└── sla-{smoke,stress,spike,endurance,web-load}.json

dashboard/                      → GitHub Pages (public, no login)
├── index.html                  — Chart.js · light/dark · AI analysis · CSV/Excel export
└── data.json                   — Auto-updated after every test run
```

---

## Key features

### Scenario control — equivalent to Performance Centre UI

Every setting you'd configure manually in MicroFocus Performance Centre is now a GitHub Actions workflow input:

| Category | Options |
| --- | --- |
| **Scheduler** | `real_world` (ramp/steady/ramp-down) · `goal_oriented` (LR auto-scales VUsers to hit TPH target) · `basic` |
| **Think time** | `as_recorded` · `ignore` · `multiply` · `random_percentage` · `fixed_seconds` |
| **Pacing** | `immediately` · `fixed_delay` · `random_delay` · `fixed_from_iteration_start` · `random_from_iteration_start` |
| **Throughput** | TPH-native — formula built in: `3600 ÷ target_TPH = pacing_seconds` |
| **Browser** (Web) | Chrome · Firefox · IE11 · Android · iOS |
| **Network** (Web) | Unlimited · Cable · DSL · GPRS · Modem |
| **SLA breach** | `log_only` · `warn_and_log` · `fail_job` |
| **APM tool** | Choose at run time — credentials auto-injected from secrets |

### 7-APM integration — one config line switches everything

Set `apm.tool` in `configs/project.json` once. Every subsequent run pushes metrics to that tool automatically. Switch tools by changing one line — no workflow changes needed.

| Tool | Market position | Metric format |
| --- | --- | --- |
| **Datadog** | 51% market share · cloud-native leader | `loadrunner.*` series API v2 |
| **Dynatrace** | Gartner Leader 15 consecutive years | MINT line format · events/ingest |
| **AppDynamics** | Cisco · enterprise Java/.NET | Custom Metrics REST API |
| **New Relic** | Full-stack · GB-based pricing | Metric API + NerdGraph NRQL |
| **Splunk** | Log-heavy · SignalFx backend | SignalFlow ingest |
| **Elastic APM** | Open-source · Elasticsearch | ES index + APM intake |
| **Grafana Cloud** | Prometheus-native · OSS-first | Remote write (Prom format) |

### Dashboard — live, public, no login

→ **[niyartalukdar.github.io/Hermes-Automation](https://niyartalukdar.github.io/Hermes-Automation/)**

- **Percentile selector** — Avg / P90 / P95 / P98 / P99 (P90 default)
- **Human-readable metrics table** — PASS / WARN / BREACH status per metric with mini bar charts
- **Per-run percentile breakdown** — all percentiles side-by-side for every run
- **Date navigation** — Today / Yesterday / This week / Last month / Same day last month / Same day last year / Last 90 days
- **Export** — CSV and Excel (all percentiles included) from every tab
- **AI Analysis** — Claude Sonnet powered; scope by latest / last 5 / last 10 / all runs; 9 quick prompts + free-text
- **APM live panel** — fetches real metrics from your integrated tool at deploy time, displays inline
- **Light / Dark mode** — toggle persists in localStorage; charts redraw dynamically

### SLA validation — post-test, configurable breach behaviour

The test **always runs to completion**. SLA checks run after. Three breach modes:

```
log_only      → violations logged, job always exits 0
warn_and_log  → GitHub ⚠️ annotations, job exits 0
fail_job      → violations logged, job exits 1
```

Per-transaction thresholds supported alongside global thresholds.

---

## Repo structure

```
Hermes-Automation/
├── .github/
│   └── workflows/
│       ├── lr-api-performance.yml
│       ├── lr-web-performance.yml
│       └── publish-dashboard.yml
├── scripts/
│   ├── configure-api-scenario.ps1
│   ├── configure-web-scenario.ps1
│   ├── run-lr-scenario.ps1
│   ├── validate-sla.ps1
│   ├── push_metrics.py             ← universal APM dispatcher (7 tools)
│   ├── fetch_apm_metrics.py        ← dashboard APM data fetch
│   └── update_dashboard.py
├── configs/
│   ├── project.json                ← set your APM tool here
│   ├── sla-load.json
│   ├── sla-smoke.json
│   ├── sla-stress.json
│   ├── sla-spike.json
│   ├── sla-endurance.json
│   └── sla-web-load.json
├── dashboard/
│   ├── index.html
│   └── data.json
├── EXECUTION_GUIDE.md
├── SECRETS_SETUP.md
└── LICENSE
```

---

## Quick start

### 1. Set your APM tool

Edit `configs/project.json`:

```json
{ "apm": { "tool": "dynatrace" } }
```

Options: `datadog` · `dynatrace` · `appdynamics` · `newrelic` · `splunk` · `elastic` · `grafana` · `none`

### 2. Add secrets

See [`SECRETS_SETUP.md`](./SECRETS_SETUP.md) and [`EXECUTION_GUIDE.md`](./EXECUTION_GUIDE.md) — includes credential tables for all 7 APM tools.

**LoadRunner (always required):**

```
LR_LICENSE_SERVER   LR_CONTROLLER_HOST
LR_SCRIPT_USERNAME  LR_SCRIPT_PASSWORD
TARGET_URL_STAGING  TARGET_URL_PROD
```

**Per-user credentials (for OAuth / user-specific data):**

```
LR_USER_1_USERNAME / LR_USER_1_PASSWORD  ...up to LR_USER_N
```

Falls back to shared service account if not set.

### 3. Register self-hosted Windows runner

```
Repo → Settings → Actions → Runners → New self-hosted runner
Labels: self-hosted,loadrunner,windows
```

### 4. Enable GitHub Pages

```
Repo → Settings → Pages → Source: GitHub Actions
```

### 5. Run a test

```
Actions → LoadRunner API Performance Test → Run workflow
```

Fill in: environment, scheduler mode, VUser count, ramp-up, steady state, think time, pacing, SLA breach action, APM tool.

**Example — 1 VUser targeting 100 TPH:**

- Scheduler: `basic` · VUsers: `1`
- Pacing: `fixed_from_iteration_start` · Pacing seconds: `36` *(formula: 3600 ÷ 100 TPH = 36 seconds)*
- Think time: `ignore`

---

## Technology stack

| Layer | Technology |
| --- | --- |
| Test execution | MicroFocus LoadRunner (VuGen · lr_batch · LRE) |
| CI/CD | GitHub Actions (self-hosted Windows runner) |
| Scripting | PowerShell 5.1+ · Python 3.11 |
| APM / Observability | Datadog · Dynatrace · AppDynamics · New Relic · Splunk · Elastic · Grafana |
| Dashboard | HTML5 · Chart.js · SheetJS (Excel) · Claude Sonnet API |
| Protocols | LoadRunner API · Web HTTP/HTML |
| Deployment | GitHub Pages (static, public) |

---

## Domain context

This pipeline was designed for BFSI/Insurance workload patterns — regulated, high-availability environments where performance SLAs are contractual, not aspirational. Test scenario designs cover:

- Authentication and identity (ADB2C, OAuth flows)
- Policy management and rating APIs
- Claims processing and document services
- Modernisation workloads migrating from legacy to cloud-native

SLA thresholds, TPH targets, and error budgets reflect real BFSI non-functional requirements.

---

## License

MIT — fork and adapt freely.
