#!/usr/bin/env bash
# Client: eth0 -> R1 eth0; 2001:db8:10::/64
set -euo pipefail
ip link set dev eth0 up
ip -6 addr replace 2001:db8:10::2/64 dev eth0
ip -6 route replace default via 2001:db8:10::1 dev eth0
printf '
[Client] IPv6 / default route:
'
ip -6 addr show dev eth0
ip -6 route show default
