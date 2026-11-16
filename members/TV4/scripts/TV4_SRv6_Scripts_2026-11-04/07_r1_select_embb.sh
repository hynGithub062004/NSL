#!/usr/bin/env bash
# CHAY TREN R1. Thay the TOAN BO route chung den 2001:db8:40::/64.
# Day la chuyen duong thu cong, CHUA phai hai slice dong thoi doc lap.
set -euo pipefail
ip -6 route replace 2001:db8:40::/64 \
  encap seg6 mode encap \
  segs 2001:db8:200::2,2001:db8:400::4 \
  via 2001:db8:12::2 dev eth1
printf '
[R1] Policy eMBB: R1 -> R2 -> R4 -> Server
'
ip -6 route show 2001:db8:40::/64
