#!/usr/bin/env python3
"""TV4 Core Controller - stage 1 (read-only).

Runs on the GNS3 VM.  Only reads R1 routing configuration using
"sudo -n docker". It cannot change IPv6, SRv6, QoS or MTU.

Endpoints:
  GET /health
  GET /policies
  GET /v1/policy    (alias pending final team API contract)

Local test only: http://127.0.0.1:8014
"""

from __future__ import annotations

import re
import subprocess
from datetime import datetime, timezone
from flask import Flask, jsonify

app = Flask(__name__)

DESTINATION = "2001:db8:40::/64"
FINAL_SID = "2001:db8:400::4"
SLICES = {
    "embb": {
        "source": "2001:db8:10::2", "table": 100,
        "expected_policy": "high_bandwidth", "expected_first_sid": "2001:db8:200::2",
    },
    "urllc": {
        "source": "2001:db8:10::3", "table": 101,
        "expected_policy": "low_latency", "expected_first_sid": "2001:db8:300::3",
    },
}


class CoreUnavailable(Exception):
    pass


def run_readonly(args: list[str]) -> str:
    """Do not use a shell; all commands are fixed or internally constructed."""
    try:
        result = subprocess.run(args, text=True, capture_output=True,
                                timeout=8, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise CoreUnavailable(f"Cannot execute read-only command: {exc}") from exc
    if result.returncode != 0:
        details = (result.stderr or result.stdout).strip()
        raise CoreUnavailable(f"Read-only command failed: {details[:300]}")
    return result.stdout


def locate_r1() -> str:
    output = run_readonly(["sudo", "-n", "docker", "ps", "--format", "{{.ID}}\t{{.Names}}"])
    matches: list[str] = []
    for line in output.splitlines():
        parts = line.split("\t", 1)
        if len(parts) == 2 and re.fullmatch(r"GNS3\.R1\.[A-Za-z0-9_-]+", parts[1]):
            matches.append(parts[0])
    if len(matches) != 1:
        raise CoreUnavailable(f"Expected exactly one running GNS3.R1 container; found {len(matches)}")
    return matches[0]


def r1_command(container_id: str, *args: str) -> str:
    return run_readonly(["sudo", "-n", "docker", "exec", container_id, "ip", "-6", *args])


def get_core_snapshot() -> dict:
    container_id = locate_r1()
    rules = r1_command(container_id, "rule", "show")
    policies = {}
    for slice_id, config in SLICES.items():
        route = r1_command(container_id, "route", "show", "table", str(config["table"]))
        source = config["source"]
        table = config["table"]
        rule_present = any(
            re.search(rf"\bfrom\s+{re.escape(source)}(?:/128)?\b", line)
            and re.search(rf"\blookup\s+{table}\b", line)
            and f"to {DESTINATION}" in line
            for line in rules.splitlines()
        )
        has_srv6 = (DESTINATION in route and "encap seg6" in route
                    and FINAL_SID in route)
        via_r2 = "2001:db8:200::2" in route
        via_r3 = "2001:db8:300::3" in route
        if has_srv6 and via_r2 and not via_r3:
            active_policy = "high_bandwidth"
            path = "R1 -> R2 -> R4 -> Server"
        elif has_srv6 and via_r3 and not via_r2:
            active_policy = "low_latency"
            path = "R1 -> R3 -> R4 -> Server"
        else:
            active_policy = "unknown"
            path = "unverified"
        expected = config["expected_policy"]
        policies[slice_id] = {
            "source_ipv6": source,
            "routing_table": table,
            "active_policy": active_policy,
            "expected_policy": expected,
            "path": path,
            "rule_present": rule_present,
            "matches_expected_policy": rule_present and active_policy == expected,
            "route_raw": route.strip(),
        }
    return {
        "checked_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "ok" if all(p["matches_expected_policy"] for p in policies.values()) else "degraded",
        "slices": policies,
    }


@app.get("/health")
def health():
    try:
        locate_r1()
        return jsonify({"service": "tv4-core-controller", "status": "ok",
                        "core_r1_container": "found", "mode": "read_only"}), 200
    except CoreUnavailable as exc:
        return jsonify({"service": "tv4-core-controller", "status": "unavailable",
                        "mode": "read_only", "error": str(exc)}), 503


@app.get("/policies")
@app.get("/v1/policy")
def policies():
    try:
        return jsonify(get_core_snapshot()), 200
    except CoreUnavailable as exc:
        return jsonify({"status": "unavailable", "error": str(exc)}), 503


if __name__ == "__main__":
    print("TV4 read-only API starting on http://127.0.0.1:8014", flush=True)
    app.run(host="127.0.0.1", port=8014, debug=False, use_reloader=False)
