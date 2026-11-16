#!/usr/bin/env bash
# CHAY TREN CLIENT; kiem tra Client -> Server.
set -euo pipefail
printf '[Client] Ping Server 2001:db8:40::2:
'
ping -c 5 2001:db8:40::2
printf '
[Client] Traceroute (co the co * do SRv6 / ICMP):
'
if command -v traceroute >/dev/null 2>&1; then
  traceroute -6 -n -w 1 -q 1 2001:db8:40::2 || true
else
  echo 'traceroute khong co san.'
fi
