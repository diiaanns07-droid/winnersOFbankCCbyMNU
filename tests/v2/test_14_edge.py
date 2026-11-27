"""№14 (технический ревьюер): крайние случаи ядра v2 — странные входы, сбои модели, бюджет вызовов, запись отчёта.

Зелёные тесты фиксируют устойчивость, которая уже есть. Тесты с ``xfail`` — найденные ошибки: владелец, файл, строка и
воспроизведение записаны в ``docs/plan-v2/status/14.md`` (раздел «Волна 3»). Метка нестрогая (``strict=False``):
исправление владельца даёт XPASS, а не красный тест в чужой ветке; №14 снимает метку на следующем цикле.

Все прогоны — без сети: mock-провайдер с записанными ответами официального прогона или подменённый провайдер.
"""
from __future__ import annotations

import json
import os
import zipfile
from pathlib import Path

import pytest

from bcc_review.contracts import ProviderError
from bcc_review.v2 import pipeline
from bcc_review.v2.llm import LLMClient, LLMError, Truncated, merge_lists
from bcc_review.v2.providers.mock import MockProvider

ROOT = Path(__file__).resolve().parents[2]
OFFICIAL = ROOT / "release" / "input" / "requirements.md"
OFFICIAL_FIXTURES = ROOT / "tests" / "v2" / "fixtures" / "official"
STRESS = ROOT / "tests" / "v2" / "fixtures" / "03_stress"
SCHEMA = {"type": "object", "additionalProperties": False, "required": ["items"],
          "properties": {"items": {"type": "array", "items": {"type": "string"}}}}


def _bug(owner: str, what: str):
    return pytest.mark.xfail(reason=f"№{owner}: {what} (docs/plan-v2/status/14.md)", strict=False)


def _has_pdf() -> bool:
    try:
        import fitz  # noqa: F401
        return True
    except ImportError:
        try:
            import pymupdf  # noqa: F401
            return True
        except ImportError:
            return False


needs_pdf = pytest.mark.skipif(not _has_pdf(), reason="нужен pymupdf")


# --------------------------------------------------------------------------- входы

def _odd_inputs(d: Path) -> dict[str, Path]:
    """Странные, но читаемые входы: агент обязан выдать отчёт без трейсбэка."""
    files = {
        "empty.md": b"",
        "blank.md": b"   \n\n\t\n",
        "one_line.md": "Система должна работать быстро.".encode(),
        "no_requirements.md": "У лукоморья дуб зелёный;\nЗлатая цепь на дубе том:\n".encode(),
        "random_bytes.md": bytes(range(256)) * 8,
        "cp1251.txt": "Ф-1. Система должна блокировать карту за 5 секунд.\n".encode("cp1251"),
        "utf16.txt": "Ф-1. Система должна блокировать карту за 5 секунд.\n".encode("utf-16"),
        "nul.md": "Ф-1. Система\x00 должна\x00 работать.\n".encode(),
        "long_line.md": ("Система должна " + "очень " * 20000 + "быстро.\n").encode(),
        "empty.html": b"<html><body></body></html>",
        "crlf.md": "# ТЗ\r\n\r\nФ-1. Лимит 100 000 тенге в сутки.\r\n".encode(),
    }
    out = {}
    for name, data in files.items():
        p = d / name
        p.write_bytes(data)
        out[name] = p
    return out


def _unreadable_inputs(d: Path) -> dict[str, Path]:
    """Файлы, которые прочитать нельзя: отчёт о сбое с понятной причиной по-русски, код выхода 3."""
    out = {}
    (d / "fake.pdf").write_bytes(b"not a pdf at all" + bytes(range(100)))
    (d / "empty.pdf").write_bytes(b"")
    (d / "empty.docx").write_bytes(b"")
    with zipfile.ZipFile(d / "zip_not_docx.docx", "w") as z:
        z.writestr("a.txt", "x")
    (d / "doc.xyz").write_text("text", encoding="utf-8")
    (d / "noext").write_text("Система должна", encoding="utf-8")
    for name in ("fake.pdf", "empty.pdf", "empty.docx", "zip_not_docx.docx", "doc.xyz", "noext"):
        out[name] = d / name
    return out


def _review(tmp_path: Path, doc: Path, name: str = "r", **opts):
    base = {"runs_dir": str(tmp_path / "runs"), "html": False, "cache": False}
    out = tmp_path / "out" / f"{name}.md"
    report, written = pipeline.review(doc, out, {**base, **opts})
    return report, written, out


def _schema_errors(report: dict) -> list[str]:
    import jsonschema
    schema = json.loads((ROOT / "contracts" / "v2.json").read_text(encoding="utf-8"))
    return [f"{'/'.join(map(str, e.absolute_path))}: {e.message[:120]}"
            for e in jsonschema.Draft202012Validator(schema).iter_errors(report)]


ODD = ["empty.md", "blank.md", "one_line.md", "no_requirements.md", "random_bytes.md", "cp1251.txt", "utf16.txt",
       "nul.md", "long_line.md", "empty.html", "crlf.md"]
UNREADABLE = ["fake.pdf", "empty.pdf", "empty.docx", "zip_not_docx.docx", "doc.xyz", "noext"]


@pytest.mark.parametrize("provider", ["mock", "offline"])
@pytest.mark.parametrize("name", ODD)
def test_odd_inputs_give_report_that_verifies(tmp_path, name, provider):
    from bcc_review.v2 import verify
    doc = _odd_inputs(tmp_path)[name]
    empty_mock = tmp_path / "empty_mock"
    empty_mock.mkdir()
    report, written, out = _review(tmp_path, doc, provider=provider, mock_dir=str(empty_mock))
    assert out.is_file() and Path(written["json"]).is_file()
    assert report["run"]["status"] in ("complete", "partial"), report["run"]["warnings"]
    assert not _schema_errors(json.loads(Path(written["json"]).read_text(encoding="utf-8")))
    res = verify.verify_report(Path(written["json"]), doc)
    assert res["ok"], res["errors"][:3]


@pytest.mark.parametrize("name", UNREADABLE)
def test_unreadable_input_gives_failed_report_with_reason(tmp_path, name, capsys):
    from bcc_review.v2.__main__ import main
    doc = _unreadable_inputs(tmp_path)[name]
    out = tmp_path / "out" / "r.md"
    code = main([str(doc), str(out), "--provider", "mock", "--runs-dir", str(tmp_path / "runs"), "--no-html", "-q"])
    assert code == 3
    report = json.loads(out.with_suffix(".json").read_text(encoding="utf-8"))
    assert report["run"]["status"] == "failed"
    assert report["verdict"]["development"] == "none" and report["verdict"]["testing"] == "none"
    reason = " ".join(report["run"]["warnings"])
    assert any("а" <= ch <= "я" for ch in reason.lower()), reason          # причина по-русски
    assert "Traceback" not in out.read_text(encoding="utf-8")


@pytest.mark.parametrize("name", ["fake.pdf", "doc.xyz"])
def test_unreadable_input_report_matches_contract(tmp_path, name):
    doc = _unreadable_inputs(tmp_path)[name]
    report, written, _ = _review(tmp_path, doc, provider="mock")
    assert not _schema_errors(json.loads(Path(written["json"]).read_text(encoding="utf-8")))


@pytest.mark.parametrize("name", ["empty.md", "blank.md", "empty.html"])
def test_empty_document_is_not_ready_and_costs_no_calls(tmp_path, name):
    doc = _odd_inputs(tmp_path)[name]
    report, _, _ = _review(tmp_path, doc, provider="mock")
    v = report["verdict"]
    assert v["development"] != "yes" and v["testing"] != "yes", v
    assert report["run"]["calls"]["total"] == 0
    assert any("нет текста" in w for w in report["run"]["warnings"] + report["document"].get("warnings", []))


@needs_pdf
@pytest.mark.parametrize("provider", ["offline", "mock"])
def test_document_warnings_reach_report(tmp_path, provider):
    report, written, out = _review(tmp_path, STRESS / "scan_page.pdf", provider=provider)
    warns = " ".join((report.get("document") or {}).get("warnings") or []) + " ".join(report["run"]["warnings"])
    assert "Страница 2" in warns and "скан" in warns
    assert "скан" in out.read_text(encoding="utf-8")


def test_report_never_overwrites_input(tmp_path):
    src = tmp_path / "tz.html"
    src.write_text("<html><body><h1>ТЗ</h1><p>Ф-1. Система должна блокировать карту за 5 секунд.</p></body></html>",
                   encoding="utf-8")
    before = src.read_bytes()
    from bcc_review.v2.__main__ import main
    main([str(src), str(tmp_path / "tz.md"), "--provider", "offline", "--runs-dir", str(tmp_path / "runs"), "-q"])
    assert src.read_bytes() == before


# --------------------------------------------------------------------------- сбои модели

class Faulty(MockProvider):
    """Ответы официального прогона (mock), но ``fault(stage, k)`` может вернуть исключение или свой ответ."""

    def __init__(self, fault, **kw):
        super().__init__(fixtures_dir=OFFICIAL_FIXTURES, **kw)
        self.fault = fault
        self.n: dict[str, int] = {}

    def invoke(self, *, stage="", **kw):
        self.n[stage] = self.n.get(stage, 0) + 1
        r = self.fault(stage, self.n[stage])
        if isinstance(r, Exception):
            raise r
        if isinstance(r, dict):
            return r
        return super().invoke(stage=stage, **kw)


def _faulty_run(tmp_path, monkeypatch, fault, doc: Path = OFFICIAL, **opts):
    def make_llm(o, run, input_path=None):
        llm = LLMClient(Faulty(fault), model="m", provider_name="fake", max_calls=o["max_calls"],
                        max_seconds=o["max_seconds"], trace=run.trace if run else None, sleep=lambda s: None,
                        stage_timeout_s=float(o.get("stage_timeout") or 0))
        return llm, "fake"
    monkeypatch.setattr(pipeline, "make_llm", make_llm)
    return _review(tmp_path, doc, **opts)


def _truncated(stage, k):
    return {"data": {}, "usage": {}, "model": "m", "stop_reason": "max_tokens"}


def test_network_down_gives_failed_report_not_traceback(tmp_path, monkeypatch):
    report, written, out = _faulty_run(tmp_path, monkeypatch, lambda s, k: ProviderError("network", "нет соединения"))
    assert out.is_file()
    assert report["run"]["status"] == "failed"
    assert report["verdict"]["development"] == "none"
    assert report["run"]["calls"]["total"] <= 16


def test_network_down_is_explained_first(tmp_path, monkeypatch):
    report, _, _ = _faulty_run(tmp_path, monkeypatch, lambda s, k: ProviderError("network", "нет соединения"))
    first = report["run"]["warnings"][0].lower()
    assert "соединени" in first or "сет" in first, first
    assert not any("исчерпан бюджет" in w for w in report["run"]["warnings"])


def test_truncated_lenses_keep_run_alive(tmp_path, monkeypatch):
    report, _, out = _faulty_run(tmp_path, monkeypatch, lambda s, k: _truncated(s, k) if s.startswith("lens") else None)
    assert out.is_file() and report["run"]["status"] == "partial"
    assert report["run"]["stages"]["consistency"] == "ok" and report["run"]["stages"]["judge"] in ("ok", "partial")
    assert report["findings"]


def test_judge_crash_falls_back_to_code_registry(tmp_path, monkeypatch):
    report, _, _ = _faulty_run(tmp_path, monkeypatch, lambda s, k: RuntimeError("сбой") if s == "judge" else None)
    assert report["run"]["status"] == "partial"
    assert report["run"]["stages"]["judge"] in ("partial", "failed")
    assert report["findings"] and all(f["evidence"] for f in report["findings"])
    assert any("судья" in w.lower() for w in report["run"]["warnings"])


@pytest.mark.parametrize("fault", ["timeout", "none_data", "quota"])
def test_one_stage_fault_does_not_break_others(tmp_path, monkeypatch, fault):
    stage = {"timeout": "lens_qa", "none_data": "consistency", "quota": "lens_risk"}[fault]

    def f(s, k):
        if s != stage:
            return None
        if fault == "none_data":
            return {"data": None, "usage": {}, "model": "m", "stop_reason": "end_turn"}
        return ProviderError(fault, "сбой этапа")

    report, _, out = _faulty_run(tmp_path, monkeypatch, f)
    assert out.is_file() and report["run"]["status"] == "partial"
    assert report["run"]["stages"][stage] == "failed"
    assert report["run"]["stages"]["segment"] == "ok"
    assert report["findings"]


def test_provider_invalid_json_gets_one_repair():
    class P:
        name, handles_retries = "p", False

        def __init__(self):
            self.n = 0

        def invoke(self, **kw):
            self.n += 1
            if self.n == 1:
                raise ProviderError("invalid_output", "Ответ не является JSON (позиция 120)")
            return {"data": {"items": ["ok"]}, "usage": {}, "model": "m", "stop_reason": "end_turn"}

    llm = LLMClient(P(), model="m", sleep=lambda s: None)
    assert llm.ask("lens_qa", "s", "u", SCHEMA) == {"items": ["ok"]}


def test_one_bad_json_per_stage_still_completes(tmp_path, monkeypatch):
    report, _, _ = _faulty_run(tmp_path, monkeypatch,
                               lambda s, k: ProviderError("invalid_output", "не JSON") if k == 1 else None)
    stages = report["run"]["stages"]
    # починка удваивает вызовы: на хвосте прогона может кончиться бюджет 16 — но рецензенты целы
    assert all(stages[s] == "ok" for s in ("segment", "lens_analyst", "lens_qa", "lens_architect", "lens_risk",
                                           "consistency")), stages


class _NeedTokens:
    """Ответ требует 1000 токенов на пункт пакета; меньше лимита — обрезка."""
    name, handles_retries = "p", False

    def __init__(self):
        self.calls: list[tuple[int, int]] = []

    def invoke(self, *, messages, max_output_tokens=None, **_):
        n = messages[-1]["content"].count(",") + 1
        self.calls.append((n, max_output_tokens))
        if n * 1000 > (max_output_tokens or 0):
            return {"data": {}, "usage": {}, "model": "m", "stop_reason": "max_tokens"}
        return {"data": {"items": ["x"] * n}, "usage": {}, "model": "m", "stop_reason": "end_turn"}


def test_split_halves_get_expanded_output_limit():
    p = _NeedTokens()
    llm = LLMClient(p, model="m", sleep=lambda s: None)
    out = llm.ask_split("lens_x", lambda it: ("s", ",".join(it)), [str(i) for i in range(40)], SCHEMA, merge_lists)
    assert len(out["items"]) == 40


def test_split_cannot_fit_raises_truncated_not_other():
    """Что уже верно: если не помогает и деление — наверх уходит ``Truncated`` (этап пометится сбоем)."""
    p = _NeedTokens()
    llm = LLMClient(p, model="m", sleep=lambda s: None)
    with pytest.raises(Truncated):
        llm.ask_split("lens_x", lambda it: ("s", ",".join(it)), [str(i) for i in range(200)], SCHEMA, merge_lists)
    assert len(p.calls) <= 4


# --------------------------------------------------------------------------- бюджет и длинные документы

def _long_doc(tmp_path: Path, times: int) -> Path:
    p = tmp_path / f"long_{times}.md"
    p.write_text(OFFICIAL.read_text(encoding="utf-8") * times, encoding="utf-8")
    return p


def test_long_document_600_lines_completes_within_budget(tmp_path, monkeypatch):
    report, _, _ = _faulty_run(tmp_path, monkeypatch, lambda s, k: None, doc=_long_doc(tmp_path, 3))
    run = report["run"]
    # статус может быть partial: записанные ответы тестировщика покрывают строки приёмки только первой копии
    assert run["status"] in ("complete", "partial")
    assert "failed" not in run["stages"].values(), run["stages"]
    assert run["calls"]["total"] <= 16
    assert not any("бюджет" in w for w in run["warnings"])


def test_long_document_leaves_budget_for_judge(tmp_path, monkeypatch):
    report, _, _ = _faulty_run(tmp_path, monkeypatch, lambda s, k: None, doc=_long_doc(tmp_path, 10))
    st = report["run"]["stage_stats"]
    assert st["judge"]["calls"] >= 1 and st["clarify"]["calls"] >= 1
    assert report["run"]["status"] == "complete"


# --------------------------------------------------------------------------- настройка провайдера

def test_gemini_without_key_gives_rules_report(tmp_path, monkeypatch):
    for k in ("GEMINI_API_KEY", "GOOGLE_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    report, _, out = _review(tmp_path, OFFICIAL, provider="gemini")
    assert out.is_file()
    assert report["run"].get("model_error")
    assert report["run"]["calls"]["total"] == 0
    assert report["run"]["status"] != "failed"


def test_anthropic_without_key_gives_rules_report(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    report, _, out = _review(tmp_path, OFFICIAL, provider="anthropic")
    assert out.is_file() and report["run"].get("model_error")
    assert report["run"]["calls"]["total"] == 0


def test_unknown_provider_name_is_explained(tmp_path):
    report, _, out = _review(tmp_path, OFFICIAL, provider="gpt-9000")
    assert out.is_file()
    assert report["run"].get("model_error") or report["run"]["warnings"]


# --------------------------------------------------------------------------- CLI

def test_cli_missing_input_file_is_code_2(tmp_path, capsys):
    from bcc_review.v2.__main__ import main
    assert main([str(tmp_path / "нет.md"), str(tmp_path / "r.md"), "--provider", "offline"]) == 2
    assert "не найден" in capsys.readouterr().err


def test_cli_output_in_new_nested_directory(tmp_path):
    from bcc_review.v2.__main__ import main
    out = tmp_path / "a" / "b" / "c" / "отчёт.md"
    code = main([str(OFFICIAL), str(out), "--provider", "mock", "--runs-dir", str(tmp_path / "runs"), "-q",
                 "--no-html"])
    assert code == 0 and out.is_file() and out.with_suffix(".json").is_file()


@pytest.mark.skipif(os.name == "nt", reason="права на запись в POSIX")
def test_cli_unwritable_output_does_not_hang(tmp_path):
    from bcc_review.v2.__main__ import main
    ro = tmp_path / "ro"
    ro.mkdir()
    ro.chmod(0o500)
    try:
        if os.access(ro, os.W_OK):
            pytest.skip("запущено с правами root: каталог только для чтения не мешает записи")
        with pytest.raises((PermissionError, OSError)):
            main([str(OFFICIAL), str(ro / "r.md"), "--provider", "offline", "--runs-dir", str(tmp_path / "runs"),
                  "-q"])
    finally:
        ro.chmod(0o700)


def test_llm_errors_have_russian_message_for_budget():
    llm = LLMClient(MockProvider(fixtures_dir=OFFICIAL_FIXTURES), model="m", max_calls=0, sleep=lambda s: None)
    with pytest.raises(LLMError) as e:
        llm.ask("judge", "s", "u", SCHEMA)
    assert "бюджет" in e.value.message


# --------------------------------------------------------------------------- враждебные (но валидные по схеме) ответы

def _mock_dir(tmp_path: Path, **stages) -> Path:
    d = tmp_path / "mock"
    d.mkdir(exist_ok=True)
    for name in ("lens_analyst", "lens_qa", "lens_architect", "lens_risk", "consistency"):
        (d / f"{name}.json").write_text(json.dumps(stages.get(name, {"candidates": []}), ensure_ascii=False),
                                        encoding="utf-8")
    for name, data in stages.items():
        (d / f"{name}.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return d


def _cand(**kw) -> dict:
    c = {"title": "Месяц операции не определён", "kind": "ambiguity", "criterion": "unambiguous", "severity": "major",
         "requirement_ids": ["R-01"], "evidence": [{"quote": "Месяц определяется по дате совершения покупки", "line": 38}],
         "problem": "Не сказано, какая дата считается датой покупки.", "scenario": "", "impact": "", "recommendation": "",
         "rewrite": "", "question": "", "blocks": "both"}
    c.update(kw)
    return c


def test_hostile_segment_ranges_are_clamped(tmp_path):
    seg = {"requirements": [
        {"source_id": "Ф-1", "kind": "functional", "summary": "a", "line_start": -5, "line_end": 10 ** 6},
        {"source_id": "Ф-2", "kind": "functional", "summary": "b", "line_start": 50, "line_end": 40},
        {"source_id": "Ф-2", "kind": "functional", "summary": "b", "line_start": 50, "line_end": 40},
        {"source_id": "", "kind": "other", "summary": "", "line_start": 0, "line_end": 0}],
        "excluded": [{"what": "", "line_start": 999999, "line_end": -1, "reason": ""}]}
    report, written, _ = _review(tmp_path, OFFICIAL, provider="mock", mock_dir=str(_mock_dir(tmp_path, segment=seg)))
    n = report["document"]["lines"]
    for r in report["requirements"]:
        assert 1 <= r["line_start"] <= r["line_end"] <= n, r
    assert len({r["id"] for r in report["requirements"]}) == len(report["requirements"])


def test_markup_in_model_text_is_escaped_in_html(tmp_path):
    bad = _cand(title="<script>alert(1)</script> | --- | ## Заголовок",
                problem="<img src=x onerror=alert(2)> </details></td></tr>")
    report, written, _ = _review(tmp_path, OFFICIAL, provider="mock", html=True,
                                 mock_dir=str(_mock_dir(tmp_path, lens_analyst={"candidates": [bad]})))
    html = Path(written["html"]).read_text(encoding="utf-8")
    assert "<script>alert(1)" not in html and "<img src=x onerror" not in html
    md = Path(written["md"]).read_text(encoding="utf-8")
    import re
    assert not re.search(r"(?<!\\)<script>", md) and not re.search(r"(?<!\\)<img src=x", md)   # только \<…


def test_empty_title_candidate_still_gives_valid_report(tmp_path):
    from bcc_review.v2 import verify
    empty = _cand(title="")
    report, written, _ = _review(tmp_path, OFFICIAL, provider="mock",
                                 mock_dir=str(_mock_dir(tmp_path, lens_analyst={"candidates": [empty]})))
    assert all(f["title"].strip() for f in report["findings"])
    res = verify.verify_report(Path(written["json"]), OFFICIAL)
    assert res["ok"], res["errors"][:3]


def test_unknown_lens_name_is_not_a_complete_run(tmp_path):
    report, _, _ = _review(tmp_path, OFFICIAL, provider="mock", lenses=["foo"])
    assert report["run"]["status"] != "complete"


# --------------------------------------------------------------------------- режим --answers

ANSWERS = ("Q-01 [месяц расходов]: Месяц расходов определяется по дате и времени совершения покупки в UTC+5.\n"
           "Q-02: B\n")


@_bug("11", "файл ответов в cp1251 (Блокнот Windows) роняет пересмотр: recheck.load_answers читает только UTF-8 "
            "(UnicodeDecodeError)")
def test_answers_file_in_cp1251_is_read(tmp_path):
    ans = tmp_path / "answers.md"
    ans.write_bytes(ANSWERS.encode("cp1251"))
    report, _, _ = _review(tmp_path, OFFICIAL, provider="mock", answers=str(ans))
    answers = (report.get("clarification") or {}).get("answers")
    assert (len(answers) if isinstance(answers, list) else int(answers or 0)) >= 1


def test_answers_mode_failure_is_reported(tmp_path, monkeypatch):
    from bcc_review.v2.stages import revise

    def boom(*a, **kw):
        raise RuntimeError("сбой пересмотра")

    monkeypatch.setattr(revise, "run_modes", boom)
    ans = tmp_path / "answers.md"
    ans.write_text(ANSWERS, encoding="utf-8")
    report, _, _ = _review(tmp_path, OFFICIAL, provider="mock", answers=str(ans))
    assert report["run"]["stages"].get("recheck") == "failed"
    assert any("--answers" in w for w in report["run"]["warnings"])


def test_missing_answers_file_is_an_error(tmp_path, capsys):
    from bcc_review.v2.__main__ import main
    out = tmp_path / "r.md"
    code = main([str(OFFICIAL), str(out), "--provider", "mock", "--answers", str(tmp_path / "нет.md"),
                 "--runs-dir", str(tmp_path / "runs"), "--no-html", "-q"])
    if code == 0:
        report = json.loads(out.with_suffix(".json").read_text(encoding="utf-8"))
        assert any("не найден" in w for w in report["run"]["warnings"])
    else:
        assert "не найден" in capsys.readouterr().err


def test_answers_utf8_file_changes_report(tmp_path):
    ans = tmp_path / "answers.md"
    ans.write_text(ANSWERS, encoding="utf-8")
    report, _, _ = _review(tmp_path, OFFICIAL, provider="mock", answers=str(ans))
    assert report.get("clarification") and report["run"]["stages"].get("recheck") == "ok"


def test_unwritable_runs_dir_still_gives_report(tmp_path):
    blocker = tmp_path / "runs_is_a_file"
    blocker.write_text("", encoding="utf-8")
    out = tmp_path / "out" / "r.md"
    report, written = pipeline.review(OFFICIAL, out, {"provider": "offline", "runs_dir": str(blocker), "html": False})
    assert out.is_file() and report["findings"]


def test_output_path_that_is_a_directory(tmp_path):
    from bcc_review.v2.__main__ import main
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    code = main([str(OFFICIAL), str(out_dir), "--provider", "offline", "--runs-dir", str(tmp_path / "runs"), "-q"])
    assert code in (0, 2)
    assert code == 2 or any(p.suffix == ".md" for p in out_dir.iterdir())


def test_same_input_gives_same_markdown(tmp_path):
    """Два прогона, в которых линзы завершаются в разном порядке (как у живой модели), дают один Markdown."""
    import re
    import threading
    import time

    from bcc_review.v2.stages import lens
    real = lens.run_named
    texts = []
    for order in (["analyst", "qa", "architect", "risk"], ["risk", "architect", "qa", "analyst"]):
        done = {n: threading.Event() for n in order}

        def chained(ctx, name, order=order, done=done):
            i = order.index(name) if name in order else -1
            if i > 0:
                done[order[i - 1]].wait(5)
                time.sleep(0.05)            # предыдущая линза успевает записать свой статус
            try:
                return real(ctx, name)
            finally:
                if name in done:
                    done[name].set()

        lens.run_named = chained
        try:
            _, written, _ = _review(tmp_path, OFFICIAL, name="det" + order[0], provider="mock")
        finally:
            lens.run_named = real
        md = Path(written["md"]).read_text(encoding="utf-8")
        texts.append(re.sub(r"\d", "0", re.sub(r"20\d{6}-\d{6}-[0-9a-f]{4}", "RUN", md)))
    assert texts[0] == texts[1]


def test_fatal_error_mid_run_sets_model_error(tmp_path, monkeypatch):
    report, _, _ = _faulty_run(tmp_path, monkeypatch,
                               lambda s, k: ProviderError("quota", "дневная квота исчерпана") if s == "lens_risk" else None)
    assert report["run"].get("model_error")
    assert report["run"]["warnings"][0] == report["run"]["model_error"]


def test_failed_early_questions_survive_slow_judge(tmp_path, monkeypatch):
    import time

    def f(stage, k):
        if stage == "judge" and k == 1:
            time.sleep(2.5)                       # судья дольше лимита этапа (2 с)
        if stage == "clarify" and k == 1:
            return ProviderError("bad_request", "ранний вызов отклонён")    # без повтора и починки
        return None

    report, _, _ = _faulty_run(tmp_path, monkeypatch, f, stage_timeout=2.0, judge_check=False)
    assert report["questions"], [w for w in report["run"]["warnings"] if "clarify" in w]


def test_transient_stage_file_write_error_does_not_abort_run(tmp_path, monkeypatch):
    from bcc_review.v2 import runs
    real = runs.RunDir.save_stage
    hit = {"n": 0}

    def flaky(self, name, record):
        if name == "segment" and not hit["n"]:
            hit["n"] = 1
            raise PermissionError(13, "файл занят другим процессом")
        return real(self, name, record)

    monkeypatch.setattr(runs.RunDir, "save_stage", flaky)
    report, _, out = _review(tmp_path, OFFICIAL, provider="mock")
    assert report["run"]["status"] != "failed" and report["findings"]


@pytest.mark.parametrize("argv", [["вход.md"], ["вход.md", "отчёт.md", "--bogus"], ["вход.md", "o.md", "--max-calls", "x"],
                                  ["--help"]])
def test_cli_messages_are_russian(argv, capsys):
    import re

    from bcc_review.v2.__main__ import main
    with pytest.raises(SystemExit):
        main(argv)
    cap = capsys.readouterr()
    text = cap.out + cap.err
    english = re.findall(r"\b(usage|positional arguments|options|show this help message|error|the following arguments"
                         r"|unrecognized arguments|invalid int value|required)\b", text)
    assert not english, english


@_bug("01", "ход выполнения в консоли — внутренние имена этапов латиницей: «segment: запуск», «lens_architect: "
            "готово за …» (pipeline.stage, self.log)")
def test_console_progress_is_russian(tmp_path, capsys):
    import re

    from bcc_review.v2.__main__ import main
    main([str(OFFICIAL), str(tmp_path / "r.md"), "--provider", "mock", "--runs-dir", str(tmp_path / "runs"),
          "--no-html"])
    err = capsys.readouterr().err
    codes = re.findall(r"\b(segment|lens_\w+|consistency|judge|clarify|quotes|rules)\b", err)
    assert not codes, sorted(set(codes))


def test_fast_start_remap_error_does_not_abort_run(tmp_path, monkeypatch):
    def boom(*a, **kw):
        raise ValueError("строка цитаты не число")

    monkeypatch.setattr(pipeline, "remap_output", boom)
    report, _, _ = _review(tmp_path, OFFICIAL, provider="mock", fast_start=True)
    assert report["run"]["status"] != "failed" and report["findings"]


@_bug("01", "быстрый старт + нет сети: нарезка и 5 рецензентов повторяют network параллельно и сжигают все 16 вызовов, "
            "не замечая, что ошибка уже признана фатальной (llm._ask_model не проверяет self.fatal перед повтором)")
def test_network_down_with_fast_start_stops_retries(tmp_path, monkeypatch):
    report, _, _ = _faulty_run(tmp_path, monkeypatch, lambda s, k: ProviderError("network", "нет соединения"),
                               fast_start=True)
    assert report["run"]["status"] == "failed"
    assert not any("исчерпан бюджет" in w for w in report["run"]["warnings"]), report["run"]["warnings"][:4]
    assert report["run"]["calls"]["total"] < 16


@_bug("06", "пустой тест-кейс модели (без названия, «когда» и «тогда», expected_defined=false) попадает в отчёт строкой "
            "«| T-01 | R-1 |  |  |  | ❔ Не определено требованиями. |»: normalize_test_case сам пишет «Не определено» в then, "
            "и фильтр «title or then» его пропускает (stages/lens_qa.py:853); ID «R-1» не существует")
def test_empty_test_cases_are_dropped(tmp_path):
    from bcc_review.v2.stages import lens_qa
    props = lens_qa.SCHEMA["properties"]
    qa = {k: [] for k in props}
    tc_props = props["test_cases"]["items"]["properties"]
    tc = {k: ([] if v.get("type") == "array" else (False if v.get("type") == "boolean" else ""))
          for k, v in tc_props.items()}
    tc["requirement_ids"] = ["R-1"]
    qa["test_cases"] = [tc, tc]
    report, _, _ = _review(tmp_path, OFFICIAL, provider="mock", mock_dir=str(_mock_dir(tmp_path, lens_qa=qa)))
    assert all(t.get("title") or t.get("when") for t in report["test_cases"]), report["test_cases"][:2]


def test_hostile_judge_answer_is_sanitized(tmp_path):
    """Враждебный, но валидный по схеме ответ судьи: дубли ключей, кандидат и в дефекте, и в отклонённых, ссылки на
    несуществующих кандидатов, приоритеты −3 и 99, critical без сценария или с blocks=none, чек-лист с n=0 и 999.
    Код должен всё поправить: каждый кандидат ровно в одном месте, verify проходит."""
    from bcc_review.v2 import verify
    from bcc_review.v2.stages import judge as J
    q = {"A": ("Месяц определяется по дате совершения покупки в Алматы", 38),
         "B": ("Возврат уменьшает расходы месяца исходной покупки", 38),
         "C": ("Февральский счётчик вырос на 4 000", 64), "D": ("По умолчанию уведомление выключено", 37)}
    lens = {"candidates": [_cand(title=k, evidence=[{"quote": v[0], "line": v[1]}],
                                 severity="critical" if k == "C" else "major") for k, v in q.items()]}
    schema = J.response_schema()["properties"]["findings"]["items"]["properties"]

    def f(key, ids, **kw):
        base = {k: ("" if v.get("type") == "string" else 0 if v.get("type") == "integer" else False
                    if v.get("type") == "boolean" else []) for k, v in schema.items()}
        if "enum" in schema.get("kind", {}):
            base["kind"] = "ambiguity"
        if "enum" in schema.get("criterion", {}):
            base["criterion"] = "unambiguous"
        base.update(key=key, candidate_ids=ids, base=ids[0] if ids else "", title="T" + key, severity="major",
                    blocks="both", priority=0)
        base.update(kw)
        return {k: v for k, v in base.items() if k in schema}

    code = J._MODEL_REJECT_CODES[0]
    judge_ans = {"findings": [f("K1", ["C-001", "C-002"], priority=1), f("K1", ["C-001"], priority=1),
                              f("K2", ["C-003"], severity="critical", priority=-3), f("K3", [], title="", priority=99),
                              f("K4", ["C-404"], severity="critical"),
                              f("K5", ["C-004"], severity="critical", scenario="s", blocks="none")],
                 "rejected": [{"candidate_id": "C-002", "reason_code": code, "reason": "ложный", "line": 38},
                              {"candidate_id": "C-777", "reason_code": code, "reason": "?", "line": -1}],
                 "checklist": [], "verdict_summary": ""}
    mock = _mock_dir(tmp_path, lens_analyst=lens, judge=judge_ans)
    report, written, _ = _review(tmp_path, OFFICIAL, provider="mock", mock_dir=str(mock), judge_check=False,
                                 clarify=False)
    warns = " ".join(report["run"]["warnings"])
    assert "C-404" in warns and "судья недоступен" not in warns, warns[:300]   # ответ судьи принят, а не запасной
    cids = [c for x in report["findings"] for c in x["candidate_ids"]]
    assert len(cids) == len(set(cids)), cids
    assert all(x["evidence"] and x["title"] for x in report["findings"])
    assert all(0 <= int(x.get("priority") or 0) <= 7 for x in report["findings"])
    crit = [x for x in report["findings"] if x["severity"] == "critical"]
    assert all(x.get("blocks") not in ("", "none") for x in crit)
    res = verify.verify_report(Path(written["json"]), OFFICIAL)
    assert res["ok"], res["errors"][:3]
