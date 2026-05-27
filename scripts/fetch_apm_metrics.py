#!/usr/bin/env python3
"""
fetch_apm_metrics.py
Fetches live infrastructure + application metrics from Dynatrace and AppDynamics
and writes dashboard/apm-metrics.json so the static dashboard can display them
without exposing API tokens in the browser.

Called by the GitHub Actions publish-dashboard workflow before deploying Pages.
"""

import argparse
import json
import sys
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta

# ── Dynatrace helpers ──────────────────────────────────────────────────────────

def dt_get(env_id: str, token: str, path: str, params: dict = None) -> dict:
    url = f"https://{env_id}.live.dynatrace.com/api/v2/{path}"
    if params:
        qs = "&".join(f"{k}={urllib.parse.quote(str(v))}" for k, v in params.items())
        url = f"{url}?{qs}"
    req = urllib.request.Request(url, headers={"Authorization": f"Api-Token {token}"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read())
    except Exception as e:
        print(f"  ⚠️  DT {path}: {e}", file=sys.stderr)
        return {}

import urllib.parse

def fetch_dynatrace(env_id: str, token: str) -> dict:
    print("  📡 Fetching Dynatrace metrics…")
    now_ms   = int(datetime.now(timezone.utc).timestamp() * 1000)
    hour_ms  = now_ms - 3_600_000        # last 1 hour
    day_ms   = now_ms - 86_400_000       # last 24 hours

    # ── Service error rate (last 1h) ──
    err = dt_get(env_id, token, "metrics/query", {
        "metricSelector": "builtin:service.errors.total.rate:avg",
        "resolution":     "1h",
        "from":           hour_ms,
        "to":             now_ms,
    })
    error_rate = _dt_scalar(err, 0.0)

    # ── Service response time p95 (last 1h) ──
    rt = dt_get(env_id, token, "metrics/query", {
        "metricSelector": "builtin:service.response.time:percentile(95)",
        "resolution":     "1h",
        "from":           hour_ms,
        "to":             now_ms,
    })
    response_time_p95_us = _dt_scalar(rt, 0.0)
    response_time_p95_ms = round(response_time_p95_us / 1000, 1)

    # ── Throughput (requests/min, last 1h) ──
    thr = dt_get(env_id, token, "metrics/query", {
        "metricSelector": "builtin:service.requestCount.total:sum",
        "resolution":     "1h",
        "from":           hour_ms,
        "to":             now_ms,
    })
    throughput = _dt_scalar(thr, 0.0)

    # ── CPU usage (last 1h) ──
    cpu = dt_get(env_id, token, "metrics/query", {
        "metricSelector": "builtin:host.cpu.usage:avg",
        "resolution":     "1h",
        "from":           hour_ms,
        "to":             now_ms,
    })
    cpu_pct = round(_dt_scalar(cpu, 0.0), 1)

    # ── Memory usage (last 1h) ──
    mem = dt_get(env_id, token, "metrics/query", {
        "metricSelector": "builtin:host.mem.usage:avg",
        "resolution":     "1h",
        "from":           hour_ms,
        "to":             now_ms,
    })
    mem_pct = round(_dt_scalar(mem, 0.0), 1)

    # ── Response time trend (last 24h, hourly) for sparkline ──
    trend_raw = dt_get(env_id, token, "metrics/query", {
        "metricSelector": "builtin:service.response.time:percentile(95)",
        "resolution":     "1h",
        "from":           day_ms,
        "to":             now_ms,
    })
    trend = _dt_trend(trend_raw, divisor=1000)   # µs → ms

    # ── Active problems ──
    problems = dt_get(env_id, token, "problems", {"problemSelector": "status(OPEN)"})
    open_problems = problems.get("totalCount", 0)

    # ── LR custom metrics (pushed by our pipeline) ──
    lr_rt = dt_get(env_id, token, "metrics/query", {
        "metricSelector": "performance.loadrunner.response_time.avg:avg",
        "resolution":     "1h",
        "from":           day_ms,
        "to":             now_ms,
    })
    lr_err = dt_get(env_id, token, "metrics/query", {
        "metricSelector": "performance.loadrunner.error_rate_percent:avg",
        "resolution":     "1h",
        "from":           day_ms,
        "to":             now_ms,
    })
    lr_tps = dt_get(env_id, token, "metrics/query", {
        "metricSelector": "performance.loadrunner.throughput_tps:avg",
        "resolution":     "1h",
        "from":           day_ms,
        "to":             now_ms,
    })

    return {
        "source":               "dynatrace",
        "fetched_at":           datetime.now(timezone.utc).isoformat(),
        "env_id":               env_id,
        "dashboard_url":        f"https://{env_id}.live.dynatrace.com",
        "service_error_rate":   round(error_rate, 3),
        "response_time_p95_ms": response_time_p95_ms,
        "throughput_rpm":       round(throughput, 1),
        "cpu_usage_pct":        cpu_pct,
        "memory_usage_pct":     mem_pct,
        "open_problems":        open_problems,
        "response_time_trend":  trend,
        "lr_avg_rt_trend":      _dt_trend(lr_rt),
        "lr_error_rate_trend":  _dt_trend(lr_err),
        "lr_tps_trend":         _dt_trend(lr_tps),
    }


def _dt_scalar(data: dict, default=0.0) -> float:
    try:
        series = data["resolution"]["results"][0]["data"]
        vals = [v for v in series if v is not None]
        return vals[-1] if vals else default
    except Exception:
        return default


def _dt_trend(data: dict, divisor=1.0) -> list:
    try:
        series = data["resolution"]["results"][0]["data"]
        return [round((v or 0) / divisor, 2) for v in series]
    except Exception:
        return []


# ── AppDynamics helpers ────────────────────────────────────────────────────────

def apd_get(controller: str, account: str, api_key: str, path: str) -> dict:
    import base64
    creds = base64.b64encode(f"{account}@{account}:{api_key}".encode()).decode()
    url = f"{controller}/controller/{path}"
    req = urllib.request.Request(url, headers={
        "Authorization": f"Basic {creds}",
        "Content-Type":  "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read())
    except Exception as e:
        print(f"  ⚠️  AppD {path}: {e}", file=sys.stderr)
        return {}


def fetch_appdynamics(controller: str, account: str, api_key: str, app_id: str) -> dict:
    print("  📡 Fetching AppDynamics metrics…")
    now_ms  = int(datetime.now(timezone.utc).timestamp() * 1000)
    hour_ms = now_ms - 3_600_000

    def metric(path_segment: str):
        """Fetch a single AppDynamics metric value (last 60 min)."""
        encoded = urllib.parse.quote(path_segment, safe="")
        data = apd_get(controller, account, api_key,
            f"rest/applications/{app_id}/metric-data?"
            f"metric-path={encoded}&time-range-type=BEFORE_NOW"
            f"&duration-in-mins=60&rollup=true&output=JSON")
        try:
            return data[0]["metricValues"][0]["value"]
        except Exception:
            return 0

    def metric_timeseries(path_segment: str, points=24):
        """Fetch hourly timeseries for a metric (last 24h)."""
        encoded = urllib.parse.quote(path_segment, safe="")
        data = apd_get(controller, account, api_key,
            f"rest/applications/{app_id}/metric-data?"
            f"metric-path={encoded}&time-range-type=BEFORE_NOW"
            f"&duration-in-mins=1440&rollup=false&output=JSON")
        try:
            values = data[0]["metricValues"]
            return [v["value"] for v in values[-points:]]
        except Exception:
            return []

    # Standard AppDynamics metric paths
    avg_rt         = metric("Overall Application Performance|Average Response Time (ms)")
    error_rate     = metric("Overall Application Performance|Error Rate")
    calls_per_min  = metric("Overall Application Performance|Calls per Minute")
    cpu_busy       = metric("Infrastructure|JVM|Process CPU Busy (%)")
    heap_used      = metric("Infrastructure|JVM|Heap Used (MB)")

    # Violations / health rule violations (open)
    violations = apd_get(controller, account, api_key,
        f"rest/applications/{app_id}/policy-violations?"
        f"time-range-type=BEFORE_NOW&duration-in-mins=60&output=JSON")
    open_violations = len(violations) if isinstance(violations, list) else 0

    # LR custom metrics
    lr_avg_rt  = metric_timeseries("Custom Metrics|LoadRunner|API|Average Response Time (ms)")
    lr_err_rt  = metric_timeseries("Custom Metrics|LoadRunner|API|Error Rate Percent")
    lr_tps     = metric_timeseries("Custom Metrics|LoadRunner|API|Throughput TPS")

    return {
        "source":               "appdynamics",
        "fetched_at":           datetime.now(timezone.utc).isoformat(),
        "controller_url":       controller,
        "dashboard_url":        f"{controller}/controller/#/location=APP_DASHBOARD&timeRange=last_1_hour.BEFORE_NOW.-1.-1.60&application={app_id}",
        "avg_response_time_ms": round(avg_rt, 1),
        "error_rate_pct":       round(error_rate, 3),
        "calls_per_min":        round(calls_per_min, 1),
        "cpu_busy_pct":         round(cpu_busy, 1),
        "heap_used_mb":         round(heap_used, 1),
        "open_violations":      open_violations,
        "lr_avg_rt_trend":      lr_avg_rt,
        "lr_error_rate_trend":  lr_err_rt,
        "lr_tps_trend":         lr_tps,
    }


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Fetch APM metrics for dashboard")
    parser.add_argument("--dt-env-id",       default="")
    parser.add_argument("--dt-token",        default="")
    parser.add_argument("--apd-controller",  default="")
    parser.add_argument("--apd-account",     default="")
    parser.add_argument("--apd-api-key",     default="")
    parser.add_argument("--apd-app-id",      default="")
    parser.add_argument("--output",          default="dashboard/apm-metrics.json")
    args = parser.parse_args()

    result = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "dynatrace":    None,
        "appdynamics":  None,
    }

    if args.dt_env_id and args.dt_token:
        try:
            result["dynatrace"] = fetch_dynatrace(args.dt_env_id, args.dt_token)
            print("  ✅ Dynatrace metrics fetched")
        except Exception as e:
            print(f"  ❌ Dynatrace fetch failed: {e}", file=sys.stderr)
            result["dynatrace"] = {"error": str(e)}
    else:
        print("  ⏭️  Dynatrace skipped (no credentials)")

    if args.apd_controller and args.apd_api_key:
        try:
            result["appdynamics"] = fetch_appdynamics(
                args.apd_controller, args.apd_account,
                args.apd_api_key, args.apd_app_id
            )
            print("  ✅ AppDynamics metrics fetched")
        except Exception as e:
            print(f"  ❌ AppDynamics fetch failed: {e}", file=sys.stderr)
            result["appdynamics"] = {"error": str(e)}
    else:
        print("  ⏭️  AppDynamics skipped (no credentials)")

    import os
    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    with open(args.output, "w") as f:
        json.dump(result, f, indent=2)
    print(f"\n✅ Written → {args.output}")


if __name__ == "__main__":
    main()
