#!/usr/bin/env bash
# Doc trang thai tren R1; khong thay doi cau hinh.
set -euo pipefail
printf '[R1] Current SRv6 policy:
'
ip -6 route show 2001:db8:40::/64
printf '
[R1] Routes to R2/R3 SIDs:
'
ip -6 route show 2001:db8:200::2/128
ip -6 route show 2001:db8:300::3/128
printf '
[R1] IPv6 forwarding:
'
sysctl net.ipv6.conf.all.forwarding
