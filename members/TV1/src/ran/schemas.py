"""Runtime validation for the versioned handoff contracts."""

from __future__ import annotations

import math
import re
from typing import Any


SCHEMA_VERSION = "1.0.0"
REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


class SchemaValidationError(ValueError):
    """Raised when a State or Action violates the integration contract."""


def _require(mapping: dict[str, Any], keys: set[str], label: str) -> None:
    missing = sorted(keys - mapping.keys())
    if missing:
        raise SchemaValidationError(f"{label} missing fields: {', '.join(missing)}")


def _finite_number(value: Any, label: str) -> None:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise SchemaValidationError(f"{label} must be numeric")
    if not math.isfinite(float(value)):
        raise SchemaValidationError(f"{label} must be finite")


def validate_state(state: dict[str, Any]) -> None:
    _require(
        state,
        {"schema_version", "time_slot", "scenario_id", "seed", "embb", "urllc"},
        "State",
    )
    if state["schema_version"] != SCHEMA_VERSION:
        raise SchemaValidationError("Unsupported State schema_version")
    if not isinstance(state["time_slot"], int) or state["time_slot"] < 0:
        raise SchemaValidationError("State time_slot must be a non-negative integer")
    _require(state["embb"], {"queue_bits", "cqi"}, "State.embb")
    _require(
        state["urllc"],
        {"queue_packets", "queue_bits", "cqi", "oldest_packet_delay_ms", "deadline_ms"},
        "State.urllc",
    )
    if state["embb"]["queue_bits"] < 0 or state["urllc"]["queue_packets"] < 0:
        raise SchemaValidationError("State queue values cannot be negative")


def validate_action(action: dict[str, Any], total_rb: int, expected_slot: int) -> None:
    _require(
        action,
        {"schema_version", "request_id", "time_slot", "scheduler", "action_id", "rb_allocation"},
        "Action",
    )
    if action["schema_version"] != SCHEMA_VERSION:
        raise SchemaValidationError("Unsupported Action schema_version")
    if action["time_slot"] != expected_slot:
        raise SchemaValidationError(
            f"Action time_slot={action['time_slot']} does not match current slot={expected_slot}"
        )
    if not isinstance(action["request_id"], str) or not REQUEST_ID_PATTERN.fullmatch(
        action["request_id"]
    ):
        raise SchemaValidationError("Action request_id has an invalid format")
    if not isinstance(action["scheduler"], str) or not action["scheduler"].strip():
        raise SchemaValidationError("Action scheduler must be a non-empty string")
    allocation = action["rb_allocation"]
    _require(allocation, {"embb", "urllc"}, "Action.rb_allocation")
    for slice_name in ("embb", "urllc"):
        value = allocation[slice_name]
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise SchemaValidationError(f"Action RB for {slice_name} must be a non-negative integer")
    allocated = allocation["embb"] + allocation["urllc"]
    if allocated > total_rb:
        raise SchemaValidationError(f"Action allocates {allocated} RB but total_rb={total_rb}")


def validate_kpi(kpi: dict[str, Any]) -> None:
    required = {
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
    _require(kpi, required, "RAN KPI")
    for field in required - {
        "schema_version",
        "request_id",
        "scenario_id",
        "algorithm",
        "time_slot",
        "seed",
    }:
        _finite_number(kpi[field], f"RAN KPI.{field}")

