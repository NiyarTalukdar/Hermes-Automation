#!/usr/bin/env python3
"""
push_metrics.py — Universal APM metric dispatcher for LoadRunner CI/CD pipeline.

Supports:
  datadog        — Datadog Metrics API v2 (series)
  dynatrace      — Dynatrace Metrics Ingest API v2 (MINT)
  appdynamics    — AppDynamics Custom Metrics REST API
  newrelic       — New Relic Metric API (OTLP-compatible)
  splunk         — Splunk Observability Cloud (SignalFx) Ingest API
  elastic        — Elastic APM / Elasticsearch Metrics API

Usage:
  python3 push_metrics.py --tool datadog --results-dir results/ \
    --run-id 1234 --protocol api --scenario load --environment staging

All credentials are read from environment variables (injected from GitHub Secrets).
"""

import argparse
import json
import os
import sys
import time
import urllib.request
import urllib.error
import urllib.parse
import base64
from datetime import datetime, timezone
from pathlib import Path


# ── Result loading ─────────────────────────────────────────────────────────────

def load_results(results_dir: str) -> dict:
    p = Path(results_dir) / "summary.json"
    if p.exists():
        with open(p) as f:
            return json.load(f)
    return {
        "avg_response_time": 0, "max_response_time": 0,
        "p90_response_time": 0, "p95_response_time": 0,
        "p99_response_time": 0, "error_count": 0,
        "total_transactions": 0, "tps": 0.0, "error_rate": 0.0,
        "sla_passed": True,
    }


def http_post(url: str, payload: bytes, headers: dict, timeout=20) -> int:
    req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")[:300]
        print(f"  HTTP {e.code}: {body}", file=sys.stderr)
        return e.code


# ── DATADOG ────────────────────────────────────────────────────────────────────

def push_datadog(m: dict, meta: dict) -> bool:
    """
    Datadog Metrics API v2
    Env vars: DD_API_KEY, DD_SITE (default: datadoghq.com)
    """
    api_key = os.getenv("DD_API_KEY", "")
    site    = os.getenv("DD_SITE", "datadoghq.com")
    if not api_key:
        print("  ⚠️  DD_API_KEY not set — skipping Datadog", file=sys.stderr); return False

    now = int(time.time())
    tags = [f"protocol:{meta['protocol']}", f"scenario:{meta['scenario']}",
            f"environment:{meta['environment']}", f"run_id:{meta['run_id']}"]

    def series(name, value, mtype="gauge"):
        return {"metric": f"loadrunner.{name}", "type": mtype,
                "points": [{"timestamp": now, "value": value}], "tags": tags}

    payload = json.dumps({"series": [
        series("response_time.avg",    m["avg_response_time"]),
        series("response_time.max",    m["max_response_time"]),
        series("response_time.p90",    m["p90_response_time"]),
        series("response_time.p95",    m["p95_response_time"]),
        series("response_time.p99",    m["p99_response_time"]),
        series("error_count",          m["error_count"], "count"),
        series("transactions.total",   m["total_transactions"], "count"),
        series("throughput.tps",       m["tps"]),
        series("error_rate.percent",   m["error_rate"]),
        series("sla.passed",           1 if m.get("sla_passed") else 0),
    ]}).encode()

    code = http_post(
        f"https://api.{site}/api/v2/series",
        payload,
        {"DD-API-KEY": api_key, "Content-Type": "application/json"},
    )
    ok = code in (200, 202)
    print(f"  {'✅' if ok else '❌'} Datadog → HTTP {code}")
    return ok


# ── DYNATRACE ──────────────────────────────────────────────────────────────────

def push_dynatrace(m: dict, meta: dict) -> bool:
    """
    Dynatrace Metrics Ingest API v2 (MINT line format)
    Env vars: DT_ENVIRONMENT_ID, DT_API_TOKEN
    Token scopes needed: metrics.ingest, events.ingest
    """
    env_id = os.getenv("DT_ENVIRONMENT_ID", "")
    token  = os.getenv("DT_API_TOKEN", "")
    if not env_id or not token:
        print("  ⚠️  DT_ENVIRONMENT_ID / DT_API_TOKEN not set — skipping Dynatrace", file=sys.stderr); return False

    dims = ','.join([f'protocol="{meta["protocol"]}"', f'scenario="{meta["scenario"]}"',
                     f'environment="{meta["environment"]}"', f'run_id="{meta["run_id"]}"'])
    lines = "\n".join([
        f'loadrunner.response_time.avg,{dims} gauge,{m["avg_response_time"]}',
        f'loadrunner.response_time.max,{dims} gauge,{m["max_response_time"]}',
        f'loadrunner.response_time.p90,{dims} gauge,{m["p90_response_time"]}',
        f'loadrunner.response_time.p95,{dims} gauge,{m["p95_response_time"]}',
        f'loadrunner.response_time.p99,{dims} gauge,{m["p99_response_time"]}',
        f'loadrunner.error_count,{dims} gauge,{m["error_count"]}',
        f'loadrunner.transactions.total,{dims} gauge,{m["total_transactions"]}',
        f'loadrunner.throughput.tps,{dims} gauge,{m["tps"]}',
        f'loadrunner.error_rate.percent,{dims} gauge,{m["error_rate"]}',
    ])

    code = http_post(
        f"https://{env_id}.live.dynatrace.com/api/v2/metrics/ingest",
        lines.encode(),
        {"Authorization": f"Api-Token {token}", "Content-Type": "text/plain; charset=utf-8"},
    )

    # Post annotation event
    event = json.dumps({
        "eventType": "CUSTOM_ANNOTATION",
        "title": f"LR {meta['protocol']} Test Completed",
        "properties": {**meta, "avg_rt": m["avg_response_time"],
                       "error_rate": m["error_rate"], "tps": m["tps"],
                       "sla_passed": str(m.get("sla_passed", True))},
    }).encode()
    http_post(
        f"https://{env_id}.live.dynatrace.com/api/v2/events/ingest",
        event,
        {"Authorization": f"Api-Token {token}", "Content-Type": "application/json"},
    )

    ok = code in (200, 202)
    print(f"  {'✅' if ok else '❌'} Dynatrace → HTTP {code}")
    return ok


# ── APPDYNAMICS ────────────────────────────────────────────────────────────────

def push_appdynamics(m: dict, meta: dict) -> bool:
    """
    AppDynamics Custom Metrics REST API
    Env vars: APPDYNAMICS_CONTROLLER_URL, APPDYNAMICS_ACCOUNT_NAME,
              APPDYNAMICS_API_KEY, APPDYNAMICS_APP_ID
    """
    controller = os.getenv("APPDYNAMICS_CONTROLLER_URL", "")
    account    = os.getenv("APPDYNAMICS_ACCOUNT_NAME", "")
    api_key    = os.getenv("APPDYNAMICS_API_KEY", "")
    app_id     = os.getenv("APPDYNAMICS_APP_ID", "")
    if not controller or not api_key:
        print("  ⚠️  APPDYNAMICS_* vars not set — skipping AppDynamics", file=sys.stderr); return False

    creds   = base64.b64encode(f"{account}@{account}:{api_key}".encode()).decode()
    proto   = meta["protocol"].upper()
    base    = f"Custom Metrics|LoadRunner|{proto}"

    payload = json.dumps([
        {"metricName": f"{base}|Average Response Time (ms)", "aggregatorType": "AVERAGE", "value": int(m["avg_response_time"])},
        {"metricName": f"{base}|Max Response Time (ms)",     "aggregatorType": "MAX",     "value": int(m["max_response_time"])},
        {"metricName": f"{base}|P95 Response Time (ms)",     "aggregatorType": "AVERAGE", "value": int(m["p95_response_time"])},
        {"metricName": f"{base}|Error Count",                "aggregatorType": "SUM",     "value": int(m["error_count"])},
        {"metricName": f"{base}|Total Transactions",         "aggregatorType": "SUM",     "value": int(m["total_transactions"])},
        {"metricName": f"{base}|Throughput TPS",             "aggregatorType": "AVERAGE", "value": int(m["tps"])},
        {"metricName": f"{base}|Error Rate Percent",         "aggregatorType": "AVERAGE", "value": int(m["error_rate"])},
    ]).encode()

    code = http_post(
        f"{controller}/controller/rest/applications/{app_id}/metric-data",
        payload,
        {"Authorization": f"Basic {creds}", "Content-Type": "application/json"},
    )
    ok = code in (200, 204)
    print(f"  {'✅' if ok else '❌'} AppDynamics → HTTP {code}")
    return ok


# ── NEW RELIC ──────────────────────────────────────────────────────────────────

def push_newrelic(m: dict, meta: dict) -> bool:
    """
    New Relic Metric API
    Env vars: NEWRELIC_API_KEY, NEWRELIC_ACCOUNT_ID
              NEWRELIC_REGION (US | EU, default: US)
    """
    api_key    = os.getenv("NEWRELIC_API_KEY", "")
    account_id = os.getenv("NEWRELIC_ACCOUNT_ID", "")
    region     = os.getenv("NEWRELIC_REGION", "US").upper()
    if not api_key:
        print("  ⚠️  NEWRELIC_API_KEY not set — skipping New Relic", file=sys.stderr); return False

    url = ("https://metric-api.eu.newrelic.com/metric/v1"
           if region == "EU" else "https://metric-api.newrelic.com/metric/v1")

    now_ms = int(time.time() * 1000)
    attrs  = {"protocol": meta["protocol"], "scenario": meta["scenario"],
              "environment": meta["environment"], "run_id": meta["run_id"]}

    def nr_metric(name, value, mtype="gauge"):
        return {"name": f"loadrunner.{name}", "type": mtype,
                "value": value, "timestamp": now_ms, "attributes": attrs}

    payload = json.dumps([{"metrics": [
        nr_metric("response_time.avg",   m["avg_response_time"]),
        nr_metric("response_time.max",   m["max_response_time"]),
        nr_metric("response_time.p90",   m["p90_response_time"]),
        nr_metric("response_time.p95",   m["p95_response_time"]),
        nr_metric("response_time.p99",   m["p99_response_time"]),
        nr_metric("error_count",         m["error_count"], "count"),
        nr_metric("transactions.total",  m["total_transactions"], "count"),
        nr_metric("throughput.tps",      m["tps"]),
        nr_metric("error_rate.percent",  m["error_rate"]),
        nr_metric("sla.passed",          1 if m.get("sla_passed") else 0),
    ]}]).encode()

    code = http_post(url, payload,
        {"Api-Key": api_key, "Content-Type": "application/json"})
    ok = code in (200, 202)
    print(f"  {'✅' if ok else '❌'} New Relic → HTTP {code}")
    return ok


# ── SPLUNK OBSERVABILITY (SignalFx) ────────────────────────────────────────────

def push_splunk(m: dict, meta: dict) -> bool:
    """
    Splunk Observability Cloud (formerly SignalFx) Ingest API
    Env vars: SPLUNK_ACCESS_TOKEN, SPLUNK_REALM (default: us0)
    """
    token = os.getenv("SPLUNK_ACCESS_TOKEN", "")
    realm = os.getenv("SPLUNK_REALM", "us0")
    if not token:
        print("  ⚠️  SPLUNK_ACCESS_TOKEN not set — skipping Splunk", file=sys.stderr); return False

    dims = {"protocol": meta["protocol"], "scenario": meta["scenario"],
            "environment": meta["environment"], "run_id": meta["run_id"]}
    now_ms = int(time.time() * 1000)

    def sfx(name, value):
        return {"metric": f"loadrunner.{name}", "value": value,
                "dimensions": dims, "timestamp": now_ms}

    payload = json.dumps({"gauge": [
        sfx("response_time.avg",   m["avg_response_time"]),
        sfx("response_time.max",   m["max_response_time"]),
        sfx("response_time.p90",   m["p90_response_time"]),
        sfx("response_time.p95",   m["p95_response_time"]),
        sfx("response_time.p99",   m["p99_response_time"]),
        sfx("throughput.tps",      m["tps"]),
        sfx("error_rate.percent",  m["error_rate"]),
    ], "counter": [
        sfx("error_count",         m["error_count"]),
        sfx("transactions.total",  m["total_transactions"]),
    ]}).encode()

    code = http_post(
        f"https://ingest.{realm}.signalfx.com/v2/datapoint",
        payload,
        {"X-SF-TOKEN": token, "Content-Type": "application/json"},
    )
    ok = code in (200, 204)
    print(f"  {'✅' if ok else '❌'} Splunk Observability → HTTP {code}")
    return ok


# ── ELASTIC APM ────────────────────────────────────────────────────────────────

def push_elastic(m: dict, meta: dict) -> bool:
    """
    Elastic APM / Elasticsearch Metrics Index
    Env vars: ELASTIC_APM_SERVER_URL, ELASTIC_APM_SECRET_TOKEN
              (or ELASTIC_API_KEY for Elastic Cloud)
              ELASTIC_ES_URL, ELASTIC_ES_INDEX (default: loadrunner-metrics)
    """
    apm_url   = os.getenv("ELASTIC_APM_SERVER_URL", "")
    apm_token = os.getenv("ELASTIC_APM_SECRET_TOKEN", "")
    es_url    = os.getenv("ELASTIC_ES_URL", "")
    es_key    = os.getenv("ELASTIC_API_KEY", "")
    es_index  = os.getenv("ELASTIC_ES_INDEX", "loadrunner-metrics")

    if not apm_url and not es_url:
        print("  ⚠️  ELASTIC_APM_SERVER_URL / ELASTIC_ES_URL not set — skipping Elastic", file=sys.stderr)
        return False

    doc = {
        "@timestamp":            datetime.now(timezone.utc).isoformat(),
        "loadrunner.protocol":   meta["protocol"],
        "loadrunner.scenario":   meta["scenario"],
        "loadrunner.environment":meta["environment"],
        "loadrunner.run_id":     meta["run_id"],
        "loadrunner.response_time.avg":   m["avg_response_time"],
        "loadrunner.response_time.max":   m["max_response_time"],
        "loadrunner.response_time.p90":   m["p90_response_time"],
        "loadrunner.response_time.p95":   m["p95_response_time"],
        "loadrunner.response_time.p99":   m["p99_response_time"],
        "loadrunner.error_count":         m["error_count"],
        "loadrunner.transactions.total":  m["total_transactions"],
        "loadrunner.throughput.tps":      m["tps"],
        "loadrunner.error_rate.percent":  m["error_rate"],
        "loadrunner.sla_passed":          m.get("sla_passed", True),
    }

    ok = False

    # Path 1: Elasticsearch index (preferred — works with Elastic Cloud & self-hosted)
    if es_url and es_key:
        payload = json.dumps(doc).encode()
        code = http_post(
            f"{es_url}/{es_index}/_doc",
            payload,
            {"Authorization": f"ApiKey {es_key}", "Content-Type": "application/json"},
        )
        ok = code in (200, 201)
        print(f"  {'✅' if ok else '❌'} Elastic (ES index) → HTTP {code}")

    # Path 2: APM Server intake (agent-style event)
    elif apm_url and apm_token:
        event_lines = (
            '{"metadata":{"service":{"name":"loadrunner-pipeline","version":"1.0"}}}\n'
            + json.dumps({"metricset": {"samples": {
                k.replace("loadrunner.", "").replace(".", "_"): {"value": v}
                for k, v in doc.items() if isinstance(v, (int, float))
            }, "tags": {k: str(v) for k, v in doc.items() if isinstance(v, str)}}})
            + "\n"
        )
        code = http_post(
            f"{apm_url}/intake/v2/events",
            event_lines.encode(),
            {"Authorization": f"Bearer {apm_token}", "Content-Type": "application/x-ndjson"},
        )
        ok = code in (200, 202)
        print(f"  {'✅' if ok else '❌'} Elastic (APM Server) → HTTP {code}")

    return ok


# ── GRAFANA CLOUD (Prometheus Remote Write) ────────────────────────────────────

def push_grafana(m: dict, meta: dict) -> bool:
    """
    Grafana Cloud — Prometheus Remote Write endpoint
    Env vars: GRAFANA_PROMETHEUS_URL  (full remote_write URL)
              GRAFANA_PROMETHEUS_USER (numeric Prometheus instance ID)
              GRAFANA_API_KEY         (Grafana Cloud API key)
    Note: Uses JSON-over-HTTP as a simpler alternative to protobuf remote_write.
          For production, use the prometheus-remote-write protobuf format.
    """
    prom_url  = os.getenv("GRAFANA_PROMETHEUS_URL", "")
    prom_user = os.getenv("GRAFANA_PROMETHEUS_USER", "")
    api_key   = os.getenv("GRAFANA_API_KEY", "")
    if not prom_url or not api_key:
        print("  ⚠️  GRAFANA_PROMETHEUS_URL / GRAFANA_API_KEY not set — skipping Grafana Cloud", file=sys.stderr)
        return False

    creds   = base64.b64encode(f"{prom_user}:{api_key}".encode()).decode()
    now_ms  = int(time.time() * 1000)
    labels  = {
        "__name__":   "loadrunner_metric",
        "protocol":   meta["protocol"],
        "scenario":   meta["scenario"],
        "environment":meta["environment"],
        "run_id":     str(meta["run_id"]),
    }

    metric_map = {
        "loadrunner_response_time_avg_ms":    m["avg_response_time"],
        "loadrunner_response_time_max_ms":    m["max_response_time"],
        "loadrunner_response_time_p90_ms":    m["p90_response_time"],
        "loadrunner_response_time_p95_ms":    m["p95_response_time"],
        "loadrunner_response_time_p99_ms":    m["p99_response_time"],
        "loadrunner_error_count_total":       m["error_count"],
        "loadrunner_transactions_total":      m["total_transactions"],
        "loadrunner_throughput_tps":          m["tps"],
        "loadrunner_error_rate_percent":      m["error_rate"],
        "loadrunner_sla_passed":              1 if m.get("sla_passed") else 0,
    }

    # Grafana Cloud accepts Prometheus remote_write via protobuf or snappy-compressed.
    # As a JSON-friendly fallback, we push via the /api/v1/import/prometheus text format
    # (available in VictoriaMetrics-backed Grafana Cloud stacks).
    lines = []
    for metric_name, value in metric_map.items():
        lbl_str = ",".join(f'{k}="{v}"' for k, v in {**labels, "__name__": metric_name}.items() if k != "__name__")
        lines.append(f"{metric_name}{{{lbl_str}}} {value} {now_ms}")

    payload = "\n".join(lines).encode()
    code = http_post(
        prom_url,  # e.g. https://prometheus-prod-xx.grafana.net/api/prom/push
        payload,
        {"Authorization": f"Basic {creds}", "Content-Type": "text/plain"},
    )
    ok = code in (200, 204)
    print(f"  {'✅' if ok else '❌'} Grafana Cloud → HTTP {code}")
    return ok


# ── Dispatcher ─────────────────────────────────────────────────────────────────

TOOL_MAP = {
    "datadog":      push_datadog,
    "dynatrace":    push_dynatrace,
    "appdynamics":  push_appdynamics,
    "newrelic":     push_newrelic,
    "splunk":       push_splunk,
    "elastic":      push_elastic,
    "grafana":      push_grafana,
    "none":         lambda m, meta: (print("  ⏭️  APM tool = none — skipping"), True)[1],
}


def main():
    parser = argparse.ArgumentParser(description="Push LR metrics to selected APM tool")
    parser.add_argument("--tool",         required=True,
                        choices=list(TOOL_MAP.keys()),
                        help="APM tool to push metrics to")
    parser.add_argument("--results-dir",  required=True)
    parser.add_argument("--run-id",       required=True)
    parser.add_argument("--protocol",     required=True, choices=["api", "web"])
    parser.add_argument("--scenario",     default="load")
    parser.add_argument("--environment",  default="staging")
    args = parser.parse_args()

    print(f"\n📊 Pushing LR metrics → {args.tool.upper()}")
    metrics = load_results(args.results_dir)
    meta    = {
        "run_id":      args.run_id,
        "protocol":    args.protocol.upper(),
        "scenario":    args.scenario,
        "environment": args.environment,
    }

    print(f"   Avg RT: {metrics['avg_response_time']:.0f}ms | "
          f"TPS: {metrics['tps']:.1f} | "
          f"Errors: {metrics['error_rate']:.3f}% | "
          f"SLA: {'PASS' if metrics.get('sla_passed') else 'FAIL'}")

    fn  = TOOL_MAP[args.tool]
    ok  = fn(metrics, meta)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
