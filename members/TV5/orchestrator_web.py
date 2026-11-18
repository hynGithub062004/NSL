"""TV5 session orchestration for the lab web, using TV1/TV2/TV3 source modules.

Sessions live in this single web process; completed traces are saved under web_data.
Core lab measurements are orchestrated separately by web.app and never joined as
packet-level RAN measurements.
"""
from __future__ import annotations

import csv
import json
import threading
import time
from pathlib import Path
from uuid import uuid4

import yaml

from web.runner import ROOT, SCHEDULERS, scenario_config
from members.TV1.src.ran import RANSimulator
from members.TV1.src.ran.schemas import validate_action as validate_tv1
from members.TV2.src.schedulers.action_validator import validate_action as validate_tv2


class SessionError(Exception):
    pass


class Orchestrator:
    def __init__(self, output_root: Path):
        self.output_root = Path(output_root)
        self.sessions = {}
        self.lock = threading.RLock()

    def create(self, spec: dict, algorithm: str, seed: int, fallback: bool = True,
               inject_dqn_failure: bool = False) -> dict:
        with self.lock:
            if algorithm not in (*SCHEDULERS, 'dqn'):
                raise SessionError('Thuật toán không hợp lệ')
            if inject_dqn_failure and algorithm != 'dqn':
                raise SessionError('Chỉ tiêm lỗi cho DQN')
            config = scenario_config(spec, seed)
            sim = RANSimulator(config)
            sim.reset(seed=seed)
            tv2 = yaml.safe_load((ROOT / 'members/TV2/configs/schedulers.yaml').read_text(encoding='utf-8'))
            total = spec['total_rb']
            tv2['common'].update(total_rb=total, slot_duration_ms=config['simulation']['slot_duration_ms'])
            tv2['static'].update(rb_embb=total // 2, rb_urllc=total - total // 2)
            agent = None
            init_error = None
            if algorithm == 'dqn' and not inject_dqn_failure:
                try:
                    from members.TV3.dqn_scheduler import DQNScheduler
                    agent = DQNScheduler(ROOT / 'members/TV3/models/dqn_v3_best.zip', total_rb=total)
                except (ImportError, OSError, RuntimeError, ValueError) as exc:
                    init_error = f'{type(exc).__name__}: {exc}'
                    if not fallback:
                        raise SessionError(init_error) from exc
            if inject_dqn_failure:
                init_error = 'Kiểm thử lỗi DQN có chủ đích'
                if not fallback:
                    raise SessionError(init_error)
            run_id = uuid4().hex[:16]
            self.sessions[run_id] = {'sim': sim, 'config': config, 'tv2': tv2, 'agent': agent,
                'init_error': init_error, 'algorithm': algorithm, 'seed': seed, 'fallback': fallback,
                'inject': inject_dqn_failure, 'target': spec['slots'], 'pending': None,
                'records': [], 'actions': [], 'done': False, 'created': time.time(),
                'partial': spec['slots'] < yaml.safe_load((ROOT / 'members/TV1/configs' / f'{spec["scenario"]}.yaml').read_text(encoding='utf-8'))['simulation']['slots']}
            return self.state(run_id)

    def _get(self, run_id):
        if run_id not in self.sessions:
            raise KeyError('Không tìm thấy session TV5 (session RAM mất khi khởi động lại web)')
        return self.sessions[run_id]

    def state(self, run_id):
        with self.lock:
            s = self._get(run_id)
            return {'run_id': run_id, 'done': s['done'], 'completed_slots': len(s['actions']),
                    'target_slots': s['target'], 'requested_scheduler': s['algorithm'],
                    'state': None if s['done'] else s['sim'].get_state(), 'core_status': 'SEPARATE_MEASUREMENT'}

    def decision(self, run_id):
        with self.lock:
            s = self._get(run_id)
            if s['done']:
                raise SessionError('Session đã hoàn thành')
            if s['pending'] is not None:
                return s['pending']
            state = s['sim'].get_state()
            request_id = f'{run_id}-{state["time_slot"]:06d}'
            started = time.perf_counter()
            failures = []
            candidates = [s['algorithm']]
            if s['algorithm'] == 'dqn' and s['fallback']:
                candidates += ['qos_heuristic', 'static']
            for name in candidates:
                try:
                    if name == 'dqn':
                        if s['init_error']:
                            raise RuntimeError(s['init_error'])
                        action = s['agent'].predict(state, request_id=request_id)
                        from members.TV3.network_slicing_env import make_action
                        if action != make_action(action['action_id'], state, s['sim'].total_rb, request_id):
                            raise ValueError('DQN action_id không khớp ánh xạ TV3')
                    else:
                        action = SCHEDULERS[name]().select_action(state, s['tv2'], request_id=request_id)
                        validate_tv2(action, state, s['sim'].total_rb, require_all_rb=True)
                    validate_tv1(action, s['sim'].total_rb, state['time_slot'])
                    if action['request_id'] != request_id or action['scheduler'] != name:
                        raise ValueError('Sai request_id hoặc nhãn scheduler')
                    break
                except (RuntimeError, ValueError, OSError, ImportError, TimeoutError) as exc:
                    failures.append(f'{name}: {type(exc).__name__}: {exc}')
            else:
                raise SessionError('Tất cả scheduler thất bại: ' + '; '.join(failures))
            s['pending'] = {'run_id': run_id, 'action': action, 'requested_scheduler': s['algorithm'],
                            'selected_scheduler': name, 'fallback_used': name != s['algorithm'],
                            'fallback_reason': '; '.join(failures),
                            'scheduler_latency_ms': round((time.perf_counter() - started) * 1000, 6)}
            return s['pending']

    def step(self, run_id):
        with self.lock:
            decision = self.decision(run_id)
            s = self._get(run_id)
            state = s['sim'].get_state()
            transition = s['sim'].apply_action(decision['action'])
            kpi = transition['ran_kpi']
            if kpi['request_id'] != decision['action']['request_id'] or kpi['algorithm'] != decision['selected_scheduler']:
                raise SessionError('Không khớp khóa nối TV1/TV5')
            record = {'run_id': run_id, 'time_slot': state['time_slot'], 'request_id': kpi['request_id'],
                      'seed': s['seed'], 'scenario_id': s['config']['scenario']['id'],
                      'requested_scheduler': s['algorithm'], 'selected_scheduler': decision['selected_scheduler'],
                      'fallback_used': decision['fallback_used'], 'fallback_reason': decision['fallback_reason'],
                      'action_id': decision['action']['action_id'],
                      'embb_rb': decision['action']['rb_allocation']['embb'],
                      'urllc_rb': decision['action']['rb_allocation']['urllc'],
                      'scheduler_latency_ms': decision['scheduler_latency_ms'],
                      'selected_policy_embb': 'high_bandwidth', 'selected_policy_urllc': 'low_latency',
                      'core_status': 'SEPARATE_MEASUREMENT',
                      **{k: v for k, v in kpi.items() if k not in ('units', 'schema_version', 'seed', 'algorithm', 'scenario_id', 'time_slot', 'request_id')}}
            s['records'].append(record)
            s['actions'].append({'decision': decision, 'ran_kpi': kpi})
            s['pending'] = None
            s['done'] = len(s['actions']) >= s['target'] or bool(transition['done'])
            if s['done']:
                self._save(run_id, s)
            return {'run_id': run_id, 'completed_slots': len(s['actions']), 'done': s['done'],
                    'decision': decision, 'ran_kpi': kpi,
                    'next_state': None if s['done'] else transition['next_state'],
                    'core_status': 'SEPARATE_MEASUREMENT'}

    def run_to_end(self, run_id):
        with self.lock:
            s = self._get(run_id)
            while not s['done']:
                self.step(run_id)
            return self.metrics(run_id)

    def metrics(self, run_id):
        with self.lock:
            if run_id not in self.sessions:
                if len(run_id) != 16 or any(c not in '0123456789abcdef' for c in run_id):
                    raise KeyError('Session TV5 không hợp lệ')
                path = self.output_root / run_id / 'status.json'
                if path.is_file():
                    return json.loads(path.read_text(encoding='utf-8'))
            s = self._get(run_id)
            return {'run_id': run_id, 'status': 'completed' if s['done'] else 'active',
                    'completed_slots': len(s['actions']), 'target_slots': s['target'],
                    'fallback_count': sum(bool(r['fallback_used']) for r in s['records']),
                    'rb_conservation_ok': all(r['embb_rb'] + r['urllc_rb'] == s['sim'].total_rb for r in s['records']),
                    'last_slots': s['records'][-10:], 'core_status': 'SEPARATE_MEASUREMENT',
                    'result_csv': f'/api/tv5/sessions/{run_id}/download' if s['done'] else None,
                    'partial_smoke_test': s['partial']}

    def list_saved(self):
        saved = []
        for path in sorted(self.output_root.glob('*/status.json'), key=lambda p: p.stat().st_mtime, reverse=True)[:100]:
            try:
                row = json.loads(path.read_text(encoding='utf-8'))
                saved.append({k: row[k] for k in ('run_id', 'status', 'completed_slots', 'target_slots', 'fallback_count')})
            except (OSError, ValueError, KeyError):
                continue
        return saved

    def _save(self, run_id, s):
        out = self.output_root / run_id
        out.mkdir(parents=True, exist_ok=True)
        (out / 'config.json').write_text(json.dumps(s['config'], ensure_ascii=False, indent=2), encoding='utf-8')
        with (out / 'unified_tv5.csv').open('w', encoding='utf-8-sig', newline='') as fh:
            writer = csv.DictWriter(fh, fieldnames=list(s['records'][0]))
            writer.writeheader()
            writer.writerows(s['records'])
        with (out / 'orchestrator_log.jsonl').open('w', encoding='utf-8') as fh:
            for row in s['actions']:
                fh.write(json.dumps(row, ensure_ascii=False) + '\n')
        (out / 'status.json').write_text(json.dumps(self.metrics(run_id), ensure_ascii=False, indent=2), encoding='utf-8')
