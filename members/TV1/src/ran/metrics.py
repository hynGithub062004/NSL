"""Per-slot RAN KPI calculations."""

from __future__ import annotations


def _safe_ratio(numerator: float, denominator: float) -> float:
    return numerator / denominator if denominator > 0 else 0.0


def _jain(values: list[float]) -> float:
    active = [value for value in values if value >= 0]
    if not active or all(value == 0 for value in active):
        return 1.0
    numerator = sum(active) ** 2
    denominator = len(active) * sum(value * value for value in active)
    return numerator / denominator if denominator else 1.0


def calculate_slot_kpi(
    *,
    request_id: str,
    seed: int,
    scenario_id: str,
    algorithm: str,
    time_slot: int,
    slot_duration_ms: float,
    total_rb: int,
    allocated_embb_rb: int,
    allocated_urllc_rb: int,
    used_embb_rb: int,
    used_urllc_rb: int,
    embb_demand_bits: int,
    urllc_demand_bits: int,
    served_embb_bits: int,
    served_urllc_bits: int,
    completed_delays_ms: list[float],
    dropped_packets: int,
    deadline_ms: float,
    schema_version: str,
) -> dict:
    resolved_packets = len(completed_delays_ms) + dropped_packets
    late_completed = sum(delay > deadline_ms for delay in completed_delays_ms)
    mean_delay = _safe_ratio(sum(completed_delays_ms), len(completed_delays_ms))

    embb_satisfaction = _safe_ratio(served_embb_bits, embb_demand_bits)
    urllc_satisfaction = _safe_ratio(served_urllc_bits, urllc_demand_bits)
    if embb_demand_bits == 0:
        embb_satisfaction = 1.0
    if urllc_demand_bits == 0:
        urllc_satisfaction = 1.0

    slot_seconds = slot_duration_ms / 1000.0
    throughput_mbps = served_embb_bits / slot_seconds / 1_000_000.0
    return {
        "schema_version": schema_version,
        "request_id": request_id,
        "seed": seed,
        "scenario_id": scenario_id,
        "algorithm": algorithm,
        "time_slot": time_slot,
        "throughput_e": round(throughput_mbps, 6),
        "delay_u": round(mean_delay, 6),
        "drop_u": round(_safe_ratio(dropped_packets, resolved_packets), 6),
        "sla_violation": round(
            _safe_ratio(dropped_packets + late_completed, resolved_packets), 6
        ),
        "fairness": round(_jain([embb_satisfaction, urllc_satisfaction]), 6),
        "rb_utilization": round(
            _safe_ratio(used_embb_rb + used_urllc_rb, total_rb), 6
        ),
        "allocated_embb_rb": allocated_embb_rb,
        "allocated_urllc_rb": allocated_urllc_rb,
        "used_embb_rb": used_embb_rb,
        "used_urllc_rb": used_urllc_rb,
        "served_embb_bits": served_embb_bits,
        "served_urllc_bits": served_urllc_bits,
        "completed_urllc_packets": len(completed_delays_ms),
        "dropped_urllc_packets": dropped_packets,
        "units": {
            "throughput_e": "Mbps",
            "delay_u": "ms",
            "drop_u": "ratio",
            "sla_violation": "ratio",
            "fairness": "index_0_to_1",
            "rb_utilization": "ratio",
        },
    }

