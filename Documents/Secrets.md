# GitHub Secrets & Variables Setup Guide

All sensitive values are stored as **GitHub Actions Secrets** (encrypted).
Non-sensitive config goes in **Repository Variables** (plain text, visible in logs).

---

## Required Secrets

Navigate to: `Repo → Settings → Secrets and variables → Actions → New repository secret`

### LoadRunner Infrastructure
| Secret Name              | Description                                       | Example Value               |
|--------------------------|---------------------------------------------------|-----------------------------|
| `LR_LICENSE_SERVER`      | Hostname/IP of the LR License Server              | `lr-license.corp.internal`  |
| `LR_CONTROLLER_HOST`     | Hostname of the LR Controller machine             | `lr-ctrl-01.corp.internal`  |
| `LR_SCRIPT_USERNAME`     | Default service account for LR Controller auth    | `svc_loadrunner`            |
| `LR_SCRIPT_PASSWORD`     | Password for the default service account          | `***`                       |

### Per-User Credentials (Individual Logins for Test Scripts)
For scripts requiring individual user sessions (OAuth, MFA, per-user data):
```
LR_USER_1_USERNAME   →  testuser001@example.com
LR_USER_1_PASSWORD   →  ***
LR_USER_2_USERNAME   →  testuser002@example.com
LR_USER_2_PASSWORD   →  ***
...
LR_USER_50_USERNAME  →  testuser050@example.com
LR_USER_50_PASSWORD  →  ***
```
> These are injected into the LoadRunner parameter file at runtime and cycle across VUsers.
> Provision users in your test environment's IAM/AD before running tests.

### Target Environment URLs
| Secret Name           | Description                  |
|-----------------------|------------------------------|
| `TARGET_URL_DEV`      | Base URL for dev environment |
| `TARGET_URL_STAGING`  | Base URL for staging         |
| `TARGET_URL_PROD`     | Base URL for production      |

### Dynatrace
| Secret Name         | Description                                       |
|---------------------|---------------------------------------------------|
| `DT_ENVIRONMENT_ID` | Your Dynatrace environment ID (e.g. `abc12345`)   |
| `DT_API_TOKEN`      | API token with `metrics.ingest`, `events.ingest`  |

**Dynatrace API Token Scopes required:**
- `metrics.ingest`
- `events.ingest`
- `DataExport` (for reading back metrics in dashboards)

### AppDynamics
| Secret Name                  | Description                             |
|------------------------------|-----------------------------------------|
| `APPDYNAMICS_CONTROLLER_URL` | Full controller URL (no trailing slash) |
| `APPDYNAMICS_ACCOUNT_NAME`   | AppDynamics account name                |
| `APPDYNAMICS_API_KEY`        | AppDynamics API key                     |
| `APPDYNAMICS_APP_ID`         | Numeric Application ID                  |

### Notifications
| Secret Name        | Description                          |
|--------------------|--------------------------------------|
| `SLACK_WEBHOOK_URL`| Incoming webhook URL for Slack alerts|

---

## Repository Variables (non-sensitive)

Navigate to: `Repo → Settings → Secrets and variables → Actions → Variables tab`

| Variable Name          | Description                         | Default   |
|------------------------|-------------------------------------|-----------|
| `DEFAULT_VUSERS`       | Default VUser count                 | `50`      |
| `DEFAULT_DURATION_MIN` | Default test duration (minutes)     | `10`      |
| `DASHBOARD_PUBLIC_URL` | Public URL of your GitHub Pages site| *(set me)*|

---

## Self-Hosted Runner Setup

LoadRunner requires a Windows runner with LoadRunner installed.

### Runner Labels Required
```
self-hosted, loadrunner, windows
```

### Installation
```powershell
# On your Windows LR machine:
# 1. Go to Repo → Settings → Actions → Runners → New self-hosted runner
# 2. Select Windows, copy the config commands
# 3. During ./config.cmd, enter labels: self-hosted,loadrunner,windows
# 4. Install as a service: ./svc.sh install && ./svc.sh start

# Required environment variables on the runner machine:
[System.Environment]::SetEnvironmentVariable("LR_INSTALL_DIR", "C:\Program Files\Micro Focus\LoadRunner", "Machine")
```

### Runner machine requirements
- Windows Server 2019+ or Windows 10+
- LoadRunner 2023+ installed and licensed
- PowerShell 5.1+
- Python 3.9+ (for result parsing scripts)
- Network access to LR Controller and License Server
- Outbound HTTPS to Dynatrace and AppDynamics

---

## Dashboard Access (Public / No Login Required)

The performance dashboard is published to **GitHub Pages** — no authentication needed,
no login, accessible by anyone with the URL (or restricted to your org if the repo is private).

```
https://<org>.github.io/<repo>/
```

---

### Step 1 — Enable GitHub Pages

1. Go to your repository on GitHub
2. Click **Settings** (top navigation bar, far right)
3. In the left sidebar scroll down to **Pages** (under the *Code and automation* section)
4. Under **Build and deployment → Source**, select **GitHub Actions** *(not "Deploy from a branch")*
   - This is required because the pipeline uses the `actions/deploy-pages` action, not a branch commit

> **Why "GitHub Actions" source?**
> The `publish-dashboard.yml` workflow uses `actions/upload-pages-artifact` +
> `actions/deploy-pages`, which is the modern Pages deployment method.
> If you select "Deploy from a branch" instead, the workflow will upload
> the artifact but the actual deployment step will fail with a 404.

---

### Step 2 — Grant Pages write permissions to Actions

The deploy workflow needs two permissions that are off by default on new repos:

1. Go to **Settings → Actions → General**
2. Scroll to **Workflow permissions**
3. Select **Read and write permissions**
4. Tick **Allow GitHub Actions to create and approve pull requests** (needed for the pages token)
5. Click **Save**

Alternatively, these permissions are declared per-workflow in `publish-dashboard.yml`:
```yaml
permissions:
  contents: read
  pages: write
  id-token: write
```
GitHub still requires the repo-level setting to allow them.

---

### Step 3 — Add the `github-pages` environment (auto-created on first deploy)

GitHub Pages deployments use a protected environment called `github-pages`.
It is created automatically the first time `actions/deploy-pages` runs successfully.

If you want to add protection rules (e.g. require a manual approval before publishing):
1. Go to **Settings → Environments → github-pages**
2. Add required reviewers or branch protection rules as needed

---

### Step 4 — Trigger your first deployment

Either:
- Push any change to `dashboard/` on `main`, **or**
- Go to **Actions → Publish Dashboard to GitHub Pages → Run workflow**

After ~30 seconds, the Pages URL will appear in:
- The workflow run summary (under the deploy step output)
- **Settings → Pages** (shown as *"Your site is live at …"*)

---

### Step 5 — Verify the dashboard loads correctly

Open the URL in a private/incognito window to confirm it loads without login.

**Expected URL pattern:**
```
https://<your-org>.github.io/<your-repo>/
```

**What you should see:**
- Dark-themed dashboard with stat cards (Avg RT, Error Rate, TPS, SLA Pass Rate)
- Response time trend chart with SLA limit line
- Run history table with PASS/FAIL badges
- Dynatrace and AppDynamics quick-link cards at the bottom

---

### Troubleshooting

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| Deploy step says `Error: HttpError: Not Found` | Pages not enabled | Complete Step 1 above |
| Deploy step says `Error: Artifact not found` | `upload-pages-artifact` step failed | Check that `dashboard/` folder exists and isn't empty |
| Dashboard loads but shows "Could not load data.json" | `data.json` missing from the `dashboard/` folder | Run any test workflow once — it commits `data.json` after results are parsed |
| Dashboard URL returns 404 | Pages source set to "branch" instead of "GitHub Actions" | Change source to **GitHub Actions** in Settings → Pages |
| Org repo shows login prompt | Repo visibility is Private | Either make the repo public, or use GitHub Pages with GitHub Enterprise (requires licence) |
| Charts show no data after filtering | All runs filtered out | Reset filters — try Protocol: All, Environment: All |

---

### Private repos and access control

If the repo is **private**, GitHub Pages is only available on **GitHub Enterprise** plans.
For private repos on free/Team plans, consider one of these alternatives:

- Host `dashboard/index.html` + `data.json` on **Azure Static Web Apps** (free tier)
- Use **AWS S3 + CloudFront** with the `update_dashboard.py` script uploading to a bucket
- Self-host via **Nginx** on your internal network and push files via SCP in the workflow

The dashboard is a single HTML file + a JSON file — it runs anywhere that serves static files.

---

## APM Tool Secrets — configure only the tool you choose

Only the secrets for your **selected APM tool** need to be set.
All others can be left empty or omitted entirely.

---

### 🟣 Datadog (51% market share — cloud-native leader)
| Secret | Description | Where to get it |
|--------|-------------|-----------------|
| `DD_API_KEY` | Datadog API key | Organization Settings → API Keys |
| `DD_APP_KEY` | Datadog Application key (for read queries) | Organization Settings → Application Keys |
| `DD_SITE` | Datadog site (default: `datadoghq.com`) | `datadoghq.com` / `datadoghq.eu` / `us3.datadoghq.com` |

---

### 🔷 Dynatrace (Gartner Leader 15 consecutive years)
| Secret | Description | Where to get it |
|--------|-------------|-----------------|
| `DT_ENVIRONMENT_ID` | Your DT environment ID (e.g. `abc12345`) | From your DT URL: `https://<ID>.live.dynatrace.com` |
| `DT_API_TOKEN` | API token | Settings → Access Tokens → Generate token |

**Required token scopes:** `metrics.ingest`, `events.ingest`, `metrics.read`

---

### 🌀 AppDynamics (Cisco — enterprise Java/.NET)
| Secret | Description |
|--------|-------------|
| `APPDYNAMICS_CONTROLLER_URL` | Full controller URL (no trailing slash) |
| `APPDYNAMICS_ACCOUNT_NAME` | Account name |
| `APPDYNAMICS_API_KEY` | API key (Settings → API Keys) |
| `APPDYNAMICS_APP_ID` | Numeric application ID |

---

### 🟢 New Relic (24% system admin market share)
| Secret | Description | Where to get it |
|--------|-------------|-----------------|
| `NEWRELIC_API_KEY` | User API key (starts with `NRAK-`) | API Keys → Create key → User |
| `NEWRELIC_ACCOUNT_ID` | Numeric account ID | Account Settings → top of page |
| `NEWRELIC_REGION` | `US` or `EU` | Based on your data center |

---

### 🔴 Splunk Observability Cloud (SignalFx)
| Secret | Description | Where to get it |
|--------|-------------|-----------------|
| `SPLUNK_ACCESS_TOKEN` | Ingest + API access token | Settings → Access Tokens |
| `SPLUNK_REALM` | Your realm (e.g. `us0`, `us1`, `eu0`) | Settings → Organizations → Realm |

---

### 🟡 Elastic APM / Elasticsearch
| Secret | Description | Notes |
|--------|-------------|-------|
| `ELASTIC_ES_URL` | Elasticsearch URL (e.g. `https://xxx.es.io:9243`) | Elastic Cloud → Deployment → Copy endpoint |
| `ELASTIC_API_KEY` | Base64 Elastic API key | Kibana → Stack Management → API Keys |
| `ELASTIC_APM_SERVER_URL` | APM Server URL | Elastic Cloud → Deployment → APM |
| `ELASTIC_APM_SECRET_TOKEN` | APM secret token | Same location |
| `ELASTIC_ES_INDEX` | Index name (default: `loadrunner-metrics`) | Optional |

---

### 📈 Grafana Cloud (Prometheus remote write)
| Secret | Description | Where to get it |
|--------|-------------|-----------------|
| `GRAFANA_PROMETHEUS_URL` | Prometheus remote_write URL | Grafana Cloud → Stack → Prometheus → Details |
| `GRAFANA_PROMETHEUS_USER` | Prometheus instance ID (numeric) | Same page |
| `GRAFANA_API_KEY` | Grafana Cloud API key | Grafana Cloud → Security → API Keys |

---

## APM Tool Quick Comparison

| Tool | Best for | Pricing | Self-hosted? |
|------|----------|---------|--------------|
| **Datadog** | Cloud-native, Kubernetes, full-stack | Per-host | ❌ |
| **Dynatrace** | AI root-cause, enterprise scale | Per-host | ✅ (Managed) |
| **AppDynamics** | Java/.NET enterprise, business transactions | Per-CPU core | ✅ (On-prem) |
| **New Relic** | Full-stack, flexible GB-based pricing | Per GB ingest | ❌ |
| **Splunk** | Log-heavy, security + observability combined | Per host/GB | ✅ |
| **Elastic** | Open-source, self-hosted Elasticsearch stacks | Open-source free | ✅ |
| **Grafana** | Prometheus-native, OSS-first teams | Free tier available | ✅ |

