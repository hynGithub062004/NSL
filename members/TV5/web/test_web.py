"""Small contract tests for parameterized RAN and local web persistence."""
import json
from pathlib import Path

from fastapi.testclient import TestClient

from web import app as module
from web.runner import run_one


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
