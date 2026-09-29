#!/usr/bin/env python3
"""Validate the generated handoff samples and CSV contract headers."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from ran.schemas import validate_action, validate_kpi, validate_state  # noqa: E402


REQUIRED_KPI_COLUMNS = {
    "schema_version",
    "request_id",
    "seed",
    "scenario_id",
    "algorithm",
    "time_slot",
    "throughput_e",
    "delay_u",
    "drop_u",
    "sla_violation",
    "fairness",
    "rb_utilization",
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", required=True)
    parser.add_argument("--total-rb", type=int, default=50)
    args = parser.parse_args()
    results = Path(args.results)
    transition = json.loads((results / "transition_sample.json").read_text(encoding="utf-8"))
    validate_state(transition["state"])
    validate_action(transition["action"], args.total_rb, transition["state"]["time_slot"])
    validate_kpi(transition["ran_kpi"])
    with (results / "ran_metrics.csv").open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        missing = REQUIRED_KPI_COLUMNS - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"ran_metrics.csv missing columns: {sorted(missing)}")
        rows = list(reader)
    if not rows:
        raise ValueError("ran_metrics.csv has no data rows")
    summary = json.loads((results / "run_summary.json").read_text(encoding="utf-8"))
    manifest = json.loads((results / "run_manifest.json").read_text(encoding="utf-8"))
    counters = summary["urllc_packet_counters"]
    if not counters["conservation_ok"]:
        raise ValueError("URLLC packet conservation check failed")
    if summary["processed_slots"] != len(rows):
        raise ValueError("run_summary processed_slots does not match ran_metrics.csv")
    if not manifest.get("run_id") or not manifest.get("config_sha256"):
        raise ValueError("run_manifest is missing reproducibility identifiers")
    print(
        json.dumps(
            {
                "status": "valid",
                "rows": len(rows),
                "run_id": manifest["run_id"],
                "packet_conservation": True,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
