"""Session-based TV5 RAN Orchestrator V2.

Real TV1 simulator, real TV2/TV3 schedulers. TV4 SRv6 is NOT connected.
An in-memory, single-process teaching prototype, not a 1 ms real-time controller.
"""
from __future__ import annotations

import csv
import json
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4

import yaml
TV1_SRC = (
    Path(__file__).resolve().parents[2]
    / "members"
    / "TV1"
    / "src"
)

if str(TV1_SRC) not in sys.path:
    sys.path.insert(0, str(TV1_SRC))
from ran.rb_capacity import CQI_SPECTRAL_EFFICIENCY
from members.TV1.src.ran import RANSimulator, simulator
from members.TV1.src.ran.schemas import validate_action as tv1_validate_action
from members.TV2.src.schedulers.action_validator import validate_action as tv2_validate_action
from members.TV2.src.schedulers.queue_based import QueueBasedScheduler
from members.TV2.src.schedulers.qos_heuristic import QoSHeuristicScheduler
from members.TV2.src.schedulers.static import StaticScheduler
from members.TV5.integration_runner import POLICIES, ROOT, SCENARIOS, verify

CONFIG_TV2 = ROOT / 'members/TV2/configs/schedulers.yaml'
OUTPUT_ROOT = ROOT / 'members/TV5/results/api_v2'
SUPPORTED_SCHEDULERS = (
    'static',
    'queue_based',
    'qos_heuristic',
    'dqn',
)


class SessionNotFound(KeyError):
    pass


class SessionFinished(ValueError):
    pass


@dataclass
class Session:
    run_id: str
    scheduler: str
    scenario: str
    seed: int
    target_slots: int
    simulator: RANSimulator
    tv2_config: dict
    agent: Any = None
    allow_fallback: bool = False
    dqn_initialization_error: str | None = None
    fallback_count: int = 0
    pending_fallback_used: bool = False
    pending_fallback_reason: str = ''
    completed_slots: int = 0
    done: bool = False
    pending_action: dict | None = None
    pending_latencies_ms: dict = field(default_factory=dict)
    records: list[dict] = field(default_factory=list)
    action_log: list[dict] = field(default_factory=list)


class Orchestrator:
    """Single-worker RAN integration API: returns RAN-only data; never fakes TV4."""

    def __init__(self, output_root: Path = OUTPUT_ROOT):
        self._sessions: dict[str, Session] = {}
        self._lock = threading.RLock()
        self.output_root = Path(output_root)

    def create(self, scheduler: str, scenario: str, seed: int, slots: int, allow_fallback: bool = False) -> dict:
        with self._lock:
            if not isinstance(allow_fallback, bool):
                raise ValueError('allow_fallback must be boolean')
            if scheduler not in SUPPORTED_SCHEDULERS:
                raise ValueError(f'Scheduler must be one of {SUPPORTED_SCHEDULERS}')
            if scenario not in SCENARIOS:
                raise ValueError(f'Scenario must be one of {SCENARIOS}')
            if not isinstance(seed, int) or seed < 0:
                raise ValueError('seed must be a nonnegative integer')
            simulator = RANSimulator.from_yaml(ROOT / 'members/TV1/configs' / f'{scenario}.yaml')
            if not isinstance(slots, int) or not (1 <= slots <= simulator.total_slots):
                raise ValueError(f'slots must be in [1, {simulator.total_slots}]')
            simulator.reset(seed=seed)
            tv2_config = yaml.safe_load(CONFIG_TV2.read_text(encoding='utf-8'))
            tv2_config['common']['slot_duration_ms'] = simulator.slot_duration_ms
            tv2_config['common']['total_rb'] = simulator.total_rb

            agent = None
            init_error = None
            if scheduler == 'dqn':
                try:
                    from members.TV3.dqn_scheduler import DQNScheduler
                    agent = DQNScheduler(
                        model_path=ROOT / 'members/TV3/models/dqn_v2_best.zip',
                        total_rb=simulator.total_rb,
                    )
                except Exception as exc:
                    if not allow_fallback:
                        raise
                    init_error = f'{type(exc).__name__}: {exc}'
            run_id = 'run-' + uuid4().hex[:16]
            session = Session(
                run_id, scheduler, scenario, seed, slots, simulator, tv2_config,
                agent=agent, allow_fallback=allow_fallback,
                dqn_initialization_error=init_error,
            )
            self._sessions[run_id] = session
            state = simulator.get_state()
            verify('state.schema.json', state)
            return {'run_id': run_id, 'status': 'active', 'scheduler': scheduler,
                    'scenario_id': scenario, 'seed': seed, 'target_slots': slots,
                    'state': state, 'allow_fallback': allow_fallback, 'core_status': 'NOT_CONNECTED'}

    def _get(self, run_id: str) -> Session:
        try:
            return self._sessions[run_id]
        except KeyError as exc:
            raise SessionNotFound(f'Unknown run_id: {run_id}') from exc

    def state(self, run_id: str) -> dict:
        with self._lock:
            s = self._get(run_id)
            return {'run_id': run_id, 'done': s.done, 'completed_slots': s.completed_slots,
                    'state': None if s.done else s.simulator.get_state()}

    def _candidate_action(self, s, name, state, request_id):
        if name == 'dqn':
            if s.dqn_initialization_error:
                raise RuntimeError('DQN init failed: ' + s.dqn_initialization_error)
            if s.agent is None:
                raise RuntimeError('DQN agent not initialized')
            return s.agent.predict(state, request_id=request_id)
        if name == 'qos_heuristic':
            return QoSHeuristicScheduler().select_action(
                state, s.tv2_config, request_id=request_id
            )
        if name == 'static':
            return StaticScheduler().select_action(
                state, s.tv2_config, request_id=request_id
            )
        if name == 'queue_based':
            return QueueBasedScheduler().select_action(
                state, s.tv2_config, request_id=request_id
            )
        raise ValueError('Unsupported scheduler: ' + name)

    def _validate_candidate(self, action, name, state, request_id, total_rb):
        verify('action.schema.json', action)
        tv1_validate_action(action, total_rb, state['time_slot'])

        if name == 'dqn':
            from members.TV3.network_slicing_env import make_action
            expected = make_action(
                action['action_id'], state, total_rb, request_id
            )
            if action != expected:
                raise ValueError('DQN Action does not match TV3 action mapping')
        else:
            tv2_validate_action(
                action, state, total_rb, require_all_rb=True
            )

        if action['request_id'] != request_id or action['scheduler'] != name:
            raise ValueError('Request ID or scheduler mismatched')

    def _decide(self, s: Session) -> dict:
        if s.done:
            raise SessionFinished(
                'Session finished. Create a new session to continue.'
            )
        if s.pending_action is not None:
            return s.pending_action

        state = s.simulator.get_state()
        verify('state.schema.json', state)
        request_id = f'{s.run_id}-{state["time_slot"]:06d}'

        chain = [s.scheduler]
        if s.allow_fallback and s.scheduler == 'dqn':
            chain = ['dqn', 'qos_heuristic', 'static']
        elif s.allow_fallback and s.scheduler == 'qos_heuristic':
            chain = ['qos_heuristic', 'static']

        errors = []
        scheduler_ms = 0.0
        validation_ms = 0.0

        for name in chain:
            start = time.perf_counter()
            try:
                action = self._candidate_action(
                    s, name, state, request_id
                )
            except Exception as exc:
                scheduler_ms += (time.perf_counter() - start) * 1000.0
                if not s.allow_fallback:
                    raise
                errors.append(f'{name}: {type(exc).__name__}: {exc}')
                continue

            scheduler_ms += (time.perf_counter() - start) * 1000.0
            start = time.perf_counter()

            try:
                self._validate_candidate(
                    action, name, state, request_id,
                    s.simulator.total_rb
                )
            except Exception as exc:
                validation_ms += (time.perf_counter() - start) * 1000.0
                if not s.allow_fallback:
                    raise
                errors.append(f'{name}: {type(exc).__name__}: {exc}')
                continue

            validation_ms += (time.perf_counter() - start) * 1000.0

            s.pending_action = action
            s.pending_fallback_used = name != s.scheduler
            s.pending_fallback_reason = '; '.join(errors)
            s.pending_latencies_ms = {
                'scheduler_latency_ms': round(scheduler_ms, 6),
                'validation_latency_ms': round(validation_ms, 6),
            }
            return action

        raise RuntimeError(
            'All fallback candidates failed: ' + '; '.join(errors)
        )

    def decision(self, run_id: str) -> dict:
        with self._lock:
            s = self._get(run_id)
            action = self._decide(s)
            return {'run_id': run_id, 'action': action,
                    'requested_scheduler': s.scheduler,
                    'selected_scheduler': action['scheduler'],
                    'fallback_used': s.pending_fallback_used,
                    'fallback_reason': s.pending_fallback_reason,
                    **s.pending_latencies_ms}

    def step(self, run_id: str) -> dict:
        with self._lock:
            s = self._get(run_id)
            action = self._decide(s)
            state = s.simulator.get_state()
            transition = s.simulator.apply_action(action)
            verify('ran_kpi.schema.json', transition['ran_kpi'])
            kpi = transition['ran_kpi']
            for key, expected in {
                'request_id': action['request_id'], 'seed': s.seed,
                'scenario_id': s.scenario, 'time_slot': state['time_slot'],
                'algorithm': action['scheduler'],
            }.items():
                if kpi[key] != expected:
                    raise ValueError(f'KPI join key mismatch: {key}')
            for slice_id, policy in POLICIES.items():
                # Policy label is a plan ONLY; no SRv6 changes or measurements occur here.
                s.records.append({
                    'run_id': s.run_id, 'schema_version': '1.0.0',
                    'scenario_id': s.scenario, 'seed': s.seed,
                    'time_slot': state['time_slot'], 'request_id': action['request_id'],
                    'requested_scheduler': s.scheduler, 'selected_scheduler': action['scheduler'],
                    'fallback_used': s.pending_fallback_used, 'fallback_reason': s.pending_fallback_reason,
                    'slice_id': slice_id, 'selected_policy': policy,
                    'action_id': action['action_id'],
                    'embb_rb': action['rb_allocation']['embb'],
                    'urllc_rb': action['rb_allocation']['urllc'],
                    'embb_queue_bits': state['embb']['queue_bits'],
                    'urllc_queue_bits': state['urllc']['queue_bits'],
                    'scheduler_latency_ms': s.pending_latencies_ms['scheduler_latency_ms'],
                    'validation_latency_ms': s.pending_latencies_ms['validation_latency_ms'],
                    **{key: value for key, value in kpi.items() if key not in
                       ('schema_version', 'request_id', 'seed', 'scenario_id', 'algorithm', 'time_slot', 'units')},
                    'core_status': 'NOT_CONNECTED', 'rtt_ms': '',
                    'core_throughput_mbps': '', 'packet_loss': '', 'switching_time_ms': '',
                })
            s.action_log.append({
                'run_id': run_id,
                'action': action,
                'ran_kpi': kpi,
                'requested_scheduler': s.scheduler,
                'selected_scheduler': action['scheduler'],
                'fallback_used': s.pending_fallback_used,
                'fallback_reason': s.pending_fallback_reason,
                **s.pending_latencies_ms,
            })
            if s.pending_fallback_used:
                s.fallback_count += 1

            applied_fallback = s.pending_fallback_used
            applied_reason = s.pending_fallback_reason

            s.pending_action = None
            s.pending_latencies_ms = {}
            s.pending_fallback_used = False
            s.pending_fallback_reason = ''
            s.completed_slots += 1
            s.done = s.completed_slots >= s.target_slots or bool(transition['done'])
            if s.done:
                self._save(s)
            return {'run_id': run_id, 'completed_slots': s.completed_slots,
                    'done': s.done, 'action': action,
                    'fallback_used': applied_fallback,
                    'fallback_reason': applied_reason,
                    'ran_kpi': kpi, 'next_state': None if s.done else transition['next_state'],
                    'selected_policies': POLICIES, 'core_status': 'NOT_CONNECTED'}

    def run_to_end(self, run_id: str) -> dict:
        # Used only for small local smoke tests and offline experiments.
        with self._lock:
            s = self._get(run_id)
            while not s.done:
                self.step(run_id)
            return self.metrics(run_id)

    def metrics(self, run_id: str) -> dict:
        with self._lock:
            s = self._get(run_id)
            unique_slots = [r for r in s.records if r['slice_id'] == 'embb']
            result = {
                'run_id': run_id, 'status': 'completed' if s.done else 'active',
                'scheduler': s.scheduler, 'scenario_id': s.scenario,
                'seed': s.seed, 'completed_slots': s.completed_slots,
                'target_slots': s.target_slots, 'fallback_count': s.fallback_count,
                'core_status': 'NOT_CONNECTED',
                'rb_conservation_ok': all(int(r['embb_rb']) + int(r['urllc_rb']) == s.simulator.total_rb
                                          for r in unique_slots),
                'last_slots': [
                    {key: r[key] for key in ('time_slot','request_id','selected_scheduler',
                           'fallback_used','fallback_reason','action_id','embb_rb','urllc_rb','throughput_e','delay_u','drop_u')}
                    for r in unique_slots[-5:]
                ],
                'result_csv': (str((self.output_root / run_id / 'unified_without_core.csv').relative_to(ROOT))
                               if s.done and self.output_root.is_relative_to(ROOT) else None),
            }
            if s.done and s.completed_slots == s.simulator.total_slots:
                result['ran_run_summary'] = s.simulator.build_run_summary()
            elif s.done:
                result['note'] = ('Partial smoke-test: do not use TV1 run summary for ' 
                                  'full-run KPI comparison; only a subset of slots was executed.')
            return result

    def _save(self, s: Session) -> None:
        output = self.output_root / s.run_id
        output.mkdir(parents=True, exist_ok=True)
        path = output / 'unified_without_core.csv'
        with path.open('w', newline='', encoding='utf-8-sig') as stream:
            writer = csv.DictWriter(stream, fieldnames=list(s.records[0]))
            writer.writeheader()
            writer.writerows(s.records)
        with (output / 'orchestrator_log.jsonl').open('w', encoding='utf-8') as stream:
            for line in s.action_log:
                stream.write(json.dumps(line, ensure_ascii=False) + '\n')
        (output / 'status.json').write_text(json.dumps({
            'run_id': s.run_id, 'scheduler': s.scheduler, 'scenario_id': s.scenario,
            'seed': s.seed, 'completed_slots': s.completed_slots,
            'core_status': 'NOT_CONNECTED', 'fallback_count': s.fallback_count,
            'partial_smoke_test': s.completed_slots < s.simulator.total_slots,
        }, ensure_ascii=False, indent=2), encoding='utf-8')
        # Export full-run TV1 summary only when simulation has actually run all configured slots.
        if s.completed_slots == s.simulator.total_slots:
            s.simulator.export_results(output / 'ran')
