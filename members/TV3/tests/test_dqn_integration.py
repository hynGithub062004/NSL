
"""
TV3 - Integration Test with TV1 RAN Simulator

Tests:
- Real TV1 State -> DQN Scheduler -> TV1 Action
- Contract 1.0.0
- 50 RB allocation
- 500 slots
- 3 scenarios x 3 seeds
- Packet conservation

No model training required.
"""

from pathlib import Path

import pytest

from members.TV1.src.ran import RANSimulator
from members.TV3.dqn_scheduler import DQNScheduler


ROOT = Path(__file__).resolve().parents[3]

SCENARIOS = (
    "stable_load",
    "urllc_burst",
    "poor_channel",
)

SEEDS = (42, 43, 44)

EXPECTED_SLOTS = 500


@pytest.fixture(scope="module")
def scheduler():
    return DQNScheduler()


@pytest.mark.parametrize("scenario", SCENARIOS)
@pytest.mark.parametrize("seed", SEEDS)
def test_dqn_tv1_integration(
    scheduler,
    scenario,
    seed,
):

    config_path = (
        ROOT
        / "members"
        / "TV1"
        / "configs"
        / f"{scenario}.yaml"
    )

    assert config_path.is_file()

    simulator = RANSimulator.from_yaml(config_path)

    state = simulator.reset(seed=seed)

    steps = 0

    while not simulator.done:

        request_id = f"test-{scenario}-{seed}-{steps}"

        action = scheduler.predict(
            state=state,
            request_id=request_id
        )

        # Validate TV3 Action
        assert action["schema_version"] == "1.0.0"
        assert action["scheduler"] == "dqn"
        assert action["request_id"] == request_id
        assert action["time_slot"] == steps

        allocation = action["rb_allocation"]

        assert allocation["embb"] >= 0
        assert allocation["urllc"] >= 0

        assert (
            allocation["embb"]
            + allocation["urllc"]
        ) == simulator.total_rb

        # TV1 validates and applies Action
        transition = simulator.apply_action(action)

        assert transition["request_id"] == request_id

        assert transition["ran_kpi"]["time_slot"] == steps

        steps += 1

        if transition["done"]:
            assert transition["next_state"] is None
            break

        state = transition["next_state"]

    assert steps == EXPECTED_SLOTS

    # Verify official TV1 summary
    summary = simulator.build_run_summary()

    assert summary["status"] == "complete"
    assert summary["processed_slots"] == EXPECTED_SLOTS

    assert (
        summary["urllc_packet_counters"]["conservation_ok"]
        is True
    )

    # No manually calculated KPI values
    assert "traffic_and_service" in summary
    assert "urllc_run_rates" in summary
    assert "completed_urllc_delay_ms" in summary
