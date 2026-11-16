"""Unit tests isolated from RAN/TV1 dependencies. Run from repository root."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from members.TV5 import core_apply_v2
from members.TV5.core_client import CoreAPIError

class FakeCore:
    def __init__(self):
        self.current = {"embb": "high_bandwidth", "urllc": "low_latency"}
        self.calls = []
        self.mode = "ok"
    def health(self):
        return {"status": "ok"}
    def policies(self):
        if self.mode == "disconnect":
            raise CoreAPIError("Cannot connect to TV4 Core: simulated")
        if self.mode == "ambiguous":
            return {"status": "ok", "canonical_valid": True}
        return {"status": "ok", "canonical_valid": True,
                "slices": {k: {"current_policy": v} for k, v in self.current.items()}}
    def apply_policy(self, request_id, slice_id, policy, confirm):
        self.calls.append((request_id, slice_id, policy, confirm))
        if self.mode == "rejected":
            return {"status": "rejected", "applied": False}
        if self.mode not in ("no_effect", "ambiguous"):
            self.current[slice_id] = policy
        return {"status": "ok", "applied": True}

@pytest.fixture
def setup(monkeypatch, tmp_path):
    fake = FakeCore()
    app = FastAPI()
    app.include_router(core_apply_v2.router)
    monkeypatch.setattr(core_apply_v2, "get_client", lambda: fake)
    monkeypatch.setenv("TV5_CORE_AUDIT_DIR", str(tmp_path))
    monkeypatch.delenv("TV5_ENABLE_CORE_APPLY", raising=False)
    return TestClient(app), fake, monkeypatch

def body(**extra):
    return {"request_id": "tv5-apply-001", "slice_id": "embb", "policy": "low_latency", "confirm": "APPLY_TV4", **extra}

def test_apply_disabled_by_default(setup):
    client, fake, _ = setup
    assert client.post('/core/apply-policy', json=body()).status_code == 403
    assert fake.calls == []

def test_missing_confirm_rejected(setup):
    client, fake, monkeypatch = setup
    monkeypatch.setenv("TV5_ENABLE_CORE_APPLY", "1")
    data = body(); del data["confirm"]
    assert client.post('/core/apply-policy', json=data).status_code == 422
    assert client.post('/core/apply-policy', json=body(confirm="wrong")).status_code == 422
    assert fake.calls == []

def test_success_verified_and_other_slice_unchanged(setup):
    client, fake, monkeypatch = setup
    monkeypatch.setenv("TV5_ENABLE_CORE_APPLY", "1")
    r = client.post('/core/apply-policy', json=body(run_id="run-demo", scenario_id="stable_load", seed=42, scheduler="static"))
    assert r.status_code == 200, r.text
    assert r.json()["verified"] is True
    assert fake.current["urllc"] == "low_latency"
    assert fake.calls == [("tv5-apply-001", "embb", "low_latency", "APPLY_TV4")]
    assert r.json()["context"]["run_id"] == "run-demo"

def test_duplicate_active_policy_skips_apply(setup):
    client, fake, monkeypatch = setup
    monkeypatch.setenv("TV5_ENABLE_CORE_APPLY", "1")
    fake.current["embb"] = "low_latency"
    r = client.post('/core/apply-policy', json=body())
    assert r.status_code == 200 and r.json()["status"] == "no_change"
    assert not fake.calls

def test_rejected_apply_is_not_success(setup):
    client, fake, monkeypatch = setup
    monkeypatch.setenv("TV5_ENABLE_CORE_APPLY", "1")
    fake.mode = "rejected"
    r = client.post('/core/apply-policy', json=body())
    assert r.status_code == 409 and r.json()["verified"] is False

def test_no_change_in_core_after_apply_is_not_success(setup):
    client, fake, monkeypatch = setup
    monkeypatch.setenv("TV5_ENABLE_CORE_APPLY", "1")
    fake.mode = "no_effect"
    r = client.post('/core/apply-policy', json=body())
    assert r.status_code == 409

def test_disconnect_returns_503_before_apply(setup):
    client, fake, monkeypatch = setup
    monkeypatch.setenv("TV5_ENABLE_CORE_APPLY", "1")
    fake.mode = "disconnect"
    r = client.post('/core/apply-policy', json=body())
    assert r.status_code == 503 and not fake.calls

def test_unknown_policy_schema_needs_manual_verification(setup):
    client, fake, monkeypatch = setup
    monkeypatch.setenv("TV5_ENABLE_CORE_APPLY", "1")
    fake.mode = "ambiguous"
    r = client.post('/core/apply-policy', json=body())
    assert r.status_code == 202
    assert r.json()["verified"] is False

def test_recommendation_is_not_auto_apply(setup):
    client, fake, _ = setup
    r = client.get('/core/recommend-policy/urllc')
    assert r.status_code == 200
    assert r.json()['policy'] == 'low_latency'
    assert r.json()['auto_apply'] is False
    assert fake.calls == []


def test_core_client_apply_contract(monkeypatch):
    from members.TV5.core_client import CoreClient
    calls = []
    monkeypatch.setattr(CoreClient, "_request", lambda self, method, endpoint, payload: calls.append((method, endpoint, payload)) or {"applied": True})
    client = CoreClient()
    client.apply_policy("case-100", "embb", "low_latency", "APPLY_TV4")
    assert calls == [("POST", "/apply-policy", {
        "request_id": "case-100", "slice_id": "embb", "policy": "low_latency", "confirm": "APPLY_TV4"
    })]


def test_core_client_preview_keeps_confirm_absent(monkeypatch):
    from members.TV5.core_client import CoreClient
    calls = []
    monkeypatch.setattr(CoreClient, "_request", lambda self, method, endpoint, payload: calls.append(payload) or {"applied": False})
    CoreClient().preview_policy("case-preview", "embb", "low_latency")
    assert "confirm" not in calls[0]


def test_upstream_duplicate_request_id_http_409_not_masked(setup):
    client, fake, monkeypatch = setup
    monkeypatch.setenv("TV5_ENABLE_CORE_APPLY", "1")
    def reject(*args):
        raise CoreAPIError("TV4 HTTP error: 409; body=duplicate request_id mismatch")
    fake.apply_policy = reject
    r = client.post('/core/apply-policy', json=body())
    assert r.status_code == 409
