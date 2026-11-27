#!/bin/bash
# $1 = каталог прогона, $2 = mock-dir, $3 = id, $4 = документ, $5 = worktree кода
cd "$5"
python -m bcc_review.v2 stage judge --doc "$4" --from "$1" --provider mock --mock-dir "$2" --no-cache \
  --runs-dir /home/user/r26/off --run-id "$3" --out /home/user/r26/off/$3/report.md -q > /home/user/r26/off_$3.log 2>&1
cd /home/user/c31 && python -m evaluation.v2.score /home/user/r26/off/$3/report.json --run-dir /home/user/r26/off/$3 --arbiter off \
  --out /home/user/r26/off/$3.score.json --md /home/user/r26/off/$3.score.md >/dev/null 2>&1
python3 - "$3" <<'PY'
import sys,re
k=sys.argv[1]; t=open(f'/home/user/r26/off/{k}.score.md').read()
g=lambda p:(re.search(p,t) or [None,'?'])[1]
print(f"{k}: К {g(r'К1–К5 найдены \| (\S+)')} крит {g(r'из них критичными \| (\S+)')} С {g(r'С1–С20 найдены \| (\S+)')} ключ {g(r'Ключевые 25: \*\*(\S+)\*\*')} зам {g(r'всего замечаний \| (\S+)')} дубл {g(r'дублей (\d+)')} лож.крит {g(r'критичных ложных \| (\S+)')} промахи {re.findall(r'^\* \*\*(С\d+|К\d)\*\*',t,re.M)}")
PY
