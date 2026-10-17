from __future__ import annotations

import re
from abc import ABC, abstractmethod
from typing import Any


REQUEST_ID_INVALID_CHARACTERS = re.compile(
    r"[^A-Za-z0-9._-]"
)


class BaseScheduler(ABC):
    """Giao diện chung cho các scheduler truyền thống của TV2."""

    name = "base"

    @abstractmethod
    def select_action(
        self,
        state: dict[str, Any],
        config: dict[str, Any],
        request_id: str | None = None,
    ) -> dict[str, Any]:
        """Nhận State của TV1 và trả Action theo Contract 1.0.0."""
        raise NotImplementedError

    @staticmethod
    def generate_request_id(
        state: dict[str, Any],
    ) -> str:
        """Tạo request_id xác định khi chưa có Orchestrator."""

        raw_request_id = (
            f"{state['scenario_id']}-"
            f"{state['seed']}-"
            f"{state['time_slot']}"
        )

        request_id = REQUEST_ID_INVALID_CHARACTERS.sub(
            "-",
            raw_request_id,
        )

        request_id = request_id[:64]

        if not request_id:
            request_id = "request"

        if not request_id[0].isalnum():
            request_id = f"r{request_id}"

        return request_id[:64]

    def build_action(
        self,
        state: dict[str, Any],
        rb_embb: int,
        rb_urllc: int,
        action_id: int,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        """Tạo Action đúng action.schema.json."""

        if request_id is None:
            request_id = self.generate_request_id(state)

        return {
            "schema_version": state["schema_version"],
            "request_id": request_id,
            "time_slot": int(state["time_slot"]),
            "scheduler": self.name,
            "action_id": int(action_id),
            "rb_allocation": {
                "embb": int(rb_embb),
                "urllc": int(rb_urllc),
            },
        }
