from __future__ import annotations

import hashlib
import random
from typing import Any

from .base_scheduler import BaseScheduler


class RandomScheduler(BaseScheduler):
    """Phan bo ngau nhien toan bo RB, tai lap theo seed va time slot."""

    name = "random"

    def select_action(
        self,
        state: dict[str, Any],
        config: dict[str, Any],
        request_id: str | None = None,
    ) -> dict[str, Any]:
        common = config.get("common", {})
        random_config = config.get("random", {})

        total_rb = int(common.get("total_rb", 50))
        run_seed = int(state["seed"])
        time_slot = int(state["time_slot"])
        action_id = int(random_config.get("action_id", 3))

        if total_rb <= 0:
            raise ValueError("total_rb must be positive")
        if run_seed < 0:
            raise ValueError("state.seed must be non-negative")
        if time_slot < 0:
            raise ValueError("state.time_slot must be non-negative")

        seed_material = f"{run_seed}:{time_slot}".encode("utf-8")
        derived_seed = int.from_bytes(
            hashlib.sha256(seed_material).digest()[:8],
            "big",
        )
        rng = random.Random(derived_seed)

        rb_embb = rng.randint(0, total_rb)
        rb_urllc = total_rb - rb_embb

        return self.build_action(
            state=state,
            rb_embb=rb_embb,
            rb_urllc=rb_urllc,
            action_id=action_id,
            request_id=request_id,
        )
