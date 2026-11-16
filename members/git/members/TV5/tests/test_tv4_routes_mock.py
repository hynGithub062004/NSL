
from fastapi.testclient import TestClient
from members.TV5 import api_v2
from members.TV5.core_client import CoreAPIError


class FakeTV4Client:
    def __init__(self):
        self.preview_args = None

    def health(self):
        return {"status": "ok"}

    def policies(self):
        return {
            "embb": "high_bandwidth",
            "urllc": "low_latency"
        }

    def core_kpi(self, slice_id):
        return {
            "slice_id": slice_id,
            "measurement": {"is_live": False}
        }

    def events(self):
        return {"events": []}

    def preview_policy(self, request_id, slice_id, policy):
        self.preview_args = (request_id, slice_id, policy)
        return {
            "mode": "preview",
            "applied": False
        }


def test_core_read_endpoints(monkeypatch):
    fake = FakeTV4Client()

    monkeypatch.setattr(
        api_v2, "get_tv4_client", lambda: fake
    )

    client = TestClient(api_v2.app)

    assert client.get("/core/health").status_code == 200
    assert client.get("/core/policies").status_code == 200
    assert client.get("/core/events").status_code == 200

    for slice_id in ("embb", "urllc"):
        response = client.get(f"/core/kpi/{slice_id}")

        assert response.status_code == 200
        assert response.json()["slice_id"] == slice_id
        assert response.json()["measurement"]["is_live"] is False

    print("PASS: TV4 Core read endpoints")


def test_preview_policy(monkeypatch):
    fake = FakeTV4Client()

    monkeypatch.setattr(
        api_v2, "get_tv4_client", lambda: fake
    )

    client = TestClient(api_v2.app)

    response = client.post(
        "/core/preview-policy",
        json={
            "request_id": "tv5-test-001",
            "slice_id": "embb",
            "policy": "low_latency"
        }
    )

    assert response.status_code == 200
    assert response.json()["mode"] == "preview"
    assert response.json()["applied"] is False

    assert fake.preview_args == (
        "tv5-test-001", "embb", "low_latency"
    )

    print("PASS: TV5 forwards preview to Core Client")


def test_preview_rejects_confirm(monkeypatch):
    fake = FakeTV4Client()

    monkeypatch.setattr(
        api_v2, "get_tv4_client", lambda: fake
    )

    client = TestClient(api_v2.app)

    response = client.post(
        "/core/preview-policy",
        json={
            "request_id": "tv5-test-002",
            "slice_id": "embb",
            "policy": "low_latency",
            "confirm": "APPLY_TV4"
        }
    )

    assert response.status_code == 422
    assert fake.preview_args is None

    print("PASS: Preview rejects confirm field")


def test_core_connection_error(monkeypatch):
    class FailingClient:
        def health(self):
            raise CoreAPIError("Simulated Core disconnect")

    monkeypatch.setattr(
        api_v2, "get_tv4_client", lambda: FailingClient()
    )

    client = TestClient(api_v2.app)

    response = client.get("/core/health")

    assert response.status_code == 503
    assert "Simulated Core disconnect" in response.json()["detail"]

    print("PASS: TV5 handles Core connection errors")
