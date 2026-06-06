#!/usr/bin/env python3
"""
update_dashboard.py — Appends a new test run record to the dashboard
data store (dashboard/data.json).  The static HTML dashboard reads
this file on load via fetch(), so no server is needed.
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path


DASHBOARD_DATA = Path(__file__).parent.parent / "dashboard" / "data.json"


def load_store() -> dict:
    if DASHBOARD_DATA.exists():
        with open(DASHBOARD_DATA) as f:
            return json.load(f)
    return {"runs": [], "sla_config": {"max_avg_rt": 2000, "max_error_rate": 1.0, "min_tps": 10}}


def save_store(store: dict):
    DASHBOARD_DATA.parent.mkdir(parents=True, exist_ok=True)
    with open(DASHBOARD_DATA, "w") as f:
        json.dump(store, f, indent=2)


def load_results(results_dir: str) -> dict:
    summary_file = Path(results_dir) / "summary.json"
    if summary_file.exists():
        with open(summary_file) as f:
            return json.load(f)
    return {}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--results-dir",  required=True)
    parser.add_argument("--run-id",       required=True)
    parser.add_argument("--protocol",     required=True, choices=["api","web"])
    parser.add_argument("--scenario",     required=True)
    parser.add_argument("--environment",  required=True)
    parser.add_argument("--status",       required=True)
    parser.add_argument("--apm-tool",     default="none")
    parser.add_argument("--browser",      default="")
    args = parser.parse_args()

    metrics = load_results(args.results_dir)
    store   = load_store()

    record = {
        "run_id":            args.run_id,
        "timestamp":         datetime.now(timezone.utc).isoformat(),
        "protocol":          args.protocol.upper(),
        "scenario":          args.scenario,
        "environment":       args.environment,
        "status":            args.status,
        "avg_response_time": metrics.get("avg_response_time", 0),
        "max_response_time": metrics.get("max_response_time", 0),
        "p50_response_time": metrics.get("p50_response_time", 0),
        "p75_response_time": metrics.get("p75_response_time", 0),
        "p90_response_time": metrics.get("p90_response_time", 0),
        "p95_response_time": metrics.get("p95_response_time", 0),
        "p98_response_time": metrics.get("p98_response_time", 0),
        "p99_response_time": metrics.get("p99_response_time", 0),
        "error_count":       metrics.get("error_count", 0),
        "total_transactions":metrics.get("total_transactions", 0),
        "tps":               metrics.get("tps", 0),
        "tph":               metrics.get("tph", round(metrics.get("tps", 0) * 3600, 1)),
        "error_rate":        metrics.get("error_rate", 0),
        "vusers":            metrics.get("vusers", 0),
        "sla_passed":        metrics.get("sla_passed", args.status == "success"),
        "apm_tool":          getattr(args, "apm_tool", "none"),
    }
    if args.browser:
        record["browser"] = args.browser

    store["runs"].insert(0, record)  # newest first
    store["runs"] = store["runs"][:200]  # keep last 200 runs

    save_store(store)
    print(f"✅ Dashboard updated — {len(store['runs'])} total runs stored")

    # Emit GitHub Actions outputs
    print(f"avg_response_time={record['avg_response_time']:.0f}")
    print(f"error_rate={record['error_rate']:.2f}")
    print(f"tps={record['tps']:.2f}")
    print(f"sla_passed={str(record['sla_passed']).lower()}")


if __name__ == "__main__":
    main()
