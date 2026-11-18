"""TV4: replay TV1/TV5 schedule over IPv6 UDP from Client in GNS3.

No simulated success is written: every row is logged only after UDP sendto returns.
Real delivery must be corroborated by TV4 receiver log and (ideally) PCAP.
"""
from __future__ import annotations
import argparse
import csv
import json
import math
from pathlib import Path
import socket
import time


def rows(path):
    with path.open(encoding='utf-8-sig',newline='') as fp:
        return list(csv.DictReader(fp))


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--urllc',type=Path,required=True)
    p.add_argument('--embb',type=Path,required=True)
    p.add_argument('--manifest',type=Path,required=True)
    p.add_argument('--out',type=Path,required=True)
    p.add_argument('--dest',default='2001:db8:40::2')
    p.add_argument('--source-urllc',default='2001:db8:10::3')
    p.add_argument('--source-embb',default='2001:db8:10::2')
    p.add_argument('--urllc-port',type=int,default=5501)
    p.add_argument('--embb-port',type=int,default=5502)
    p.add_argument('--chunk-bytes',type=int,default=600)
    p.add_argument('--scale',type=float,default=1.0,help='Realtime playback slot multiplier; scale != 1 is not 1:1 RAN timing')
    args=p.parse_args()
    if not (1<=args.chunk_bytes<=700):p.error('chunk must be 1..700 bytes to avoid 1500 MTU with SRv6')
    if args.scale<=0:p.error('scale must be positive')
    meta=json.loads(args.manifest.read_text(encoding='utf-8'))
    run_id=meta['run_id']; slot_ms=float(meta['slot_duration_ms'])
    events=[]
    for r in rows(args.urllc):
        if r['ran_status']!='completed': continue
        if r['run_id']!=run_id:raise ValueError('run_id mismatch in URLLC file')
        nbits=int(r['size_bits'])
        if nbits>args.chunk_bytes*8:raise ValueError('URLLC packet exceeds one safe datagram; choose smaller RAN packet')
        events.append({'run_id':run_id,'slice':'urllc','packet_id':r['packet_id'],
                       'arrival_slot':int(r['arrival_slot']),'send_slot':int(r['send_slot']),
                       'ran_delay_ms':float(r['ran_delay_ms']),'deadline_ms':float(r['deadline_ms']),
                       'useful_bits':nbits,'data':'U'*math.ceil(nbits/8)})
    for r in rows(args.embb):
        if r['run_id']!=run_id:raise ValueError('run_id mismatch in eMBB file')
        nbits=int(r['served_bits']); slot=int(r['time_slot']);remain=nbits;part=0
        while remain>0:
            part_bits=min(remain,args.chunk_bytes*8)
            events.append({'run_id':run_id,'slice':'embb','packet_id':f'e-{slot:06d}-{part:03d}',
                           'arrival_slot':slot,'send_slot':slot,'ran_delay_ms':0.0,
                           'deadline_ms':None,'useful_bits':part_bits,'data':'E'*math.ceil(part_bits/8)})
            remain-=part_bits;part+=1
    events.sort(key=lambda e:(e['send_slot'],0 if e['slice']=='urllc' else 1,e['packet_id']))
    socks={}
    for name,source in [('urllc',args.source_urllc),('embb',args.source_embb)]:
        s=socket.socket(socket.AF_INET6,socket.SOCK_DGRAM)
        s.bind((source,0))
        socks[name]=s
    args.out.parent.mkdir(parents=True,exist_ok=True)
    start=time.monotonic_ns()
    transmitted=0
    try:
        with args.out.open('w',encoding='utf-8') as f:
            for event in events:
                scheduled_ns=start+int(event['send_slot']*slot_ms*1e6*args.scale)
                now=time.monotonic_ns()
                if scheduled_ns>now:time.sleep((scheduled_ns-now)/1e9)
                event['sent_mono_ns']=time.monotonic_ns()
                event['playback_lag_ms']=round((event['sent_mono_ns']-scheduled_ns)/1e6,3)
                buf=json.dumps(event,ensure_ascii=True,separators=(',',':')).encode('utf-8')
                port=args.urllc_port if event['slice']=='urllc' else args.embb_port
                if len(buf)>1300:raise RuntimeError('Packet too large for conservative SRv6 MTU budget')
                socks[event['slice']].sendto(buf,(args.dest,port))
                safe=dict(event);safe.pop('data',None)
                f.write(json.dumps(safe,ensure_ascii=False)+'\n');f.flush()
                transmitted+=1
    finally:
        for s in socks.values():s.close()
    print(json.dumps({'run_id':run_id,'transmitted_datagrams':transmitted,'out':str(args.out),
                      'playback_scale':args.scale,'note':'UDP sent does not guarantee Server received'},indent=2))

if __name__=='__main__':main()
