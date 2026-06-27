# Hermes-Automation — End-to-End Execution Guide

---

## Step 1 — One-time project setup

### 1A. Set your APM tool (do this once, not every run)

Edit `configs/project.json` and set your integrated APM tool:

```json
{
  "apm": {
    "tool": "dynatrace"
  }
}
```

Valid values: `datadog` `dynatrace` `appdynamics` `newrelic` `splunk` `elastic` `grafana` `none`

The publish-dashboard workflow reads this automatically. Your dashboard will
show that tool's panel without you having to select it every run.

### 1B. Add required secrets for your APM tool

Go to **Repo → Settings → Secrets and variables → Actions**

| Tool | Secrets needed |
|------|---------------|
| Dynatrace | `DT_ENVIRONMENT_ID`, `DT_API_TOKEN` |
| Datadog | `DD_API_KEY`, `DD_APP_KEY`, `DD_SITE` |
| AppDynamics | `APPDYNAMICS_CONTROLLER_URL`, `APPDYNAMICS_ACCOUNT_NAME`, `APPDYNAMICS_API_KEY`, `APPDYNAMICS_APP_ID` |
| New Relic | `NEWRELIC_API_KEY`, `NEWRELIC_ACCOUNT_ID`, `NEWRELIC_REGION` |
| Splunk | `SPLUNK_ACCESS_TOKEN`, `SPLUNK_REALM` |
| Elastic | `ELASTIC_ES_URL`, `ELASTIC_API_KEY` |
| Grafana | `GRAFANA_PROMETHEUS_URL`, `GRAFANA_PROMETHEUS_USER`, `GRAFANA_API_KEY` |

Also add LoadRunner secrets (required for all runs):
```
LR_LICENSE_SERVER        → hostname of your LR license server
LR_CONTROLLER_HOST       → hostname of LR controller machine
LR_SCRIPT_USERNAME       → LR Controller login username
LR_SCRIPT_PASSWORD       → LR Controller login password
TARGET_URL_DEV           → base URL for dev environment
TARGET_URL_STAGING       → base URL for staging environment
TARGET_URL_PROD          → base URL for production environment
```

### 1C. Register your Windows LoadRunner runner

On the machine where LoadRunner Enterprise is installed:

1. Go to **Repo → Settings → Actions → Runners → New self-hosted runner**
2. Select **Windows**
3. Run the config commands shown
4. When prompted for labels, enter exactly: `self-hosted,loadrunner,windows`
5. Install as a Windows service so it survives reboots:
   ```powershell
   .\svc.sh install
   .\svc.sh start
   ```
6. Set this environment variable on the runner machine:
   ```powershell
   [System.Environment]::SetEnvironmentVariable(
     "LR_INSTALL_DIR",
     "C:\Program Files\Micro Focus\LoadRunner",
     "Machine"
   )
   ```

### 1D. Place your LR scripts in the repo

```
scripts/
  api/
    load.lrs          ← your API protocol scenario file
    smoke.lrs
    stress.lrs
  web/
    load.lrs          ← your Web HTTP/HTML scenario file
    smoke.lrs
    stress.lrs
```

---

## Step 2 — Configure SLA thresholds

Edit `configs/sla-load.json` (and the web/smoke/stress variants).
These are checked POST-TEST — they never stop the test mid-run.

```json
{
  "thresholds": {
    "avg_response_time_ms":  { "warn": 1500,  "fail": 2000  },
    "p95_response_time_ms":  { "warn": 3000,  "fail": 4500  },
    "error_rate_percent":    { "warn": 0.5,   "fail": 1.0   },
    "throughput_tps":        { "warn_below": 20, "fail_below": 10 }
  },
  "transactions": [
    {
      "name": "Login",
      "avg_response_time_ms": { "warn": 800, "fail": 1200 },
      "error_rate_percent":   { "warn": 0.1, "fail": 0.5  }
    }
  ]
}
```

Transaction names must match exactly what you named them in your LR script.

---

## Step 3 — Run the workflow

Go to **Actions → LoadRunner Web HTTP/HTML Performance Test → Run workflow**

### Scheduler settings (Performance Centre equivalent)

| Field | What it controls | PC equivalent |
|-------|-----------------|---------------|
| `scheduler_mode` | `real_world` = ramp up → steady → ramp down | PC "Real World Schedule" |
| `vuser_count` | Number of virtual users | Group VUser count |
| `ramp_up_minutes` | Time to reach full VUser load | "Gradually start X users over Y minutes" |
| `steady_state_minutes` | Duration at full load | Schedule duration |
| `ramp_down_minutes` | Time to stop all VUsers | "Gradually stop all VUsers" |

For **goal-oriented** (LR finds VUser count automatically):
- Set `scheduler_mode` = `goal_oriented`
- Set `goal_metric` = `transactions_per_second`
- Set `goal_value` = e.g. `50` (target 50 TPS)
- Set `goal_max_vusers` = e.g. `300` (ceiling)

### Think time settings

| Mode | Behaviour | Use when |
|------|-----------|----------|
| `as_recorded` | Use delays recorded in VuGen | Realistic simulation |
| `ignore` | No think time at all | Maximum stress / finding limits |
| `multiply` | Scale recorded time by factor | e.g. `0.5` = half the delay |
| `random_percentage` | Random % of recorded (set `think_time_range`) | Realistic variation |
| `fixed_seconds` | Fixed delay regardless of recording | Precise control |

**Think time range** (random_percentage mode): enter as `MIN-MAX` e.g. `50-150`
means random between 50% and 150% of recorded think time.

### Pacing settings

| Mode | Behaviour |
|------|-----------|
| `immediately` | Next iteration starts right after current ends |
| `fixed_delay` | Wait N seconds between iterations |
| `random_delay` | Wait random time between min and max seconds |
| `fixed_from_iteration_start` | Fixed time from start of previous iteration (controls TPS precisely) |
| `random_from_iteration_start` | Random time from start of previous iteration |

> **To control TPS:** use `fixed_from_iteration_start` with `pacing_min_seconds`.
> Example: to target 10 TPS with 50 VUsers, set pacing to `fixed_from_iteration_start`
> with 5 seconds (50 VUsers ÷ 10 TPS = 5s per iteration start).

### SLA breach action

| Option | What happens when SLA breaches |
|--------|-------------------------------|
| `log_only` | Violations printed to log + Step Summary. **Job always passes.** Test ran to completion. |
| `warn_and_log` | Violations shown as GitHub ⚠️ annotations. **Job always passes.** |
| `fail_job` | Violations logged + **job is marked ❌ failed** (test already completed). |

> The test is **never stopped mid-run** by SLA validation.
> SLA checks run after the test completes.
> To stop LR mid-run on breach, configure SLA actions inside the .lrs file in LR Controller.

### APM tool

Leave this as the default from `configs/project.json` unless you want to
override for a specific run.

---

## Step 4 — Monitor the run

### Pipeline stages

```
✅ Pre-flight Checks       (resolves all parameters, prints config table)
       ↓
📡 Mark Test Start (APM)   (posts annotation to your APM tool — non-blocking)
       ↓
⚡ Execute Load Test        (runs on your Windows LR runner)
   ├── Authenticate with LR Controller (using LR_SCRIPT_USERNAME/PASSWORD)
   ├── configure-web-scenario.ps1 (patches .lrs with all runtime settings)
   ├── run-lr-scenario.ps1 (executes via lr_batch.exe, polls until done)
   ├── validate-sla.ps1 (compares results vs SLA — never stops the test)
   └── uploads results artifact
       ↓
📊 Publish Metrics (APM)   (pushes LR metrics to your APM tool)
   ├── push_metrics.py --tool <your_tool>
   └── update_dashboard.py (appends run to dashboard/data.json)
```

### While the test runs — watch in LR Enterprise

The test still shows in LoadRunner Enterprise UI as normal:
- Open LR Enterprise → Controller → your scenario
- You'll see VUser ramp, transaction monitor, error counts in real time
- Nothing changes in how LR runs — the CI/CD pipeline just triggers it remotely

---

## Step 5 — View results

### GitHub Actions Step Summary

After the run, click the workflow run → **Summary** tab. You'll see:
- Full configuration table (scheduler, think time, pacing, etc.)
- SLA validation results with every metric checked
- Breach/warning list with actual vs threshold values
- Direct link to the dashboard

### Dashboard (GitHub Pages)

```
https://niyartalukdar.github.io/Hermes-Automation/
```

- **Overview tab** — LR KPI cards + APM snapshot for your integrated tool
- **APM tab** — Full metric panel for your tool (auto-named e.g. "🔷 Dynatrace")
- **Run History tab** — All test runs with SLA pass/fail

### In your APM tool

Your LR metrics appear under:
- **Dynatrace**: Metrics → `performance.loadrunner.*`
- **Datadog**: Metrics → `loadrunner.*`
- **AppDynamics**: Custom Metrics → `Custom Metrics|LoadRunner|<PROTOCOL>|*`
- **New Relic**: Query `FROM Metric SELECT * WHERE metricName LIKE 'loadrunner.%'`
- **Splunk**: Metrics → `loadrunner.*`
- **Elastic**: Index `loadrunner-metrics` in Kibana
- **Grafana**: Prometheus → `loadrunner_*`

A `CUSTOM_ANNOTATION` / deployment event is also posted at test start and end,
so you can overlay the LR test window on your APM dashboards.

---

## Step 6 — SLA violations in the log

Example output when SLA breaches with `log_only`:

```
── SLA Validation [WEB] ─────────────────────────────────────
   Results  : results/12345/summary.json
   SLA file : configs/sla-web-load.json

── Global Thresholds
  ✅ PASS  Avg Response Time (ms) = 1240 (limit: 2000)
  🚨 BREACH P95 Response Time (ms) = 5100 (threshold: 4500)
  ⚠️  WARN  Error Rate (%) = 0.72 (warn threshold: 0.5)
  ✅ PASS  Throughput (TPS) = 34 (min: 10)

── Per-Transaction Thresholds
  ✅ PASS  [Login] Avg RT (ms) = 680 (limit: 1200)
  🚨 BREACH [Checkout] P95 RT (ms) = 6200 (threshold: 3500)

── Result
  🚨 2 SLA breach(es) detected, 1 warning(s)
  Breach action: log_only
  ℹ️  Violations logged only — job continues (breach action: log_only)
```

The `sla-violations.json` file is saved in the results artifact for every run.

---

## Quick reference — changing APM tool

To switch from Dynatrace to New Relic:

1. Edit `configs/project.json`:
   ```json
   { "apm": { "tool": "newrelic" } }
   ```
2. Add New Relic secrets (`NEWRELIC_API_KEY`, `NEWRELIC_ACCOUNT_ID`)
3. Commit and push → dashboard auto-redeploys showing New Relic panel
4. Next workflow run automatically pushes metrics to New Relic

No workflow file changes needed. One line in `project.json` switches everything.

