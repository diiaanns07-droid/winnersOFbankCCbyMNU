#!/bin/bash
# $1 = имя прогона №31, $2 = модель, $3 = документ
cd /home/user/wrel
M=/home/user/m31/evaluation/v2/measurements/$1
OUT=/home/user/r26/runs
mkdir -p $OUT
python -m bcc_review.v2 stage judge --doc "$3" --from "$M" --provider claude_cli --model "$2" --no-cache \
  --runs-dir $OUT --run-id "j26_$1" --out "$OUT/j26_$1/report.md" -q > /home/user/r26/$1.log 2>&1
echo "rc=$?" >> /home/user/r26/$1.log
