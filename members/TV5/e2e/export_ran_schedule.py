"""TV5: export TV1's *real* packet completions and eMBB service as a replay plan.

Run from repository root. No edits to TV1 or TV2 sources are required.
Only completed URLLC packets are sent to Core; all arrivals remain in the
reference table so receiver-side delivery ratios use the correct denominator.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
import sys

import yaml


def write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', newline='', encoding='utf-8-sig') as fp:
        writer = csv.DictWriter(fp, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def build_plan(config_path: Path, dest: Path, slots: int, seed: int, rb_embb: int, rb_urllc: int):
    from members.TV1.src.ran import RANSimulator

    with config_path.open(encoding='utf-8') as fp:
        config = yaml.safe_load(fp)
    if not isinstance(config, dict):
        raise ValueError('Invalid YAML config')
    config['simulation']['seed'] = seed
    config['simulation']['slots'] = slots
    total_rb = int(config['radio']['total_rb'])
    if rb_embb < 0 or rb_urllc < 0 or rb_embb + rb_urllc != total_rb:
        raise ValueError(f'RB allocations must sum to total_rb={total_rb}')
    sim = RANSimulator(config)
    sim.reset(seed=seed)
    config_key = hashlib.sha256(json.dumps({'config': config, 'rb_embb': rb_embb, 'rb_urllc': rb_urllc}, sort_keys=True).encode()).hexdigest()[:13]
    run_id = f'e2e{config_key}'
    arrivals: dict[str, dict] = {}
    embb_rows: list[dict] = []
    report = {'run_id': run_id, 'source': 'TV1_RANSimulator', 'scheduler': 'static', 'seed': seed,
              'slots': slots, 'rb_embb': rb_embb, 'rb_urllc': rb_urllc,
              'slot_duration_ms': sim.slot_duration_ms,
              'status': 'RAN_REPLAY_PLAN_ONLY_NOT_E2E', 'config_path': str(config_path),
              'description': 'This plan reflects TV1 real arrivals/serving. It is not proof of delivery in GNS3.'}
    for slot in range(slots):
        state = sim.get_state()
        before = list(sim.urllc_queue.packets)
        # TV1 TrafficGenerator creates the packet_id and arrival_slot. Do not invent them.
        for packet in before:
            if packet.packet_id not in arrivals:
                arrivals[packet.packet_id] = {
                    'run_id': run_id, 'packet_id': packet.packet_id,
                    'arrival_slot': packet.arrival_slot, 'send_slot': '',
                    'size_bits': packet.size_bits, 'deadline_ms': packet.deadline_ms,
                    'ran_delay_ms': '', 'ran_status': 'unresolved'
                }
        action = {
            'schema_version': '1.0.0', 'request_id': f'{run_id}-{slot:06d}',
            'time_slot': slot, 'scheduler': 'static', 'action_id': 0,
            'rb_allocation': {'embb': rb_embb, 'urllc': rb_urllc}
        }
        transition = sim.apply_action(action)
        kpi = transition['ran_kpi']
        completed_n = int(kpi['completed_urllc_packets'])
        dropped_n = int(kpi['dropped_urllc_packets'])
        after = {packet.packet_id for packet in sim.urllc_queue.packets}
        departed = [packet for packet in before if packet.packet_id not in after]
        if len(departed) != completed_n + dropped_n:
            raise RuntimeError('TV1 conservation mismatch in URLLC queue at slot '+str(slot))
        for pkt in departed[:completed_n]:
            entry = arrivals[pkt.packet_id]
            entry['send_slot'] = slot
            entry['ran_delay_ms'] = (slot - int(pkt.arrival_slot) + 1) * sim.slot_duration_ms
            entry['ran_status'] = 'completed'
        for pkt in departed[completed_n:]:
            arrivals[pkt.packet_id]['ran_status'] = 'dropped'
        embb_rows.append({'run_id': run_id, 'time_slot': slot,
                          'served_bits': int(kpi['served_embb_bits']),
                          'embb_rb': rb_embb, 'urllc_rb': rb_urllc})
    summary = sim.build_run_summary()
    if sum(v['ran_status']=='completed' for v in arrivals.values()) != summary['urllc_packet_counters']['completed']:
        raise RuntimeError('TV1 completed counters mismatch')
    if len(arrivals) != summary['urllc_packet_counters']['arrived']:
        raise RuntimeError('TV1 arrival counters mismatch')
    dest.mkdir(parents=True, exist_ok=True)
    write_csv(dest/'ran_urllc_packets.csv', list(arrivals.values()),
              ['run_id','packet_id','arrival_slot','send_slot','size_bits','deadline_ms','ran_delay_ms','ran_status'])
    write_csv(dest/'ran_embb_slots.csv', embb_rows,
              ['run_id','time_slot','served_bits','embb_rb','urllc_rb'])
    (dest/'ran_plan_manifest.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    (dest/'ran_summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'run_id': run_id, 'urllc_generated': len(arrivals),
                      'urllc_completed': summary['urllc_packet_counters']['completed'],
                      'urllc_dropped': summary['urllc_packet_counters']['dropped'],
                      'embb_slots': len(embb_rows), 'output': str(dest)}, indent=2))


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--config',type=Path,default=Path('members/TV1/configs/stable_load.yaml'))
    p.add_argument('--out',type=Path,default=Path('members/TV5/e2e/runs/stable_static_42'))
    p.add_argument('--slots',type=int,default=25)
    p.add_argument('--seed',type=int,default=42)
    p.add_argument('--rb-embb',type=int,default=25)
    p.add_argument('--rb-urllc',type=int,default=25)
    args=p.parse_args()
    if args.slots<=0: p.error('--slots must be >0')
    # When executed by path instead of -m, the repository root is not automatically importable.
    root=Path(__file__).resolve().parents[3]
    sys.path.insert(0,str(root))
    build_plan(args.config,args.out,args.slots,args.seed,args.rb_embb,args.rb_urllc)


if __name__=='__main__':
    main()
