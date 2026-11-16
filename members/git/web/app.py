"""Local UI and batch API. Start from repository root: uvicorn web.app:app --port 8080."""
from __future__ import annotations

import csv
import html
import io
import json
import os
import re
import threading
import uuid
import zipfile
import yaml
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field, model_validator

from .runner import ROOT, aggregate, run_one
from members.TV5.orchestrator_web import Orchestrator, SessionError

DATA = Path(os.environ.get("NSL_WEB_DATA", str(ROOT / "web_data"))).resolve()
DATA.mkdir(parents=True, exist_ok=True)
CORE = os.environ.get("TV4_CORE_URL", "http://127.0.0.1:18018").rstrip("/")
app = FastAPI(title="NSL Lab Dashboard", version="1.0")
LOCK = threading.Lock()
JOBS: dict[str, dict] = {}
TV5 = Orchestrator(DATA / 'tv5_sessions')
ALGORITHMS = ("static", "queue_based", "qos_heuristic", "dqn")
CORE_SCENARIOS = ("normal", "delay", "outage", "loss", "recovery")


class Experiment(BaseModel):
    scenario: str = "stable_load"
    algorithms: list[str] = Field(default_factory=lambda: list(ALGORITHMS))
    seeds: list[int] = Field(default_factory=lambda: [42, 43, 44])
    slots: int = Field(500, ge=1, le=500)
    total_rb: int = Field(50, ge=10, le=100)
    embb_arrival: int = Field(18000, ge=0, le=200000)
    urllc_arrival: float = Field(1.5, ge=0, le=20)
    deadline_ms: float = Field(5, ge=1, le=100)
    embb_cqi: int = Field(11, ge=1, le=15)
    urllc_cqi: int = Field(8, ge=1, le=15)
    burst_multiplier: float = Field(6, ge=1, le=20)
    core_scenario: str = "normal"
    core_mode: str = "live"  # live, off; no historical KPI mixed into this run

    @model_validator(mode="after")
    def valid(self):
        if self.scenario not in ("stable_load", "urllc_burst", "poor_channel"):
            raise ValueError("Unknown RAN scenario")
        if not self.algorithms or len(set(self.algorithms)) != len(self.algorithms) or any(a not in ALGORITHMS for a in self.algorithms):
            raise ValueError("Select unique supported algorithms")
        if not self.seeds or len(self.seeds) > 10 or len(set(self.seeds)) != len(self.seeds) or any(s < 0 or s > 2**31 - 1 for s in self.seeds):
            raise ValueError("Select 1–10 unique nonnegative seeds")
        if self.core_scenario not in CORE_SCENARIOS or self.core_mode not in ("live", "off"):
            raise ValueError("Unknown Core scenario or mode")
        return self


class TV5Session(BaseModel):
    experiment: Experiment
    algorithm: str = 'static'
    seed: int = Field(42, ge=0)
    fallback: bool = True
    inject_dqn_failure: bool = False


class SuiteRequest(BaseModel):
    experiment: Experiment
    scenarios: list[str] = Field(default_factory=lambda: ['stable_load', 'urllc_burst', 'poor_channel'])
    core_scenarios: list[str] = Field(default_factory=lambda: ['normal'])

    @model_validator(mode='after')
    def validate_suite(self):
        if not self.scenarios or len(set(self.scenarios)) != len(self.scenarios) or any(x not in ('stable_load', 'urllc_burst', 'poor_channel') for x in self.scenarios):
            raise ValueError('Bộ RAN phải gồm các kịch bản hợp lệ, không lặp')
        if not self.core_scenarios or len(set(self.core_scenarios)) != len(self.core_scenarios) or any(x not in CORE_SCENARIOS for x in self.core_scenarios):
            raise ValueError('Bộ Core phải gồm các kịch bản hợp lệ, không lặp')
        return self


def core_request(method: str, path: str, payload: dict | None = None, timeout: int = 120) -> dict:
    # CORE is configured by the machine owner, never taken from browser input.
    data = json.dumps(payload).encode() if payload is not None else None
    request = Request(CORE + path, data=data, method=method,
                      headers={"Content-Type": "application/json", "Accept": "application/json"})
    try:
        with urlopen(request, timeout=timeout) as response:
            return json.load(response)
    except HTTPError as exc:
        raise RuntimeError(f"Core HTTP {exc.code}: {exc.read(300).decode(errors='replace')}") from exc
    except (URLError, TimeoutError) as exc:
        raise RuntimeError(f"Không kết nối được Core tại {CORE}: {exc}") from exc


def save(job: dict) -> None:
    folder = DATA / job["id"]
    folder.mkdir(parents=True, exist_ok=True)
    # Readers poll while the worker runs; never expose a partially written JSON.
    temporary = folder / "job.json.tmp"
    temporary.write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, folder / "job.json")


def execute(job: dict, release_lock: bool = True):
    folder = DATA / job["id"]
    spec = job["spec"]
    applied = False
    try:
        job["status"] = "running"
        save(job)
        if "dqn" in spec["algorithms"]:
            # Fail before changing the GNS3 lab if the local model cannot load.
            from members.TV3.dqn_scheduler import DQNScheduler
            DQNScheduler(ROOT / "members/TV3/models/dqn_v2_best.zip", total_rb=spec["total_rb"])
        if spec["core_mode"] == "live":
            # Lab agent extends the existing TV4 controller on the GNS3 VM.
            job["core_health"] = core_request("GET", "/v1/lab/health")
            job["policies_initial"] = core_request("GET", "/policies")
            job["baseline_scenario_result"] = core_request("POST", "/v1/lab/scenario", {"scenario": "normal", "run_id": job["id"]})
            applied = True
            job["policies_before"] = core_request("GET", "/policies")
            if spec["core_scenario"] != "normal":
                job["core_before"] = core_request("POST", "/v1/lab/measure",
                                                  {"run_id": job["id"], "scenario": "normal"}, timeout=180)
                if job["core_before"].get("measurement", {}).get("is_live") is not True:
                    raise RuntimeError("TV4 did not return a live baseline measurement")
            job["core_scenario_result"] = core_request("POST", "/v1/lab/scenario", {"scenario": spec["core_scenario"], "run_id": job["id"]})
            job["policies_after"] = core_request("GET", "/policies")
            job["events"].append("Đã áp kịch bản Core: " + spec["core_scenario"])
            save(job)
        for algorithm in spec["algorithms"]:
            for seed in spec["seeds"]:
                result = run_one(spec, seed, algorithm, folder / algorithm / str(seed), job["id"])
                job["results"].append(result)
                job["progress"] = len(job["results"])
                save(job)
        job["comparison"] = aggregate(job["results"])
        if spec["core_mode"] == "live":
            job["core"] = core_request("POST", "/v1/lab/measure", {"run_id": job["id"], "scenario": spec["core_scenario"]}, timeout=180)
            if job["core"].get("measurement", {}).get("is_live") is not True:
                raise RuntimeError("TV4 did not return a live measurement")
            try:
                job["core_events"] = core_request("GET", "/v1/events")
            except Exception as exc:
                job["events"].append("Không đọc được nhật ký TV4: " + str(exc))
            job["events"].append("Đo Core mới hoàn tất; số liệu Core dùng chung cho cả bốn thuật toán RAN")
        job["status"] = "completed"
    except Exception as exc:
        job["status"] = "failed"
        job["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        if applied:
            try:
                job["restore_result"] = core_request("POST", "/v1/lab/scenario", {"scenario": "normal", "run_id": job["id"]})
                job["policies_restored"] = core_request("GET", "/policies")
                for slice_id, expected in {"embb": "high_bandwidth", "urllc": "low_latency"}.items():
                    observed = job["policies_restored"].get("slices", {}).get(slice_id, {}).get("active_policy")
                    if observed != expected:
                        raise RuntimeError(f"Restore readback mismatch for {slice_id}: {observed}")
                if spec["core_scenario"] != "normal" and job["core"] is not None:
                    job["core_restored"] = core_request("POST", "/v1/lab/measure",
                                                        {"run_id": job["id"], "scenario": "normal"}, timeout=180)
                    if job["core_restored"].get("measurement", {}).get("is_live") is not True:
                        raise RuntimeError("TV4 did not return live recovery measurement")
                job["events"].append("Đã khôi phục kịch bản Core bình thường")
            except Exception as exc:
                job["events"].append("CẦN KHÔI PHỤC CORE THỦ CÔNG: " + str(exc))
                job["status"] = "failed"
        save(job)
        if release_lock:
            LOCK.release()


def load(run_id: str) -> dict:
    if not re.fullmatch(r"[a-f0-9]{16}", run_id):
        raise HTTPException(404, "Unknown run")
    path = DATA / run_id / "job.json"
    if not path.is_file():
        raise HTTPException(404, "Unknown run")
    return json.loads(path.read_text(encoding="utf-8"))


def report_html(job: dict) -> str:
    rows = job["comparison"]
    def bars(key, multiplier=1):
        maximum = max([(r[key] or 0) * multiplier for r in rows] + [1])
        body = []
        for i, row in enumerate(rows):
            value = (row[key] or 0) * multiplier
            label = f"{value:.4f}" if row[key] is not None else "N/A"
            body.append(f'<text x="5" y="{35+i*48}">{html.escape(row["algorithm"])}</text>'
                        f'<rect x="125" y="{15+i*48}" width="{round(390*value/maximum, 2)}" height="28" fill="#087ba7"/>'
                        f'<text x="525" y="{35+i*48}">{label}</text>')
        return '<svg viewBox="0 0 600 220" width="600" role="img">' + ''.join(body) + '</svg>'
    table = ''.join('<tr>' + ''.join(f'<td>{html.escape(str(value))}</td>' for value in row.values()) + '</tr>' for row in rows)
    columns = ''.join(f'<th>{html.escape(k)}</th>' for k in rows[0]) if rows else ''
    core = html.escape(json.dumps({"before": job.get("core_before"), "after": job.get("core"),
                                   "after_recovery": job.get("core_restored"),
                                   "policy_initial": job.get("policies_initial"),
                                   "policy_before": job.get("policies_before"),
                                   "policy_after": job.get("policies_after"),
                                   "policy_restored": job.get("policies_restored"),
                                   "qdisc_scenario": job.get("core_scenario_result"),
                                   "qdisc_restored": job.get("restore_result")}, ensure_ascii=False, indent=2))
    events = html.escape('\n'.join(job.get("events", [])))
    return f'''<!doctype html><html lang="vi"><meta charset="utf-8"><title>NSL {job['id']}</title>
<style>body{{font:15px Arial;max-width:1000px;margin:40px auto;color:#16334a}}table{{border-collapse:collapse;width:100%}}td,th{{border:1px solid #ccdce5;padding:8px;text-align:left}}svg{{max-width:100%}}pre{{white-space:pre-wrap;background:#f1f6f9;padding:15px}}</style>
<h1>Báo cáo NSL · {job['id']}</h1><p>Trạng thái: {html.escape(job['status'])}; RAN: {html.escape(job['spec']['scenario'])}; Core: {html.escape(job['spec']['core_scenario'])}; seed: {html.escape(str(job['spec']['seeds']))}</p>
<p>RAN mô phỏng; Core đo tuần tự trong cửa sổ riêng. Không phải phép đo trễ End-to-End cùng một gói. Dữ liệu Core lịch sử không được ghép vào đây.</p>
<h2>Trung bình các seed</h2><table><tr>{columns}</tr>{table}</table>
<h2>Thông lượng eMBB (Mbps)</h2>{bars('throughput_e') if rows else '<p>Chưa có dữ liệu</p>'}
<h2>Tỷ lệ rớt gói URLLC (%)</h2>{bars('drop_rate_total',100) if rows else '<p>Chưa có dữ liệu</p>'}
<h2>Core trước–sau và policy readback</h2><pre>{core}</pre><h2>Nhật ký kịch bản</h2><pre>{events}</pre></html>'''


@app.get("/")
def index():
    return FileResponse(Path(__file__).parent / "index.html")


@app.get("/api/health")
def health():
    try:
        core = core_request("GET", "/v1/lab/health", timeout=3)
    except Exception as exc:
        core = {"status": "unavailable", "error": str(exc)}
    return {"status": "ok", "core": core, "core_url": CORE,
            "note": "Core API historical KPI is not used as live data"}


@app.get('/api/readiness')
def readiness():
    required = {
        'TV1 config stable_load': ROOT / 'members/TV1/configs/stable_load.yaml',
        'TV1 config urllc_burst': ROOT / 'members/TV1/configs/urllc_burst.yaml',
        'TV1 config poor_channel': ROOT / 'members/TV1/configs/poor_channel.yaml',
        'TV2 QoS scheduler': ROOT / 'members/TV2/src/schedulers/qos_heuristic.py',
        'TV3 DQN checkpoint': ROOT / 'members/TV3/models/dqn_v2_best.zip',
        'TV4 VM agent': ROOT / 'members/TV4/controller/tv4_web_agent.py',
        'TV5 web orchestrator': ROOT / 'members/TV5/orchestrator_web.py',
    }
    files = {k: {'available': v.is_file(), 'path': str(v.relative_to(ROOT))} for k, v in required.items()}
    try:
        core = core_request('GET', '/v1/lab/health', timeout=4)
    except Exception as exc:
        core = {'status': 'unavailable', 'error': str(exc)}
    return {'files': files, 'core': core, 'live_core_ready': core.get('status') == 'ok',
            'missing': [k for k, v in files.items() if not v['available']]}


@app.post("/api/runs", status_code=202)
def create(spec: Experiment):
    if not LOCK.acquire(blocking=False):
        raise HTTPException(409, "Một thí nghiệm đang chạy; đợi hoàn tất để tránh thay đổi Core đồng thời")
    run_id = uuid.uuid4().hex[:16]
    job = {"id": run_id, "created_at": datetime.now(timezone.utc).isoformat(),
           "status": "queued", "spec": spec.model_dump(), "progress": 0,
           "total": len(spec.algorithms) * len(spec.seeds), "results": [], "comparison": [],
           "core": None, "core_before": None, "events": [], "error": None,
           "note": "RAN mô phỏng; Core đo trên GNS3 VM theo cửa sổ riêng. Không phải phép đo End-to-End cùng gói tin."
                   + (" Chạy dưới 500 slot là thử nghiệm ngắn, không phải benchmark đầy đủ." if spec.slots < 500 else "")}
    save(job)
    threading.Thread(target=execute, args=(job,), daemon=True).start()
    return {"id": run_id, "status": "queued"}


@app.get("/api/runs")
def list_runs():
    runs = []
    for path in sorted(DATA.glob("*/job.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:50]:
        try:
            job = json.loads(path.read_text(encoding="utf-8"))
            runs.append({key: job[key] for key in ("id", "created_at", "status", "progress", "total", "spec")})
        except (OSError, KeyError, ValueError):
            continue
    return runs


@app.get("/api/runs/{run_id}")
def get_run(run_id: str):
    return load(run_id)


@app.get("/api/runs/{run_id}/download")
def download(run_id: str):
    load(run_id)
    folder = DATA / run_id
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in folder.rglob("*"):
            if path.is_file():
                archive.write(path, path.relative_to(folder))
        job = load(run_id)
        if job["comparison"]:
            csv_stream = io.StringIO()
            writer = csv.DictWriter(csv_stream, fieldnames=list(job["comparison"][0]))
            writer.writeheader()
            writer.writerows(job["comparison"])
            archive.writestr("comparison.csv", csv_stream.getvalue().encode("utf-8-sig"))
        archive.writestr("report.html", report_html(job).encode("utf-8"))
        archive.writestr("README.txt", "RAN mô phỏng; Core được đo trong cửa sổ riêng, không suy ra E2E latency.\nCore historical KPI không dùng trong kết quả này.\n".encode())
    return Response(stream.getvalue(), media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="NSL_{run_id}.zip"'})


def tv5_call(callback, *args):
    try:
        return callback(*args)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except (SessionError, ValueError) as exc:
        raise HTTPException(409, str(exc)) from exc


@app.post('/api/tv5/sessions', status_code=201)
def tv5_create(payload: TV5Session):
    return tv5_call(TV5.create, payload.experiment.model_dump(), payload.algorithm,
                    payload.seed, payload.fallback, payload.inject_dqn_failure)


@app.get('/api/tv5/sessions')
def tv5_saved_sessions():
    return TV5.list_saved()


@app.get('/api/tv5/sessions/{run_id}/state')
def tv5_state(run_id: str):
    return tv5_call(TV5.state, run_id)


@app.post('/api/tv5/sessions/{run_id}/decision')
def tv5_decision(run_id: str):
    return tv5_call(TV5.decision, run_id)


@app.post('/api/tv5/sessions/{run_id}/step')
def tv5_step(run_id: str):
    return tv5_call(TV5.step, run_id)


@app.post('/api/tv5/sessions/{run_id}/run-to-end')
def tv5_run_to_end(run_id: str):
    return tv5_call(TV5.run_to_end, run_id)


@app.get('/api/tv5/sessions/{run_id}/metrics')
def tv5_metrics(run_id: str):
    return tv5_call(TV5.metrics, run_id)


@app.get('/api/tv5/sessions/{run_id}/download')
def tv5_download(run_id: str):
    metrics = tv5_call(TV5.metrics, run_id)
    if metrics['status'] != 'completed':
        raise HTTPException(409, 'Chưa hoàn thành session')
    folder = TV5.output_root / run_id
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w', zipfile.ZIP_DEFLATED) as archive:
        for path in folder.iterdir():
            if path.is_file():
                archive.write(path, path.name)
    return Response(stream.getvalue(), media_type='application/zip',
                    headers={'Content-Disposition': f'attachment; filename="TV5_{run_id}.zip"'})


def suite_save(suite):
    folder = DATA / suite['id']
    folder.mkdir(parents=True, exist_ok=True)
    tmp = folder / 'suite.json.tmp'
    tmp.write_text(json.dumps(suite, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(tmp, folder / 'suite.json')


def suite_worker(suite):
    try:
        suite['status'] = 'running'
        suite_save(suite)
        for scenario in suite['scenarios']:
            for core_scenario in suite['core_scenarios']:
                spec = {**suite['experiment'], 'scenario': scenario, 'core_scenario': core_scenario}
                if scenario != suite['experiment']['scenario']:
                    preset = yaml.safe_load((ROOT / 'members/TV1/configs' / f'{scenario}.yaml').read_text(encoding='utf-8'))
                    spec.update(embb_arrival=preset['embb']['arrival_rate_bits_per_slot'],
                                urllc_arrival=preset['urllc']['arrival_rate_packets_per_slot'],
                                embb_cqi=preset['channel']['embb_initial_cqi'],
                                urllc_cqi=preset['channel']['urllc_initial_cqi'],
                                burst_multiplier=preset['urllc']['burst_multiplier'])
                run_id = uuid.uuid4().hex[:16]
                child = {'id': run_id, 'created_at': datetime.now(timezone.utc).isoformat(),
                         'status': 'queued', 'spec': spec, 'progress': 0,
                         'total': len(spec['algorithms']) * len(spec['seeds']), 'results': [],
                         'comparison': [], 'core': None, 'core_before': None, 'events': [], 'error': None,
                         'note': 'Bộ kiểm thử; RAN mô phỏng, Core đo riêng; dưới 500 slot là thử nghiệm ngắn.'}
                suite['current'] = {'scenario': scenario, 'core_scenario': core_scenario, 'run_id': run_id}
                suite_save(suite)
                execute(child, release_lock=False)
                suite['runs'].append({'id': run_id, 'scenario': scenario, 'core_scenario': core_scenario,
                                      'status': child['status'], 'error': child['error']})
                suite['progress'] += 1
                suite_save(suite)
        suite['status'] = 'completed' if all(r['status'] == 'completed' for r in suite['runs']) else 'partial_failed'
    except Exception as exc:
        suite['status'] = 'failed'
        suite['error'] = f'{type(exc).__name__}: {exc}'
    finally:
        suite['current'] = None
        suite_save(suite)
        LOCK.release()


@app.post('/api/suites', status_code=202)
def create_suite(payload: SuiteRequest):
    if not LOCK.acquire(blocking=False):
        raise HTTPException(409, 'Một thí nghiệm đang chạy')
    suite = {'id': uuid.uuid4().hex[:16], 'created_at': datetime.now(timezone.utc).isoformat(),
             'status': 'queued', 'experiment': payload.experiment.model_dump(),
             'scenarios': payload.scenarios, 'core_scenarios': payload.core_scenarios,
             'total': len(payload.scenarios) * len(payload.core_scenarios), 'progress': 0,
             'current': None, 'runs': [], 'error': None}
    suite_save(suite)
    threading.Thread(target=suite_worker, args=(suite,), daemon=True).start()
    return {'id': suite['id'], 'status': 'queued'}


@app.get('/api/suites/{suite_id}')
def get_suite(suite_id: str):
    if not re.fullmatch(r'[a-f0-9]{16}', suite_id):
        raise HTTPException(404, 'Unknown suite')
    path = DATA / suite_id / 'suite.json'
    if not path.is_file():
        raise HTTPException(404, 'Unknown suite')
    return json.loads(path.read_text(encoding='utf-8'))


@app.get('/api/suites')
def list_suites():
    output = []
    for path in sorted(DATA.glob('*/suite.json'), key=lambda p: p.stat().st_mtime, reverse=True)[:50]:
        try:
            suite = json.loads(path.read_text(encoding='utf-8'))
            output.append({k: suite[k] for k in ('id', 'created_at', 'status', 'progress', 'total')})
        except (OSError, ValueError, KeyError):
            continue
    return output
