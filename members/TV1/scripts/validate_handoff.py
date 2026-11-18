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


def check_e2e_exports(results: Path, rows: list[dict], summary: dict, manifest: dict) -> dict:
    """Cross-check ran_embb_slots.csv and ran_urllc_packets.csv with TV1 outputs."""
    embb_path = results / "ran_embb_slots.csv"
    urllc_path = results / "ran_urllc_packets.csv"
    if not embb_path.exists() or not urllc_path.exists():
        raise ValueError("missing ran_embb_slots.csv or ran_urllc_packets.csv")
    run_id = manifest["run_id"]
    with embb_path.open(encoding="utf-8", newline="") as handle:
        embb_rows = list(csv.DictReader(handle))
    with urllc_path.open(encoding="utf-8", newline="") as handle:
        urllc_rows = list(csv.DictReader(handle))

    if len(embb_rows) != summary["processed_slots"]:
        raise ValueError("ran_embb_slots.csv row count != processed_slots")
    metrics_by_slot = {int(r["time_slot"]): int(r["served_embb_bits"]) for r in rows}
    for row in embb_rows:
        slot = int(row["time_slot"])
        if row["run_id"] != run_id:
            raise ValueError(f"ran_embb_slots.csv run_id mismatch at slot {slot}")
        if int(row["served_embb_bits"]) != metrics_by_slot.get(slot):
            raise ValueError(f"served_embb_bits mismatch with ran_metrics.csv at slot {slot}")
        if float(row["emit_time_ms"]) != (slot + 1) * float(summary["slot_duration_ms"]):
            raise ValueError(f"emit_time_ms convention broken at slot {slot}")
    embb_total = sum(int(r["served_embb_bits"]) for r in embb_rows)
    if embb_total != summary["traffic_and_service"]["served_embb_bits"]:
        raise ValueError("sum(ran_embb_slots.served_embb_bits) != run_summary served_embb_bits")

    counters = summary["urllc_packet_counters"]
    status_count = {"completed": 0, "dropped": 0, "unresolved": 0}
    for row in urllc_rows:
        if row["run_id"] != run_id:
            raise ValueError(f"ran_urllc_packets.csv run_id mismatch for {row['packet_id']}")
        status_count[row["final_status"]] += 1
        if row["final_status"] == "completed":
            emitted = float(row["emit_time_ms"]) - float(row["arrival_time_ms"])
            if emitted != float(row["delay_ms"]):
                raise ValueError(f"emit/arrival/delay mismatch for {row['packet_id']}")
        elif row["emit_time_ms"] != "":
            raise ValueError(f"non-completed packet has emit_time_ms: {row['packet_id']}")
    if len(urllc_rows) != counters["arrived"]:
        raise ValueError("ran_urllc_packets.csv row count != arrived URLLC packets")
    for status, key in (
        ("completed", "completed"),
        ("dropped", "dropped"),
        ("unresolved", "unresolved_at_end"),
    ):
        if status_count[status] != counters[key]:
            raise ValueError(f"URLLC {status} count mismatch with run_summary.json")
    return {
        "embb_slots": len(embb_rows),
        "embb_served_bits_total": embb_total,
        "urllc_packets": len(urllc_rows),
        "urllc_status": status_count,
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
    e2e = check_e2e_exports(results, rows, summary, manifest)
    print(
        json.dumps(
            {
                "status": "valid",
                "rows": len(rows),
                "run_id": manifest["run_id"],
                "packet_conservation": True,
                "e2e_exports": e2e,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
