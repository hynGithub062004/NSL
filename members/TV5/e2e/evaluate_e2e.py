"""TV5: join TV1 real arrival schedule to TV4 GNS3 Server receive logs.

Computes delivery/unique useful bits. Hybrid E2E delay is reported separately,
only if caller asserts all monotonic clocks share one kernel and playback was 1:1.
"""
from __future__ import annotations
import argparse
import csv
import json
from pathlib import Path


def read_csv(path):
    with path.open(encoding='utf-8-sig',newline='') as fp:return list(csv.DictReader(fp))

def jsonl(path):
    with path.open(encoding='utf-8') as fp:
        return [json.loads(x) for x in fp if x.strip()]

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--urllc',required=True,type=Path)
    p.add_argument('--embb',required=True,type=Path)
    p.add_argument('--manifest',required=True,type=Path)
    p.add_argument('--sender',required=True,type=Path)
    p.add_argument('--receiver',required=True,type=Path)
    p.add_argument('--out',required=True,type=Path)
    p.add_argument('--shared-clock',action='store_true',help='same GNS3 VM monotonic clock, 1:1 playback')
    args=p.parse_args()
    manifest=json.loads(args.manifest.read_text(encoding='utf-8'))
    run_id=manifest['run_id']
    generated=[x for x in read_csv(args.urllc) if x['run_id']==run_id]
    embb=[x for x in read_csv(args.embb) if x['run_id']==run_id]
    sent={x['packet_id']:x for x in jsonl(args.sender) if x.get('run_id')==run_id}
    recv={}
    for x in jsonl(args.receiver):
        if x.get('run_id')==run_id and x['packet_id'] in sent and x['packet_id'] not in recv:
            recv[x['packet_id']]=x
    total_generated=len(generated)
    completed=[x for x in generated if x['ran_status']=='completed']
    delivered=[x for x in completed if x['packet_id'] in recv]
    urllc_result={'generated_at_ran':total_generated,'completed_at_ran':len(completed),
                  'delivered_to_server':len(delivered),
                  'server_delivery_rate_over_ran_generated':len(delivered)/total_generated if total_generated else None}
    if args.shared_clock:
        delays=[];ontime=0
        for packet in delivered:
            msg=recv[packet['packet_id']]
            elapsed=(int(msg['recv_mono_ns'])-int(sent[packet['packet_id']]['sent_mono_ns']))/1e6
            delay=float(packet['ran_delay_ms'])+elapsed
            if elapsed<0:raise RuntimeError('Impossible negative one-way transport time; clocks differ')
            delays.append(delay)
            if delay<=float(packet['deadline_ms']):ontime+=1
        urllc_result.update({'hybrid_e2e_on_time':ontime,
                             'hybrid_e2e_on_time_ratio':ontime/total_generated if total_generated else None,
                             'hybrid_e2e_delay_ms_mean':sum(delays)/len(delays) if delays else None,
                             'timing_warning':'RAN delay simulated + Core monotonic real delay. Validation of 1 ms replay jitter required.'})
    else:
        urllc_result['on_time_e2e']='NOT_MEASURED_CLOCK_NOT_VERIFIED'
    expected_embb_bits=sum(int(x['served_bits']) for x in embb)
    unique_embb_bits=sum(int(x['useful_bits']) for x in recv.values() if x['slice']=='embb')
    start_ns=min((int(x['sent_mono_ns']) for x in sent.values()),default=None)
    finish_ns=max((int(x['recv_mono_ns']) for x in recv.values()),default=None)
    duration_s=((finish_ns-start_ns)/1e9) if start_ns and finish_ns and finish_ns>start_ns else None
    output={'run_id':run_id,'source':'TV1 simulator -> TV4 GNS3 Client/Server logs',
            'status':'CORE_PACKET_REPLAY_VERIFIED_IF_RECEIVER_LOG_FROM_REAL_GNS3',
            'urllc':urllc_result,
            'embb':{'ran_served_bits':expected_embb_bits,'received_unique_bits':unique_embb_bits,
                    'received_fraction_vs_ran_served':unique_embb_bits/expected_embb_bits if expected_embb_bits else None,
                    'core_replay_goodput_mbps':unique_embb_bits/duration_s/1e6 if duration_s else None,
                    'observation_seconds':duration_s},
            'sent_datagrams':len(sent),'received_unique_datagrams':len(recv),
            'limitations':['Do not equate simulated RAN clock with radio hardware time.',
                           'Do not claim 5 ms E2E deadline without validating clock and replay jitter.',
                           'Received logs do not prove SRv6 route unless policy readback/PCAP accompany the run.']}
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(json.dumps(output,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(output,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
