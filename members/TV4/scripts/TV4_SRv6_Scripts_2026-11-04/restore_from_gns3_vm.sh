#!/usr/bin/env bash
# Script CHAY TREN GNS3 VM, sau khi giai nen thu muc nay vao VM.
# Usage: bash restore_from_gns3_vm.sh CLIENT_ID R1_ID R2_ID R3_ID R4_ID SERVER_ID [embb|urllc]
# Yeu cau: Docker containers dang chay. KHONG tu suy doan ID node.
set -euo pipefail
if [[ $# -lt 6 || $# -gt 7 ]]; then
  echo 'Usage: bash restore_from_gns3_vm.sh CLIENT_ID R1_ID R2_ID R3_ID R4_ID SERVER_ID [embb|urllc]' >&2
  exit 2
fi
CLIENT="$1"; R1="$2"; R2="$3"; R3="$4"; R4="$5"; SERVER="$6"
POLICY="${7:-embb}"
if [[ "$POLICY" != 'embb' && "$POLICY" != 'urllc' ]]; then
  echo 'Policy phai la embb hoac urllc.' >&2; exit 2
fi
if docker info >/dev/null 2>&1; then
  DOCKER=(docker)
else
  DOCKER=(sudo docker)
  "${DOCKER[@]}" info >/dev/null
fi
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

declare -a IDS=("$CLIENT" "$R1" "$R2" "$R3" "$R4" "$SERVER")
declare -a NAMES=(Client R1 R2 R3 R4 Server)

echo '====== KIEM TRA MAPPING CONTAINER ======'
for i in "${!IDS[@]}"; do
  printf '%-7s ID=%-15s  ' "${NAMES[$i]}" "${IDS[$i]}"
  "${DOCKER[@]}" inspect --format '{{.Name}}  [{{.Config.Image}}]' "${IDS[$i]}"
done
printf '
CHU Y: Neu gan nham ID -> sai node, co the pha cau hinh.
'
read -r -p 'Nhap YES neu mapping CHINH XAC va muon ap dung: ' OK
if [[ "$OK" != 'YES' ]]; then echo 'Da huy.'; exit 1; fi

run_on() {
  local id="$1" file="$2" node="$3"
  printf '
===== Dang cau hinh %s (%s) =====
' "$node" "$file"
  "${DOCKER[@]}" exec -i "$id" bash -s < "$HERE/$file"
}
# Tu interface/cac route do phu thuoc: Server -> R4 -> R2/R3 -> R1 -> Client.
run_on "$SERVER" '06_server.sh' Server
run_on "$R4" '05_r4.sh' R4
run_on "$R2" '03_r2.sh' R2
run_on "$R3" '04_r3.sh' R3
run_on "$R1" '02_r1.sh' R1
run_on "$CLIENT" '01_client.sh' Client
if [[ "$POLICY" == 'urllc' ]]; then
  run_on "$R1" '08_r1_select_urllc.sh' R1
fi
printf '
===== KIEM TRA CLIENT -> SERVER =====
'
run_on "$CLIENT" '10_test_client.sh' Client
printf '
Hoan tat. Policy hien tai: %s
' "$POLICY"
