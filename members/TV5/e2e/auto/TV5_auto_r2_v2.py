#!/usr/bin/env python3
"""TV5 GNS3 lab-only R2 failover monitor v2 (standard library, no TV4 code changes).

On VM with TV4 controller at 127.0.0.1:8018. Commands:
  python3 TV5_auto_r2.py status
  python3 -u TV5_auto_r2.py monitor
  python3 TV5_auto_r2.py inject
  python3 TV5_auto_r2.py restore

Monitors actual GNS3 container reachability, not historical Core KPI.
Test scope: fault on R2 eth1 -> R4, not arbitrary network failures.

Revision 2026-11-18: bounded retries for end-to-end ping after policy update,
so one transient failed ping is not falsely reported as failover failure.
No automatic changes to R4 return routes, which were not shown necessary
in the controlled R4 return-route diagnostic test.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

CORE = 'http://127.0.0.1:8018'
HOME = Path.home()
TV5_LOG = HOME / 'TV5_auto_r2_events.jsonl'
TV5_SUMMARY = HOME / 'TV5_auto_r2_summary.json'
TV4_LOG = HOME / 'TV4_auto_r2_lab_events.jsonl'
EMBB_SRC = '2001:db8:10::2'
URLLC_SRC = '2001:db8:10::3'
SERVER = '2001:db8:40::2'
R2_SRC = '2001:db8:24::2'
R4_PEER = '2001:db8:24::4'


def stamp():
    return datetime.now(timezone.utc).isoformat(timespec='milliseconds')


def event(file: Path, kind: str, **kv):
    row = {'at_utc': stamp(), 'event': kind, **kv}
    with file.open('a', encoding='utf-8') as out:
        out.write(json.dumps(row, ensure_ascii=False) + '\n')
    print('[' + row['at_utc'] + '] ' + kind +
          (' ' + json.dumps(kv, ensure_ascii=False) if kv else ''), flush=True)
    return row


def cmd(args: list[str], timeout: float = 15) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, text=True,
                          timeout=timeout, check=False)


def container(label: str) -> str:
    p = cmd(['sudo', '-n', 'docker', 'ps', '--filter', f'name=GNS3.{label}.',
             '--format', '{{.ID}}'], timeout=10)
    ids = p.stdout.strip().splitlines()
    if p.returncode or len(ids) != 1 or not re.fullmatch(r'[0-9a-f]{12,64}', ids[0]):
        raise RuntimeError(f'Cannot find exactly one GNS3.{label} Docker node; '
                           f'found={ids}, stderr={p.stderr.strip()}')
    return ids[0]


def core(method: str, route: str, body: dict | None = None) -> dict:
    data = json.dumps(body).encode('utf-8') if body is not None else None
    req = Request(CORE + route, data=data, method=method,
                  headers={'Accept': 'application/json', 'Content-Type': 'application/json'})
    try:
        with urlopen(req, timeout=10) as res:
            return json.load(res)
    except HTTPError as e:
        raise RuntimeError(f'Core HTTP {e.code}: {e.read(400).decode(errors="replace")}') from e
    except (URLError, TimeoutError) as e:
        raise RuntimeError(f'Cannot connect to TV4 Core at {CORE}: {e}') from e


def policy_state() -> dict:
    doc = core('GET', '/v1/policy')
    slices = doc.get('slices') or {}
    return {'embb': (slices.get('embb') or {}).get('active_policy'),
            'urllc': (slices.get('urllc') or {}).get('active_policy'),
            'canonical_valid': doc.get('canonical_valid')}


def ping(node: str, source: str, target: str, count: int = 3) -> dict:
    cid = container(node)
    command = ['sudo', '-n', 'docker', 'exec', cid, 'ping', '-6', '-n',
               '-I', source, '-c', str(count), '-i', '0.2', '-W', '1', target]
    p = cmd(command, timeout=10)
    m = re.search(r'(\d+) packets transmitted,\s*(\d+) received', p.stdout)
    if not m:
        raise RuntimeError(f'Ping failed/invalid output at {node}: exit={p.returncode}, '
                           f'stdout={p.stdout[-280:]}, stderr={p.stderr[-280:]}')
    sent, received = int(m.group(1)), int(m.group(2))
    return {'node': node, 'source': source, 'target': target,
            'sent': sent, 'received': received,
            'reachable': received > 0, 'loss_pct': round((sent - received) / sent * 100, 1)}


def embb_probe():
    return ping('Client', EMBB_SRC, SERVER)


def urllc_probe():
    return ping('Client', URLLC_SRC, SERVER, 2)


def r2_probe():
    # Independent outgoing R2-eth1 -> R4-eth0 link probe, valid for this specific test.
    return ping('R2', R2_SRC, R4_PEER, 2)


def switch_policy(name: str, run_id: str) -> dict:
    rid = 'tv5-auto-' + run_id + '-' + uuid.uuid4().hex[:10]
    answer = core('POST', '/v1/policy/apply',
                  {'request_id': rid, 'slice_id': 'embb',
                   'policy': name, 'confirm': 'APPLY_TV4'})
    if answer.get('applied') is not True or answer.get('verified') is not True:
        raise RuntimeError('TV4 controller did not confirm verified apply: ' + str(answer))
    state = policy_state()
    if state['canonical_valid'] is not True or state['embb'] != name or state['urllc'] != 'low_latency':
        raise RuntimeError('Policy readback mismatch: ' + str(state))
    return {'request_id': rid, 'response': answer, 'policy_readback': state}


def check_baseline():
    state = policy_state()
    if state['canonical_valid'] is not True or state['embb'] != 'high_bandwidth' or state['urllc'] != 'low_latency':
        raise RuntimeError('Baseline must have eMBB=high_bandwidth and URLLC=low_latency: ' + str(state))
    before = qdisc(show=True)
    if not baseline_qdisc(before):
        raise RuntimeError('Refusing monitor: R2 eth1 qdisc not at expected 5ms / 0.1% / 100Mbit baseline: ' + before)
    checks = {'embb': embb_probe(), 'urllc': urllc_probe(), 'r2_link': r2_probe()}
    for key, result in checks.items():
        if not result['reachable']:
            raise RuntimeError(f'Baseline ping failed at {key}: {result}')
    return {'policies': state, 'probes': checks}


def qdisc(show: bool = False, failure: bool = False) -> str:
    cid = container('R2')
    if show:
        command = ['sudo', '-n', 'docker', 'exec', cid, 'tc', 'qdisc', 'show', 'dev', 'eth1']
    else:
        # Deliberately scoped to the already confirmed GNS3.R2 Docker node only.
        loss = '100%' if failure else '0.1%'
        command = ['sudo', '-n', 'docker', 'exec', cid, 'tc', 'qdisc', 'replace',
                   'dev', 'eth1', 'root', 'netem', 'delay', '5ms',
                   'loss', loss, 'rate', '100mbit', 'limit', '1000']
    p = cmd(command)
    if p.returncode:
        raise RuntimeError('qdisc failed: ' + p.stderr.strip())
    if show:
        return p.stdout.strip()
    return qdisc(show=True)


def baseline_qdisc(s: str) -> bool:
    # Refuse to overwrite unexpected user/lab settings on R2 eth1.
    return ('netem' in s and re.search(r'\bdelay\s+5(?:\.0+)?ms\b', s) is not None
            and re.search(r'\bloss\s+0\.1(?:0+)?%', s) is not None
            and re.search(r'\brate\s+100[Mm]bit\b', s) is not None)


def outage_qdisc(s: str) -> bool:
    return 'netem' in s and re.search(r'\bloss\s+100(?:\.0+)?%', s) is not None


def lab_action(mode: str):
    if mode == 'inject':
        state = policy_state()
        if state['embb'] != 'high_bandwidth' or state['urllc'] != 'low_latency':
            raise RuntimeError('Cannot inject: expected initial eMBB over R2 and URLLC over R3')
        if not r2_probe()['reachable']:
            raise RuntimeError('Cannot inject: R2-R4 link already failed')
    before = qdisc(show=True)
    if mode == 'inject' and not baseline_qdisc(before):
        raise RuntimeError('Refusing to inject: unexpected R2 eth1 qdisc: ' + before)
    if mode == 'restore' and not (outage_qdisc(before) or baseline_qdisc(before)):
        raise RuntimeError('Refusing to overwrite unknown R2 eth1 qdisc: ' + before)
    after = qdisc(failure=mode == 'inject')
    event(TV4_LOG, 'R2_OUTAGE_INJECTED' if mode == 'inject' else 'R2_LINK_RESTORED',
          mode=mode, qdisc_before=before, qdisc_after=after)
    print('R2 qdisc now:', after, flush=True)


def status():
    print('Core policies:', json.dumps(policy_state(), ensure_ascii=False))
    print('R2 eth1 qdisc:', qdisc(show=True))
    for label, fn in [('eMBB ping', embb_probe), ('URLLC ping', urllc_probe),
                      ('R2->R4 link ping', r2_probe)]:
        print(label + ':', json.dumps(fn(), ensure_ascii=False), flush=True)


def verify_after_policy(run_id: str, phase: str, attempts: int = 8,
                        gap: float = 1.0) -> dict:
    """Verify *traffic*, not just R1 route config, with bounded retry.

    One failed ping immediately after the API update is not a definitive
    failure: neighbor entries and in-flight packets can be transient.
    The routine makes no claims about 5G SLA or precise switching time.
    """
    if attempts < 1 or gap < 0:
        raise ValueError('Invalid retry settings')
    probes = []
    for index in range(1, attempts + 1):
        eb = embb_probe()
        ur = urllc_probe()
        state = policy_state()
        ok = (eb['reachable'] and ur['reachable'] and
              state['canonical_valid'] is True and
              state['urllc'] == 'low_latency' and
              state['embb'] == ('low_latency' if phase == 'failover' else 'high_bandwidth'))
        attempt = {'attempt': index, 'embb': eb, 'urllc': ur,
                   'policies': state, 'both_slices_reachable': ok}
        probes.append(attempt)
        event(TV5_LOG, 'POST_POLICY_PROBE', run_id=run_id,
              phase=phase, **attempt)
        if ok:
            return {'passed': True, 'attempts': index,
                    'phase': phase, 'embb': eb, 'urllc': ur,
                    'policies': state, 'probes': probes}
        if index < attempts:
            time.sleep(gap)
    return {'passed': False, 'attempts': attempts,
            'phase': phase, 'probes': probes,
            'note': 'Route may be applied, but end-to-end connectivity unverified'}


def monitor(limit: float, misses: int, heals: int, interval: float,
            verify_attempts: int, verify_gap: float):
    run_id = uuid.uuid4().hex[:16]
    phase = 'MONITORING'
    fail_streak = 0
    heal_streak = 0
    start = time.monotonic()
    summary = {'run_id': run_id, 'status': 'STARTED', 'started_utc': stamp(),
               'mode': 'GNS3 VM live probes + TV4 Core policy API',
               'thresholds': {'failure_consecutive': misses,
                              'recovery_consecutive': heals, 'interval_seconds': interval,
                              'post_policy_verification_attempts': verify_attempts,
                              'post_policy_verification_gap_seconds': verify_gap}}
    try:
        initial = check_baseline()
        summary['baseline'] = initial
        event(TV5_LOG, 'BASELINE_OK', run_id=run_id, checks=initial)
        event(TV5_LOG, 'MONITOR_READY_INJECT_R2_NOW', run_id=run_id)
        while time.monotonic() - start < limit:
            if phase == 'MONITORING':
                eb = embb_probe()
                fail_streak = fail_streak + 1 if not eb['reachable'] else 0
                event(TV5_LOG, 'PROBE_PRIMARY', run_id=run_id, probe=eb, fail_streak=fail_streak)
                if fail_streak >= misses:
                    # Require independent path evidence and working alternate path.
                    r2, ur = r2_probe(), urllc_probe()
                    event(TV5_LOG, 'FAILURE_CONFIRMATION', run_id=run_id,
                          r2_link=r2, urllc=ur)
                    if not r2['reachable'] and ur['reachable']:
                        event(TV5_LOG, 'FAULT_DETECTED', run_id=run_id,
                              reason='eMBB failed and R2->R4 failed, while URLLC/R3 works')
                        result = switch_policy('low_latency', run_id)
                        event(TV5_LOG, 'POLICY_APPLY_R3', run_id=run_id, details=result)
                        # Allow bounded stabilization; never assume API route
                        # verification equals actual data-plane reachability.
                        phase = 'R3_APPLIED_VERIFYING_TRAFFIC'
                        verify = verify_after_policy(run_id, 'failover', verify_attempts, verify_gap)
                        event(TV5_LOG, 'AFTER_REROUTE_VERIFICATION', run_id=run_id,
                              passed=verify['passed'], attempts=verify['attempts'],
                              details=verify)
                        if not verify['passed']:
                            raise RuntimeError('R3 route applied, but eMBB/URLLC traffic '
                                               'not verified after bounded retries')
                        phase = 'DIVERTED_WAITING_FOR_R2_RECOVERY'
                        summary['failover_verified'] = True
                        summary['failover_probe_attempts'] = verify['attempts']
                    else:
                        event(TV5_LOG, 'FAILOVER_BLOCKED', run_id=run_id,
                              reason='R2 link not proven failed or alternate URLLC path unhealthy')
                        fail_streak = 0
            else:
                r2 = r2_probe()
                heal_streak = heal_streak + 1 if r2['reachable'] else 0
                event(TV5_LOG, 'PROBE_R2_RECOVERY', run_id=run_id,
                      probe=r2, heal_streak=heal_streak)
                if heal_streak >= heals:
                    event(TV5_LOG, 'R2_LINK_STABLE', run_id=run_id)
                    result = switch_policy('high_bandwidth', run_id)
                    event(TV5_LOG, 'POLICY_RESTORE_R2', run_id=run_id, details=result)
                    phase = 'R2_APPLIED_VERIFYING_TRAFFIC'
                    verified = verify_after_policy(run_id, 'recovery', verify_attempts, verify_gap)
                    event(TV5_LOG, 'FINAL_VERIFICATION', run_id=run_id,
                          passed=verified['passed'], attempts=verified['attempts'],
                          details=verified)
                    if not verified['passed']:
                        raise RuntimeError('Automatic return to R2 policy: traffic verification failed')
                    summary['recovery_probe_attempts'] = verified['attempts']
                    summary.update(status='PASS', restored_automatically=True,
                                   ended_utc=stamp(), final_policy=policy_state())
                    event(TV5_LOG, 'AUTO_R2_TEST_PASS', run_id=run_id, summary=summary)
                    return
            time.sleep(interval)
        summary.update(status='TIMEOUT', phase=phase, ended_utc=stamp(),
                       note='No automatic forced reset; inspect lab and restore R2 qdisc if needed')
        event(TV5_LOG, 'TEST_TIMEOUT', run_id=run_id, summary=summary)
    except Exception as e:
        summary.update(status='ERROR', phase=phase, error=str(e), ended_utc=stamp())
        event(TV5_LOG, 'TEST_ERROR', run_id=run_id, message=str(e))
        raise
    finally:
        TV5_SUMMARY.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        print('TV5 evidence:', TV5_LOG)
        print('TV5 summary:', TV5_SUMMARY)
        print('TV4 lab evidence:', TV4_LOG)


def main():
    parser = argparse.ArgumentParser(description='TV5 GNS3 R2 automatic failover and return test')
    parser.add_argument('action', choices=['monitor', 'status', 'inject', 'restore'])
    parser.add_argument('--max-seconds', type=float, default=600)
    parser.add_argument('--fail-count', type=int, default=2)
    parser.add_argument('--heal-count', type=int, default=3)
    parser.add_argument('--interval', type=float, default=0.8)
    parser.add_argument('--verify-attempts', type=int, default=8)
    parser.add_argument('--verify-gap', type=float, default=1.0)
    args = parser.parse_args()
    if (args.max_seconds < 10 or args.fail_count < 1 or args.heal_count < 1 or
            args.interval < 0.1 or args.verify_attempts < 1 or args.verify_gap < 0):
        parser.error('Thresholds must be positive; interval >=0.1 seconds')
    if args.action == 'status':
        status()
    elif args.action in ('inject', 'restore'):
        lab_action(args.action)
    else:
        monitor(args.max_seconds, args.fail_count, args.heal_count, args.interval,
                args.verify_attempts, args.verify_gap)


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, subprocess.TimeoutExpired, OSError, ValueError) as e:
        print('ERROR:', str(e), file=sys.stderr, flush=True)
        sys.exit(1)
