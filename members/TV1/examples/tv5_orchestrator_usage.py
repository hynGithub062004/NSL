"""Minimal in-process TV5 integration example."""

from ran import RANSimulator


def run_one_decision(config_path: str, scheduler_callable) -> dict:
    ran = RANSimulator.from_yaml(config_path)
    state = ran.get_state()
    action = scheduler_callable(state)
    transition = ran.apply_action(action)
    # TV5 should join Core KPI later with transition['request_id'] and the
    # seed/scenario/algorithm/time_slot fields in transition['ran_kpi'].
    return transition

