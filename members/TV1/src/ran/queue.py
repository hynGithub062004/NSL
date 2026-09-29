"""eMBB bit queue and URLLC packet FIFO queue."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Iterable

from .packet import Packet


@dataclass(frozen=True)
class UrllcServiceResult:
    served_bits: int
    completed_packets: tuple[Packet, ...]


class EmbbQueue:
    def __init__(self) -> None:
        self.bits = 0

    def reset(self) -> None:
        self.bits = 0

    def enqueue(self, bits: int) -> None:
        if bits < 0:
            raise ValueError("Cannot enqueue negative bits")
        self.bits += bits

    def serve(self, capacity_bits: int) -> int:
        if capacity_bits < 0:
            raise ValueError("Capacity cannot be negative")
        served = min(self.bits, capacity_bits)
        self.bits -= served
        return served


class UrllcQueue:
    def __init__(self) -> None:
        self.packets: deque[Packet] = deque()

    def reset(self) -> None:
        self.packets.clear()

    def enqueue(self, packets: Iterable[Packet]) -> None:
        self.packets.extend(packets)

    @property
    def packet_count(self) -> int:
        return len(self.packets)

    @property
    def total_bits(self) -> int:
        return sum(packet.remaining_bits for packet in self.packets)

    @property
    def oldest_delay_ms(self) -> float:
        return self.packets[0].age_ms if self.packets else 0.0

    def serve(self, capacity_bits: int) -> UrllcServiceResult:
        if capacity_bits < 0:
            raise ValueError("Capacity cannot be negative")
        budget = capacity_bits
        completed: list[Packet] = []
        served = 0
        while self.packets and budget > 0:
            packet = self.packets[0]
            amount = packet.serve(budget)
            served += amount
            budget -= amount
            if packet.remaining_bits == 0:
                completed.append(self.packets.popleft())
            else:
                break
        return UrllcServiceResult(served, tuple(completed))

    def age_and_drop(self, slot_duration_ms: float) -> tuple[Packet, ...]:
        survivors: deque[Packet] = deque()
        dropped: list[Packet] = []
        while self.packets:
            packet = self.packets.popleft()
            packet.age_ms += slot_duration_ms
            if packet.age_ms >= packet.deadline_ms:
                dropped.append(packet)
            else:
                survivors.append(packet)
        self.packets = survivors
        return tuple(dropped)

