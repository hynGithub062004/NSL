#!/usr/bin/env bash
# R1: headend SRv6; eMBB mac dinh khi chay lai script nay.
# eth0-Client / eth1-R2 / eth2-R3
set -euo pipefail
ip link set dev eth0 up
ip link set dev eth1 up
ip link set dev eth2 up
ip -6 addr replace 2001:db8:10::1/64 dev eth0
ip -6 addr replace 2001:db8:12::1/64 dev eth1
ip -6 addr replace 2001:db8:13::1/64 dev eth2
sysctl -w net.ipv6.conf.all.forwarding=1
# Den cac SID tren R2 va R3 (hai duong khac nhau):
ip -6 route replace 2001:db8:200::2/128 via 2001:db8:12::2 dev eth1
ip -6 route replace 2001:db8:300::3/128 via 2001:db8:13::3 dev eth2
# Khoi phuc policy eMBB mac dinh; URLCC thay bang script 08.
ip -6 route replace 2001:db8:40::/64 \
  encap seg6 mode encap \
  segs 2001:db8:200::2,2001:db8:400::4 \
  via 2001:db8:12::2 dev eth1
printf '
[R1] Active SRv6 policy:
'
ip -6 route show 2001:db8:40::/64
