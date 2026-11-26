#!/usr/bin/env bash
# Путь жюри для профиля Gemini: обычная установка кандидата и публичный CLI из соседнего каталога.
#
#   bash tests/p12/jury/run_jury_path.sh CANDIDATE_DIR [LABEL] [PYTHON]
#
# CANDIDATE_DIR — checkout кандидата (например, git worktree на bcc/integration). Скрипт:
#   1) создаёт чистый venv и ставит кандидата командой  pip install ".[gemini]"  (не editable);
#   2) из отдельного каталога запускает ровно
#        python -m bcc_review INPUT.md OUT.md --provider gemini --max-calls 2 --max-seconds 90 --no-cache
#        python -m bcc_review verify OUT.json INPUT.md
#      для двух случаев: без ключа и с синтетическим GEMINI_API_KEY только в окружении;
#   3) печатает строку таблицы на случай.
# Имитация: в случае с ключом подменяется только самый нижний HTTP-транспорт SDK
# (observer/sitecustomize.py через PYTHONPATH; пакет не меняется). Сеть не используется:
# наблюдатель считает каждое socket.connect.
set -euo pipefail

CAND="$(cd "$1" && pwd)"
LABEL="${2:-$(git -C "$CAND" rev-parse --short HEAD 2>/dev/null || echo candidate)}"
PY="${3:-python3.12}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/p12-jury-XXXXXX")"
INPUT="$CAND/contracts/examples/two_linked_requirements.md"
FIXTURE="$HERE/../fixtures/gemini/ok_empty.json"

"$PY" -m venv "$WORK/venv"
(cd "$CAND" && "$WORK/venv/bin/python" -m pip install -q --disable-pip-version-check ".[gemini]")
mkdir -p "$WORK/run"
cd "$WORK/run"
BASE=(env -i "PATH=$WORK/venv/bin:/usr/bin:/bin" "HOME=$WORK/run" "LANG=C.UTF-8")
"${BASE[@]}" python -c "import sys, bcc_review, google.genai as g; \
print(f'# {sys.argv[1]}: python {sys.version.split()[0]}, google-genai {g.__version__}, пакет {bcc_review.__file__}')" "$LABEL"

for CASE in nokey key; do
  OUT="$WORK/out-$CASE/OUT.md"; LOG="$WORK/out-$CASE/observe.jsonl"
  mkdir -p "$WORK/out-$CASE"; : > "$LOG"
  EXTRA=("PYTHONPATH=$HERE/observer" "P12_OBSERVE_LOG=$LOG")
  if [ "$CASE" = key ]; then
    EXTRA+=("P12_FAKE_TRANSPORT=1" "P12_FIXTURE=$FIXTURE" "GEMINI_API_KEY=AIzaSyntheticP12KeyNotReal000000000000")
  fi
  set +e
  "${BASE[@]}" "${EXTRA[@]}" python -m bcc_review "$INPUT" "$OUT" --provider gemini --max-calls 2 --max-seconds 90 \
    --no-cache > "$WORK/out-$CASE/stdout.txt" 2>&1
  RUN_EXIT=$?
  "${BASE[@]}" python -m bcc_review verify "${OUT%.md}.json" "$INPUT" > "$WORK/out-$CASE/verify.txt" 2>&1
  VERIFY_EXIT=$?
  set -e
  "$WORK/venv/bin/python" - "$LABEL" "$CASE" "$WORK/out-$CASE" "$RUN_EXIT" "$VERIFY_EXIT" <<'EOF'
import json, sys
from pathlib import Path
label, case, d, run_exit, verify_exit = sys.argv[1:]
d = Path(d)
run = json.loads((d / "OUT.json").read_text(encoding="utf-8"))["run"]
obs = [json.loads(x) for x in (d / "observe.jsonl").read_text().splitlines() if x.strip()]
http = [o for o in obs if o["event"] == "http"]
sockets = sum(1 for o in obs if o["event"] == "socket.connect")
reached = ", ".join(f"{s['name']}×{s['calls']}" for s in run["stages"] if s["calls"]) or "—"
reason = run["budget"]["reason"] or next((r.split(": ", 2)[-1][:40] for r in run["status_reasons"]
                                          if "not_configured" in r), "—")
key = "нет" if case == "nokey" else "синтетический"
transport = "сеть не трогалась" if case == "nokey" else "HTTPTransport подменён"
verify = (d / "verify.txt").read_text().split(" — ")[0].strip()
print(f"| {label} | {key} | {transport}; HTTP {len(http)}, socket {sockets}, ключ из env в запросе: "
      f"{all(o['api_key_from_env'] for o in http) if http else '—'} | {run['calls']['physical']} ({reached}) | "
      f"{run['mode']} / {run['status']}; {reason} | {verify} (exit {verify_exit}) |")
EOF
done
echo "# артефакты: $WORK"
