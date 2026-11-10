#!/usr/bin/env bash
# R3: SID End cho URLLC, eth0-R1 / eth1-R4.
set -euo pipefail
ip link set dev eth0 up
ip link set dev eth1 up
ip -6 addr replace 2001:db8:13::3/64 dev eth0
ip -6 addr replace 2001:db8:34::3/64 dev eth1
sysctl -w net.ipv6.conf.all.forwarding=1
sysctl -w net.ipv6.conf.all.seg6_enabled=1
sysctl -w net.ipv6.conf.eth0.seg6_enabled=1
ip -6 route replace 2001:db8:300::3/128 encap seg6local action End dev eth0
ip -6 route replace 2001:db8:400::4/128 via 2001:db8:34::4 dev eth1
ip -6 route replace 2001:db8:10::/64 via 2001:db8:13::1 dev eth0
printf '
[R3] SID and routes:
'
ip -6 route show 2001:db8:300::3/128
ip -6 route show 2001:db8:400::4/128
