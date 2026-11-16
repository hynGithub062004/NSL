#!/usr/bin/env python3
"""TV4 SRv6 Core Controller — unified lab API (stage 5).

Requires existing files in the SAME directory:
  tv4_core_controller_readonly.py
  tv4_core_controller_apply.py
  tv4_core_kpi_api.py

Runs on GNS3 VM using the established Flask virtualenv; binds ONLY
127.0.0.1:8018. Ports 8014, 8015, 8016 and 8017 remain unchanged.

Endpoints:
  GET  /health
  GET  /policies (alias /v1/policy)
  POST /v1/policy/apply (alias /apply-policy)
  GET  /core-kpi?slice_id=embb|urllc
  GET  /v1/measurements/baseline?slice_id=embb|urllc
  GET  /v1/events?limit=30

The policy application function is reused from the ALREADY-TESTED controlled
apply module: without `confirm`, it only previews; with `confirm=APPLY_TV4`
it changes only the requested R1 route table and verifies/attempts rollback.

The KPI function is reused from the ALREADY-TESTED CSV API and is HISTORICAL,
not real-time. `switching_time_ms` remains null until it is measured.

This is a private GNS3 LAB controller, not a secured production API. Use an
SSH tunnel for Windows testing. Do NOT expose port 8018 to public networks.
"""

from __future__ import annotations

import json
from collections import deque

from flask import Flask, jsonify, request

import tv4_core_controller_apply as policy_service
import tv4_core_kpi_api as kpi_service
from tv4_core_controller_readonly import CoreUnavailable, locate_r1


app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 8192
PORT = 8018


@app.get("/health")
def health():
    """Check both capabilities separately, without changing the network."""
    try:
        locate_r1()
        core_state = "ok"
    except CoreUnavailable:
        core_state = "unavailable"

    missing = [str(path) for path in (kpi_service.RTT_CSV, kpi_service.IPERF_CSV)
               if not path.is_file()]
    kpi_state = "ok" if not missing else "unavailable"
    overall = "ok" if core_state == "ok" and kpi_state == "ok" else "degraded"
    return jsonify({
        "service": "tv4-core-unified",
        "status": overall,
        "mode": "controlled_apply_plus_historical_kpi",
        "bind": f"127.0.0.1:{PORT}",
        "core_controller": {"status": core_state, "requires_confirmation": True},
        "core_kpi": {"status": kpi_state, "is_live": False,
                     "missing_files": missing},
    }), 200 if overall == "ok" else 503


# Reuse previously tested request handling and route / CSV validation.
# Register on this NEW Flask app rather than importing an existing .app,
# so /health accurately reflects 8018, not an old port.
app.add_url_rule("/policies", endpoint="unified_policies", view_func=policy_service.get_policies, methods=["GET"])
app.add_url_rule("/v1/policy", endpoint="unified_policy_alias", view_func=policy_service.get_policies, methods=["GET"])
app.add_url_rule("/v1/policy/apply", endpoint="unified_apply", view_func=policy_service.apply_policy, methods=["POST"])
app.add_url_rule("/apply-policy", endpoint="unified_apply_alias", view_func=policy_service.apply_policy, methods=["POST"])
app.add_url_rule("/core-kpi", endpoint="unified_kpi", view_func=kpi_service.core_kpi, methods=["GET"])
app.add_url_rule("/v1/measurements/baseline", endpoint="unified_kpi_baseline", view_func=kpi_service.core_kpi, methods=["GET"])


@app.get("/v1/events")
def events():
    """Read best-effort policy audit events (not traffic measurements)."""
    raw_limit = request.args.get("limit", "30")
    try:
        limit = int(raw_limit)
    except (TypeError, ValueError):
        return jsonify({"status": "error", "message": "limit must be an integer between 1 and 100"}), 400
    if limit < 1 or limit > 100:
        return jsonify({"status": "error", "message": "limit must be an integer between 1 and 100"}), 400

    path = policy_service.AUDIT_FILE
    if not path.exists():
        return jsonify({"status": "ok", "events": [], "count": 0,
                        "audit_type": "best_effort_policy_events"}), 200

    try:
        with path.open("r", encoding="utf-8") as stream:
            # Efficiently retain only the most recent N lines.
            lines = deque(stream, maxlen=limit)
        parsed = [json.loads(line) for line in lines if line.strip()]
    except (OSError, ValueError) as exc:
        return jsonify({"status": "unavailable", "message": "Cannot read valid policy audit events",
                        "details": str(exc)[:160]}), 503

    return jsonify({"status": "ok", "events": parsed, "count": len(parsed),
                    "audit_type": "best_effort_policy_events",
                    "note": "Recorded requests only; not proof of traffic SLA or fault recovery"}), 200


if __name__ == "__main__":
    print(f"TV4 unified LAB API on http://127.0.0.1:{PORT}", flush=True)
    app.run(host="127.0.0.1", port=PORT, debug=False, use_reloader=False, threaded=True)
