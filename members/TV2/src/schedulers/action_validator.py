from __future__ import annotations

import re
from typing import Any


VALID_SCHEDULERS = {
    "static",
    "queue_based",
    "qos_heuristic",
}

REQUEST_ID_PATTERN = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$"
)


class ActionValidationError(ValueError):
    """Lỗi khi Action của TV2 không hợp lệ."""


def validate_action(
    action: dict[str, Any],
    state: dict[str, Any],
    total_rb: int,
    require_all_rb: bool = True,
) -> dict[str, Any]:
    """Kiểm tra Action trước khi gửi sang RAN Simulator."""

    required_fields = {
        "schema_version",
        "request_id",
        "time_slot",
        "scheduler",
        "action_id",
        "rb_allocation",
    }

    action_fields = set(action)

    missing_fields = sorted(
        required_fields - action_fields
    )

    extra_fields = sorted(
        action_fields - required_fields
    )

    if missing_fields:
        raise ActionValidationError(
            f"Action thiếu trường: {missing_fields}"
        )

    if extra_fields:
        raise ActionValidationError(
            f"Action có trường không được phép: {extra_fields}"
        )

    if action["schema_version"] != "1.0.0":
        raise ActionValidationError(
            "schema_version phải bằng 1.0.0"
        )

    if action["schema_version"] != state["schema_version"]:
        raise ActionValidationError(
            "schema_version của Action không khớp State"
        )

    request_id = action["request_id"]

    if not isinstance(request_id, str):
        raise ActionValidationError(
            "request_id phải là chuỗi"
        )

    if REQUEST_ID_PATTERN.fullmatch(request_id) is None:
        raise ActionValidationError(
            "request_id không đúng pattern hoặc dài quá 64 ký tự"
        )

    time_slot = action["time_slot"]

    if type(time_slot) is not int or time_slot < 0:
        raise ActionValidationError(
            "time_slot phải là số nguyên không âm"
        )

    if time_slot != state["time_slot"]:
        raise ActionValidationError(
            f"time_slot không khớp: "
            f"expected={state['time_slot']}, "
            f"actual={time_slot}"
        )

    scheduler = action["scheduler"]

    if not isinstance(scheduler, str) or not scheduler:
        raise ActionValidationError(
            "scheduler phải là chuỗi không rỗng"
        )

    if scheduler not in VALID_SCHEDULERS:
        raise ActionValidationError(
            f"scheduler không được hỗ trợ: {scheduler!r}"
        )

    action_id = action["action_id"]

    if type(action_id) is not int or action_id < 0:
        raise ActionValidationError(
            "action_id phải là số nguyên không âm"
        )

    allocation = action["rb_allocation"]

    if not isinstance(allocation, dict):
        raise ActionValidationError(
            "rb_allocation phải là dictionary"
        )

    required_allocation_fields = {
        "embb",
        "urllc",
    }

    if set(allocation) != required_allocation_fields:
        raise ActionValidationError(
            "rb_allocation chỉ được chứa embb và urllc"
        )

    rb_embb = allocation["embb"]
    rb_urllc = allocation["urllc"]

    if type(rb_embb) is not int:
        raise ActionValidationError(
            "rb_allocation.embb phải là số nguyên"
        )

    if type(rb_urllc) is not int:
        raise ActionValidationError(
            "rb_allocation.urllc phải là số nguyên"
        )

    if rb_embb < 0 or rb_urllc < 0:
        raise ActionValidationError(
            "Số RB không được âm"
        )

    allocated_rb = rb_embb + rb_urllc

    if allocated_rb > total_rb:
        raise ActionValidationError(
            f"Tổng RB {allocated_rb} vượt quá "
            f"total_rb={total_rb}"
        )

    if require_all_rb and allocated_rb != total_rb:
        raise ActionValidationError(
            f"Tổng RB {allocated_rb} khác "
            f"total_rb={total_rb}"
        )

    return action
