from __future__ import annotations

from typing import Any

from .base_scheduler import BaseScheduler


class StaticScheduler(BaseScheduler):
    """Cấp phát RB cố định, không phụ thuộc State."""

    name = "static"

    def select_action(
        self,
        state: dict[str, Any],
        config: dict[str, Any],
        request_id: str | None = None,
    ) -> dict[str, Any]:
        static_config = config["static"]

        rb_embb = int(
            static_config["rb_embb"]
        )

        rb_urllc = int(
            static_config["rb_urllc"]
        )

        action_id = int(
            static_config.get("action_id", 0)
        )

        return self.build_action(
            state=state,
            rb_embb=rb_embb,
            rb_urllc=rb_urllc,
            action_id=action_id,
            request_id=request_id,
        )
