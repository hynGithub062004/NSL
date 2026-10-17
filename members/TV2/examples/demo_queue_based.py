from schedulers import SCHEDULERS
from schedulers.action_validator import validate_action


scheduler = SCHEDULERS["queue_based"]

config = {
    "common": {
        "total_rb": 50,
        "require_all_rb": True,
    },
    "queue_based": {
        "min_rb_embb": 5,
        "min_rb_urllc": 5,
        "action_id": 1,
    },
}

cases = [
    (0, 0),
    (1000, 1000),
    (3000, 1000),
    (1000, 3000),
    (0, 5000),
    (5000, 0),
    (1234, 5678),
]

for time_slot, (embb_queue, urllc_queue) in enumerate(cases):
    state = {
        "schema_version": "1.0.0",
        "time_slot": time_slot,
        "scenario_id": "stable_load",
        "seed": 42,
        "embb": {
            "queue_bits": embb_queue,
            "cqi": 10,
        },
        "urllc": {
            "queue_packets": 10,
            "queue_bits": urllc_queue,
            "cqi": 8,
            "oldest_packet_delay_ms": 2.0,
            "deadline_ms": 5.0,
        },
    }

    action = scheduler.select_action(
        state=state,
        config=config,
    )

    validate_action(
        action=action,
        state=state,
        total_rb=config["common"]["total_rb"],
        require_all_rb=config["common"]["require_all_rb"],
    )

    allocation = action["rb_allocation"]
    allocated_total = (
        allocation["embb"]
        + allocation["urllc"]
    )

    print(
        f"queues=({embb_queue}, {urllc_queue}) "
        f"allocation={allocation} "
        f"total={allocated_total}"
    )

print("ALL QUEUE-BASED CASES: PASS")