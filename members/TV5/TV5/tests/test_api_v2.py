from fastapi.testclient import TestClient

from members.TV5 import api_v2
from members.TV5.orchestrator_v2 import Orchestrator


def test_end_to_end_static(tmp_path, monkeypatch):
    monkeypatch.setattr(api_v2, 'service', Orchestrator(output_root=tmp_path))
    client = TestClient(api_v2.app)
    assert client.get('/health').json()['core_connected'] is False
    r = client.post('/sessions', json={'scheduler':'static','scenario':'stable_load','seed':42,'slots':3})
    assert r.status_code == 201, r.text
    uid = r.json()['run_id']
    r = client.get(f'/sessions/{uid}/state')
    assert r.status_code == 200 and r.json()['state']['time_slot'] == 0
    r = client.post(f'/sessions/{uid}/decision')
    assert r.status_code == 200, r.text
    action = r.json()['action']
    assert action['scheduler'] == 'static'
    assert sum(action['rb_allocation'].values()) == 50
    assert client.post(f'/sessions/{uid}/decision').json()['action'] == action
    step = client.post(f'/sessions/{uid}/step')
    assert step.status_code == 200 and step.json()['completed_slots'] == 1
    finished = client.post(f'/sessions/{uid}/run-to-end')
    assert finished.status_code == 200, finished.text
    assert finished.json()['completed_slots'] == 3
    assert finished.json()['rb_conservation_ok'] is True
    assert finished.json()['core_status'] == 'NOT_CONNECTED'
    assert (tmp_path / uid / 'unified_without_core.csv').is_file()
    assert client.post('/apply-policy').status_code == 503
    assert client.post(f'/sessions/{uid}/step').status_code == 409


def test_queue_based_valid_and_run_isolation(tmp_path, monkeypatch):
    monkeypatch.setattr(api_v2,'service',Orchestrator(output_root=tmp_path))
    client = TestClient(api_v2.app)
    payload = {'scheduler':'queue_based','scenario':'urllc_burst','seed':42,'slots':4}
    first=client.post('/sessions',json=payload).json()['run_id']
    second=client.post('/sessions',json=payload).json()['run_id']
    assert first != second
    a=client.post(f'/sessions/{first}/run-to-end')
    assert a.status_code == 200, a.text
    b=client.post(f'/sessions/{second}/run-to-end')
    assert b.status_code == 200, b.text
    assert a.json()['rb_conservation_ok']
    assert b.json()['rb_conservation_ok']
    assert (tmp_path/first/'unified_without_core.csv').read_bytes() != b''
    assert client.get('/sessions/bad/state').status_code == 404
