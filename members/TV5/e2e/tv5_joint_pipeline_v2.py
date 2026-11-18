#!/usr/bin/env python3
"""TV5 V2: select -> prepare RAN -> TV4 apply -> GNS3 packet replay -> KPI -> restore.

PLAN (default) does not change Core/GNS3; it can generate a new local TV1/TV2
RAN replay plan. RUN requires explicit consent and exclusive use of the lab.

All outputs are new; existing V1 files, calibration and raw runs are untouched.
This is Hybrid RAN-simulation + real GNS3 replay, NOT hardware-radio E2E SLA.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import re
import shlex
import subprocess
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from members.TV5.e2e.joint_policy_selector import select_joint_policy
from members.TV5.e2e.tv5_joint_runner_d import (
    load_calibration, validate_ran, api_json, live_precheck,
)

REPO = Path(__file__).resolve().parents[3]
TV4 = 'http://127.0.0.1:18018'
GNS3 = 'gns3@192.168.211.128'
REMOTE_ROOT = '/home/gns3/NSL_D_calibration_20261119'
CANDIDATE_DIR = {'static': 'static', 'qos_heuristic': 'qos'}
LABEL_RE = re.compile(r'^tv5v2_s[0-9]{1,7}_[a-z0-9_]{3,30}$')
NOTES = [
    'Hybrid: RAN is a simulator; Core datagrams are replayed on real GNS3 containers.',
    'Shared monotonic clock is verified only for the host namespaces, not the simulated radio clock.',
    'The eMBB goodput is an observed replay-window quotient; it can vary with timing.',
    'TV4 policy readback is not independent SRv6 packet-path proof. Supply PCAP or route evidence separately.',
    'R2/R3 health flags are operator statements, not automated health probes.',
    'Static 25/25 and TV2 QoS are applied through the RAN export, not dynamically re-optimized per slot.',
    'The chosen policy is calibrated for stable_load only, not generalized to other load scenarios.',
]


def stamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8') as out:
        json.dump(data, out, indent=2, ensure_ascii=False)
        out.write('\n')


def atomic_progress(path: Path, obj: dict) -> None:
    """The V2-owned audit is updated atomically; pre-existing audits are never overwritten."""
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    tmp.replace(path)


def run_checked(argv: list[str], *, capture: bool = False) -> str:
    result = subprocess.run(argv, check=True, text=True,
                            stdout=subprocess.PIPE if capture else None)
    return result.stdout if capture else ''


def ssh(command: str, *, capture: bool = False) -> str:
    return run_checked(['ssh', GNS3, command], capture=capture)


def remote_q(value: str) -> str:
    return shlex.quote(value)


def get_pids() -> tuple[int, int]:
    # Locate actual running GNS3 containers rather than relying on old PIDs.
    containers = ssh("sudo -n docker ps --format '{{.Names}} {{.ID}}'", capture=True)
    ids = {}
    for raw in containers.splitlines():
        parts = raw.strip().split()
        if len(parts) != 2:
            continue
        for name in ('Client', 'Server'):
            if parts[0].startswith('GNS3.' + name + '.'):
                ids.setdefault(name, []).append(parts[1])
    if any(len(ids.get(n, [])) != 1 for n in ('Client', 'Server')):
        raise RuntimeError('Must have exactly one running GNS3.Client and GNS3.Server')
    cmd = "sudo -n docker inspect -f '{{.Name}}|{{.State.Pid}}|{{.State.Running}}' " + ' '.join(ids[x][0] for x in ('Client','Server'))
    output = ssh(cmd, capture=True)
    result = {}
    for line in output.splitlines():
        parts = line.strip().split('|')
        if len(parts) != 3:
            continue
        for name in ('Client','Server'):
            if parts[0].startswith('/GNS3.' + name + '.'):
                if parts[2].lower() != 'true' or int(parts[1]) <= 1:
                    raise RuntimeError('GNS3 container stopped or PID invalid: ' + name)
                result[name] = int(parts[1])
    if set(result) != {'Client','Server'}:
        raise RuntimeError('Cannot resolve Client and Server namespace PIDs')
    return result['Client'], result['Server']


def make_ran(args: argparse.Namespace, choice: dict) -> Path:
    folder = CANDIDATE_DIR.get(choice['scheduler'])
    if not folder:
        raise ValueError('V2 supports only static/qos_heuristic, no other scheduler')
    ran_dir = args.ran_root / folder
    if not ran_dir.exists():
        cmd = [sys.executable, str(REPO / 'members/TV5/e2e/export_ran_schedule_tv2.py'),
               '--config', str(REPO / 'members/TV1/configs/stable_load.yaml'),
               '--scheduler', choice['scheduler'], '--seed', str(args.seed),
               '--slots', '25', '--rb-embb', '25', '--rb-urllc', '25',
               '--out', str(ran_dir)]
        run_checked(cmd)
    # validate even preexisting directory; no overwrites.
    validate_ran(ran_dir / 'ran_plan_manifest.json', choice, args.seed, 25, 50)
    return ran_dir


def guarded_state(choice: dict, baseline_only: bool = True) -> dict:
    health, before = live_precheck(TV4, choice)
    embb = before['slices']['embb']['active_policy']
    if baseline_only and embb != 'high_bandwidth':
        raise RuntimeError('Core not at baseline eMBB=high_bandwidth; refuse run')
    if before['slices']['urllc']['active_policy'] != 'low_latency':
        raise RuntimeError('URLLC policy changed; fail closed')
    return {'health':health, 'policy':before}


def change_embb(policy: str, request_id: str) -> tuple[dict,dict]:
    if policy not in ('high_bandwidth', 'low_latency'):
        raise ValueError('Invalid eMBB policy')
    response = api_json(TV4 + '/apply-policy', {'request_id':request_id,
                          'slice_id':'embb', 'policy':policy, 'confirm':'APPLY_TV4'})
    after = api_json(TV4 + '/policies')
    ok = (response.get('applied') is True and response.get('verified') is True and
          response.get('other_slice_untouched') is True and
          after.get('canonical_valid') is True and
          after.get('slices', {}).get('embb', {}).get('active_policy') == policy and
          after.get('slices', {}).get('urllc', {}).get('active_policy') == 'low_latency')
    if not ok:
        raise RuntimeError('TV4 apply/readback mismatch; manual review required')
    return response, after


def remote_preflight(remote_ran: str, remote_measure: str) -> None:
    # If remotely staged data exists, do NOT silently reuse old data.
    cmd = ('cd ' + remote_q(REMOTE_ROOT) + ' && test -f sender.py && '
           'test -f receiver.py && test -f evaluate_e2e.py && '
           'test ! -e ' + remote_q(remote_ran) + ' && '
           'test ! -e ' + remote_q(remote_measure))
    ssh(cmd)


def upload_ran(ran_dir: Path, remote_parent: str) -> None:
    ssh('cd ' + remote_q(REMOTE_ROOT) + ' && mkdir -p ' + remote_q(remote_parent))
    remote_dest = GNS3 + ':' + REMOTE_ROOT + '/' + remote_parent + '/'
    run_checked(['scp', '-r', str(ran_dir), remote_dest])


def remote_measurement(remote_ran: str, remote_measure: str, client_pid: int, server_pid: int) -> None:
    # All interpolated strings are validated and/or shlex-quoted.
    recv = remote_measure + '/recv.jsonl'
    sent = remote_measure + '/sent.jsonl'
    log = remote_measure + '/receiver.log'
    plan = remote_ran + '/ran_plan_manifest.json'
    urllc = remote_ran + '/ran_urllc_packets.csv'
    embb = remote_ran + '/ran_embb_slots.csv'
    core = ('cd ' + remote_q(REMOTE_ROOT) + ' || exit 1; set -eu; '
            'mkdir ' + remote_q(remote_measure) + '; '
            'sudo -n nsenter --target ' + str(server_pid) + ' --net -- python3 receiver.py '
            '--out ' + remote_q(recv) + ' --duration 8 > ' + remote_q(log) + ' 2>&1 & '
            'rpid=$!; sleep 1; '
            'sudo -n nsenter --target ' + str(client_pid) + ' --net -- python3 sender.py '
            '--urllc ' + remote_q(urllc) + ' --embb ' + remote_q(embb) +
            ' --manifest ' + remote_q(plan) + ' --out ' + remote_q(sent) + '; '
            'wait "$rpid"; test -s ' + remote_q(recv) + '; test -s ' + remote_q(sent))
    ssh(core)


def remote_evaluate(remote_ran: str, remote_measure: str) -> None:
    cmd = ('cd ' + remote_q(REMOTE_ROOT) + ' && python3 evaluate_e2e.py '
           '--urllc ' + remote_q(remote_ran+'/ran_urllc_packets.csv') +
           ' --embb ' + remote_q(remote_ran+'/ran_embb_slots.csv') +
           ' --manifest ' + remote_q(remote_ran+'/ran_plan_manifest.json') +
           ' --sender ' + remote_q(remote_measure+'/sent.jsonl') +
           ' --receiver ' + remote_q(remote_measure+'/recv.jsonl') +
           ' --out ' + remote_q(remote_measure+'/e2e_metrics.json') + ' --shared-clock')
    ssh(cmd)


def download_logs(remote_measure: str, run_folder: Path) -> Path:
    run_checked(['scp','-r', GNS3+':'+REMOTE_ROOT+'/'+remote_measure, str(run_folder)])
    path = run_folder / Path(remote_measure).name
    for x in ('sent.jsonl','recv.jsonl','e2e_metrics.json','receiver.log'):
        if not (path / x).is_file():
            raise RuntimeError('Missing downloaded evidence: ' + x)
    return path


def analyze(path: Path, expected_run_id: str) -> dict:
    metric = json.loads((path / 'e2e_metrics.json').read_text(encoding='utf-8-sig'))
    sent = [json.loads(line) for line in (path / 'sent.jsonl').read_text(encoding='utf-8').splitlines() if line.strip()]
    recv = [json.loads(line) for line in (path / 'recv.jsonl').read_text(encoding='utf-8').splitlines() if line.strip()]
    if metric.get('run_id') != expected_run_id or not sent or not recv:
        raise RuntimeError('Run ID mismatch or empty packet evidence')
    sent_keys = [(r['run_id'],r['packet_id']) for r in sent]
    recv_keys = [(r['run_id'],r['packet_id']) for r in recv]
    if any(key[0] != expected_run_id for key in sent_keys+recv_keys):
        raise RuntimeError('Packet run_id differs from RAN manifest')
    if len(set(sent_keys)) != len(sent_keys) or len(set(recv_keys)) != len(recv_keys):
        raise RuntimeError('Duplicate packet keys in send/receive log')
    if set(sent_keys) != set(recv_keys):
        raise RuntimeError('Packet ID sets disagree; record the logs and diagnose before using KPI')
    lags = sorted(float(r['playback_lag_ms']) for r in sent)
    if any(not math.isfinite(n) for n in lags):
        raise RuntimeError('Invalid playback lag')
    expected_count = metric.get('sent_datagrams')
    if expected_count != len(sent) or metric.get('received_unique_datagrams') != len(recv):
        raise RuntimeError('Metric packet counts do not match raw logs')
    return {'run_id':expected_run_id, 'status':'HYBRID_GNS3_REPLAY_VERIFIED_NOT_STRICT_E2E',
            'sent_unique':len(sent), 'received_unique':len(recv),
            'urllc_generated':metric['urllc']['generated_at_ran'],
            'urllc_on_time':metric['urllc']['hybrid_e2e_on_time'],
            'urllc_on_time_ratio':metric['urllc']['hybrid_e2e_on_time_ratio'],
            'urllc_hybrid_mean_ms':metric['urllc']['hybrid_e2e_delay_ms_mean'],
            'embb_replay_goodput_mbps':metric['embb']['core_replay_goodput_mbps'],
            'playback_lag_mean_ms':sum(lags)/len(lags),
            'playback_lag_p95_ms':lags[math.ceil(0.95*len(lags))-1],
            'playback_lag_max_ms':max(lags),
            'playback_lag_over_1ms_count':sum(n>1 for n in lags)}


def select_and_plan(args: argparse.Namespace) -> tuple[dict, Path, dict]:
    spec = load_calibration(args.csv, 'stable_load', args.seed, args.g_min,
                            args.r2_healthy, args.r3_healthy)
    result = select_joint_policy({k:v for k,v in spec.items() if not k.startswith('_')})
    choice = result.get('selected')
    if not choice:
        raise RuntimeError('NO_FEASIBLE_CANDIDATE')
    ran_dir = make_ran(args, choice)
    manifest = json.loads((ran_dir/'ran_plan_manifest.json').read_text(encoding='utf-8-sig'))
    plan = {'status':'PLAN_ONLY_NO_CORE_CHANGE', 'created_utc':stamp(),
            'seed':args.seed, 'scenario':'stable_load', 'calibration_sha256':spec['_csv_sha256'],
            'selected':choice, 'selector_audit':result, 'ran_dir':str(ran_dir),
            'ran_run_id':manifest['run_id'], 'ran_export_status':manifest['status'],
            'health_flags_are_operator_assertions':True, 'limitations':NOTES}
    live = guarded_state(choice, baseline_only=True)
    plan['tv4_before'] = live['policy']
    return plan, ran_dir, live


def execute(args: argparse.Namespace) -> dict:
    if args.seed < 0 or args.slots != 25 or args.total_rb != 50:
        raise ValueError('V2 calibrated only for 25 slots / 50 RB and nonnegative seeds')
    if not math.isfinite(args.g_min) or args.g_min < 0 or args.g_min > 1e6:
        raise ValueError('Invalid goodput threshold')
    if args.mode == 'run':
        if not args.confirm == 'RUN_TV5_V2' or not args.exclusive_lab:
            raise ValueError('Run requires --confirm RUN_TV5_V2 and --exclusive-lab')
        if args.tag is None or not LABEL_RE.fullmatch(args.tag):
            raise ValueError('Provide unique --tag tv5v2_s<seed>_<label> for run')
        if not args.tag.startswith('tv5v2_s' + str(args.seed) + '_'):
            raise ValueError('Run tag must include evaluation seed')
    if args.plan_out.exists():
        raise FileExistsError('Plan/audit path exists: choose new --plan-out')
    if args.mode == 'run' and args.audit_dir.exists():
        raise FileExistsError('Audit directory exists: choose unique --audit-dir')
    plan,ran_dir,live = select_and_plan(args)
    new_json(args.plan_out, plan)
    if args.mode == 'plan':
        return {'status':plan['status'], 'seed':args.seed, 'scheduler':plan['selected']['scheduler'],
                'embb_policy':plan['selected']['embb_policy'], 'ran_run_id':plan['ran_run_id'],
                'plan_file':str(args.plan_out), 'core_changed':False}

    selected = plan['selected']
    folder = CANDIDATE_DIR[selected['scheduler']]
    remote_parent = 'evaluation/seed'+str(args.seed)+'/v2_'+args.tag
    remote_ran = remote_parent + '/' + folder
    remote_measure = 'measurements/' + args.tag

    # Preflight remote directory collision, topology PID and CLI files BEFORE any apply.
    remote_preflight(remote_ran, remote_measure)
    client_pid, server_pid = get_pids()
    args.audit_dir.mkdir(parents=True, exist_ok=False)
    audit_path = args.audit_dir / 'audit.json'
    audit = dict(plan)
    audit.update(status='READY_TO_APPLY', tag=args.tag, remote_ran=remote_ran,
                 remote_measure=remote_measure,
                 gns3_namespace_pids={'client':client_pid,'server':server_pid},
                 restoration={'attempted':False,'verified':False})
    atomic_progress(audit_path, audit)
    change_started = False
    error = None
    try:
        # Re-check no external user changed the baseline during SSH preflight.
        guarded_state(selected, baseline_only=True)
        change_started = True
        audit['status'] = 'APPLY_IN_PROGRESS'
        atomic_progress(audit_path, audit)
        r, p = change_embb(selected['embb_policy'], args.tag+'-apply')
        audit['tv4_apply_response'], audit['tv4_after'] = r, p
        audit['status'] = 'APPLIED_AND_TV4_READBACK_VERIFIED'
        atomic_progress(audit_path, audit)
        upload_ran(ran_dir, remote_parent)
        audit['status'] = 'RAN_UPLOADED'
        atomic_progress(audit_path, audit)
        remote_measurement(remote_ran, remote_measure, client_pid, server_pid)
        audit['status'] = 'PACKETS_REPLAYED'
        atomic_progress(audit_path, audit)
        remote_evaluate(remote_ran, remote_measure)
        audit['status'] = 'HYBRID_KPI_CALCULATED'
        atomic_progress(audit_path, audit)
        local_logs = download_logs(remote_measure, args.audit_dir)
        audit['summary'] = analyze(local_logs, plan['ran_run_id'])
        audit['status'] = 'HYBRID_GNS3_REPLAY_VERIFIED_NOT_STRICT_E2E'
        audit['local_measurement_dir'] = str(local_logs)
        atomic_progress(audit_path, audit)
    except BaseException as exc:
        error = exc
        audit['status'] = 'RUN_ERROR_RESTORE_PENDING'
        audit['error'] = f'{type(exc).__name__}: {exc}'
        atomic_progress(audit_path, audit)
    finally:
        if change_started:
            audit['restoration']['attempted'] = True
            audit['restoration']['started_utc'] = stamp()
            atomic_progress(audit_path, audit)
            try:
                r, p = change_embb('high_bandwidth', args.tag+'-restore')
                audit['restoration'].update(verified=True, response=r, tv4_after=p,
                                            completed_utc=stamp())
                audit['status'] = 'COMPLETED_RESTORED' if error is None else 'RUN_ERROR_CORE_RESTORED'
            except BaseException as restore_exc:
                audit['restoration']['error'] = f'{type(restore_exc).__name__}: {restore_exc}'
                audit['status'] = 'RESTORE_UNVERIFIED_MANUAL_TV4_REVIEW_REQUIRED'
                (args.audit_dir/'RESTORE_UNVERIFIED.txt').write_text(
                    'Core restore not verified. Ask TV4 to check /policies; expected '
                    'eMBB=high_bandwidth and URLLC=low_latency. Do not blindly retry.\n',encoding='utf-8')
                error = error or restore_exc
            atomic_progress(audit_path, audit)
    if error is not None:
        raise RuntimeError('V2 run encountered error. Review audit and restoration: '+ str(audit_path)) from error
    return {'status':audit['status'], 'seed':args.seed, 'scheduler':selected['scheduler'],
            'embb_policy':selected['embb_policy'], 'restore_verified':audit['restoration']['verified'],
            'summary':audit.get('summary'), 'audit':str(audit_path)}


def main() -> None:
    ap = argparse.ArgumentParser(description='TV5 V2 joint hybrid E2E pipeline; PLAN safe by default')
    ap.add_argument('--csv', required=True, type=Path)
    ap.add_argument('--ran-root', required=True, type=Path, help='seedNN folder containing static/ or qos/')
    ap.add_argument('--seed', required=True, type=int)
    ap.add_argument('--g-min', type=float, default=8.0)
    ap.add_argument('--slots',type=int,default=25)
    ap.add_argument('--total-rb',type=int,default=50)
    ap.add_argument('--r2-healthy',action='store_true')
    ap.add_argument('--r3-healthy',action='store_true')
    ap.add_argument('--mode',choices=('plan','run'),default='plan')
    ap.add_argument('--confirm',default='')
    ap.add_argument('--exclusive-lab',action='store_true')
    ap.add_argument('--tag',default=None)
    ap.add_argument('--plan-out',required=True,type=Path)
    ap.add_argument('--audit-dir',type=Path,default=None)
    args=ap.parse_args()
    if args.audit_dir is None:
        args.audit_dir = args.ran_root / ('v2_audit_'+(args.tag or 'no_tag'))
    try:
        result = execute(args)
        print(json.dumps(result, indent=2, ensure_ascii=False))
    except Exception as e:
        print(f'FAILED_CLOSED: {type(e).__name__}: {e}',file=sys.stderr)
        sys.exit(2)

if __name__ == '__main__':
    main()
