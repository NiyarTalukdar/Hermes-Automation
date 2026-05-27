#!/usr/bin/env python3
"""Push LoadRunner test results to Dynatrace as custom metrics and events."""

import argparse
import csv
import json
import os
import sys
import time
from pathlib import Path
import urllib.request
import urllib.error


def load_results(results_dir: str, protocol: str) -> dict:
    """Parse LR exported CSV/JSON results into a unified dict."""
    results_dir = Path(results_dir)
    summary = {}

    # Try JSON summary first (exported by export-lr-results.ps1)
    summary_file = results_dir / "summary.json"
    if summary_file.exists():
        with open(summary_file) as f:
            summary = json.load(f)
    else:
        # Fall back to CSV parsing
        csv_file = next(results_dir.glob("*.csv"), None)
        if csv_file:
            with open(csv_file, newline="") as f:
                reader = csv.DictReader(f)
                rows = list(reader)
                if rows:
                    times = [float(r.get("response_time", 0)) for r in rows]
                    errors = [int(r.get("errors", 0)) for r in rows]
                    summary = {
                        "avg_response_time": sum(times) / len(times) if times else 0,
                        "max_response_time": max(times) if times else 0,
                        "error_count": sum(errors),
                        "total_transactions": len(rows),
                        "tps": len(rows) / 60,  # rough estimate
                    }

    summary.setdefault("avg_response_time", 0)
    summary.setdefault("max_response_time", 0)
    summary.setdefault("p90_response_time", 0)
    summary.setdefault("p95_response_time", 0)
    summary.setdefault("p99_response_time", 0)
    summary.setdefault("error_count", 0)
    summary.setdefault("total_transactions", 0)
    summary.setdefault("tps", 0)
    summary.setdefault("error_rate", 0)
    summary["protocol"] = protocol.upper()
    return summary


def push_metrics(env_id: str, api_token: str, metrics: dict, labels: dict) -> bool:
    """Push metrics to Dynatrace Metrics API v2 (MINT format)."""
    label_str = ",".join(f'{k}="{v}"' for k, v in labels.items())
    lines = []
    metric_map = {
        "performance.loadrunner.response_time.avg":   metrics["avg_response_time"],
        "performance.loadrunner.response_time.max":   metrics["max_response_time"],
        "performance.loadrunner.response_time.p90":   metrics["p90_response_time"],
        "performance.loadrunner.response_time.p95":   metrics["p95_response_time"],
        "performance.loadrunner.response_time.p99":   metrics["p99_response_time"],
        "performance.loadrunner.error_count":          metrics["error_count"],
        "performance.loadrunner.transactions_total":   metrics["total_transactions"],
        "performance.loadrunner.throughput_tps":       metrics["tps"],
        "performance.loadrunner.error_rate_percent":   metrics["error_rate"],
    }
    for metric_key, value in metric_map.items():
        lines.append(f'{metric_key},{label_str} gauge,{value}')

    payload = "\n".join(lines).encode("utf-8")
    url = f"https://{env_id}.live.dynatrace.com/api/v2/metrics/ingest"
    req = urllib.request.Request(
        url,
        data=payload,
        headers={
            "Authorization": f"Api-Token {api_token}",
            "Content-Type": "text/plain; charset=utf-8",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            print(f"✅ Dynatrace metrics ingested (HTTP {resp.status})")
            return True
    except urllib.error.HTTPError as e:
        print(f"❌ Dynatrace metrics push failed: {e.code} {e.reason}", file=sys.stderr)
        return False


def push_event(env_id: str, api_token: str, labels: dict, status: str = "PASS") -> bool:
    """Create a Dynatrace deployment/annotation event for the test end."""
    payload = json.dumps({
        "eventType": "CUSTOM_ANNOTATION",
        "title": f"LoadRunner {labels.get('protocol','?')} Test Completed — {status}",
        "properties": {
            "dt.event.category": "PERFORMANCE_TEST",
            **labels,
            "test_status": status,
        },
    }).encode("utf-8")
    url = f"https://{env_id}.live.dynatrace.com/api/v2/events/ingest"
    req = urllib.request.Request(
        url,
        data=payload,
        headers={
            "Authorization": f"Api-Token {api_token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            print(f"✅ Dynatrace event created (HTTP {resp.status})")
            return True
    except urllib.error.HTTPError as e:
        print(f"❌ Dynatrace event push failed: {e.code} {e.reason}", file=sys.stderr)
        return False


def main():
    parser = argparse.ArgumentParser(description="Push LR results to Dynatrace")
    parser.add_argument("--env-id",       required=True,  help="Dynatrace environment ID")
    parser.add_argument("--api-token",    required=True,  help="Dynatrace API token")
    parser.add_argument("--results-dir",  required=True,  help="Path to LR results directory")
    parser.add_argument("--protocol",     required=True,  choices=["api","web"], help="LR protocol")
    parser.add_argument("--run-id",       required=True,  help="GitHub Actions run ID")
    parser.add_argument("--scenario",     default="load", help="Test scenario name")
    parser.add_argument("--environment",  default="staging", help="Target environment")
    parser.add_argument("--browser",      default="",     help="Browser emulation (web only)")
    args = parser.parse_args()

    print(f"📊 Loading results from {args.results_dir}...")
    metrics = load_results(args.results_dir, args.protocol)
    print(f"   Avg RT: {metrics['avg_response_time']:.0f}ms | TPS: {metrics['tps']:.1f} | Errors: {metrics['error_rate']:.2f}%")

    labels = {
        "protocol":    args.protocol.upper(),
        "scenario":    args.scenario,
        "environment": args.environment,
        "github_run":  args.run_id,
    }
    if args.browser:
        labels["browser"] = args.browser

    ok_metrics = push_metrics(args.env_id, args.api_token, metrics, labels)
    ok_event   = push_event(args.env_id, args.api_token, labels)

    # Output for GitHub Actions step summary
    print(f"avg_response_time={metrics['avg_response_time']:.0f}")
    print(f"p95_response_time={metrics['p95_response_time']:.0f}")
    print(f"error_rate={metrics['error_rate']:.2f}")
    print(f"tps={metrics['tps']:.2f}")

    sys.exit(0 if (ok_metrics and ok_event) else 1)


if __name__ == "__main__":
    main()
