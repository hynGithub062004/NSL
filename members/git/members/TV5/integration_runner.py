"""TV5 stage-1 REAL RAN + REAL TV2/DQN integration, NO REAL SRv6 CORE.

Run from the NSL repository root; copy this file to members/TV5/.

Source of truth:
 - TV1 owns the RAN state/action/KPI and JSON schemas, version 1.0.0.
 - TV2 owns baseline algorithms and its action_id codes.
 - TV3 owns DQN-specific 5-action mapping and checkpoint.
 - TV4 is not yet implemented in supplied 2026-10-25 repository snapshot.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from members.TV1.src.ran import RANSimulator
import yaml
from members.TV1.src.ran.schemas import validate_action as tv1_validate_action
from members.TV2.src.schedulers.static import StaticScheduler
from members.TV2.src.schedulers.queue_based import QueueBasedScheduler
from members.TV2.src.schedulers.action_validator import validate_action as tv2_validate_action

try:
    from jsonschema import Draft202012Validator
except ImportError as exc:
    raise SystemExit('Install dependency: python -m pip install jsonschema') from exc

CONTRACTS = ROOT / 'members' / 'TV1' / 'contracts'
SCENARIOS = ('stable_load', 'urllc_burst', 'poor_channel')
POLICIES = {'embb': 'high_bandwidth', 'urllc': 'low_latency'}


def verify(schema_filename: str, value: dict[str, Any]) -> None:
    schema = json.loads((CONTRACTS / schema_filename).read_text(encoding='utf-8'))
    Draft202012Validator(schema).validate(value)


def make_request_id(seed: int, scenario: str, algorithm: str, slot: int) -> str:
    value = f'{seed}-{scenario}-{algorithm}-{slot:06d}'
    value = re.sub(r'[^A-Za-z0-9._-]', '-', value)[:64]
    if not value or not value[0].isalnum():
        raise ValueError('Invalid request_id')
    return value


def run(algorithm: str, scenario: str, seed: int, slots: int | None,
        output_root: Path, allow_fallback: bool = False) -> Path:
    if scenario not in SCENARIOS:
        raise ValueError(f'Only TV1 scenarios are allowed: {SCENARIOS}')
    if algorithm not in ('static','queue_based','dqn'):
        raise ValueError('Available real algorithms: static, queue_based, dqn')
    simulator = RANSimulator.from_yaml(ROOT / 'members/TV1/configs' / (scenario + '.yaml'))
    simulator.reset(seed=seed)
    total_slots = simulator.total_slots if slots is None else slots
    if total_slots < 1 or total_slots > simulator.total_slots:
        raise ValueError(f'slots must be in 1..{simulator.total_slots}')
    tv2_cfg = yaml.safe_load((ROOT / 'members/TV2/configs/schedulers.yaml').read_text(encoding='utf-8'))
    schedulers = {'static':StaticScheduler(), 'queue_based':QueueBasedScheduler()}
    agent = None
    init_error = None
    if algorithm == 'dqn':
        try:
            from members.TV3.dqn_scheduler import DQNScheduler
            agent = DQNScheduler(model_path=ROOT / 'members/TV3/models/dqn_v2_best.zip', total_rb=simulator.total_rb)
        except Exception as exc:
            init_error = exc
            if not allow_fallback:
                raise RuntimeError('Cannot load REAL DQN; install TV3 dependencies / check checkpoint') from exc

    out = Path(output_root) / scenario / algorithm / f'seed_{seed}'
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    handoffs = []
    for _ in range(total_slots):
        state = simulator.get_state()
        verify('state.schema.json', state)
        request_id = make_request_id(seed, scenario, algorithm, state['time_slot'])
        fallback_used = False
        fallback_reason = ''
        try:
            if init_error is not None:
                raise RuntimeError(f'DQN initialization failed: {init_error}')
            if algorithm == 'dqn':
                action = agent.predict(state, request_id=request_id)
                # Only DQN ids have a five-element table. Never apply it to TV2 actions.
                from members.TV3.network_slicing_env import make_action
                reference = make_action(action['action_id'], state, simulator.total_rb, request_id)
                if action != reference:
                    raise ValueError('DQN action_id/allocation mismatch with TV3 source')
            else:
                action = schedulers[algorithm].select_action(state, tv2_cfg, request_id=request_id)
                tv2_validate_action(action, state, simulator.total_rb, require_all_rb=True)
        except (ValueError, OSError, RuntimeError, ImportError, TimeoutError) as exc:
            if algorithm != 'dqn' or not allow_fallback:
                raise
            # Temporary real fallback to TV2 Static (QoS heuristic does not yet exist).
            fallback_used, fallback_reason = True, f'{type(exc).__name__}: {exc}'
            action = schedulers['static'].select_action(state, tv2_cfg, request_id=request_id)
            tv2_validate_action(action, state, simulator.total_rb, require_all_rb=True)

        verify('action.schema.json', action)
        tv1_validate_action(action, simulator.total_rb, state['time_slot'])
        if action['request_id'] != request_id or action['time_slot'] != state['time_slot']:
            raise ValueError('Action join keys mismatch')
        transition = simulator.apply_action(action)
        kpi = transition['ran_kpi']
        verify('ran_kpi.schema.json', kpi)
        for key, wanted in (('request_id', request_id), ('seed', seed),
                            ('scenario_id', scenario), ('time_slot', state['time_slot']),
                            ('algorithm', action['scheduler'])):
            if kpi[key] != wanted:
                raise ValueError(f'TV1 KPI join mismatch: {key}')

        for slice_id, policy in POLICIES.items():
            handoff = {
                'schema_version':'1.0.0', 'request_id':request_id,
                'seed':seed, 'scenario_id':scenario,
                'algorithm':action['scheduler'], 'time_slot':state['time_slot'],
                'selected_policy':policy
            }
            verify('core_handoff.schema.json', handoff)
            # The existing TV1 handoff schema omits slice_id.
            # Do NOT submit this alone as proof TV4 performed traffic steering.
            handoffs.append({'slice_id': slice_id, 'payload': handoff})
            rows.append({
                'mode':'real_ran_core_not_connected',
                'schema_version':'1.0.0',
                'seed':seed,'scenario_id':scenario,
                'algorithm':algorithm, 'effective_scheduler':action['scheduler'],
                'time_slot':state['time_slot'], 'request_id':request_id,
                'slice_id':slice_id, 'selected_policy':policy,
                'fallback_used':fallback_used, 'fallback_reason':fallback_reason,
                'action_id':action['action_id'],
                'embb_rb':action['rb_allocation']['embb'],
                'urllc_rb':action['rb_allocation']['urllc'],
                'embb_queue_bits':state['embb']['queue_bits'],
                'urllc_queue_bits':state['urllc']['queue_bits'],
                'urllc_queue_packets':state['urllc']['queue_packets'],
                **{key: val for key,val in kpi.items() if key not in ('schema_version','request_id','seed','scenario_id','algorithm','time_slot','units')},
                'core_status':'NOT_CONNECTED',
                'rtt_ms':'', 'core_throughput_mbps':'', 'packet_loss':'', 'switching_time_ms':''
            })

    simulator.export_results(out / 'ran')
    csv_out = out / 'unified_without_core.csv'
    with csv_out.open('w', newline='', encoding='utf-8-sig') as fp:
        writer = csv.DictWriter(fp,fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    with (out / 'handoff_with_slice_id.jsonl').open('w',encoding='utf-8') as fp:
        for entry in handoffs:
            fp.write(json.dumps(entry,ensure_ascii=False)+'\n')
    summary = simulator.build_run_summary()
    status = {
        'note':'REAL TV1 RAN + REAL TV2/TV3 action, NO REAL TV4 measurements',
        'algorithm_requested':algorithm,
        'fallback_count':sum(1 for r in rows if r['slice_id']=='embb' and r['fallback_used']),
        'core_connected':False,
        'simulator_summary':summary,
    }
    (out / 'tv5_status.json').write_text(json.dumps(status,indent=2,ensure_ascii=False),encoding='utf-8')
    return csv_out


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scheduler',choices=['static','queue_based','dqn'],required=True)
    parser.add_argument('--scenario',choices=SCENARIOS,default='stable_load')
    parser.add_argument('--seed',type=int,default=42)
    parser.add_argument('--slots',type=int,default=None)
    parser.add_argument('--output-root',type=Path,default=ROOT / 'members/TV5/results/integration_stage1')
    parser.add_argument('--allow-fallback',action='store_true',help='Demo only; DQN failure uses real TV2 Static, never label as true DQN result')
    args=parser.parse_args()
    path = run(args.scheduler,args.scenario,args.seed,args.slots,args.output_root,args.allow_fallback)
    print('SUCCESS: real TV1 + scheduler pipeline; SRv6 Core NOT CONNECTED')
    print('Result CSV:',path)


if __name__ == '__main__':
    main()
