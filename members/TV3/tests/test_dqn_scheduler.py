
"""
TV3 - Unit Tests for DQN Scheduler Adapter

Contract: 1.0.0
Shared RAN Simulator: TV1

Run:
python -m pytest members/TV3/tests/test_dqn_scheduler.py -v
"""

import copy

import pytest

from members.TV3.dqn_scheduler import DQNScheduler


@pytest.fixture(scope="module")
def scheduler():
    # Load trained model once for all tests.
    return DQNScheduler()


@pytest.fixture
def valid_state():
    return {
        "schema_version": "1.0.0",
        "time_slot": 125,
        "scenario_id": "urllc_burst",
        "seed": 42,
        "embb": {
            "queue_bits": 238400,
            "cqi": 11,
        },
        "urllc": {
            "queue_packets": 18,
            "queue_bits": 46080,
            "cqi": 7,
            "oldest_packet_delay_ms": 4.0,
            "deadline_ms": 5.0,
        },
    }


# ==================================================
# 1. CONTRACT OUTPUT
# ==================================================

def test_action_contract(scheduler, valid_state):

    action = scheduler.predict(
        valid_state,
        request_id="req-000125"
    )

    assert action["schema_version"] == "1.0.0"
    assert action["request_id"] == "req-000125"
    assert action["time_slot"] == 125
    assert action["scheduler"] == "dqn"

    assert 0 <= action["action_id"] < 5

    allocation = action["rb_allocation"]

    assert allocation["embb"] >= 0
    assert allocation["urllc"] >= 0

    assert allocation["embb"] + allocation["urllc"] == 50


# ==================================================
# 2. DETERMINISTIC INFERENCE
# ==================================================

def test_deterministic_prediction(
    scheduler,
    valid_state
):

    first = scheduler.predict(
        valid_state,
        request_id="req-repeat"
    )

    second = scheduler.predict(
        valid_state,
        request_id="req-repeat"
    )

    assert first == second


# ==================================================
# 3. REQUEST ID PRESERVATION
# ==================================================

def test_request_id_preserved(
    scheduler,
    valid_state
):

    request_id = "orchestrator-123"

    action = scheduler.predict(
        valid_state,
        request_id=request_id
    )

    assert action["request_id"] == request_id


# ==================================================
# 4. INPUT STATE MUST NOT CHANGE
# ==================================================

def test_state_unchanged(
    scheduler,
    valid_state
):

    original = copy.deepcopy(valid_state)

    scheduler.predict(
        valid_state,
        request_id="req-no-mutation"
    )

    assert valid_state == original


# ==================================================
# 5. INVALID CQI
# ==================================================

@pytest.mark.parametrize(
    "bad_cqi",
    [0, 16, -1, 3.5, None, True]
)
def test_invalid_cqi(
    scheduler,
    valid_state,
    bad_cqi
):

    state = copy.deepcopy(valid_state)
    state["urllc"]["cqi"] = bad_cqi

    with pytest.raises(ValueError):
        scheduler.predict(
            state,
            request_id="req-invalid-cqi"
        )


# ==================================================
# 6. INVALID DEADLINE
# ==================================================

@pytest.mark.parametrize(
    "bad_deadline",
    [0, -1, None, float("nan"), float("inf")]
)
def test_invalid_deadline(
    scheduler,
    valid_state,
    bad_deadline
):

    state = copy.deepcopy(valid_state)
    state["urllc"]["deadline_ms"] = bad_deadline

    with pytest.raises(ValueError):
        scheduler.predict(
            state,
            request_id="req-invalid-deadline"
        )


# ==================================================
# 7. INVALID QUEUE
# ==================================================

@pytest.mark.parametrize(
    "bad_queue",
    [-1, 1.5, None, True]
)
def test_invalid_queue(
    scheduler,
    valid_state,
    bad_queue
):

    state = copy.deepcopy(valid_state)
    state["embb"]["queue_bits"] = bad_queue

    with pytest.raises(ValueError):
        scheduler.predict(
            state,
            request_id="req-invalid-queue"
        )


# ==================================================
# 8. MISSING STATE FIELD
# ==================================================

def test_missing_state_field(
    scheduler,
    valid_state
):

    state = copy.deepcopy(valid_state)
    del state["urllc"]["cqi"]

    with pytest.raises(ValueError):
        scheduler.predict(
            state,
            request_id="req-missing"
        )


# ==================================================
# 9. INVALID SCHEMA VERSION
# ==================================================

def test_invalid_schema_version(
    scheduler,
    valid_state
):

    state = copy.deepcopy(valid_state)
    state["schema_version"] = "2.0.0"

    with pytest.raises(ValueError):
        scheduler.predict(
            state,
            request_id="req-schema"
        )


# ==================================================
# 10. INVALID REQUEST ID
# ==================================================

@pytest.mark.parametrize(
    "request_id",
    ["", None, 123]
)
def test_invalid_request_id(
    scheduler,
    valid_state,
    request_id
):

    with pytest.raises(ValueError):
        scheduler.predict(
            valid_state,
            request_id=request_id
        )


# ==================================================
# 11. ALL ACTIONS MUST USE 50 RB
# ==================================================

def test_rb_allocation(
    scheduler,
    valid_state
):

    for embb_cqi in range(1, 16):

        for urllc_cqi in range(1, 16):

            state = copy.deepcopy(valid_state)

            state["embb"]["cqi"] = embb_cqi
            state["urllc"]["cqi"] = urllc_cqi

            action = scheduler.predict(
                state,
                request_id="req-rb-check"
            )

            allocation = action["rb_allocation"]

            assert (
                allocation["embb"]
                + allocation["urllc"]
            ) == 50


# ==================================================
# 12. NO CHECKPOINT
# ==================================================

def test_missing_checkpoint(tmp_path):

    nonexistent = tmp_path / "missing_model.zip"

    with pytest.raises(FileNotFoundError):
        DQNScheduler(model_path=nonexistent)
