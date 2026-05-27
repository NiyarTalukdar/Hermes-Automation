#!/usr/bin/env python3
"""Push LoadRunner test results to AppDynamics as custom metrics."""

import argparse
import json
import sys
from pathlib import Path
import urllib.request
import urllib.error
import base64


def load_results(results_dir: str) -> dict:
    summary_file = Path(results_dir) / "summary.json"
    if summary_file.exists():
        with open(summary_file) as f:
            return json.load(f)
    return {
        "avg_response_time": 0, "max_response_time": 0,
        "p95_response_time": 0, "error_count": 0,
        "total_transactions": 0, "tps": 0, "error_rate": 0,
    }


def push_custom_metrics(controller: str, account: str, api_key: str,
                         app_id: str, metrics: dict, protocol: str) -> bool:
    """Push metrics via AppDynamics Custom Metrics REST API."""
    creds = base64.b64encode(f"{account}@{account}:{api_key}".encode()).decode()
    base_path = f"Custom Metrics|LoadRunner|{protocol.upper()}"

    payload = json.dumps([
        {"metricName": f"{base_path}|Average Response Time (ms)", "aggregatorType": "AVERAGE",     "value": int(metrics["avg_response_time"])},
        {"metricName": f"{base_path}|Max Response Time (ms)",     "aggregatorType": "MAX",         "value": int(metrics["max_response_time"])},
        {"metricName": f"{base_path}|P95 Response Time (ms)",     "aggregatorType": "AVERAGE",     "value": int(metrics["p95_response_time"])},
        {"metricName": f"{base_path}|Error Count",                "aggregatorType": "SUM",         "value": int(metrics["error_count"])},
        {"metricName": f"{base_path}|Total Transactions",         "aggregatorType": "SUM",         "value": int(metrics["total_transactions"])},
        {"metricName": f"{base_path}|Throughput TPS",             "aggregatorType": "AVERAGE",     "value": int(metrics["tps"])},
        {"metricName": f"{base_path}|Error Rate Percent",         "aggregatorType": "AVERAGE",     "value": int(metrics["error_rate"])},
    ]).encode("utf-8")

    url = f"{controller}/controller/rest/applications/{app_id}/metric-data"
    req = urllib.request.Request(
        url, data=payload,
        headers={
            "Authorization": f"Basic {creds}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            print(f"✅ AppDynamics metrics pushed (HTTP {resp.status})")
            return True
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        print(f"❌ AppDynamics push failed: {e.code} — {body}", file=sys.stderr)
        return False


def create_appdynamics_event(controller: str, account: str, api_key: str,
                              app_id: str, scenario: str, protocol: str,
                              run_id: str, error_rate: float) -> bool:
    """Create an AppDynamics custom event marking test completion."""
    creds = base64.b64encode(f"{account}@{account}:{api_key}".encode()).decode()
    severity = "ERROR" if error_rate > 5.0 else "INFO"
    payload = json.dumps({
        "summary": f"LR {protocol.upper()} Performance Test Completed",
        "comment": f"Scenario: {scenario} | Run: {run_id} | Error Rate: {error_rate:.2f}%",
        "eventtype": "CUSTOM",
        "severity": severity,
        "customeventtype": "PERFORMANCE_TEST_END",
        "propertySerializations": [
            {"name": "github_run_id",  "value": run_id,       "valueType": "STRING", "type": "STRING"},
            {"name": "protocol",       "value": protocol,      "valueType": "STRING", "type": "STRING"},
            {"name": "scenario",       "value": scenario,      "valueType": "STRING", "type": "STRING"},
            {"name": "error_rate",     "value": str(error_rate), "valueType": "STRING","type": "STRING"},
        ],
    }).encode("utf-8")

    url = f"{controller}/controller/rest/applications/{app_id}/events"
    req = urllib.request.Request(
        url, data=payload,
        headers={
            "Authorization": f"Basic {creds}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            print(f"✅ AppDynamics event created (HTTP {resp.status})")
            return True
    except urllib.error.HTTPError as e:
        print(f"❌ AppDynamics event failed: {e.code}", file=sys.stderr)
        return False


def main():
    parser = argparse.ArgumentParser(description="Push LR results to AppDynamics")
    parser.add_argument("--controller",  required=True)
    parser.add_argument("--account",     required=True)
    parser.add_argument("--api-key",     required=True)
    parser.add_argument("--app-id",      required=True)
    parser.add_argument("--results-dir", required=True)
    parser.add_argument("--protocol",    required=True, choices=["api","web"])
    parser.add_argument("--scenario",    default="load")
    parser.add_argument("--run-id",      default="unknown")
    args = parser.parse_args()

    metrics = load_results(args.results_dir)
    print(f"📊 Pushing {args.protocol.upper()} metrics to AppDynamics...")

    ok1 = push_custom_metrics(args.controller, args.account, args.api_key,
                               args.app_id, metrics, args.protocol)
    ok2 = create_appdynamics_event(args.controller, args.account, args.api_key,
                                    args.app_id, args.scenario, args.protocol,
                                    args.run_id, metrics["error_rate"])

    sys.exit(0 if (ok1 and ok2) else 1)


if __name__ == "__main__":
    main()
