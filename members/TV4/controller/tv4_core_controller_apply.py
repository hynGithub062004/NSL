#!/usr/bin/env python3
"""TV4 SRv6 Core Controller — stage 3, controlled route changes (lab only).

Run on GNS3 VM: ~/.venv/bin/python tv4_core_controller_apply.py
Binds 127.0.0.1:8016 (LOCAL TEST ONLY). Keeps 8014/8015 untouched.

Endpoints:
  GET  /health
  GET  /policies
  GET  /v1/policy
  POST /v1/policy/apply, /apply-policy

Request example:
  {"request_id":"tv4-lab-001", "slice_id":"embb",
   "policy":"low_latency", "confirm":"APPLY_TV4"}

Without confirm, endpoint returns a safe preview. With confirm, changes only
one R1 policy table, verifies both tables and source rules, and rolls back on
failed verification. Every change and request must be made only on the user's
OWN GNS3 lab. No external public bind, no shell commands from JSON.

Durable idempotency of *successful* confirmed requests via JSON ledger.
The program's rollback checks routing configuration, NOT user traffic/QoS.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import threading
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, jsonify, request
from tv4_core_controller_readonly import CoreUnavailable, get_core_snapshot, locate_r1

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 8192

DESTINATION = "2001:db8:40::/64"
END_SID = "2001:db8:400::4"
SLICES = {"embb": (100, "2001:db8:10::2"), "urllc": (101, "2001:db8:10::3")}
POLICIES = {
    "high_bandwidth": {"sid": "2001:db8:200::2", "via": "2001:db8:12::2", "dev": "eth1", "path": "R1 -> R2 -> R4 -> Server"},
    "low_latency": {"sid": "2001:db8:300::3", "via": "2001:db8:13::3", "dev": "eth2", "path": "R1 -> R3 -> R4 -> Server"},
}
LOCK = threading.RLock()
DATA_DIR = Path(__file__).resolve().parent
LEDGER_FILE = DATA_DIR / "successful_requests.json"
AUDIT_FILE = DATA_DIR / "policy_events.jsonl"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _run(args: list[str], timeout: float = 9) -> str:
    """Executes a FIXED non-shell argument vector; no user-defined OS args."""
    try:
        result = subprocess.run(args, text=True, capture_output=True, timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise CoreUnavailable(f"Command not available: {exc}") from exc
    if result.returncode:
        raise CoreUnavailable((result.stderr or result.stdout).strip()[:500] or f"exit={result.returncode}")
    return result.stdout


def _route_args(policy: str, table: int) -> list[str]:
    p = POLICIES[policy]
    return ["ip", "-6", "route", "replace", DESTINATION,
            "encap", "seg6", "mode", "encap", "segs", f"{p['sid']},{END_SID}",
            "via", p["via"], "dev", p["dev"], "table", str(table)]


def _apply_route(container: str, policy: str, table: int) -> None:
    _run(["sudo", "-n", "docker", "exec", container, *_route_args(policy, table)])


def _matches_canonical(route: str, policy: str) -> bool:
    p = POLICIES[policy]
    return (DESTINATION in route and "encap seg6" in route
            and "mode encap" in route and p["sid"] in route
            and END_SID in route and re.search(rf"\bvia\s+{re.escape(p['via'])}\b", route)
            and re.search(rf"\bdev\s+{re.escape(p['dev'])}\b", route)
            and all(other["sid"] not in route for name, other in POLICIES.items() if name != policy))


def _policy_of(item: dict) -> str | None:
    val = item.get("active_policy")
    if val in POLICIES and item.get("rule_present") and _matches_canonical(item.get("route_raw", ""), val):
        return val
    return None


def _ledger_load() -> dict:
    if not LEDGER_FILE.exists():
        return {}
    try:
        value = json.loads(LEDGER_FILE.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError("Expected an object")
        return value
    except (ValueError, OSError) as exc:
        raise CoreUnavailable(f"Cannot read idempotency ledger; not applying policy: {exc}") from exc


def _ledger_save(data: dict) -> None:
    temp = LEDGER_FILE.with_suffix(".json.tmp")
    try:
        with temp.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2, sort_keys=True)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp, LEDGER_FILE)
    except OSError as exc:
        raise CoreUnavailable(f"Could not save request ledger: {exc}") from exc


def _audit(event: dict) -> None:
    # Best-effort audit only. Its failure cannot cause a false routing state.
    try:
        with AUDIT_FILE.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
    except OSError:
        pass


def _json(data: dict, code: int = 200):
    return jsonify(data), code


def _error(message: str, code: int, **extra):
    return _json({"status": "error", "applied": False, "message": message, **extra}, code)


@app.get("/health")
def health():
    try:
        locate_r1()
    except CoreUnavailable as exc:
        return _json({"status": "unavailable", "mode": "controlled_apply", "error": str(exc)}, 503)
    return _json({"service": "tv4-core-controller", "status": "ok", "mode": "controlled_apply",
                  "bind": "127.0.0.1:8016", "r1": "found", "changes_require_confirm": True})


@app.get("/policies")
@app.get("/v1/policy")
def get_policies():
    try:
        snap = get_core_snapshot()
        snap["mode"] = "controlled_apply"
        # Stage 1 'degraded' just means a route differs from the initial policy,
        # so expose current policy *and* canonical verification independently.
        snap["canonical_valid"] = all(_policy_of(p) is not None for p in snap["slices"].values())
        snap["baseline_status"] = snap["status"]
        snap["status"] = "ok" if snap["canonical_valid"] else "degraded"
        return _json(snap)
    except CoreUnavailable as exc:
        return _json({"status": "unavailable", "error": str(exc)}, 503)


@app.post("/v1/policy/apply")
@app.post("/apply-policy")
def apply_policy():
    value = request.get_json(silent=True)
    if not isinstance(value, dict):
        return _error("Expected a JSON object", 400)
    rid = value.get("request_id")
    slice_id = value.get("slice_id")
    policy = value.get("policy", value.get("selected_policy"))
    if not isinstance(rid, str) or re.fullmatch(r"[A-Za-z0-9_.:-]{1,100}", rid) is None:
        return _error("Invalid request_id (1-100 ASCII letters/digits/_.:-)", 400)
    if slice_id not in SLICES or policy not in POLICIES:
        return _error("slice_id must be embb/urllc; policy must be high_bandwidth/low_latency", 400, request_id=rid)
    if "policy" in value and "selected_policy" in value and value["policy"] != value["selected_policy"]:
        return _error("policy and selected_policy disagree", 400, request_id=rid)
    confirmed = value.get("confirm") == "APPLY_TV4"
    if "confirm" in value and not confirmed:
        return _error("confirm must equal APPLY_TV4, or be omitted for preview", 400, request_id=rid)

    with LOCK:
        try:
            ledger = _ledger_load() if confirmed else {}
            prior = ledger.get(rid)
            if prior is not None:
                if prior["slice_id"] != slice_id or prior["policy"] != policy:
                    return _error("request_id already used for different action", 409, request_id=rid)
                response = dict(prior["response"])
                response["idempotent_replay"] = True
                response["note"] = "Stored result of prior request; check /policies for live state"
                return _json(response)

            before = get_core_snapshot()
            for key, item in before["slices"].items():
                if _policy_of(item) is None:
                    return _error(f"R1 {key} rule/route is missing or noncanonical; refusing change", 409, request_id=rid)
            current = before["slices"][slice_id]["active_policy"]
            table, source = SLICES[slice_id]
            path = POLICIES[policy]["path"]
            base = {"request_id": rid, "slice_id": slice_id, "selected_policy": policy,
                    "requested_policy": policy, "previous_policy": current,
                    "routing_table": table, "source_ipv6": source, "path": path,
                    "other_slice_table": SLICES["urllc" if slice_id == "embb" else "embb"][0]}
            if not confirmed:
                return _json({**base, "status": "preview_only", "applied": False,
                              "would_change": current != policy, "command_preview": _route_args(policy, table),
                              "note": "Add confirm=APPLY_TV4 in a separate request to apply for real."})

            r1 = locate_r1()
            # Idempotent no-op is a valid successful confirmed operation.
            changed = current != policy
            if changed:
                try:
                    _apply_route(r1, policy, table)
                    after = get_core_snapshot()
                    other = "urllc" if slice_id == "embb" else "embb"
                    if (_policy_of(after["slices"][slice_id]) != policy
                            or after["slices"][other]["route_raw"] != before["slices"][other]["route_raw"]
                            or not after["slices"][other]["rule_present"]
                            or not after["slices"][slice_id]["rule_present"]):
                        raise CoreUnavailable("Route verification failed or other slice was modified")
                except CoreUnavailable as exc:
                    message = str(exc)
                    try:
                        _apply_route(r1, current, table)
                        restored = get_core_snapshot()
                        if (_policy_of(restored["slices"][slice_id]) != current
                                or restored["slices"]["urllc" if slice_id == "embb" else "embb"]["route_raw"]
                                    != before["slices"]["urllc" if slice_id == "embb" else "embb"]["route_raw"]):
                            raise CoreUnavailable("Rollback verification did not pass")
                        _audit({"timestamp": utc_now(), "request_id": rid, "slice_id": slice_id,
                                "attempted_policy": policy, "status": "rolled_back", "cause": message})
                        return _json({**base, "status": "rolled_back", "applied": False,
                                      "error": message, "restored_policy": current}, 500)
                    except CoreUnavailable as rollback_exc:
                        _audit({"timestamp": utc_now(), "request_id": rid, "status": "rollback_failed",
                                "apply_error": message, "rollback_error": str(rollback_exc)})
                        return _json({**base, "status": "rollback_failed", "applied": False,
                                      "error": message, "rollback_error": str(rollback_exc),
                                      "action_required": "Inspect R1 tables 100 and 101; do not repeat writes automatically"}, 500)

            resp = {**base, "status": "applied" if changed else "already_active", "applied": True,
                    "changed": changed, "verified": True, "other_slice_untouched": True,
                    "checked_at_utc": utc_now(),
                    "note": "Routing config verified; this is not a packet-loss or connectivity SLA test"}
            ledger[rid] = {"slice_id": slice_id, "policy": policy, "response": resp}
            try:
                _ledger_save(ledger)
            except CoreUnavailable as exc:
                # Route may already be changed: don't falsely report failure as rollback.
                _audit({"timestamp": utc_now(), "request_id": rid, "status": "applied_ledger_error", "error": str(exc)})
                return _json({**resp, "status": "applied_not_recorded", "ledger_error": str(exc)}, 500)
            _audit({"timestamp": utc_now(), "request_id": rid, "status": resp["status"],
                    "previous_policy": current, "requested_policy": policy})
            return _json(resp)
        except CoreUnavailable as exc:
            return _json({"status": "unavailable", "applied": False, "request_id": rid, "error": str(exc)}, 503)


if __name__ == "__main__":
    print("TV4 lab apply API listening on http://127.0.0.1:8016", flush=True)
    app.run(host="127.0.0.1", port=8016, debug=False, use_reloader=False, threaded=True)
