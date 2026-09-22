"""Packet model used by the URLLC FIFO queue."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Packet:
    packet_id: str
    arrival_slot: int
    size_bits: int
    remaining_bits: int
    deadline_ms: float
    age_ms: float = 0.0

    @classmethod
    def create(
        cls, packet_id: str, arrival_slot: int, size_bits: int, deadline_ms: float
    ) -> "Packet":
        if size_bits <= 0:
            raise ValueError("Packet size must be positive")
        if deadline_ms <= 0:
            raise ValueError("Packet deadline must be positive")
        return cls(packet_id, arrival_slot, size_bits, size_bits, deadline_ms)

    def serve(self, capacity_bits: int) -> int:
        if capacity_bits < 0:
            raise ValueError("Capacity cannot be negative")
        served = min(self.remaining_bits, capacity_bits)
        self.remaining_bits -= served
        return served

