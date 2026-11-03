"""TV5 session-based RAN Orchestrator V2, local development server only.

Run from repo root:
python -m uvicorn members.TV5.api_v2:app --host 127.0.0.1 --port 8001
"""
from __future__ import annotations

from typing import Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from members.TV5.orchestrator_v2 import Orchestrator, SessionFinished, SessionNotFound

service = Orchestrator()
app = FastAPI(
    title='NSL TV5 - Orchestrator V2 (real RAN, core not connected)',
    version='0.2.0',
    description='Session/State/Decision/Step API with TV1+TV2/TV3 real code; no SRv6 execution',
)


class CreateSession(BaseModel):
    scheduler: Literal['static', 'queue_based', 'dqn'] = 'static'
    scenario: Literal['stable_load', 'urllc_burst', 'poor_channel'] = 'stable_load'
    seed: int = Field(42, ge=0)
    slots: int = Field(10, ge=1, le=500)


@app.get('/health')
def health():
    return {'status': 'ok', 'module': 'TV5 RAN Orchestrator V2', 'core_connected': False,
            'available_schedulers': ['static', 'queue_based', 'dqn'],
            'qos_heuristic_connected': False,
            'note': 'Process health only. Does not prove DQN model, TV4 Core, or SLA timing.'}


@app.post('/sessions', status_code=201)
def create_session(payload: CreateSession):
    try:
        return service.create(payload.scheduler, payload.scenario, payload.seed, payload.slots)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except (FileNotFoundError, ModuleNotFoundError, RuntimeError) as exc:
        raise HTTPException(503, 'Scheduler dependency unavailable: ' + str(exc)) from exc


def read_or_404(callback, run_id: str):
    try:
        return callback(run_id)
    except SessionNotFound as exc:
        raise HTTPException(404, str(exc)) from exc
    except SessionFinished as exc:
        raise HTTPException(409, str(exc)) from exc
    except (ValueError, KeyError) as exc:
        raise HTTPException(422, str(exc)) from exc


@app.get('/sessions/{run_id}/state')
def get_state(run_id: str):
    return read_or_404(service.state, run_id)


@app.post('/sessions/{run_id}/decision')
def decide(run_id: str):
    return read_or_404(service.decision, run_id)


@app.post('/sessions/{run_id}/step')
def step(run_id: str):
    return read_or_404(service.step, run_id)


@app.post('/sessions/{run_id}/run-to-end')
def run_to_end(run_id: str):
    return read_or_404(service.run_to_end, run_id)


@app.get('/sessions/{run_id}/metrics')
def metrics(run_id: str):
    return read_or_404(service.metrics, run_id)


@app.post('/apply-policy', status_code=503)
def apply_policy():
    raise HTTPException(status_code=503,
                        detail='TV4 SRv6 Core is not connected; no policy has been applied')
