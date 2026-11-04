#!/bin/bash
set -uo pipefail
DIR=/root/autodl-fs/qa/pexels
mkdir -p "$DIR"
ids="220453 614810 91227 733872 1043471 1222271 2379004 1681010 1758144 1130626 774909 415829 428338 462680 46710 630730 842548 1462980 1586996 212286 1858175 1036623 697509 842567 1015568 1183266 1310524 1484799 1699159 2065195 2179869 2379889 2381069 2422293 2472884 2589653 2647278 2681751 2695670 2790134"
ok=0
for id in $ids; do
  url="https://images.pexels.com/photos/$id/pexels-photo-$id.jpeg?auto=compress&cs=tinysrgb&w=1200"
  code=$(curl -s -m 20 -o "$DIR/$id.jpg" -w '%{http_code}' "$url")
  if [ "$code" = "200" ] && [ -s "$DIR/$id.jpg" ]; then
    ok=$((ok+1))
  else
    rm -f "$DIR/$id.jpg"
  fi
done
echo "pexels ok=$ok"
ls "$DIR" | wc -l
