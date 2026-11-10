#!/usr/bin/env python3
"""TV4 SRv6 Core Controller — stage 2: safe policy-apply PREVIEW.

This module deliberately NEVER changes a GNS3 node. It imports the already
verified stage-1 read-only collector, then exposes a validated preview of an
SRv6 route change via REST. Run on 127.0.0.1:8015 so the working read-only
service on port 8014 stays untouched.

Supported endpoints:
    GET  /health
    GET  /policies
    GET  /v1/policy
    POST /v1/policy/apply
    POST /apply-policy    (compatibility with TV5 proposed path)

Example request:
    {"request_id":"tv4-demo-001", "slice_id":"embb", "policy":"low_latency"}

Preview responses always say applied=false. No 'ip route replace' is executed.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from flask import Flask, jsonify, request

from tv4_core_controller_readonly import CoreUnavailable, get_core_snapshot

app = Flask(__name__)

DESTINATION = "2001:db8:40::/64"
END_SID = "2001:db8:400::4"
SLICES = {"embb": 100, "urllc": 101}
POLICIES = {
    "high_bandwidth": {
        "first_sid": "2001:db8:200::2", "via": "2001:db8:12::2",
        "device": "eth1", "path": "R1 -> R2 -> R4 -> Server",
    },
    "low_latency": {
        "first_sid": "2001:db8:300::3", "via": "2001:db8:13::3",
        "device": "eth2", "path": "R1 -> R3 -> R4 -> Server",
    },
}


def failure(message: str, status: int):
    return jsonify({"status": "error", "message": message, "applied": False}), status


@app.get("/health")
def health():
    try:
        snapshot = get_core_snapshot()
    except CoreUnavailable as exc:
        return jsonify({"service": "tv4-core-controller", "status": "unavailable",
                        "mode": "preview_only", "error": str(exc)}), 503
    return jsonify({"service": "tv4-core-controller", "status": snapshot["status"],
                    "mode": "preview_only", "applies_changes": False,
                    "port": 8015, "core_r1_container": "found"}), 200


@app.get("/policies")
@app.get("/v1/policy")
def policies():
    try:
        snapshot = get_core_snapshot()
        snapshot["mode"] = "preview_only"
        return jsonify(snapshot), 200
    except CoreUnavailable as exc:
        return jsonify({"status": "unavailable", "error": str(exc)}), 503


@app.post("/v1/policy/apply")
@app.post("/apply-policy")
def preview_apply():
    # Only accept small JSON objects with known fields; never use supplied
    # strings in OS or Docker commands.
    if request.content_length is not None and request.content_length > 8192:
        return failure("Request body is too large", 413)
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return failure("Expected a JSON object", 400)

    request_id = payload.get("request_id")
    slice_id = payload.get("slice_id")
    policy = payload.get("policy", payload.get("selected_policy"))
    if "policy" in payload and "selected_policy" in payload \
            and payload["policy"] != payload["selected_policy"]:
        return failure("policy and selected_policy disagree", 400)
    if not isinstance(request_id, str) or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,100}", request_id):
        return failure("Invalid request_id: use 1–100 letters, digits, _, ., :, -", 400)
    if slice_id not in SLICES:
        return failure("slice_id must be embb or urllc", 400)
    if policy not in POLICIES:
        return failure("policy must be high_bandwidth or low_latency", 400)

    try:
        snapshot = get_core_snapshot()
    except CoreUnavailable as exc:
        return jsonify({"status": "unavailable", "applied": False,
                        "request_id": request_id, "error": str(exc)}), 503

    current = snapshot["slices"][slice_id]
    if not current["rule_present"] or current["active_policy"] not in POLICIES:
        return jsonify({"status": "conflict", "applied": False,
                        "request_id": request_id, "slice_id": slice_id,
                        "message": "R1 source rule missing or current policy unrecognized; no preview generated"}), 409

    target = POLICIES[policy]
    table = SLICES[slice_id]
    planned_cmd = [
        "ip", "-6", "route", "replace", DESTINATION,
        "encap", "seg6", "mode", "encap", "segs",
        f"{target['first_sid']},{END_SID}",
        "via", target["via"], "dev", target["device"],
        "table", str(table),
    ]
    return jsonify({
        "status": "preview_only", "applied": False,
        "note": "No routes, policies, Docker nodes or QoS were changed.",
        "checked_at_utc": datetime.now(timezone.utc).isoformat(),
        "request_id": request_id,
        "slice_id": slice_id, "requested_policy": policy,
        "current_policy": current["active_policy"],
        "would_change": current["active_policy"] != policy,
        "routing_table": table, "source_ipv6": current["source_ipv6"],
        "target_path": target["path"],
        "command_preview": planned_cmd,
        "other_slice_table_untouched": SLICES["urllc" if slice_id == "embb" else "embb"],
    }), 200


if __name__ == "__main__":
    print("TV4 preview-only API: http://127.0.0.1:8015", flush=True)
    app.run(host="127.0.0.1", port=8015, debug=False, use_reloader=False)
