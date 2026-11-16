#!/usr/bin/env bash
# R2: SID End cho eMBB, eth0-R1 / eth1-R4.
# Chu y: End dev eth0 la cau hinh da kiem chung; dev lo truoc day gay ping loss.
set -euo pipefail
ip link set dev eth0 up
ip link set dev eth1 up
ip -6 addr replace 2001:db8:12::2/64 dev eth0
ip -6 addr replace 2001:db8:24::2/64 dev eth1
sysctl -w net.ipv6.conf.all.forwarding=1
sysctl -w net.ipv6.conf.all.seg6_enabled=1
sysctl -w net.ipv6.conf.eth0.seg6_enabled=1
# SID local R2: thay doi Segment Left va chuyen den SID R4.
ip -6 route replace 2001:db8:200::2/128 encap seg6local action End dev eth0
ip -6 route replace 2001:db8:400::4/128 via 2001:db8:24::4 dev eth1
# Return path toi Client:
ip -6 route replace 2001:db8:10::/64 via 2001:db8:12::1 dev eth0
printf '
[R2] SID and routes:
'
ip -6 route show 2001:db8:200::2/128
ip -6 route show 2001:db8:400::4/128
