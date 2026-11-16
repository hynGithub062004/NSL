"""Contract tests for the TV5 slot API and the scenario-suite worker."""
import time

from fastapi.testclient import TestClient

from web import app as module
from members.TV5.orchestrator_web import Orchestrator


SPEC = {'scenario': 'stable_load', 'algorithms': ['static'], 'seeds': [42],
        'slots': 3, 'core_mode': 'off'}


def test_tv5_decision_is_repeatable_and_step_applies_once(tmp_path, monkeypatch):
    monkeypatch.setattr(module, 'TV5', Orchestrator(tmp_path))
    client = TestClient(module.app)
    created = client.post('/api/tv5/sessions', json={'experiment': SPEC, 'algorithm': 'qos_heuristic'})
    assert created.status_code == 201, created.text
    uid = created.json()['run_id']
    before = client.get(f'/api/tv5/sessions/{uid}/state').json()['state']
    decision = client.post(f'/api/tv5/sessions/{uid}/decision').json()
    assert client.post(f'/api/tv5/sessions/{uid}/decision').json() == decision
    assert client.get(f'/api/tv5/sessions/{uid}/state').json()['state'] == before
    step = client.post(f'/api/tv5/sessions/{uid}/step').json()
    assert step['decision'] == decision
    assert step['completed_slots'] == 1
    metrics = client.post(f'/api/tv5/sessions/{uid}/run-to-end').json()
    assert metrics['completed_slots'] == 3 and metrics['rb_conservation_ok']
    assert metrics['partial_smoke_test'] is True
    assert client.post(f'/api/tv5/sessions/{uid}/step').status_code == 409
    assert client.get(f'/api/tv5/sessions/{uid}/download').status_code == 200


def test_tv5_injected_dqn_failure_falls_back_with_evidence(tmp_path, monkeypatch):
    monkeypatch.setattr(module, 'TV5', Orchestrator(tmp_path))
    client = TestClient(module.app)
    created = client.post('/api/tv5/sessions', json={'experiment': SPEC, 'algorithm': 'dqn',
                            'fallback': True, 'inject_dqn_failure': True})
    uid = created.json()['run_id']
    decision = client.post(f'/api/tv5/sessions/{uid}/decision').json()
    assert decision['requested_scheduler'] == 'dqn'
    assert decision['selected_scheduler'] == 'qos_heuristic'
    assert decision['fallback_used'] is True
    assert 'DQN' in decision['fallback_reason']
    assert client.post(f'/api/tv5/sessions/{uid}/run-to-end').json()['fallback_count'] == 3
    assert (tmp_path / uid / 'unified_tv5.csv').is_file()


def test_suite_runs_all_three_ran_scenarios(tmp_path, monkeypatch):
    monkeypatch.setattr(module, 'DATA', tmp_path)
    client = TestClient(module.app)
    response = client.post('/api/suites', json={'experiment': {**SPEC, 'slots': 2},
        'scenarios': ['stable_load', 'urllc_burst', 'poor_channel'], 'core_scenarios': ['normal']})
    assert response.status_code == 202
    uid = response.json()['id']
    for _ in range(100):
        suite = client.get(f'/api/suites/{uid}').json()
        if suite['status'] not in ('queued', 'running'):
            break
        time.sleep(.05)
    assert suite['status'] == 'completed', suite
    assert suite['progress'] == suite['total'] == 3
    assert all(client.get(f'/api/runs/{r["id"]}').json()['status'] == 'completed' for r in suite['runs'])
