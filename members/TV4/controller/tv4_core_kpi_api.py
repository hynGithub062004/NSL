#!/usr/bin/env python3
"""TV4 Core KPI API: READ-ONLY, historical GNS3 benchmark snapshots.

GNS3 VM, Python venv with Flask. Binds ONLY 127.0.0.1:8017.

Endpoints:
  GET /health
  GET /core-kpi?slice_id=embb|urllc
  GET /v1/measurements/baseline?slice_id=embb|urllc

KPI are aggregated from two pinned real benchmark CSV files, NOT LIVE readings.
Only the active_policy field is read live from R1 by the existing read-only
controller module (if available). Switching time was not measured -> null.
No router, QoS, Docker state, or CSV is changed by this service.
"""

from __future__ import annotations

import csv
import math
import re
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, jsonify, request

from tv4_core_controller_readonly import CoreUnavailable, get_core_snapshot

app = Flask(__name__)

RESULTS_DIR = Path.home() / "TV4_KPI_Benchmark" / "results"
RTT_CSV = RESULTS_DIR / "core_rtt_aggregate_20261106_073217.csv"
IPERF_CSV = RESULTS_DIR / "core_iperf_aggregate_20261106_080010.csv"
VALID_SLICES = {"embb", "urllc"}
RTT_REQUIRED = {
    "scenario_id", "batch_id", "slice_id", "runs", "total_sent", "total_received",
    "overall_packet_loss_pct", "mean_rtt_ms", "pooled_rtt_p95_ms",
}
IPERF_REQUIRED = {
    "scenario_id", "batch_id", "slice_id", "protocol", "runs_requested",
    "successful_tests", "failed_tests", "receiver_mbps_mean",
    "tcp_retransmits_mean", "udp_jitter_ms_mean", "udp_total_lost",
    "udp_total_packets", "udp_weighted_loss_pct",
}


class BenchmarkError(Exception):
    pass


def _read_csv(file: Path, required: set[str]) -> list[dict[str, str]]:
    try:
        with file.open("r", newline="", encoding="utf-8-sig") as stream:
            reader = csv.DictReader(stream)
            missing = required - set(reader.fieldnames or [])
            if missing:
                raise BenchmarkError(f"Missing columns in {file.name}: {', '.join(sorted(missing))}")
            data = list(reader)
    except OSError as exc:
        raise BenchmarkError(f"Cannot open {file}: {exc}") from exc
    if not data:
        raise BenchmarkError(f"Empty CSV: {file.name}")
    return data


def _one(rows: list[dict[str, str]], slice_id: str, protocol: str | None = None) -> dict[str, str]:
    found = [r for r in rows if r["slice_id"].strip().lower() == slice_id
             and (protocol is None or r.get("protocol", "").strip().lower() == protocol)]
    if len(found) != 1:
        raise BenchmarkError(f"Expected exactly one row for slice={slice_id}, protocol={protocol}; got {len(found)}")
    return found[0]


def _numeric(row: dict[str, str], key: str, integer: bool = False) -> float | int:
    raw = row.get(key, "")
    if raw is None or not raw.strip():
        raise BenchmarkError(f"Missing numeric value: {key}")
    try:
        val = float(raw)
    except (ValueError, TypeError) as exc:
        raise BenchmarkError(f"Invalid {key} value: {raw!r}") from exc
    if not math.isfinite(val):
        raise BenchmarkError(f"Non-finite {key} value")
    if integer:
        if not val.is_integer():
            raise BenchmarkError(f"{key} must be an integer")
        return int(val)
    return val


def _read_measurements(slice_id: str) -> dict:
    rtt = _one(_read_csv(RTT_CSV, RTT_REQUIRED), slice_id)
    iperf_rows = _read_csv(IPERF_CSV, IPERF_REQUIRED)
    tcp = _one(iperf_rows, slice_id, "tcp")
    udp = _one(iperf_rows, slice_id, "udp")
    scenarios = {rtt["scenario_id"], tcp["scenario_id"], udp["scenario_id"]}
    if len(scenarios) != 1:
        raise BenchmarkError("RTT and TCP/UDP scenario_id do not match")
    for row in (tcp, udp):
        if _numeric(row, "successful_tests", integer=True) <= 0:
            raise BenchmarkError("iperf summary contains no successful tests")
    total_udp = _numeric(udp, "udp_total_packets", integer=True)
    lost_udp = _numeric(udp, "udp_total_lost", integer=True)
    if total_udp <= 0 or lost_udp < 0 or lost_udp > total_udp:
        raise BenchmarkError("Invalid UDP lost/total counts")
    weighted_loss_pct = 100.0 * lost_udp / total_udp
    reported = _numeric(udp, "udp_weighted_loss_pct")
    if abs(weighted_loss_pct - reported) > 0.01:
        raise BenchmarkError("UDP weighted loss does not agree with lost/total counters")
    sent_rtt = _numeric(rtt, "total_sent", integer=True)
    recv_rtt = _numeric(rtt, "total_received", integer=True)
    if sent_rtt <= 0 or recv_rtt < 0 or recv_rtt > sent_rtt:
        raise BenchmarkError("Invalid ping sent/received counters")
    return {
        "core_kpi": {
            "rtt_ms": _numeric(rtt, "mean_rtt_ms"),  # Average ICMP round-trip time, NOT one-way delay
            "rtt_p95_ms": _numeric(rtt, "pooled_rtt_p95_ms"),
            "rtt_packet_loss_pct": _numeric(rtt, "overall_packet_loss_pct"),
            "throughput_mbps": _numeric(tcp, "receiver_mbps_mean"),  # TCP receiver mean
            "tcp_retransmits_mean": _numeric(tcp, "tcp_retransmits_mean"),
            "udp_throughput_mbps": _numeric(udp, "receiver_mbps_mean"),
            "jitter_ms": _numeric(udp, "udp_jitter_ms_mean"),
            "packet_loss_pct": weighted_loss_pct,
            "packet_loss": lost_udp / total_udp,  # fraction 0..1 (for TV5); not percentage
            "packet_loss_unit": "fraction",
            "switching_time_ms": None,  # not measured: NEVER fabricate a value
            "active_policy": None,  # filled from R1 live; never inferred from historical CSV
        },
        "measurement": {
            "type": "historical_benchmark_aggregate",
            "is_live": False,
            "scenario_id": rtt["scenario_id"],
            "rtt_batch_id": rtt["batch_id"],
            "iperf_batch_id": tcp["batch_id"],
            "rtt_runs": _numeric(rtt, "runs", integer=True),
            "tcp_successful_tests": _numeric(tcp, "successful_tests", integer=True),
            "udp_successful_tests": _numeric(udp, "successful_tests", integer=True),
            "tcp_failed_tests": _numeric(tcp, "failed_tests", integer=True),
            "udp_failed_tests": _numeric(udp, "failed_tests", integer=True),
            "udp_total_lost": lost_udp,
            "udp_total_packets": total_udp,
            "source_files": [str(RTT_CSV), str(IPERF_CSV)],
            "measured_at_utc": None,  # timestamps not explicitly stated in the CSV contents
        },
    }


@app.get("/health")
def health():
    missing = [str(f) for f in (RTT_CSV, IPERF_CSV) if not f.is_file()]
    return jsonify({
        "service": "tv4-core-kpi-api",
        "status": "unavailable" if missing else "ok",
        "mode": "read_only_historical_csv",
        "bind": "127.0.0.1:8017",
        "missing_files": missing,
    }), 503 if missing else 200


@app.get("/core-kpi")
@app.get("/v1/measurements/baseline")
def core_kpi():
    slice_id = request.args.get("slice_id", "", type=str).strip().lower()
    if slice_id not in VALID_SLICES:
        return jsonify({"status": "error", "message": "slice_id must be embb or urllc"}), 400
    try:
        result = _read_measurements(slice_id)
    except BenchmarkError as exc:
        return jsonify({"status": "unavailable", "slice_id": slice_id,
                        "error": str(exc), "is_live": False}), 503

    # If R1 is temporarily absent, historical measurements remain valid,
    # but DO NOT invent an active policy or pretend it is known.
    try:
        snapshot = get_core_snapshot()
        policy = snapshot["slices"][slice_id]
        current = policy.get("active_policy")
        if current in {"high_bandwidth", "low_latency"} and policy.get("rule_present"):
            result["core_kpi"]["active_policy"] = current
            result["policy_observation"] = {
                "status": "observed", "checked_at_utc": snapshot["checked_at_utc"],
                "routing_table": policy["routing_table"],
                "active_policy": current,
                "note": "Policy read now; NOT necessarily the policy used during benchmark",
            }
        else:
            result["policy_observation"] = {"status": "unverified", "active_policy": None}
    except (CoreUnavailable, KeyError, TypeError) as exc:
        result["policy_observation"] = {"status": "unavailable", "active_policy": None,
                                        "error": str(exc)[:200]}

    return jsonify({
        "schema_version": "tv4-core-kpi.v0.1",
        "status": "ok",
        "slice_id": slice_id,
        "returned_at_utc": datetime.now(timezone.utc).isoformat(),
        **result,
        "note": "Historical 5-run benchmark snapshots. Not a real-time Core KPI feed. RTT is round-trip, not one-way; switching time unmeasured.",
    }), 200


if __name__ == "__main__":
    print("TV4 historical KPI API listening on http://127.0.0.1:8017", flush=True)
    app.run(host="127.0.0.1", port=8017, debug=False, use_reloader=False, threaded=True)
