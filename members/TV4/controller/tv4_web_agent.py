#!/usr/bin/env python3
"""Optional lab extension for the existing TV4 Flask controller on GNS3 VM.

Launch in this directory: python tv4_web_agent.py. Use SSH tunnel to access.
This measures fresh traffic and never replaces the historical /core-kpi API.
"""
from __future__ import annotations

import json
import re
import subprocess
import threading
import time
from datetime import datetime, timezone

from flask import jsonify, request
from tv4_core_controller_unified import app
from tv4_core_controller_readonly import locate_r1

GUARD = threading.RLock()
VALID = {"normal", "delay", "outage", "loss", "recovery"}
SOURCES = {"embb": "2001:db8:10::2", "urllc": "2001:db8:10::3"}
TARGET = "2001:db8:40::2"
ACTIVE = {"scenario": "unknown", "run_id": None}


@app.get("/v1/lab/health")
def lab_health():
    try:
        locate_r1()
        nodes = {name: docker_node(name) for name in ("Client", "R2", "R3")}
        return jsonify({"status": "ok", "mode": "live_lab_agent", "nodes": list(nodes),
                        "measurement_is_live": True, "active": ACTIVE})
    except Exception as exc:
        return jsonify({"status": "unavailable", "error": str(exc)[:250]}), 503


def docker_node(label):
    output = subprocess.run(["sudo", "-n", "docker", "ps", "--filter", f"name=GNS3.{label}.",
                             "--format", "{{.ID}}"], text=True, capture_output=True, timeout=10, check=True).stdout
    ids = output.strip().splitlines()
    if len(ids) != 1:
        raise RuntimeError(f"Expected one running GNS3.{label} container, found {len(ids)}")
    return ids[0]


def run(argv, timeout=30):
    return subprocess.run(argv, text=True, capture_output=True, timeout=timeout, check=True).stdout


def qdisc(node, delay_ms, loss_pct, rate_mbit):
    cid = docker_node(node)
    run(["sudo", "-n", "docker", "exec", cid, "tc", "qdisc", "replace", "dev", "eth1", "root",
         "netem", "delay", f"{delay_ms}ms", "loss", f"{loss_pct}%", "rate", f"{rate_mbit}mbit",
         "limit", "1000"])


def policy(slice_id, name, run_id):
    # Reuse TV4's verified apply endpoint and its idempotency/rollback logic.
    with app.test_client() as client:
        result = client.post("/apply-policy", json={"request_id": f"web-{run_id}-{slice_id}-{name}-{time.time_ns()}",
                                                  "slice_id": slice_id, "policy": name, "confirm": "APPLY_TV4"})
    if result.status_code >= 400:
        raise RuntimeError(f"TV4 policy apply failed ({result.status_code}): {result.get_json()}")
    if result.get_json().get("applied") is not True:
        raise RuntimeError(f"TV4 policy was not applied: {result.get_json()}")
    return result.get_json()


def baseline(run_id):
    qdisc("R2", 5, 0.1, 100)
    qdisc("R3", 1, 0.01, 30)
    policy("embb", "high_bandwidth", run_id)
    policy("urllc", "low_latency", run_id)


@app.post("/v1/lab/scenario")
def set_scenario():
    payload = request.get_json(silent=True) or {}
    scenario, run_id = payload.get("scenario"), payload.get("run_id")
    if scenario not in VALID or not isinstance(run_id, str) or not re.fullmatch(r"[a-f0-9]{16}", run_id):
        return jsonify({"error": "Invalid scenario or run_id"}), 400
    if not GUARD.acquire(blocking=False):
        return jsonify({"error": "Lab busy"}), 409
    try:
        locate_r1()
        baseline(run_id)
        if scenario == "delay":
            qdisc("R2", 35, 0.1, 100)
        elif scenario == "loss":
            qdisc("R2", 5, 10, 100)
            qdisc("R3", 1, 2, 30)
        elif scenario == "outage":
            qdisc("R2", 5, 100, 100)
            policy("embb", "low_latency", run_id)
        ACTIVE.update(scenario=scenario, run_id=run_id)
        return jsonify({"status": "applied", "scenario": scenario, "run_id": run_id,
                        "note": "recovery restores the normal policy and qdisc; no switching-time claim"})
    except Exception as exc:
        try:
            baseline(run_id)
            ACTIVE.update(scenario="normal", run_id=run_id)
        except Exception:
            ACTIVE.update(scenario="unknown", run_id=run_id)
        return jsonify({"error": str(exc)[:300], "state": ACTIVE}), 503
    finally:
        GUARD.release()


def ping(cid, source):
    proc = subprocess.run(["sudo", "-n", "docker", "exec", "-e", "LC_ALL=C", cid, "ping", "-6", "-n", "-I", source,
                           "-i", "0.2", "-c", "10", TARGET], text=True, capture_output=True, timeout=15)
    raw = proc.stdout
    stat = re.search(r"(\d+) packets transmitted, (\d+) received, ([\d.]+)% packet loss", raw)
    samples = [float(n) for n in re.findall(r"\btime=([\d.]+)\s*ms", raw)]
    if not stat:
        raise RuntimeError("Could not parse ping result")
    samples.sort()
    return {"rtt_ms": round(sum(samples) / len(samples), 4) if samples else None,
            "rtt_p95_ms": samples[max(0, (95 * len(samples) + 99) // 100 - 1)] if samples else None,
            "ping_loss_pct": float(stat.group(3)), "sent": int(stat.group(1)), "received": int(stat.group(2))}


def iperf(cid, source, udp=False):
    command = ["sudo", "-n", "docker", "exec", cid, "iperf3", "-c", TARGET, "-B", source,
               "-p", "5201", "-t", "3", "-J"]
    if udp:
        command += ["-u", "-b", "20M", "-l", "1200"]
    else:
        command += ["-M", "1200"]
    result = json.loads(run(command, timeout=45))
    if result.get("error"):
        raise RuntimeError("iperf3: " + str(result["error"]))
    end = result["end"]
    if udp:
        summary = end["sum"]
        return {"udp_throughput_mbps": summary["bits_per_second"] / 1e6,
                "jitter_ms": summary["jitter_ms"], "packet_loss": summary["lost_percent"] / 100}
    summary = end["sum_received"]
    return {"throughput_mbps": summary["bits_per_second"] / 1e6}


@app.post("/v1/lab/measure")
def measure():
    payload = request.get_json(silent=True) or {}
    run_id = payload.get("run_id")
    if run_id != ACTIVE["run_id"] or payload.get("scenario") != ACTIVE["scenario"]:
        return jsonify({"error": "Scenario and run_id must match the active lab configuration"}), 409
    if not GUARD.acquire(blocking=False):
        return jsonify({"error": "Lab busy"}), 409
    try:
        cid = docker_node("Client")
        results = {}
        for slice_id, source in SOURCES.items():
            data = ping(cid, source)
            data.update(iperf(cid, source))
            data.update(iperf(cid, source, udp=True))
            results[slice_id] = data
        return jsonify({"status": "ok", "run_id": run_id, "scenario": ACTIVE["scenario"],
                        "measurement": {"is_live": True, "method": "sequential_ping_tcp_udp",
                                        "measured_at_utc": datetime.now(timezone.utc).isoformat(),
                                        "note": "Core traffic is measured sequentially, independently of RAN simulated packets."},
                        "slices": results})
    except Exception as exc:
        return jsonify({"error": str(exc)[:350] + " stderr=" + str(getattr(exc, "stderr", ""))[-400:] + " stdout=" + str(getattr(exc, "stdout", ""))[-400:], "measurement": {"is_live": False}}), 503
    finally:
        GUARD.release()


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8018, debug=False, use_reloader=False, threaded=True)
