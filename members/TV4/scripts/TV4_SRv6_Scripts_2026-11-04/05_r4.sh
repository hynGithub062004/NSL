#!/usr/bin/env bash
# R4: eth0-R2 / eth1-R3 / eth2-Server.
set -euo pipefail
ip link set dev eth0 up
ip link set dev eth1 up
ip link set dev eth2 up
ip -6 addr replace 2001:db8:24::4/64 dev eth0
ip -6 addr replace 2001:db8:34::4/64 dev eth1
ip -6 addr replace 2001:db8:40::1/64 dev eth2
sysctl -w net.ipv6.conf.all.forwarding=1
sysctl -w net.ipv6.conf.all.seg6_enabled=1
# Goi SRv6 den tu R2 (eth0) HOAC R3 (eth1):
sysctl -w net.ipv6.conf.eth0.seg6_enabled=1
sysctl -w net.ipv6.conf.eth1.seg6_enabled=1
# SID cuoi: giai dong goi, dua IPv6 goc den Server qua eth2.
ip -6 route replace 2001:db8:400::4/128 \
  encap seg6local action End.DX6 nh6 2001:db8:40::2 dev eth2
# Duong tra ve Client: mac dinh qua R2. KHONG co nghia hai chieu cung qua R3.
ip -6 route replace 2001:db8:10::/64 via 2001:db8:24::2 dev eth0
printf '
[R4] SID End.DX6:
'
ip -6 route show 2001:db8:400::4/128
