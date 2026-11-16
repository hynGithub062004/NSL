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
    scheduler: Literal['static', 'queue_based','qos_heuristic', 'dqn'] = 'static'
    scenario: Literal['stable_load', 'urllc_burst', 'poor_channel'] = 'stable_load'
    seed: int = Field(42, ge=0)
    slots: int = Field(10, ge=1, le=500)
    allow_fallback: bool = False


@app.get('/health')
def health():
    return {'status': 'ok', 'module': 'TV5 RAN Orchestrator V2', 'core_connected': live_core_health()['core_connected'],
            'available_schedulers': ['static','queue_based','qos_heuristic', 'dqn'],
            'qos_heuristic_connected': True,
            'note': 'Process health only. Does not prove DQN model, TV4 Core, or SLA timing.'}


@app.post('/sessions', status_code=201)
def create_session(payload: CreateSession):
    try:
        return service.create(payload.scheduler, payload.scenario, payload.seed, payload.slots, allow_fallback=payload.allow_fallback)
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
    except RuntimeError as exc:
        raise HTTPException(
            503, 'Scheduler chain unavailable: ' + str(exc)
        ) from exc
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

# ============================================
# TV5 - Integration with TV4 Core Controller
# Read-only APIs and safe preview
# ============================================

import os
from typing import Literal
from fastapi import HTTPException
from pydantic import BaseModel

from members.TV5.core_client import CoreClient, CoreAPIError


class CorePreviewRequest(BaseModel):
    request_id: str
    slice_id: Literal["embb", "urllc"]
    policy: Literal["high_bandwidth", "low_latency"]

    class Config:
        extra = "forbid"


def get_tv4_client():
    url = os.getenv(
        "TV4_CORE_URL",
        "http://127.0.0.1:18018"
    )
    return CoreClient(base_url=url, timeout=5)


def call_tv4(operation):
    try:
        return operation()
    except CoreAPIError as exc:
        raise HTTPException(
            status_code=503,
            detail=str(exc)
        ) from exc


@app.get("/core/health", tags=["TV4 Core"])
def core_health():
    return call_tv4(
        lambda: get_tv4_client().health()
    )


@app.get("/core/policies", tags=["TV4 Core"])
def core_policies():
    return call_tv4(
        lambda: get_tv4_client().policies()
    )


@app.get("/core/kpi/{slice_id}", tags=["TV4 Core"])
def core_kpi(slice_id: Literal["embb", "urllc"]):
    return call_tv4(
        lambda: get_tv4_client().core_kpi(slice_id)
    )


@app.get("/core/events", tags=["TV4 Core"])
def core_events():
    return call_tv4(
        lambda: get_tv4_client().events()
    )


@app.post("/core/preview-policy", tags=["TV4 Core"])
def core_preview(payload: CorePreviewRequest):
    return call_tv4(
        lambda: get_tv4_client().preview_policy(
            request_id=payload.request_id,
            slice_id=payload.slice_id,
            policy=payload.policy
        )
    )

# ============================================
# TV5 B07 - Controlled Core Apply
# ============================================

from members.TV5.core_apply_v2 import (
    router as core_apply_router,
    live_core_health,
    recommend_policy,
)

app.include_router(core_apply_router)


@app.get("/sessions/{run_id}/core-plan",
         tags=["TV5 RAN-Core Plan"])
def core_plan_for_run(run_id: str):
    ran = read_or_404(service.metrics, run_id)

    return {
        "run_id": run_id,
        "scenario_id": ran.get("scenario_id"),
        "seed": ran.get("seed"),
        "scheduler": ran.get("scheduler"),
        "completed_slots": ran.get("completed_slots"),
        "last_ran_slots": ran.get("last_slots", []),
        "core_policies": [
            recommend_policy("embb"),
            recommend_policy("urllc"),
        ],
        "auto_apply": False,
        "note": "RAN-Core plan only; no automatic Apply."
    }
