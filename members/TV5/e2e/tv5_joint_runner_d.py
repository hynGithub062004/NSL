#!/usr/bin/env python3
"""TV5 D: audit-ready calibration -> joint choice -> RAN manifest -> TV4 API.

Default mode is PLAN (no Core changes).  Never overwrite an existing audit.
The RAN schedule is generated separately by the existing TV5 exporter.
Requires local repo module: members.TV5.e2e.joint_policy_selector.
Not proof of strict E2E radio SLA or end-to-end optimality.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from members.TV5.e2e.joint_policy_selector import select_joint_policy

MAP = {
    'A': ('static', 'high_bandwidth', 'low_latency'),
    'B': ('qos_heuristic', 'high_bandwidth', 'low_latency'),
    'C': ('static', 'low_latency', 'low_latency'),
    'D': ('qos_heuristic', 'low_latency', 'low_latency'),
}


def load_calibration(path: Path, scenario: str, evaluation_seed: int, g_min: float,
                     r2_healthy: bool, r3_healthy: bool) -> dict:
    raw = path.read_bytes()
    rows = list(csv.DictReader(raw.decode('utf-8-sig').splitlines()))
    required = {'PhuongAn','Seed','URLLC','GoodputMbps'}
    if not rows or not required.issubset(rows[0]):
        raise ValueError('CSV missing required columns: ' + str(sorted(required)))
    grouped: dict[str, dict[int, tuple[int,int,float]]] = {k: {} for k in MAP}
    for row in rows:
        label = row['PhuongAn'].strip().upper()
        if label not in MAP:
            raise ValueError('Unknown candidate ' + label)
        seed = int(row['Seed'])
        if seed < 0 or seed in grouped[label]:
            raise ValueError(f'Invalid or duplicate seed: {label}/{seed}')
        numerator, denominator = map(int, row['URLLC'].split('/'))
        goodput = float(row['GoodputMbps'])
        if not (denominator > 0 and 0 <= numerator <= denominator and
                math.isfinite(goodput) and goodput >= 0):
            raise ValueError(f'Invalid KPI: {label}/{seed}')
        grouped[label][seed] = (numerator, denominator, goodput)
    seed_set = set(grouped['A'])
    if len(seed_set) < 2 or any(set(grouped[x]) != seed_set for x in MAP):
        raise ValueError('Calibration requires the same >=2 independent seeds for A-D')
    if evaluation_seed in seed_set:
        raise ValueError('Evaluation seed occurs in calibration data: leakage')
    if len(rows) != len(seed_set) * len(MAP):
        raise ValueError('Inconsistent number of calibration rows')
    # These samples support stable_load only; reject other scenarios explicitly.
    if scenario != 'stable_load':
        raise ValueError('CSV only calibrated for stable_load; refuse other scenarios')
    sha = hashlib.sha256(raw).hexdigest()
    candidates=[]
    for label, (scheduler, embb_policy, urllc_policy) in MAP.items():
        vals=list(grouped[label].values())
        candidates.append({
            'scheduler':scheduler, 'embb_policy':embb_policy,
            'urllc_policy':urllc_policy,
            'urllc_on_time_rate_est':sum(v[0] for v in vals)/sum(v[1] for v in vals),
            'embb_goodput_mbps_est':sum(v[2] for v in vals)/len(vals),
            'calibration_scenario':scenario,
            'calibration_seeds':sorted(seed_set),
            'evidence_id':f'csv-A-D-{label}-sha256-{sha[:16]}',
        })
    return {
        'scenario':scenario, 'evaluation_seed':evaluation_seed,
        'g_min_mbps':g_min,
        'core_health':{'r2':r2_healthy,'r3':r3_healthy},
        'candidates':candidates,
        '_csv_sha256':sha,
    }


def validate_ran(path: Path, selected: dict, seed: int, expected_slots: int,
                 expected_total_rb: int) -> dict:
    if not path.is_file():
        raise ValueError('RAN manifest not found; first export real TV1/TV2 schedule: ' + str(path))
    manifest=json.loads(path.read_text(encoding='utf-8-sig'))
    for k,v in {'scheduler': selected['scheduler'], 'seed':seed,
                'slots':expected_slots, 'status':'RAN_REPLAY_PLAN_ONLY_NOT_E2E'}.items():
        if manifest.get(k) != v:
            raise ValueError(f'RAN manifest {k}: expected {v!r}, got {manifest.get(k)!r}')
    if selected['scheduler']=='static':
        # Matches original 25/25 Static calibration; no other allocation is calibrated.
        if manifest.get('rb_embb') != expected_total_rb//2 or manifest.get('rb_urllc') != expected_total_rb-expected_total_rb//2:
            raise ValueError('Static RB split differs from 25/25 calibration')
    required=('ran_actions.csv','ran_embb_slots.csv','ran_urllc_packets.csv','ran_summary.json')
    if any(not (path.parent/x).is_file() for x in required):
        raise ValueError('Missing one or more TV1/TV2 RAN export files')
    actions=list(csv.DictReader((path.parent/'ran_actions.csv').open(encoding='utf-8-sig',newline='')))
    if len(actions)!=expected_slots:
        raise ValueError('RAN action count does not match manifest slots')
    for i,act in enumerate(actions):
        if int(act['time_slot'])!=i or act['scheduler']!=selected['scheduler'] or act.get('run_id', manifest['run_id'])!=manifest['run_id'] or (int(act['embb_rb'])+int(act['urllc_rb']))!=expected_total_rb:
            raise ValueError(f'RAN action or RB conservation failed at slot {i}')
    return {'run_id':manifest['run_id'], 'seed':seed, 'scheduler':selected['scheduler'],
            'slots':expected_slots, 'rb_conservation_ok':True,
            'status':manifest['status'], 'manifest_path':str(path)}


def api_json(url:str, data:dict|None=None,timeout:int=12)->dict:
    body=None if data is None else json.dumps(data,ensure_ascii=False).encode('utf-8')
    req=urllib.request.Request(url, data=body,
            headers={'Content-Type':'application/json'} if body is not None else {},
            method='POST' if body is not None else 'GET')
    try:
        with urllib.request.urlopen(req,timeout=timeout) as res:
            obj=json.load(res)
    except (urllib.error.URLError,ValueError) as exc:
        raise RuntimeError(f'TV4 API request failed: {exc}') from exc
    if not isinstance(obj,dict):
        raise ValueError('TV4 API returned non-JSON object')
    return obj


def live_precheck(endpoint:str, selected:dict)->tuple[dict,dict]:
    h=api_json(endpoint+'/v1/lab/health')
    p=api_json(endpoint+'/policies')
    if h.get('status')!='ok' or h.get('measurement_is_live') is not True:
        raise RuntimeError('TV4 lab is not live/healthy; fail closed')
    if p.get('status')!='ok' or p.get('canonical_valid') is not True:
        raise RuntimeError('TV4 policy snapshot is not canonical; fail closed')
    slices=p.get('slices') or {}
    if (slices.get('urllc') or {}).get('active_policy')!=selected['urllc_policy']:
        raise RuntimeError('URLLC live policy differs from selected; fail closed')
    return h,p


def no_overwrite_json(path:Path, obj:dict)->None:
    path.parent.mkdir(parents=True,exist_ok=True)
    data=json.dumps(obj,indent=2,ensure_ascii=False)+'\n'
    with path.open('x',encoding='utf-8') as f:
        f.write(data)


def execute(args)->dict:
    if args.audit_out.exists():
        raise FileExistsError('Audit file already exists; choose a NEW --audit-out file (never overwrite)')
    if args.mode=='apply' and (args.confirm!='APPLY_TV4' or not args.request_id):
        raise ValueError('Applying Core requires --confirm APPLY_TV4 and unique --request-id')
    if args.endpoint != 'http://127.0.0.1:18018':
        raise ValueError('For safety only local TV4 forwarded endpoint is permitted')
    if not 0<=args.g_min<1e6 or not math.isfinite(args.g_min):
        raise ValueError('Invalid g_min')
    if args.slots!=25 or args.total_rb!=50:
        raise ValueError('These measurements calibrated 25 slots and 50 RB only')
    spec=load_calibration(args.csv,args.scenario,args.seed,args.g_min,args.r2_healthy,args.r3_healthy)
    selected_result=select_joint_policy({k:v for k,v in spec.items() if not k.startswith('_')})
    if selected_result['selected'] is None:
        raise RuntimeError('NO_FEASIBLE_CANDIDATE; no Core change allowed')
    chosen=selected_result['selected']
    audit={'timestamp_utc':datetime.now(timezone.utc).isoformat(),
           'mode':args.mode,'status':'PLAN_ONLY_NO_CORE_CHANGE',
           'source_sha256':spec['_csv_sha256'],
           'selector':selected_result, 'health_inputs_are_operator_assertions':True,
           'limitations':['Health flags are operator assertions, not path probes.',
               'RAN schedule is simulated; not radio hardware.',
               'TV4 policy readback is not packet-path PCAP proof.',
               'Hybrid E2E cannot certify 5ms radio E2E SLA.']}
    ran_folder={'qos_heuristic':'qos'}.get(chosen['scheduler'],chosen['scheduler'])
    ran_dir=args.ran_root/ran_folder
    audit['ran']=validate_ran(ran_dir/'ran_plan_manifest.json',chosen,args.seed,args.slots,args.total_rb)
    # Always read live state before any apply to prevent accidental stale assumptions.
    health, before=live_precheck(args.endpoint,chosen)
    audit['tv4_before']=before
    audit['lab_health']={'status':health['status'],'measurement_is_live':health['measurement_is_live']}
    current=before['slices']['embb']['active_policy']
    if current not in ('low_latency','high_bandwidth'):
        raise RuntimeError('Unknown current eMBB policy; fail closed')
    if args.mode=='apply':
        if current == chosen['embb_policy']:
            audit['status']='ALREADY_APPLIED_READBACK_VERIFIED'
            audit['tv4_after']=before
        else:
            result=api_json(args.endpoint+'/apply-policy',{
                'request_id':args.request_id,'slice_id':'embb',
                'policy':chosen['embb_policy'],'confirm':'APPLY_TV4'})
            audit['tv4_apply_response']=result
            after=api_json(args.endpoint+'/policies')
            audit['tv4_after']=after
            if not (result.get('applied') is True and result.get('verified') is True and
                    result.get('other_slice_untouched') is True and
                    after.get('canonical_valid') is True and
                    after['slices']['embb']['active_policy']==chosen['embb_policy'] and
                    after['slices']['urllc']['active_policy']==chosen['urllc_policy']):
                audit['status']='APPLY_UNVERIFIED_REQUIRES_MANUAL_TV4_REVIEW'
                # Always attempt an audit write to preserve partial evidence.
                no_overwrite_json(args.audit_out,audit)
                raise RuntimeError('TV4 apply/readback failed; inspect lab and audit; DO NOT blindly retry')
            audit['status']='APPLIED_AND_TV4_READBACK_VERIFIED'
    no_overwrite_json(args.audit_out,audit)
    return audit


def main():
    ap=argparse.ArgumentParser(description='TV5 joint integration. PLAN mode never changes GNS3.')
    ap.add_argument('--csv',required=True,type=Path)
    ap.add_argument('--ran-root',required=True,type=Path,help='Directory holding static/ and qos_heuristic/ RAN exports')
    ap.add_argument('--seed',type=int,required=True)
    ap.add_argument('--scenario',default='stable_load')
    ap.add_argument('--slots',type=int,default=25)
    ap.add_argument('--total-rb',type=int,default=50)
    ap.add_argument('--g-min',type=float,default=8)
    ap.add_argument('--r2-healthy',action='store_true',help='Operator asserts R2 healthy now; not path-probed')
    ap.add_argument('--r3-healthy',action='store_true',help='Operator asserts R3 healthy now; not path-probed')
    ap.add_argument('--mode',choices=['plan','apply'],default='plan')
    ap.add_argument('--confirm',default='')
    ap.add_argument('--request-id',default='')
    ap.add_argument('--endpoint',default='http://127.0.0.1:18018')
    ap.add_argument('--audit-out',required=True,type=Path)
    args=ap.parse_args()
    try:
        result=execute(args)
        sel=result['selector']['selected']
        print(json.dumps({'status':result['status'],'scheduler':sel['scheduler'],
            'embb_policy':sel['embb_policy'],'urllc_policy':sel['urllc_policy'],
            'ran_run_id':result['ran']['run_id'],'core_changed':result['status']=='APPLIED_AND_TV4_READBACK_VERIFIED',
            'audit_file':str(args.audit_out)},ensure_ascii=False,indent=2))
    except Exception as exc:
        print(f'FAILED_CLOSED: {type(exc).__name__}: {exc}',file=sys.stderr)
        sys.exit(2)

if __name__=='__main__': main()
