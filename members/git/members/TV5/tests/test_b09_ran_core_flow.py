
import json
from pathlib import Path

from fastapi.testclient import TestClient

from members.TV5 import api_v2, core_apply_v2


class FakeCore:
    """Mock only. No GNS3 or real SRv6 operations."""

    def __init__(self):
        self.active = {
            "embb": "high_bandwidth",
            "urllc": "low_latency"
        }

    def policies(self):
        return {
            "status": "ok",
            "canonical_valid": True,
            "policies": {
                "embb": {
                    "active_policy": self.active["embb"],
                    "routing_table": 100
                },
                "urllc": {
                    "active_policy": self.active["urllc"],
                    "routing_table": 101
                }
            }
        }

    def apply_policy(self, request_id, slice_id, policy, confirm):
        assert confirm == "APPLY_TV4"

        previous = self.active[slice_id]
        self.active[slice_id] = policy

        return {
            "status": "ok",
            "applied": True,
            "request_id": request_id,
            "previous_policy": previous,
            "requested_policy": policy
        }


def test_b09_ran_to_mock_core(monkeypatch):
    # Enable controlled Apply for this isolated mock test.
    monkeypatch.setenv("TV5_ENABLE_CORE_APPLY", "1")

    fake = FakeCore()
    monkeypatch.setattr(
        core_apply_v2,
        "get_client",
        lambda: fake
    )

    client = TestClient(api_v2.app)

    # 1. Create and run a real RAN simulation
    created = client.post(
        "/sessions",
        json={
            "scheduler": "static",
            "scenario": "stable_load",
            "seed": 42,
            "slots": 10
        }
    )
    assert created.status_code == 201

    run_id = created.json()["run_id"]

    completed = client.post(
        f"/sessions/{run_id}/run-to-end"
    )
    assert completed.status_code == 200

    metrics = client.get(
        f"/sessions/{run_id}/metrics"
    ).json()

    plan = client.get(
        f"/sessions/{run_id}/core-plan"
    ).json()

    assert metrics["run_id"] == run_id
    assert plan["run_id"] == run_id
    assert metrics["completed_slots"] == 10
    assert metrics["rb_conservation_ok"] is True
    assert plan["auto_apply"] is False

    # 2. Controlled manual test override.
    # This is NOT an adaptive Core decision from RAN KPI.
    request = {
        "request_id": f"{run_id}-mock-apply",
        "slice_id": "embb",
        "policy": "low_latency",
        "confirm": "APPLY_TV4",
        "run_id": run_id,
        "scenario_id": "stable_load",
        "seed": 42,
        "scheduler": "static"
    }

    applied = client.post(
        "/core/apply-policy",
        json=request
    )

    assert applied.status_code == 200
    assert applied.json()["verified"] is True
    assert applied.json()["context"]["run_id"] == run_id

    assert fake.active["embb"] == "low_latency"
    assert fake.active["urllc"] == "low_latency"

    # 3. Restore the original mock policy.
    rollback_request = {
        **request,
        "request_id": f"{run_id}-mock-rollback",
        "policy": "high_bandwidth"
    }

    restored = client.post(
        "/core/apply-policy",
        json=rollback_request
    )

    assert restored.status_code == 200
    assert restored.json()["verified"] is True

    assert fake.active["embb"] == "high_bandwidth"
    assert fake.active["urllc"] == "low_latency"

    # 4. Save evidence
    out = (
        Path(__file__).resolve().parents[1]
        / "results"
        / "saved_tests"
        / "B09_RAN_Core"
        / "mock_integration"
    )
    out.mkdir(parents=True, exist_ok=True)

    evidence = {
        "test_type": "RAN_to_MOCK_Core",
        "run_id": run_id,
        "scenario_id": "stable_load",
        "scheduler": "static",
        "seed": 42,
        "ran_metrics": metrics,
        "core_plan": plan,
        "apply_request": request,
        "apply_response": applied.json(),
        "rollback_request": rollback_request,
        "rollback_response": restored.json(),
        "final_mock_policies": fake.policies(),
        "core_is_real": False,
        "policy_selection_mode": "manual_test_override"
    }

    (out / "TV5_B09_04_Mock_E2E_Result.json").write_text(
        json.dumps(evidence, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )
