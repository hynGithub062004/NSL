
import csv

from fastapi.testclient import TestClient
from members.TV5 import api_v2
from members.TV5.orchestrator_v2 import Orchestrator


def test_qos_via_tv5_api(tmp_path, monkeypatch):
    monkeypatch.setattr(
        api_v2,
        "service",
        Orchestrator(output_root=tmp_path),
    )

    client = TestClient(api_v2.app)

    health = client.get("/health").json()
    assert "qos_heuristic" in health["available_schedulers"]

    response = client.post("/sessions", json={
        "scheduler": "qos_heuristic",
        "scenario": "poor_channel",
        "seed": 42,
        "slots": 10,
    })

    assert response.status_code == 201, response.text

    run_id = response.json()["run_id"]

    decision = client.post(f"/sessions/{run_id}/decision")

    assert decision.status_code == 200, decision.text

    action = decision.json()["action"]

    assert action["scheduler"] == "qos_heuristic"
    assert action["action_id"] == 2
    assert sum(action["rb_allocation"].values()) == 50
    assert decision.json()["fallback_used"] is False

    result = client.post(f"/sessions/{run_id}/run-to-end")

    assert result.status_code == 200, result.text
    assert result.json()["completed_slots"] == 10
    assert result.json()["rb_conservation_ok"] is True
    assert result.json()["core_status"] == "NOT_CONNECTED"

    csv_file = tmp_path / run_id / "unified_without_core.csv"
    assert csv_file.is_file()

    with csv_file.open(newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))

    assert len(rows) == 20
    assert all(
        row["selected_scheduler"] == "qos_heuristic"
        for row in rows
    )
