"""Minimal TV2 example: consume State and return an Action only."""

from ran.schemas import SCHEMA_VERSION


def queue_based_action(state: dict, total_rb: int = 50) -> dict:
    embb_demand = state["embb"]["queue_bits"]
    urllc_demand = state["urllc"]["queue_bits"]
    total_demand = embb_demand + urllc_demand
    if total_demand == 0:
        urllc_rb = 0
    else:
        urllc_rb = round(total_rb * urllc_demand / total_demand)
    embb_rb = total_rb - urllc_rb
    return {
        "schema_version": SCHEMA_VERSION,
        "request_id": f"tv2-{state['time_slot']:06d}",
        "time_slot": state["time_slot"],
        "scheduler": "queue_based",
        "action_id": 1,
        "rb_allocation": {"embb": embb_rb, "urllc": urllc_rb},
    }

