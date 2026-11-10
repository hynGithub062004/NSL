#!/usr/bin/env bash
# Server eth0 -> R4 eth2; 2001:db8:40::/64
set -euo pipefail
ip link set dev eth0 up
ip -6 addr replace 2001:db8:40::2/64 dev eth0
ip -6 route replace default via 2001:db8:40::1 dev eth0
printf '
[Server] IPv6 / default route:
'
ip -6 addr show dev eth0
ip -6 route show default
