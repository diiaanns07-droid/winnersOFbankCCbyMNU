"""Сквозной путь владельца: экспорт ответов №13 → штатный CLI ``--answers`` → файл редакции.

Вход: ``fixtures/transfer_tz.md``, в нём два независимых разногласия: комиссия (ПС-1 ↔ «Тарифы»)
и исполнение после 18:00 (ПС-2 ↔ критерий приёмки). Модель имитирует mock-провайдер движка
(``fixtures/mock_transfer.json``). Этап набора идёт через резерв Max ``llm_stages:review_set``
(``BCC_FORCE_FALLBACK=review_set``): сценарий командного №06 — отдельная тема. Файлы ответов
сгенерированы кодом №13 (``exports/html.py:answers_markdown`` @ 540c310, ветка
claude/kind-johnson-tu7ps7) по отчёту первого прогона.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

engine = pytest.importorskip("bcc_review.engine", reason="движок bcc/integration не подключён")
pytest.importorskip("jsonschema")

from bcc_review.contracts import RunOptions  # noqa: E402

FIX = Path(__file__).parent / "fixtures"
ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
EXAMPLE = ROOT / "examples" / "team_answers" / "engine_cli"
ORIGINAL_SHA = "21286a1fb07ef65c640dcc181bcdf19e04ccc6c9c726a510b6a5341601a9c3eb"
REVISION_SHA = "a09da5508614c94a366e37bfc2b72831801b4dbab417153b62ccd9cd2706a839"


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def cli(cwd: Path, *args: str, src: Path = SRC) -> subprocess.CompletedProcess:
    env = dict(os.environ, PYTHONPATH=str(src), BCC_FORCE_FALLBACK="review_set")
    env.pop("ANTHROPIC_API_KEY", None)
    return subprocess.run([sys.executable, "-m", "bcc_review", *args, "--provider", "mock",
                           "--mock-script", str(FIX / "mock_transfer.json"), "--no-cache", "-q"],
                          cwd=cwd, env=env, capture_output=True, text=True, timeout=300)


@pytest.fixture
def case(tmp_path):
    shutil.copyfile(FIX / "transfer_tz.md", tmp_path / "transfer_tz.md")
    for name in ("answers13_Q01_A.md", "answers13_collision.md", "answers13_other_sha.md"):
        shutil.copyfile(FIX / name, tmp_path / name)
    assert sha(tmp_path / "transfer_tz.md") == ORIGINAL_SHA
    return tmp_path


def revisions(d: Path) -> list[str]:
    return sorted(p.name for p in d.glob("transfer_tz.rev-*") if p.is_file())


def answers_stage(rep: dict) -> dict:
    return next(s for s in rep["run"]["stages"] if s["name"] == "answers")


# --------------------------------------------------------------------------- 1. вопросы и ответ №13


def test_first_run_gives_questions_that_the_13_export_was_built_from(case):
    r = cli(case, "transfer_tz.md", "r1.md", "--run-id", "p08-transfer-r1")
    assert r.returncode == 0, r.stderr  # до исправления: TypeError: Question is not JSON serializable
    rep = json.loads((case / "r1.json").read_text(encoding="utf-8"))
    expected = json.loads((FIX / "expected_questions.json").read_text(encoding="utf-8"))["questions"]
    assert [{"id": q["id"], "finding_ids": q["finding_ids"], "options": q["options"]}
            for q in rep["questions"]] == expected
    assert rep["run"]["modules"]["build_questions"] == "team:bcc_review.decisions.clarify:build_questions"
    # вариант несёт проверяемую правку — экспорт №13 печатает её в «Варианты:»
    assert "Правка [b0009]: «Перевод исполнен в пятницу» → «Перевод исполнен в следующий рабочий день»" \
        in rep["questions"][0]["options"][0]
    text13 = (case / "answers13_Q01_A.md").read_text(encoding="utf-8")
    assert "format: bcc-review-answers/1" in text13 and f"source_sha256: {ORIGINAL_SHA}" in text13
    assert "### Ответ\n\nA\n" in text13


# --------------------------------------------------------------------------- 2. правка и файл редакции


def test_cli_answers_changes_only_the_agreed_phrase(case):
    r = cli(case, "transfer_tz.md", "r2.md", "--answers", "answers13_Q01_A.md", "--run-id", "p08-transfer-r2")
    assert r.returncode == 0, r.stderr
    rev = case / "transfer_tz.rev-p08-transfer-r2.md"
    assert revisions(case) == ["transfer_tz.rev-p08-transfer-r2.md", "transfer_tz.rev-p08-transfer-r2.revision.json"]
    assert sha(case / "transfer_tz.md") == ORIGINAL_SHA  # исходник не тронут

    a = (case / "transfer_tz.md").read_bytes()
    b = rev.read_bytes()
    la, lb = a.split(b"\n"), b.split(b"\n")
    assert len(la) == len(lb)
    changed = [i + 1 for i, (x, y) in enumerate(zip(la, lb)) if x != y]
    assert changed == [16]
    assert lb[15].decode() == ("| Перевод 10 000 ₸ создан в 19:00 в пятницу | Исполнить перевод | "
                               "Перевод исполнен в следующий рабочий день |")
    assert la[15].count(b"|") == lb[15].count(b"|") == 4  # таблица цела
    assert b"\r" not in b and not b.startswith(b"\xef\xbb\xbf") and b.endswith(b"\n")
    assert sha(rev) == REVISION_SHA == sha(EXAMPLE / rev.name)  # пример для №09/№18 совпадает байт-в-байт

    rep = json.loads((case / "r2.json").read_text(encoding="utf-8"))
    run = rep["run"]
    # второй прогон прочитал именно записанный файл
    assert rep["document"]["id"] == run["source_sha256"] == sha(rev)
    assert run["revision_of"] == ORIGINAL_SHA and run["source_name"] == rev.name
    assert answers_stage(rep)["status"] == "ok"
    for slot in ("parse_answers", "propose_patch", "write_revision"):
        assert run["modules"][slot].startswith("team:bcc_review.decisions."), slot
    # решение внесено и ждёт проверки повторным анализом
    (d,) = rep["decisions"]
    assert d["question_id"] == "Q-01" and d["answer"] == "A" and d["source_sha256"] == ORIGINAL_SHA
    assert d["patch_state"] == "proposed" and d["fix_status"] == "awaiting_revision"
    (e,) = d["edits"]
    assert (e["block_id"], e["start"], e["end"], e["old"]) == ("b0009", 64, 90, "Перевод исполнен в пятницу")
    assert e["status"] == "applied_not_verified" and e["revision_sha256"] == sha(rev)
    # вторая, независимая проблема (комиссия) осталась подтверждённой обеими опорами
    fee = [f for f in rep["findings"] if "комисси" in f["title"].lower() and f["kind"] == "conflict"]
    assert fee and fee[0]["status"] == "confirmed" and fee[0]["witness"]
    sched = [f for f in rep["findings"] if "18:00" in f["title"] and f["kind"] == "conflict"]
    assert all(f["status"] != "confirmed" for f in sched)  # опоры «в пятницу» больше нет


def test_engine_hands_resolved_edit_to_patch_and_source_path_to_writer(case, monkeypatch):
    """Фиксирует, какие данные дошли до построения правки и какой аргумент получил writer."""
    from bcc_review.decisions import answers, patches

    calls: dict[str, list] = {"parse": [], "patch": [], "write": []}
    real_parse, real_patch, real_write = answers.parse_answers, patches.propose_patch, patches.write_revision

    def parse(*a, **k):
        calls["parse"].append((a, k))
        return real_parse(*a, **k)

    def patch(document, finding, decision, *rest, **k):
        calls["patch"].append({"document_id": document["id"], "finding": finding,
                               "decision": json.loads(json.dumps(decision)), "rest": rest, "kwargs": k})
        return real_patch(document, finding, decision, *rest, **k)

    def write(document, edits, output, *a, **k):
        calls["write"].append({"edits": json.loads(json.dumps(list(edits))), "output": Path(output).name,
                               "args": a, "kwargs": {n: str(v) for n, v in k.items()}})
        return real_write(document, edits, output, *a, **k)

    monkeypatch.setattr(answers, "parse_answers", parse)
    monkeypatch.setattr(patches, "propose_patch", patch)
    monkeypatch.setattr(patches, "write_revision", write)
    monkeypatch.setenv("BCC_FORCE_FALLBACK", "review_set")
    engine.run_review(case / "transfer_tz.md", case / "r2.md", options=RunOptions.coerce({
        "provider": "mock", "mock_script": str(FIX / "mock_transfer.json"), "use_cache": False,
        "answers_path": str(case / "answers13_Q01_A.md"), "run_id": "p08-transfer-spy",
        "cache_dir": str(case / "cache")}))

    (pa, pk), = calls["parse"]
    assert pa[0] == str(case / "answers13_Q01_A.md") and pa[1]["id"] == ORIGINAL_SHA and not pk
    (p,) = calls["patch"]
    assert p["document_id"] == ORIGINAL_SHA and p["finding"] is None and not p["rest"] and not p["kwargs"]
    dec = p["decision"]  # правка разрешена ещё на разборе файла ответов — вопрос движку не нужен
    assert (dec["question_id"], dec["answer"], dec["choice"]) == ("Q-01", "A", "A")
    assert dec["option"].startswith("На следующий рабочий день")
    assert [(e["block_id"], e["start"], e["end"], e["old"], e["new"], e["origin"]) for e in dec["edits"]] == [
        ("b0009", 64, 90, "Перевод исполнен в пятницу", "Перевод исполнен в следующий рабочий день", "option")]
    (w,) = calls["write"]
    assert w["output"] == "transfer_tz.rev-p08-transfer-spy.md" and not w["args"]
    assert w["kwargs"] == {"source_path": str(case / "transfer_tz.md")}  # тот самый аргумент движка
    assert [(e["block_id"], e["old"]) for e in w["edits"]] == [("b0009", "Перевод исполнен в пятницу")]


# --------------------------------------------------------------------------- 3. другой SHA и коллизия


def test_rerun_on_written_revision_is_rejected_as_other_version(case):
    assert cli(case, "transfer_tz.md", "r2.md", "--answers", "answers13_Q01_A.md",
               "--run-id", "p08-transfer-r2").returncode == 0
    rev = case / "transfer_tz.rev-p08-transfer-r2.md"
    before = {n: sha(case / n) for n in revisions(case) + ["transfer_tz.md"]}
    r = cli(case, rev.name, "r3.md", "--answers", "answers13_Q01_A.md", "--run-id", "p08-transfer-r3")
    assert r.returncode == 0, r.stderr
    rep = json.loads((case / "r3.json").read_text(encoding="utf-8"))
    st = answers_stage(rep)
    assert st["status"] == "partial" and "нет применимых правок" in st["reason"]
    msgs = [w["message"] for w in rep["warnings"] if isinstance(w, dict) and w.get("stage") == "answers"]
    assert any("другой редакции" in m and ORIGINAL_SHA[:12] in m and sha(rev)[:12] in m for m in msgs)
    assert rep["decisions"] == [] and rep["document"]["id"] == sha(rev) and "revision_of" not in rep["run"]
    assert {n: sha(case / n) for n in revisions(case) + ["transfer_tz.md"]} == before  # ничего не записано


def test_answers_for_other_sha_change_nothing(case):
    r = cli(case, "transfer_tz.md", "r4.md", "--answers", "answers13_other_sha.md", "--run-id", "p08-transfer-r4")
    assert r.returncode == 0, r.stderr
    rep = json.loads((case / "r4.json").read_text(encoding="utf-8"))
    assert answers_stage(rep)["status"] == "partial"
    assert any("другой редакции" in w["message"] and "000000000000" in w["message"]
               for w in rep["warnings"] if isinstance(w, dict))
    assert revisions(case) == [] and sha(case / "transfer_tz.md") == ORIGINAL_SHA
    assert rep["document"]["id"] == ORIGINAL_SHA


def test_colliding_edits_of_one_range_are_both_rejected(case):
    r = cli(case, "transfer_tz.md", "r5.md", "--answers", "answers13_collision.md", "--run-id", "p08-transfer-r5")
    assert r.returncode == 0, r.stderr
    rep = json.loads((case / "r5.json").read_text(encoding="utf-8"))
    by_q = {d["question_id"]: d for d in rep["decisions"]}
    assert by_q["Q-01"]["patch_state"] == by_q["Q-02"]["patch_state"] == "collision"
    assert by_q["Q-01"]["edits"] == by_q["Q-02"]["edits"] == []
    reason = by_q["Q-01"]["note"]
    assert "Q-01" in reason and "Q-02" in reason and "строка 16" in reason
    assert "«Перевод исполнен в пятницу» → «Перевод исполнен в следующий рабочий день»" in reason
    assert "«Перевод исполнен в пятницу» → «Перевод исполнен в пятницу, комиссия по тарифу»" in reason
    assert sum("пересекающиеся фрагменты" in w["message"] for w in rep["warnings"] if isinstance(w, dict)) == 1
    # независимое решение применено; спорная строка 16 не тронута
    assert by_q["Q-03"]["patch_state"] == "proposed"
    rev = case / "transfer_tz.rev-p08-transfer-r5.md"
    la = (case / "transfer_tz.md").read_text(encoding="utf-8").split("\n")
    lb = rev.read_text(encoding="utf-8").split("\n")
    assert [i + 1 for i, (x, y) in enumerate(zip(la, lb)) if x != y] == [6]
    assert lb[5] == "* **ПС-2.** Перевод, созданный после 18:00 по времени Астаны, исполняется на следующий рабочий день."
    assert sha(case / "transfer_tz.md") == ORIGINAL_SHA


# --------------------------------------------------------------------------- совместимость прежних вызовов


def test_previous_calls_keep_working(case):
    from bcc_review.decisions import Decision, build_questions, parse_answers, propose_patch, write_revision
    from bcc_review.decisions._demo import SYNTHETIC_DOC, make_scripted_ask, synthetic_findings
    from bcc_review.decisions._doc import load_markdown

    doc = load_markdown(SYNTHETIC_DOC)
    qs = build_questions(doc, synthetic_findings(doc), make_scripted_ask(doc))
    json.dumps(qs, ensure_ascii=False)                       # Report.questions сериализуется
    assert qs[0].id == "Q-01" and qs[0]["id"] == "Q-01"       # атрибуты и ключи контракта
    p = propose_patch(doc, None, Decision.from_answer("Q-01", doc["id"], "A"), question=qs[0])
    assert p["state"] == "proposed"
    shutil.copyfile(SYNTHETIC_DOC, case / "loan.md")
    a = write_revision(doc, p["edits"], case / "a.md", source=case / "loan.md")
    b = write_revision(doc, p["edits"], case / "b.md", source_path=case / "loan.md")
    assert a.read_bytes() == b.read_bytes()
    from bcc_review.decisions._demo import EXAMPLES_DIR
    aset = parse_answers(EXAMPLES_DIR / "answers_team_A.md", doc)
    assert [d.question_id for d in aset] == ["Q-01", "Q-02", "Q-03", "Q-04"]   # list[Decision]
    assert [d["question_id"] for d in aset.get("decisions")] == ["Q-01", "Q-02", "Q-03", "Q-04"]  # вид движка


def test_text_revision_for_binary_input_returns_md_path(tmp_path):
    from bcc_review.decisions import write_revision
    from bcc_review.decisions._demo import SYNTHETIC_DOC
    from bcc_review.decisions._doc import load_markdown, sha256_bytes

    pdf = b"%PDF-1.4 synthetic"
    (tmp_path / "x.pdf").write_bytes(pdf)
    doc = dict(load_markdown(SYNTHETIC_DOC), id=sha256_bytes(pdf), format="pdf")
    b = next(b for b in doc["blocks"] if "банковский день" in b["text"])
    s = b["text"].index("банковский")
    e = {"block_id": b["id"], "start": s, "end": s + 10, "old": "банковский", "new": "рабочий"}
    out = write_revision(doc, [e], tmp_path / "x.rev-1.pdf", source_path=tmp_path / "x.pdf")
    assert out == tmp_path / "x.rev-1.md" and out.exists() and not (tmp_path / "x.rev-1.pdf").exists()
    assert "ближайший рабочий день" in out.read_text(encoding="utf-8")
    assert e["status"] == "applied_not_verified" and e["revision"] == "x.rev-1.md"


# --------------------------------------------------------------------------- diff для Max: путь от писателя


def test_max_engine_diff_reads_revision_path_returned_by_writer(tmp_path):
    """PDF → текстовая редакция .md. Движок без diff читает rev_path с суффиксом .pdf и падает;
    с diff (examples/team_answers/engine_cli/max_engine_apply_answers.diff) читает фактический путь."""
    pytest.importorskip("fitz", reason="резервный читатель PDF требует pymupdf")
    if shutil.which("git") is None:
        pytest.skip("нужен git для наложения diff")
    from bcc_review.contracts import normalize_document
    from bcc_review.runtime.fallback.pdf_reader import read_pdf

    pdf = ROOT / "tests" / "integration" / "fixtures" / "bcc_requirements.pdf"
    work = tmp_path / "case"
    work.mkdir()
    shutil.copyfile(pdf, work / "req.pdf")
    doc = normalize_document(read_pdf(work / "req.pdf"))
    (work / "answers.md").write_text(
        f"source_sha256: {doc['id']}\n\n## Q-001\nОтвет: событие — проведённая покупка\n"
        "Правка: «после получения события» → «после получения события о проведённой покупке»\n", encoding="utf-8")

    engine_src = (SRC / "bcc_review" / "engine.py").read_text(encoding="utf-8")
    merged = "rev_path = Path(written) if written else rev_path" in engine_src
    if not merged:  # движок без diff: проблема воспроизводится
        r = cli(work, "req.pdf", "r0.md", "--offline-lint", "--answers", "answers.md", "--run-id", "p08-pdf-0")
        assert r.returncode != 0 and "FileNotFoundError" in r.stderr and "req.rev-p08-pdf-0.pdf" in r.stderr
        assert (work / "req.rev-p08-pdf-0.md").exists()  # писатель записал .md и вернул этот путь
        patched = tmp_path / "patched"
        shutil.copytree(SRC, patched / "src", ignore=shutil.ignore_patterns("__pycache__", "*.egg-info"))
        res = subprocess.run(["git", "apply", str(EXAMPLE / "max_engine_apply_answers.diff")], cwd=patched,
                             capture_output=True, text=True)
        assert res.returncode == 0, res.stderr  # diff накладывается на текущий engine.py
        src = patched / "src"
    else:
        src = SRC
    r = cli(work, "req.pdf", "r1.md", "--offline-lint", "--answers", "answers.md", "--run-id", "p08-pdf-1", src=src)
    assert r.returncode == 0, r.stderr
    rep = json.loads((work / "r1.json").read_text(encoding="utf-8"))
    assert rep["run"]["source_name"] == "req.rev-p08-pdf-1.md" and rep["run"]["revision_of"] == doc["id"]
    assert rep["document"]["id"] == sha(work / "req.rev-p08-pdf-1.md")
    (d,) = rep["decisions"]
    assert (d["patch_state"], d["fix_status"], d["revision"]) == ("applied", "applied_not_verified", "req.rev-p08-pdf-1.md")
    assert sha(work / "req.pdf") == doc["id"]
