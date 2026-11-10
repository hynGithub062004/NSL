#!/usr/bin/env bash
set -euo pipefail

# TV4 - Restore dual-slice IPv6 policy routing on R1
# Run only inside the R1 container after base SRv6 setup.

# eMBB - table 100 - R1 -> R2 -> R4
ip -6 route replace 2001:db8:40::/64 \
  encap seg6 mode encap \
  segs 2001:db8:200::2,2001:db8:400::4 \
  via 2001:db8:12::2 dev eth1 table 100

# URLLC - table 101 - R1 -> R3 -> R4
ip -6 route replace 2001:db8:40::/64 \
  encap seg6 mode encap \
  segs 2001:db8:300::3,2001:db8:400::4 \
  via 2001:db8:13::3 dev eth2 table 101

# Source-based routing rules.
# Add only when the matching rule is absent.
# Project GNS3 export already uses priorities 1000/1001 and a destination match.
# Recognize either a source-only rule or a source+destination rule to avoid duplicates.
if ! ip -6 rule show | grep -Eq 'from 2001:db8:10::2(/128)?( to 2001:db8:40::/64)? lookup 100([[:space:]]|$)'; then
  if ip -6 rule show | grep -Eq '^1000:'; then
    echo 'ERROR: priority 1000 already occupied by a different rule' >&2
    exit 1
  fi
  ip -6 rule add pref 1000 from 2001:db8:10::2/128 to 2001:db8:40::/64 table 100
fi

if ! ip -6 rule show | grep -Eq 'from 2001:db8:10::3(/128)?( to 2001:db8:40::/64)? lookup 101([[:space:]]|$)'; then
  if ip -6 rule show | grep -Eq '^1001:'; then
    echo 'ERROR: priority 1001 already occupied by a different rule' >&2
    exit 1
  fi
  ip -6 rule add pref 1001 from 2001:db8:10::3/128 to 2001:db8:40::/64 table 101
fi

echo "=== IPv6 RULES ==="
ip -6 rule show

echo "=== eMBB TABLE 100 ==="
ip -6 route show table 100

echo "=== URLLC TABLE 101 ==="
ip -6 route show table 101