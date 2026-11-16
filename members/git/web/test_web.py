"""Small contract tests for parameterized RAN and local web persistence."""
import json
from pathlib import Path

from fastapi.testclient import TestClient

from web import app as module
from web.runner import run_one, aggregate


SPEC = {"scenario": "stable_load", "slots": 6, "total_rb": 50,
        "embb_arrival": 18000, "urllc_arrival": 1.5, "deadline_ms": 5,
        "embb_cqi": 11, "urllc_cqi": 8, "burst_multiplier": 6}


def test_same_seed_reproducible_and_rb_conserved(tmp_path):
    first = run_one(SPEC, 42, "queue_based", tmp_path / "a", "a" * 16)
    second = run_one(SPEC, 42, "queue_based", tmp_path / "b", "a" * 16)
    assert first["series"] == second["series"]
    assert all(row["embb_rb"] + row["urllc_rb"] == 50 for row in first["series"])
    assert first["run_summary"]["urllc_packet_counters"]["conservation_ok"]


def test_batch_api_persists_and_exports_without_core(tmp_path, monkeypatch):
    monkeypatch.setattr(module, "DATA", tmp_path)
    client = TestClient(module.app)
    payload = {**SPEC, "algorithms": ["static", "qos_heuristic"], "seeds": [42, 43],
               "core_mode": "off", "core_scenario": "normal"}
    response = client.post("/api/runs", json=payload)
    assert response.status_code == 202
    run_id = response.json()["id"]
    import time
    for _ in range(100):
        job = client.get(f"/api/runs/{run_id}").json()
        if job["status"] in ("completed", "failed"):
            break
        time.sleep(0.05)
    assert job["status"] == "completed", job["error"]
    assert len(job["comparison"]) == 2
    assert job["core"] is None
    assert (tmp_path / run_id / "qos_heuristic" / "42" / "slots.csv").exists()
    assert client.get(f"/api/runs/{run_id}/download").status_code == 200


def test_reject_unsupported_input():
    client = TestClient(module.app)
    assert client.post("/api/runs", json={"scenario": "../tmp"}).status_code == 422


def test_no_urllc_arrivals_are_not_reported_as_zero_drop_rate(tmp_path):
    result = run_one({**SPEC, "urllc_arrival": 0}, 42, "static", tmp_path, "b" * 16)
    assert result["metrics"]["arrived"] == 0
    assert result["metrics"]["delay_u"] is None
    assert aggregate([result])[0]["drop_rate_total"] is None


def test_core_baseline_fault_readback_and_restore(tmp_path, monkeypatch):
    monkeypatch.setattr(module, "DATA", tmp_path)
    state = {"scenario": "normal"}
    calls = []

    def fake(method, path, payload=None, timeout=120):
        calls.append((method, path, payload))
        if path == "/v1/lab/scenario":
            state["scenario"] = payload["scenario"]
            return {"status": "applied"}
        if path == "/policies":
            policy = "low_latency" if state["scenario"] == "outage" else "high_bandwidth"
            return {"slices": {"embb": {"active_policy": policy},
                               "urllc": {"active_policy": "low_latency"}}}
        if path == "/v1/lab/measure":
            return {"measurement": {"is_live": True}, "slices": {},
                    "scenario": state["scenario"]}
        if path == "/v1/events":
            return {"events": []}
        return {"status": "ok"}

    monkeypatch.setattr(module, "core_request", fake)
    client = TestClient(module.app)
    response = client.post("/api/runs", json={**SPEC, "algorithms": ["static"],
                                                "seeds": [42], "core_mode": "live",
                                                "core_scenario": "outage"})
    assert response.status_code == 202
    run_id = response.json()["id"]
    import time
    for _ in range(100):
        job = client.get(f"/api/runs/{run_id}").json()
        if job["status"] in ("completed", "failed"):
            break
        time.sleep(0.05)
    assert job["status"] == "completed", job["error"]
    assert job["core_before"]["scenario"] == "normal"
    assert job["core"]["scenario"] == "outage"
    assert job["core_restored"]["scenario"] == "normal"
    assert job["policies_after"]["slices"]["embb"]["active_policy"] == "low_latency"
    assert job["policies_restored"]["slices"]["embb"]["active_policy"] == "high_bandwidth"
    assert [p[2]["scenario"] for p in calls if p[1] == "/v1/lab/scenario"] == ["normal", "outage", "normal"]
