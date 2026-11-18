"""TV5 E2E Phase 2: real TV1 RAN + TV2 scheduler replay plan.

Does not modify TV1, TV2 or Web. Generates RAN packet/slot plans for TV4.
The exported trace is RAN simulation output, NOT a GNS3 measurement.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from pathlib import Path

import yaml


def dump_csv(path: Path, rows: list[dict], columns: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', newline='', encoding='utf-8-sig') as f:
        w = csv.DictWriter(f, fieldnames=columns, extrasaction='ignore')
        w.writeheader()
        w.writerows(rows)


def generate(args: argparse.Namespace) -> dict:
    root = Path(__file__).resolve().parents[3]
    sys.path.insert(0, str(root))
    sys.path.insert(0, str(root / 'members/TV1/src'))  # TV2 imports ran.rb_capacity
    from members.TV1.src.ran import RANSimulator
    from members.TV1.src.ran.schemas import validate_action as tv1_validate
    from members.TV2.src.schedulers.action_validator import validate_action as tv2_validate
    from members.TV2.src.schedulers.static import StaticScheduler
    from members.TV2.src.schedulers.qos_heuristic import QoSHeuristicScheduler
    from members.TV2.src.schedulers.queue_based import QueueBasedScheduler

    schedulers = {'static': StaticScheduler, 'qos_heuristic': QoSHeuristicScheduler,
                  'queue_based': QueueBasedScheduler}
    config = yaml.safe_load(args.config.read_text(encoding='utf-8'))
    config['simulation'].update(seed=args.seed, slots=args.slots)
    sim = RANSimulator(config)
    sim.reset(seed=args.seed)
    total = int(config['radio']['total_rb'])
    scheduler_config = yaml.safe_load((root / 'members/TV2/configs/schedulers.yaml').read_text(encoding='utf-8'))
    scheduler_config['common']['total_rb'] = total
    scheduler_config['common']['slot_duration_ms'] = sim.slot_duration_ms
    if args.rb_embb < 0 or args.rb_urllc < 0 or args.rb_embb + args.rb_urllc != total:
        raise ValueError(f'RB allocation must sum to {total}')
    scheduler_config['static'].update(rb_embb=args.rb_embb, rb_urllc=args.rb_urllc)
    scheduler = schedulers[args.scheduler]()

    plan_key = {'config': config, 'scheduler': args.scheduler,
                'rb_embb': args.rb_embb if args.scheduler == 'static' else None,
                'rb_urllc': args.rb_urllc if args.scheduler == 'static' else None}
    run_id = 'e2e' + hashlib.sha256(json.dumps(plan_key, sort_keys=True).encode()).hexdigest()[:13]
    arrivals = {}
    embb = []
    actions = []
    for slot in range(args.slots):
        state = sim.get_state()
        before = list(sim.urllc_queue.packets)
        for pkt in before:
            arrivals.setdefault(pkt.packet_id, {'run_id': run_id, 'packet_id': pkt.packet_id,
                'arrival_slot': pkt.arrival_slot, 'send_slot': '', 'size_bits': pkt.size_bits,
                'deadline_ms': pkt.deadline_ms, 'ran_delay_ms': '', 'ran_status': 'unresolved'})
        action = scheduler.select_action(state, scheduler_config, request_id=f'{run_id}-{slot:06d}')
        tv2_validate(action, state, total, require_all_rb=True)
        tv1_validate(action, total, slot)
        t = sim.apply_action(action)
        kpi = t['ran_kpi']
        completed_n = int(kpi['completed_urllc_packets'])
        dropped_n = int(kpi['dropped_urllc_packets'])
        after = {pkt.packet_id for pkt in sim.urllc_queue.packets}
        departed = [pkt for pkt in before if pkt.packet_id not in after]
        if len(departed) != completed_n + dropped_n:
            raise RuntimeError(f'Incomplete URLLC conservation at slot {slot}')
        for pkt in departed[:completed_n]:
            arrivals[pkt.packet_id].update(send_slot=slot,
                ran_delay_ms=(slot-int(pkt.arrival_slot)+1)*sim.slot_duration_ms,
                ran_status='completed')
        for pkt in departed[completed_n:]:
            arrivals[pkt.packet_id]['ran_status'] = 'dropped'
        rb = action['rb_allocation']
        embb.append({'run_id':run_id, 'time_slot':slot, 'served_bits':int(kpi['served_embb_bits']),
                     'embb_rb': rb['embb'], 'urllc_rb': rb['urllc']})
        actions.append({'run_id':run_id, 'time_slot':slot, 'request_id': action['request_id'],
                        'scheduler':args.scheduler, 'action_id':action['action_id'],
                        'embb_rb':rb['embb'], 'urllc_rb':rb['urllc']})
    summary = sim.build_run_summary()
    if len(arrivals) != int(summary['urllc_packet_counters']['arrived']):
        raise RuntimeError('Mismatch TV1 URLLC arrived count')
    if sum(p['ran_status']=='completed' for p in arrivals.values()) != int(summary['urllc_packet_counters']['completed']):
        raise RuntimeError('Mismatch TV1 URLLC completed count')

    out = args.out
    out.mkdir(parents=True, exist_ok=True)
    dump_csv(out/'ran_urllc_packets.csv',list(arrivals.values()),
             ['run_id','packet_id','arrival_slot','send_slot','size_bits','deadline_ms','ran_delay_ms','ran_status'])
    dump_csv(out/'ran_embb_slots.csv', embb,
             ['run_id','time_slot','served_bits','embb_rb','urllc_rb'])
    dump_csv(out/'ran_actions.csv', actions,
             ['run_id','time_slot','request_id','scheduler','action_id','embb_rb','urllc_rb'])
    manifest = {'run_id':run_id,'source':'TV1_RANSimulator+TV2_'+args.scheduler,
                'scheduler':args.scheduler, 'seed':args.seed, 'slots':args.slots,
                'slot_duration_ms':sim.slot_duration_ms,
                'rb_embb': args.rb_embb if args.scheduler=='static' else 'dynamic',
                'rb_urllc':args.rb_urllc if args.scheduler=='static' else 'dynamic',
                'status':'RAN_REPLAY_PLAN_ONLY_NOT_E2E',
                'config_path':str(args.config), 'description':'TV1/TV2 actual run. NOT evidence of GNS3 delivery.'}
    (out/'ran_plan_manifest.json').write_text(json.dumps(manifest,indent=2,ensure_ascii=False),encoding='utf-8')
    (out/'ran_summary.json').write_text(json.dumps(summary,indent=2,ensure_ascii=False),encoding='utf-8')
    result={'run_id':run_id,'scheduler':args.scheduler,'urllc_generated':len(arrivals),
            'urllc_completed':summary['urllc_packet_counters']['completed'],
            'urllc_dropped':summary['urllc_packet_counters']['dropped'],
            'embb_served_bits':sum(row['served_bits'] for row in embb),
            'embb_rb_min':min(a['embb_rb'] for a in actions),
            'embb_rb_max':max(a['embb_rb'] for a in actions),
            'output':str(out)}
    print(json.dumps(result,indent=2,ensure_ascii=False))
    return result


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--config',type=Path,default=Path('members/TV1/configs/stable_load.yaml'))
    p.add_argument('--scheduler',choices=['static','qos_heuristic','queue_based'],default='qos_heuristic')
    p.add_argument('--seed',type=int,default=42)
    p.add_argument('--slots',type=int,default=25)
    p.add_argument('--rb-embb',type=int,default=25)
    p.add_argument('--rb-urllc',type=int,default=25)
    p.add_argument('--out',type=Path,required=True)
    args=p.parse_args()
    if args.slots<1:p.error('--slots must be positive')
    generate(args)

if __name__=='__main__':main()
