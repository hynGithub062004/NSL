"""Deterministic eMBB and URLLC traffic generation."""

from __future__ import annotations

import math
import random
from dataclasses import dataclass

from .packet import Packet


@dataclass(frozen=True)
class TrafficArrival:
    embb_bits: int
    urllc_packets: tuple[Packet, ...]


class TrafficGenerator:
    def __init__(self, config: dict):
        self.config = config
        self._rng = random.Random()
        self._packet_sequence = 0

    def reset(self, seed: int) -> None:
        self._rng.seed(seed)
        self._packet_sequence = 0

    def _poisson(self, rate: float) -> int:
        if rate <= 0:
            return 0
        # Knuth is stable and dependency-free for the small rates used here.
        limit = math.exp(-rate)
        product = 1.0
        count = 0
        while product > limit:
            count += 1
            product *= self._rng.random()
        return count - 1

    def _is_burst(self, slot: int) -> bool:
        scenario = self.config["scenario"]
        if scenario.get("type") != "urllc_burst":
            return False
        start = int(scenario.get("burst_start_slot", 0))
        duration = int(scenario.get("burst_duration_slots", 0))
        period = int(scenario.get("burst_period_slots", 0))
        if period <= 0:
            return start <= slot < start + duration
        if slot < start:
            return False
        return (slot - start) % period < duration

    def generate(self, slot: int) -> TrafficArrival:
        embb = self.config["embb"]
        urllc = self.config["urllc"]
        embb_mean = float(embb["arrival_rate_bits_per_slot"])
        embb_std = float(embb.get("arrival_jitter_bits", 0))
        embb_bits = max(0, int(round(self._rng.gauss(embb_mean, embb_std))))

        packet_rate = float(urllc["arrival_rate_packets_per_slot"])
        if self._is_burst(slot):
            packet_rate *= float(urllc.get("burst_multiplier", 1.0))
        packet_count = self._poisson(packet_rate)
        packets: list[Packet] = []
        for _ in range(packet_count):
            self._packet_sequence += 1
            packets.append(
                Packet.create(
                    packet_id=f"u-{self._packet_sequence:08d}",
                    arrival_slot=slot,
                    size_bits=int(urllc["packet_size_bits"]),
                    deadline_ms=float(urllc["deadline_ms"]),
                )
            )
        return TrafficArrival(embb_bits=embb_bits, urllc_packets=tuple(packets))

