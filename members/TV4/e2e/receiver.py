"""TV4: receive genuine IPv6 UDP packets in the GNS3 Server container.

Writes one JSONL record per datagram, preserving run_id/packet_id. Launch receiver
BEFORE client playback. Uses only Python 3 standard library.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import select
import socket
import time


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--out',required=True,type=Path)
    p.add_argument('--bind',default='::')
    p.add_argument('--urllc-port',type=int,default=5501)
    p.add_argument('--embb-port',type=int,default=5502)
    p.add_argument('--duration',type=float,default=20.0)
    args=p.parse_args()
    if not (0<args.duration<=3600):p.error('duration must be 0..3600 seconds')
    sockets=[]
    for port in (args.urllc_port,args.embb_port):
        sock=socket.socket(socket.AF_INET6,socket.SOCK_DGRAM)
        sock.bind((args.bind,port))
        sockets.append(sock)
    args.out.parent.mkdir(parents=True,exist_ok=True)
    end=time.monotonic()+args.duration
    received=0
    print(f'TV4 server ready, ports {args.urllc_port}/{args.embb_port}, output {args.out}',flush=True)
    with args.out.open('w',encoding='utf-8') as f:
        try:
            while time.monotonic()<end:
                readable,_,_=select.select(sockets,[],[],min(0.3,max(0.0,end-time.monotonic())))
                for s in readable:
                    payload,peer=s.recvfrom(64000)
                    recv_mono=time.monotonic_ns()
                    try:
                        msg=json.loads(payload.decode('utf-8'))
                        if not isinstance(msg,dict) or not all(k in msg for k in ('packet_id','run_id','slice','useful_bits','sent_mono_ns')):
                            continue
                        data=msg.pop('data','')
                        if len(data)*8 < int(msg['useful_bits']):
                            continue
                        msg.update({'recv_mono_ns':recv_mono,'peer_ipv6':peer[0],
                                    'udp_payload_bytes':len(payload),'payload_bytes':len(data)})
                        f.write(json.dumps(msg,ensure_ascii=False)+'\n')
                        f.flush()
                        received+=1
                    except (ValueError,UnicodeDecodeError,TypeError):
                        continue
        finally:
            for s in sockets:s.close()
    print(f'TV4 receiver finished: {received} packets written to {args.out}',flush=True)

if __name__=='__main__':main()
