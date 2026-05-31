#!/usr/bin/env python3
"""
fetch_apm_metrics.py — Fetches live metrics from the selected APM tool
and writes dashboard/apm-metrics.json for the static dashboard to display.

Selected tool is passed via --tool argument (from GitHub Actions input).
Credentials are read from environment variables (GitHub Secrets).
"""

import argparse, json, os, sys, time, base64, urllib.request, urllib.error, urllib.parse
from datetime import datetime, timezone

NOW_MS  = int(time.time() * 1000)
DAY_MS  = NOW_MS - 86_400_000
HOUR_MS = NOW_MS - 3_600_000


def http_get(url, headers, timeout=15):
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except Exception as e:
        print(f"  ⚠️  GET {url[:60]}…: {e}", file=sys.stderr)
        return {}


# ── Datadog ────────────────────────────────────────────────────────────────────
def fetch_datadog():
    api_key = os.getenv("DD_API_KEY",""); app_key = os.getenv("DD_APP_KEY","")
    site    = os.getenv("DD_SITE","datadoghq.com")
    if not api_key: return {"error": "DD_API_KEY not set"}
    h = {"DD-API-KEY": api_key, "DD-APPLICATION-KEY": app_key}

    def query(q):
        d = http_get(f"https://api.{site}/api/v1/query?from={HOUR_MS//1000}&to={NOW_MS//1000}&query={urllib.parse.quote(q)}", h)
        try: return d["series"][0]["pointlist"][-1][1] or 0
        except: return 0

    def trend(q, pts=24):
        d = http_get(f"https://api.{site}/api/v1/query?from={DAY_MS//1000}&to={NOW_MS//1000}&query={urllib.parse.quote(q)}", h)
        try: return [round(p[1] or 0, 2) for p in d["series"][0]["pointlist"][-pts:]]
        except: return []

    # Service-level metrics
    avg_rt  = query("avg:trace.web.request.duration{*}")
    err_rt  = query("avg:trace.web.request.errors{*}")
    rps     = query("avg:trace.web.request.hits{*}.as_rate()")
    cpu     = query("avg:system.cpu.user{*}")
    mem     = query("avg:system.mem.used{*}")
    # Monitors with ALERT status
    monitors = http_get(f"https://api.{site}/api/v1/monitor?monitor_tags=env:prod&with_downtimes=false", h)
    alerts = sum(1 for m in (monitors if isinstance(monitors, list) else []) if m.get("overall_state") == "Alert")

    return {
        "tool": "datadog", "fetched_at": datetime.now(timezone.utc).isoformat(),
        "dashboard_url": f"https://app.{site}",
        "avg_response_time_ms": round(avg_rt / 1e6, 1) if avg_rt > 1000 else round(avg_rt, 1),
        "error_rate_pct": round(err_rt, 3),
        "throughput_rps": round(rps, 1),
        "cpu_usage_pct":  round(cpu, 1),
        "memory_used_mb": round(mem / 1e6, 0) if mem > 1e6 else round(mem, 0),
        "open_alerts":    alerts,
        "response_time_trend": trend("avg:trace.web.request.duration{*}"),
        "lr_avg_rt_trend":     trend("avg:loadrunner.response_time.avg{*}"),
        "lr_error_rate_trend": trend("avg:loadrunner.error_rate.percent{*}"),
        "lr_tps_trend":        trend("avg:loadrunner.throughput.tps{*}"),
    }


# ── Dynatrace ──────────────────────────────────────────────────────────────────
def fetch_dynatrace():
    env_id = os.getenv("DT_ENVIRONMENT_ID",""); token = os.getenv("DT_API_TOKEN","")
    if not env_id or not token: return {"error": "DT_ENVIRONMENT_ID / DT_API_TOKEN not set"}
    base = f"https://{env_id}.live.dynatrace.com/api/v2"
    h    = {"Authorization": f"Api-Token {token}"}

    def metric(sel, fr=HOUR_MS):
        d = http_get(f"{base}/metrics/query?metricSelector={urllib.parse.quote(sel)}&resolution=1h&from={fr}&to={NOW_MS}", h)
        try: return d["resolution"]["results"][0]["data"][-1] or 0
        except: return 0

    def trend(sel, pts=24):
        d = http_get(f"{base}/metrics/query?metricSelector={urllib.parse.quote(sel)}&resolution=1h&from={DAY_MS}&to={NOW_MS}", h)
        try: return [round((v or 0), 2) for v in d["resolution"]["results"][0]["data"][-pts:]]
        except: return []

    problems = http_get(f"{base}/problems?problemSelector=status(OPEN)", h)

    return {
        "tool": "dynatrace", "fetched_at": datetime.now(timezone.utc).isoformat(),
        "dashboard_url": f"https://{env_id}.live.dynatrace.com",
        "response_time_p95_ms": round((metric("builtin:service.response.time:percentile(95)") or 0) / 1000, 1),
        "error_rate_pct":       round(metric("builtin:service.errors.total.rate:avg") or 0, 3),
        "throughput_rpm":       round(metric("builtin:service.requestCount.total:sum") or 0, 1),
        "cpu_usage_pct":        round(metric("builtin:host.cpu.usage:avg") or 0, 1),
        "memory_usage_pct":     round(metric("builtin:host.mem.usage:avg") or 0, 1),
        "open_problems":        problems.get("totalCount", 0),
        "response_time_trend":  [round((v or 0)/1000, 1) for v in trend("builtin:service.response.time:percentile(95)")],
        "lr_avg_rt_trend":      trend("performance.loadrunner.response_time.avg:avg"),
        "lr_error_rate_trend":  trend("performance.loadrunner.error_rate_percent:avg"),
        "lr_tps_trend":         trend("performance.loadrunner.throughput_tps:avg"),
    }


# ── AppDynamics ────────────────────────────────────────────────────────────────
def fetch_appdynamics():
    ctrl = os.getenv("APPDYNAMICS_CONTROLLER_URL",""); acct = os.getenv("APPDYNAMICS_ACCOUNT_NAME","")
    key  = os.getenv("APPDYNAMICS_API_KEY","");        app  = os.getenv("APPDYNAMICS_APP_ID","")
    if not ctrl or not key: return {"error": "APPDYNAMICS_* vars not set"}
    creds = base64.b64encode(f"{acct}@{acct}:{key}".encode()).decode()
    h = {"Authorization": f"Basic {creds}", "Content-Type": "application/json"}

    def metric(path):
        enc = urllib.parse.quote(path, safe="")
        d = http_get(f"{ctrl}/controller/rest/applications/{app}/metric-data?metric-path={enc}&time-range-type=BEFORE_NOW&duration-in-mins=60&rollup=true&output=JSON", h)
        try: return d[0]["metricValues"][0]["value"]
        except: return 0

    def trend(path, pts=24):
        enc = urllib.parse.quote(path, safe="")
        d = http_get(f"{ctrl}/controller/rest/applications/{app}/metric-data?metric-path={enc}&time-range-type=BEFORE_NOW&duration-in-mins=1440&rollup=false&output=JSON", h)
        try: return [v["value"] for v in d[0]["metricValues"][-pts:]]
        except: return []

    viols = http_get(f"{ctrl}/controller/rest/applications/{app}/policy-violations?time-range-type=BEFORE_NOW&duration-in-mins=60&output=JSON", h)

    return {
        "tool": "appdynamics", "fetched_at": datetime.now(timezone.utc).isoformat(),
        "dashboard_url": f"{ctrl}/controller/#/location=APP_DASHBOARD&application={app}",
        "avg_response_time_ms": round(metric("Overall Application Performance|Average Response Time (ms)"), 1),
        "error_rate_pct":       round(metric("Overall Application Performance|Error Rate"), 3),
        "calls_per_min":        round(metric("Overall Application Performance|Calls per Minute"), 1),
        "cpu_busy_pct":         round(metric("Infrastructure|JVM|Process CPU Busy (%)"), 1),
        "heap_used_mb":         round(metric("Infrastructure|JVM|Heap Used (MB)"), 0),
        "open_violations":      len(viols) if isinstance(viols, list) else 0,
        "lr_avg_rt_trend":      trend("Custom Metrics|LoadRunner|API|Average Response Time (ms)"),
        "lr_error_rate_trend":  trend("Custom Metrics|LoadRunner|API|Error Rate Percent"),
        "lr_tps_trend":         trend("Custom Metrics|LoadRunner|API|Throughput TPS"),
    }


# ── New Relic ──────────────────────────────────────────────────────────────────
def fetch_newrelic():
    api_key = os.getenv("NEWRELIC_API_KEY",""); acct = os.getenv("NEWRELIC_ACCOUNT_ID","")
    region  = os.getenv("NEWRELIC_REGION","US").upper()
    if not api_key or not acct: return {"error": "NEWRELIC_API_KEY / NEWRELIC_ACCOUNT_ID not set"}
    gql_url = "https://api.eu.newrelic.com/graphql" if region == "EU" else "https://api.newrelic.com/graphql"
    h = {"API-Key": api_key, "Content-Type": "application/json"}

    def nrql(query):
        payload = json.dumps({"query": f'{{ actor {{ account(id: {acct}) {{ nrql(query: "{query}") {{ results }} }} }} }}'}).encode()
        req = urllib.request.Request(gql_url, data=payload, headers=h, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                d = json.loads(r.read())
                return d["data"]["actor"]["account"]["nrql"]["results"]
        except Exception as e:
            print(f"  ⚠️  NR NRQL: {e}", file=sys.stderr); return []

    def scalar(query, field="result"):
        r = nrql(query)
        try: return r[0].get(field, 0)
        except: return 0

    def timeseries(query, field="average.duration", pts=24):
        r = nrql(query)
        return [round(row.get(field, 0), 2) for row in r[-pts:]] if r else []

    avg_rt  = scalar("SELECT average(duration)*1000 AS result FROM Transaction SINCE 1 hour ago")
    err_rt  = scalar("SELECT percentage(count(*), WHERE error IS TRUE) AS result FROM Transaction SINCE 1 hour ago")
    tput    = scalar("SELECT rate(count(*), 1 minute) AS result FROM Transaction SINCE 1 hour ago")
    cpu     = scalar("SELECT average(cpuPercent) AS result FROM SystemSample SINCE 1 hour ago")
    alerts  = scalar("SELECT count(*) AS result FROM NrAiIncident WHERE event = 'open' SINCE 1 hour ago")
    rt_trend= timeseries("SELECT average(duration)*1000 FROM Transaction SINCE 24 hours ago TIMESERIES 1 hour", "average.duration")
    lr_rt   = timeseries("SELECT average(loadrunner.response_time.avg) FROM Metric SINCE 24 hours ago TIMESERIES 1 hour")
    lr_err  = timeseries("SELECT average(loadrunner.error_rate.percent) FROM Metric SINCE 24 hours ago TIMESERIES 1 hour")
    lr_tps  = timeseries("SELECT average(loadrunner.throughput.tps) FROM Metric SINCE 24 hours ago TIMESERIES 1 hour")

    return {
        "tool": "newrelic", "fetched_at": datetime.now(timezone.utc).isoformat(),
        "dashboard_url": f"https://one{'eu.' if region=='EU' else '.'}newrelic.com",
        "avg_response_time_ms": round(avg_rt, 1),
        "error_rate_pct":       round(err_rt, 3),
        "throughput_rpm":       round(tput, 1),
        "cpu_usage_pct":        round(cpu, 1),
        "open_alerts":          int(alerts),
        "response_time_trend":  rt_trend,
        "lr_avg_rt_trend":      lr_rt,
        "lr_error_rate_trend":  lr_err,
        "lr_tps_trend":         lr_tps,
    }


# ── Splunk Observability ───────────────────────────────────────────────────────
def fetch_splunk():
    token = os.getenv("SPLUNK_ACCESS_TOKEN",""); realm = os.getenv("SPLUNK_REALM","us0")
    if not token: return {"error": "SPLUNK_ACCESS_TOKEN not set"}
    h = {"X-SF-TOKEN": token, "Content-Type": "application/json"}

    def sfx_query(program, start=HOUR_MS, stop=NOW_MS):
        payload = json.dumps({"program": program, "start": start, "stop": stop, "resolution": 3600000, "maxDelay": 0}).encode()
        req = urllib.request.Request(f"https://api.{realm}.signalfx.com/v1/signalflow/execute", data=payload, headers=h, method="POST")
        results = []
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                for line in r:
                    try:
                        msg = json.loads(line)
                        if msg.get("type") == "data":
                            vals = [v for v in msg.get("data",{}).values() if v is not None]
                            if vals: results.append(round(sum(vals)/len(vals), 2))
                    except: pass
        except Exception as e:
            print(f"  ⚠️  Splunk SignalFlow: {e}", file=sys.stderr)
        return results

    def scalar(prog):
        r = sfx_query(prog); return r[-1] if r else 0

    def trend(prog, pts=24):
        r = sfx_query(prog, DAY_MS, NOW_MS); return r[-pts:]

    return {
        "tool": "splunk", "fetched_at": datetime.now(timezone.utc).isoformat(),
        "dashboard_url": f"https://app.{realm}.signalfx.com",
        "avg_response_time_ms": round(scalar("data('service.duration.mean').mean().publish()"), 1),
        "error_rate_pct":       round(scalar("data('service.error.count').sum().publish()"), 3),
        "throughput_rps":       round(scalar("data('service.request.count').sum().publish()"), 1),
        "cpu_usage_pct":        round(scalar("data('cpu.utilization').mean().publish()"), 1),
        "lr_avg_rt_trend":      trend("data('loadrunner.response_time.avg').mean().publish()"),
        "lr_error_rate_trend":  trend("data('loadrunner.error_rate.percent').mean().publish()"),
        "lr_tps_trend":         trend("data('loadrunner.throughput.tps').mean().publish()"),
    }


# ── Elastic APM / Kibana ───────────────────────────────────────────────────────
def fetch_elastic():
    es_url = os.getenv("ELASTIC_ES_URL",""); api_key = os.getenv("ELASTIC_API_KEY","")
    index  = os.getenv("ELASTIC_ES_INDEX","loadrunner-metrics")
    if not es_url or not api_key: return {"error": "ELASTIC_ES_URL / ELASTIC_API_KEY not set"}
    h = {"Authorization": f"ApiKey {api_key}", "Content-Type": "application/json"}

    # Query last 24h of LR metrics from ES index
    query = {"size": 0, "query": {"range": {"@timestamp": {"gte": "now-24h"}}},
             "aggs": {
               "avg_rt":  {"avg":   {"field": "loadrunner.response_time.avg"}},
               "max_rt":  {"max":   {"field": "loadrunner.response_time.max"}},
               "p95_rt":  {"percentiles": {"field": "loadrunner.response_time.avg", "percents": [95]}},
               "err_rt":  {"avg":   {"field": "loadrunner.error_rate.percent"}},
               "tps":     {"avg":   {"field": "loadrunner.throughput.tps"}},
               "over_time": {"date_histogram": {"field": "@timestamp", "fixed_interval": "1h"},
                             "aggs": {"rt": {"avg": {"field": "loadrunner.response_time.avg"}},
                                      "err": {"avg": {"field": "loadrunner.error_rate.percent"}},
                                      "tps": {"avg": {"field": "loadrunner.throughput.tps"}}}},
             }}

    payload = json.dumps(query).encode()
    req = urllib.request.Request(f"{es_url}/{index}/_search", data=payload, headers=h, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            d = json.loads(r.read())
    except Exception as e:
        return {"error": str(e)}

    aggs     = d.get("aggregations", {})
    buckets  = aggs.get("over_time", {}).get("buckets", [])

    return {
        "tool": "elastic", "fetched_at": datetime.now(timezone.utc).isoformat(),
        "dashboard_url": es_url.replace(":9200","").replace(":443","") + "/app/apm",
        "avg_response_time_ms": round(aggs.get("avg_rt",{}).get("value") or 0, 1),
        "max_response_time_ms": round(aggs.get("max_rt",{}).get("value") or 0, 1),
        "p95_response_time_ms": round((aggs.get("p95_rt",{}).get("values",{}).get("95.0")) or 0, 1),
        "error_rate_pct":       round(aggs.get("err_rt",{}).get("value") or 0, 3),
        "throughput_tps":       round(aggs.get("tps",{}).get("value") or 0, 1),
        "lr_avg_rt_trend":      [round(b["rt"].get("value") or 0, 1) for b in buckets],
        "lr_error_rate_trend":  [round(b["err"].get("value") or 0, 3) for b in buckets],
        "lr_tps_trend":         [round(b["tps"].get("value") or 0, 1) for b in buckets],
    }


# ── Grafana Cloud ──────────────────────────────────────────────────────────────
def fetch_grafana():
    prom_url  = os.getenv("GRAFANA_PROMETHEUS_URL","")
    prom_user = os.getenv("GRAFANA_PROMETHEUS_USER","")
    api_key   = os.getenv("GRAFANA_API_KEY","")
    if not prom_url or not api_key: return {"error": "GRAFANA_PROMETHEUS_URL / GRAFANA_API_KEY not set"}

    creds = base64.b64encode(f"{prom_user}:{api_key}".encode()).decode()
    h = {"Authorization": f"Basic {creds}"}
    query_url = prom_url.replace("/push","").replace("/api/prom/push","") + "/api/prom/api/v1/query"
    range_url = prom_url.replace("/push","").replace("/api/prom/push","") + "/api/prom/api/v1/query_range"

    def instant(promql):
        d = http_get(f"{query_url}?query={urllib.parse.quote(promql)}&time={NOW_MS//1000}", h)
        try: return float(d["data"]["result"][0]["value"][1])
        except: return 0

    def over_time(promql, pts=24):
        step = 3600
        d = http_get(f"{range_url}?query={urllib.parse.quote(promql)}&start={DAY_MS//1000}&end={NOW_MS//1000}&step={step}", h)
        try: return [round(float(v[1]),2) for v in d["data"]["result"][0]["values"][-pts:]]
        except: return []

    return {
        "tool": "grafana", "fetched_at": datetime.now(timezone.utc).isoformat(),
        "dashboard_url": prom_url.split("/api/")[0].replace("prometheus-prod","grafana").split(".grafana.net")[0] + ".grafana.net",
        "avg_response_time_ms": round(instant('avg(loadrunner_response_time_avg_ms)'), 1),
        "error_rate_pct":       round(instant('avg(loadrunner_error_rate_percent)'), 3),
        "throughput_tps":       round(instant('avg(loadrunner_throughput_tps)'), 1),
        "cpu_usage_pct":        round(instant('avg(node_cpu_seconds_total{mode="user"}) * 100'), 1),
        "lr_avg_rt_trend":      over_time('avg(loadrunner_response_time_avg_ms)'),
        "lr_error_rate_trend":  over_time('avg(loadrunner_error_rate_percent)'),
        "lr_tps_trend":         over_time('avg(loadrunner_throughput_tps)'),
    }


# ── Dispatcher ─────────────────────────────────────────────────────────────────
FETCHERS = {
    "datadog":     fetch_datadog,
    "dynatrace":   fetch_dynatrace,
    "appdynamics": fetch_appdynamics,
    "newrelic":    fetch_newrelic,
    "splunk":      fetch_splunk,
    "elastic":     fetch_elastic,
    "grafana":     fetch_grafana,
    "none":        lambda: {"tool": "none", "message": "APM monitoring disabled"},
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tool",   required=True, choices=list(FETCHERS.keys()))
    parser.add_argument("--output", default="dashboard/apm-metrics.json")
    args = parser.parse_args()

    print(f"\n📡 Fetching metrics from {args.tool.upper()}…")
    result = {
        "generated_at":  datetime.now(timezone.utc).isoformat(),
        "selected_tool": args.tool,
        "metrics":       None,
    }
    try:
        result["metrics"] = FETCHERS[args.tool]()
        print(f"  ✅ Done")
    except Exception as e:
        result["metrics"] = {"error": str(e)}
        print(f"  ❌ Failed: {e}", file=sys.stderr)

    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    with open(args.output, "w") as f:
        json.dump(result, f, indent=2)
    print(f"  Written → {args.output}")


if __name__ == "__main__":
    main()
