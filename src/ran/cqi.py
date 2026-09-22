"""Bounded deterministic CQI random-walk model."""

from __future__ import annotations

import random


class CQIModel:
    def __init__(self, config: dict):
        self.config = config["channel"]
        self._rng = random.Random()
        self.embb_cqi = int(self.config["embb_initial_cqi"])
        self.urllc_cqi = int(self.config["urllc_initial_cqi"])

    def reset(self, seed: int) -> None:
        # Separate deterministic stream from traffic while preserving global seed.
        self._rng.seed(seed ^ 0xC01)
        self.embb_cqi = int(self.config["embb_initial_cqi"])
        self.urllc_cqi = int(self.config["urllc_initial_cqi"])

    def _next(self, current: int) -> int:
        if self._rng.random() > float(self.config.get("change_probability", 0.25)):
            return current
        step = self._rng.choice((-1, 1)) * int(self.config.get("max_step", 1))
        minimum = int(self.config["min_cqi"])
        maximum = int(self.config["max_cqi"])
        return max(minimum, min(maximum, current + step))

    def update(self) -> dict[str, int]:
        self.embb_cqi = self._next(self.embb_cqi)
        self.urllc_cqi = self._next(self.urllc_cqi)
        return {"embb": self.embb_cqi, "urllc": self.urllc_cqi}

