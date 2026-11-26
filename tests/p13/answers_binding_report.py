"""Отчёт «куда попадает ответ аналитика»: браузерный сценарий + опубликованный parse_answers.

    python tests/p13/answers_binding_report.py OUTDIR [--src SRC] [--parser-src SRC]

* ``--src`` — каталог ``src`` реализации write_html (по умолчанию эта копия; для
  воспроизведения дефекта — копия прежнего коммита);
* ``--parser-src`` — каталог ``src`` копии, где есть ``bcc_review.runtime`` (опубликованный
  слот parse_answers: модуль №08 или резерв Max). Без него разбор делает только эталонный
  ``parse_answers_markdown``.

Пишет ``OUTDIR/answers-binding.md`` с ответами до сохранения, после загрузки, выгрузкой и Decision.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parents[1] / "src"), str(HERE)]

from bcc_review.exports import html as H  # noqa: E402
from test_answers_binding import SRC, run_scenario  # noqa: E402

PARSE = """
import json, sys
from bcc_review.runtime.modules import Modules
doc = json.load(open(sys.argv[1], encoding="utf-8"))["document"]
slot = Modules().get("parse_answers")
out = {"implementation": slot.label, "files": {}}
for p in sys.argv[2:]:
    r = slot.func(p, doc)
    out["files"][p] = {"decisions": r, "warnings": []} if isinstance(r, list) else r
print(json.dumps(out, ensure_ascii=False))
"""


def fmt_q(qs):
    return "\n".join(f"| {q['qid']} | {q['prompt'][5:80]}… | {json.dumps(q['value'], ensure_ascii=False)} |" for q in qs)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("outdir")
    ap.add_argument("--src", default=str(SRC))
    ap.add_argument("--parser-src", default=None)
    args = ap.parse_args()
    out = Path(args.outdir).resolve()
    out.mkdir(parents=True, exist_ok=True)
    reports, obs = run_scenario(out, Path(args.src).resolve())
    exports = {
        "r2 как загружен (до ввода ответа про push)": obs["step2"]["export_as_loaded"]["file"],
        "r2 после ответа про push": obs["step2"]["export"]["file"],
        "r2 без хранилища": obs["nostore"]["export"]["file"],
    }
    parsed = None
    if args.parser_src:
        env = dict(os.environ, PYTHONPATH=str(Path(args.parser_src).resolve()))
        proc = subprocess.run(
            [sys.executable, "-c", PARSE, str(out / "r2.json"), *exports.values()],
            env=env, capture_output=True, text=True, cwd=str(out),
        )
        parsed = json.loads(proc.stdout) if proc.returncode == 0 else {"error": proc.stderr[-2000:]}
    lines = [
        "# Куда попадает ответ аналитика (HTML №13)",
        "",
        f"* write_html: `{obs['implementation']}`",
        f"* HTML: `{obs['html_path']}` (r1 → r2 → r3 записаны по очереди в этот путь), браузер Chromium, профиль на диске",
        f"* документ: `{reports['r1']['document']['id']}` (один SHA у r1, r2, r3)",
        "",
        "## 1. r1 — ответы перед закрытием браузера",
        "", "| Q-ID | вопрос | значение |", "| --- | --- | --- |", fmt_q(obs["step1"]["questions_before_close"]), "",
        "Хранилище после записи:", "", "```json", json.dumps(obs["step1"]["storage"], ensure_ascii=False, indent=1), "```", "",
        "## 2. r2 на том же пути — после загрузки",
        "", "| Q-ID | вопрос | значение |", "| --- | --- | --- |", fmt_q(obs["step2"]["questions_loaded"]), "",
        f"Статус: {obs['step2']['status'] or '—'}", "",
        "Панель «нет в этом отчёте»: " + (json.dumps(obs["step2"]["panel"]["items"], ensure_ascii=False) if obs["step2"]["panel"] else "нет"), "",
        "Хранилище после ответа про push:", "", "```json", json.dumps(obs["step2"]["storage_after_push"], ensure_ascii=False, indent=1), "```", "",
        "## 3. r3 (тот же вопрос о событии перенумерован в Q-03) — после загрузки",
        "", "| Q-ID | вопрос | значение |", "| --- | --- | --- |", fmt_q(obs["step3"]["questions_loaded"]), "",
        "## 4. Черновик старого формата (только Q-ID)",
        "", "| Q-ID | вопрос | значение |", "| --- | --- | --- |", fmt_q(obs["legacy"]["questions_loaded"]), "",
        f"Статус: {obs['legacy']['status'] or '—'}", "",
        "## 5. Хранилище отключено: клавиатура и выгрузка", "",
        f"Статус: {obs['nostore']['status_on_load']}", "",
        "```json", json.dumps(obs["nostore"]["keyboard"], ensure_ascii=False, indent=1), "```", "",
        "## 6. Выгрузка answers.md и разбор", "",
    ]
    for title, path in exports.items():
        text = Path(path).read_text(encoding="utf-8")
        ref = H.parse_answers_markdown(text)
        lines += [f"### {title}", "", "```markdown", text.rstrip("\n"), "```", "",
                  "Эталонный parse_answers_markdown: `" + json.dumps(ref["answers"], ensure_ascii=False) + "`", ""]
        if parsed and "files" in parsed:
            res = parsed["files"][path]
            lines += [f"Опубликованный `{parsed['implementation']}`:", "", "```json",
                      json.dumps(res, ensure_ascii=False, indent=1), "```", ""]
        elif parsed:
            lines += ["Опубликованный parse_answers: ошибка запуска", "", "```", parsed["error"], "```", ""]
    (out / "answers-binding.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(out / "answers-binding.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
