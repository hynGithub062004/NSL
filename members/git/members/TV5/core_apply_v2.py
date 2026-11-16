"""TV5 B07: controlled Core Apply route; does not change SRv6 without explicit enable/confirm.

This module adds endpoints to an EXISTING FastAPI app via app.include_router(router).
Use only on the local lab host (127.0.0.1), with TV4 supervising the GNS3 core.
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from members.TV5.core_client import CoreAPIError, CoreClient

router = APIRouter(tags=["TV4 Core - Controlled Apply"])


class ApplyPolicyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$")
    slice_id: Literal["embb", "urllc"]
    policy: Literal["high_bandwidth", "low_latency"]
    confirm: Literal["APPLY_TV4"]
    # Provenance is recorded by TV5, NEVER sent to TV4's four-field contract.
    run_id: str | None = None
    scenario_id: str | None = None
    seed: int | None = None
    scheduler: str | None = None
    time_slot: int | None = Field(default=None, ge=0)


def get_client() -> CoreClient:
    return CoreClient(os.getenv("TV4_CORE_URL", "http://127.0.0.1:18018"), timeout=5)


def live_core_health() -> dict:
    """Live network probe; separate from historical Core KPI data."""
    try:
        payload = get_client().health()
        connected = isinstance(payload, dict) and payload.get("status") == "ok"
        return {"core_connected": connected, "core_health": payload}
    except (CoreAPIError, ValueError) as exc:
        return {"core_connected": False, "core_error": str(exc)}


def recommend_policy(slice_id: str, current_policy: str | None = None) -> dict:
    """Baseline service-profile rule, NOT trained/adaptive RAN-Core optimization."""
    if slice_id not in ("embb", "urllc"):
        raise ValueError("slice_id must be embb or urllc")
    target = "high_bandwidth" if slice_id == "embb" else "low_latency"
    return {
        "slice_id": slice_id,
        "policy": target,
        "rule": "service_profile_baseline_v1",
        "reason": "eMBB bandwidth preference" if slice_id == "embb" else "URLLC latency preference",
        "change_needed": None if current_policy is None else current_policy != target,
        "auto_apply": False,
        "note": "Experimental baseline only; does not use live RAN telemetry or optimize E2E KPI."
    }


@router.get("/core/recommend-policy/{slice_id}")
def core_recommend(slice_id: Literal["embb", "urllc"]):
    return recommend_policy(slice_id)


def _active_policy(data, slice_id: str) -> str | None:
    """Best-effort extractor. If Core schema is not recognized, fail verification CLOSED."""
    active_keys = ("active_policy", "current_policy", "selected_policy")
    containers = ("slices", "policies", "active_policies", "current_policies", "slice_policies", "data")

    def extract_node(node):
        if not isinstance(node, dict):
            return None
        for k in active_keys:
            if node.get(k) in ("high_bandwidth", "low_latency"):
                return node[k]
        if node.get("policy") in ("high_bandwidth", "low_latency") and node.get("slice_id") == slice_id:
            return node["policy"]
        return None

    if not isinstance(data, dict):
        return None
    for key in (slice_id,):
        if key in data:
            x = data[key]
            if isinstance(x, str) and x in ("high_bandwidth", "low_latency"):
                return x
            v = extract_node(x)
            if v:
                return v
    for key in containers:
        x = data.get(key)
        if isinstance(x, dict):
            v = _active_policy(x, slice_id)
            if v:
                return v
        elif isinstance(x, list):
            for item in x:
                if isinstance(item, dict) and item.get("slice_id") == slice_id:
                    v = extract_node(item)
                    if v:
                        return v
    return None


def _audit(record: dict):
    dest = Path(os.getenv("TV5_CORE_AUDIT_DIR", str(Path(__file__).resolve().parent / "results" / "saved_tests" / "logs")))
    dest.mkdir(parents=True, exist_ok=True)
    with (dest / "TV5_B07_CoreApply_Events.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps({"timestamp_utc": datetime.now(timezone.utc).isoformat(), **record}, ensure_ascii=False, default=str) + "\n")


def _core_error(exc: CoreAPIError, operation: str) -> HTTPException:
    msg = str(exc)
    match = re.search(r"TV4 HTTP error:\s*(\d{3})", msg)
    if "Cannot connect" in msg:
        code = 503
    elif match and int(match.group(1)) in (400, 404, 409, 422):
        code = int(match.group(1))
    else:
        code = 502
    return HTTPException(status_code=code, detail={"stage": operation, "upstream_error": msg})


@router.post("/core/apply-policy")
def controlled_apply(payload: ApplyPolicyRequest):
    """Conservative confirmation + read-after-write verification.

    HTTP 200 = verified; 202 = Controller claims apply but state schema unverified;
    HTTP 409 = rejected/inconsistent; 403 = Apply disabled; 502/503 = Core failure.
    """
    if os.getenv("TV5_ENABLE_CORE_APPLY", "0") != "1":
        raise HTTPException(403, "TV5 Apply disabled. Set TV5_ENABLE_CORE_APPLY=1 for supervised lab testing.")

    client = get_client()
    try:
        before = client.policies()
    except CoreAPIError as exc:
        _audit({"stage": "precheck_failed", "request_id": payload.request_id, "error": str(exc)})
        raise _core_error(exc, "precheck") from exc

    prior = _active_policy(before, payload.slice_id)
    other_slice = "urllc" if payload.slice_id == "embb" else "embb"
    other_before = _active_policy(before, other_slice)
    meta = payload.model_dump(exclude={"confirm"})

    if prior == payload.policy:
        result = {"status": "no_change", "applied": False,
                  "reason": "Requested policy already active; no Core Apply sent",
                  "request_id": payload.request_id, "slice_id": payload.slice_id,
                  "policy": payload.policy, "verified": True, "context": meta}
        _audit({"stage": "no_change", **result})
        return result

    try:
        # CoreClient.apply_policy must be added as documented in README.
        response = client.apply_policy(payload.request_id, payload.slice_id, payload.policy, payload.confirm)
    except CoreAPIError as exc:
        _audit({"stage": "apply_upstream_error", "request_id": payload.request_id,
                "error": str(exc), "warning": "Outcome may be unknown: DO NOT automatically retry with another request_id"})
        raise _core_error(exc, "apply; outcome_may_be_unknown") from exc

    try:
        after = client.policies()
    except CoreAPIError as exc:
        record = {"status": "verification_unavailable", "applied": response.get("applied") if isinstance(response, dict) else None,
                  "verified": False, "request_id": payload.request_id, "core_response": response,
                  "warning": "Apply may already have occurred. Read Core state before retrying.",
                  "error": str(exc), "context": meta}
        _audit({"stage": "verification_unavailable", **record})
        return JSONResponse(status_code=202, content=record)

    changed = _active_policy(after, payload.slice_id)
    other_after = _active_policy(after, other_slice)
    controller_applied = isinstance(response, dict) and response.get("applied") is True
    routing_canonical = after.get("canonical_valid") is not False if isinstance(after, dict) else False
    other_unchanged = None if None in (other_before, other_after) else other_before == other_after
    target_matches = None if changed is None else changed == payload.policy
    verified = bool(controller_applied and routing_canonical and target_matches is True and other_unchanged is True)
    rejected = not controller_applied or routing_canonical is False or target_matches is False or other_unchanged is False
    status = "verified" if verified else ("inconsistent_or_rejected" if rejected else "manual_verification_required")
    result = {"status": status, "verified": verified,
              "request_id": payload.request_id, "slice_id": payload.slice_id,
              "requested_policy": payload.policy,
              "policy_before": prior, "policy_after": changed,
              "other_slice": other_slice, "other_policy_before": other_before,
              "other_policy_after": other_after,
              "controller_response": response, "core_policies_after": after,
              "context": meta,
              "warning": None if verified else "DO NOT assume successful SRv6 switch or automatically retry. Check TV4 routing tables."}
    _audit({"stage": "apply_verification", **result})
    return JSONResponse(status_code=200 if verified else (409 if rejected else 202), content=result)
