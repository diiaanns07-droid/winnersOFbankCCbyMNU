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


@_bug("01", "отчёт о нечитаемом входе нарушает contracts/v2.json: document.format = '' и sha256 = '' "
            "(pipeline.review, запасной отчёт)")
@pytest.mark.parametrize("name", ["fake.pdf", "doc.xyz"])
def test_unreadable_input_report_matches_contract(tmp_path, name):
    doc = _unreadable_inputs(tmp_path)[name]
    report, written, _ = _review(tmp_path, doc, provider="mock")
    assert not _schema_errors(json.loads(Path(written["json"]).read_text(encoding="utf-8")))


@_bug("01", "пустой документ получает вердикт «можно начинать» и тратит вызовы модели")
@pytest.mark.parametrize("name", ["empty.md", "blank.md", "empty.html"])
def test_empty_document_is_not_ready_and_costs_no_calls(tmp_path, name):
    doc = _odd_inputs(tmp_path)[name]
    report, _, _ = _review(tmp_path, doc, provider="mock")
    v = report["verdict"]
    assert v["development"] != "yes" and v["testing"] != "yes", v
    assert report["run"]["calls"]["total"] == 0
    assert any("нет текста" in w for w in report["run"]["warnings"] + report["document"].get("warnings", []))


@needs_pdf
@_bug("03", "предупреждения документа (скан, нечитаемые страницы, правки Word) не попадают в отчёт: "
            "docview.summary не переносит view.warnings")
def test_document_warnings_reach_report(tmp_path):
    report, written, out = _review(tmp_path, STRESS / "scan_page.pdf", provider="offline")
    warns = " ".join((report.get("document") or {}).get("warnings") or []) + " ".join(report["run"]["warnings"])
    assert "Страница 2" in warns and "скан" in warns
    assert "скан" in out.read_text(encoding="utf-8")


@_bug("01", "отчёт затирает исходный файл: вход tz.html и отчёт tz.md → tz.html перезаписан HTML-отчётом")
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


@_bug("01", "нет сети: первая строка предупреждений — «выполнен частично / исчерпан бюджет», а не «нет соединения»; "
            "повторы network съедают бюджет вызовов следующих этапов (run.model_error пуст)")
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


@_bug("01", "невалидный JSON от провайдера (ProviderError invalid_output: Gemini not_json/schema_mismatch, "
            "claude -p без JSON) не получает попытки починки — этап сразу падает")
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


@_bug("01", "invalid_output на одном вызове каждого этапа роняет весь прогон в failed")
def test_one_bad_json_per_stage_still_completes(tmp_path, monkeypatch):
    report, _, _ = _faulty_run(tmp_path, monkeypatch,
                               lambda s, k: ProviderError("invalid_output", "не JSON") if k == 1 else None)
    assert report["run"]["status"] == "complete", report["run"]["warnings"][:3]


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


@_bug("01", "ask_split: после неудачи с лимитом 32 000 половины пакета просят с 16 000 и без расширения — "
            "деление пакета, которому нужно > 32 000, гарантированно падает (llm.py, ask_split)")
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
    assert report["run"]["status"] == "complete"
    assert report["run"]["calls"]["total"] <= 16


@_bug("04", "длинный документ (≈ 2000 строк, 60 страниц): нарезка тратит 11 из 16 вызовов, судье и вопросам "
            "бюджета не остаётся — реестр без отсева, прогон partial (segment.plan_chunks + общий --max-calls)")
def test_long_document_leaves_budget_for_judge(tmp_path, monkeypatch):
    report, _, _ = _faulty_run(tmp_path, monkeypatch, lambda s, k: None, doc=_long_doc(tmp_path, 10))
    st = report["run"]["stage_stats"]
    assert st["judge"]["calls"] >= 1 and st["clarify"]["calls"] >= 1
    assert report["run"]["status"] == "complete"


# --------------------------------------------------------------------------- настройка провайдера

@_bug("02", "Gemini без ключа: провайдер создаётся, ключ проверяется только при вызове — вместо отчёта правилами "
            "с объяснением (как у anthropic) прогон идёт до failed (GeminiProvider.__init__)")
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
        {"source_id": "Ф-1", "kind": "functional", "summary": "a", "line_start": -5, "line_end": 10 ** 9},
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


@_bug("10", "кандидат с пустым заголовком даёт дефект с пустым title: отчёт не проходит contracts/v2.json и verify "
            "(stages/judge.py:983 — запасного заголовка нет; так же code_only_response:1251)")
def test_empty_title_candidate_still_gives_valid_report(tmp_path):
    from bcc_review.v2 import verify
    empty = _cand(title="")
    report, written, _ = _review(tmp_path, OFFICIAL, provider="mock",
                                 mock_dir=str(_mock_dir(tmp_path, lens_analyst={"candidates": [empty]})))
    assert all(f["title"].strip() for f in report["findings"])
    res = verify.verify_report(Path(written["json"]), OFFICIAL)
    assert res["ok"], res["errors"][:3]


@_bug("01", "неизвестное имя линзы (--lenses foo, опечатка) даёт «Прогон завершён полностью» без единой линзы "
            "(__main__.py:61 не проверяет имена, стадия lens_foo — ok)")
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
    assert report.get("clarification") and report["clarification"]["answers"] >= 1


@_bug("01", "сбой режима --answers/--revise теряется: предупреждение и статус recheck=failed пишутся в self.*, "
            "а report.run уже собран (pipeline.py:495–498; успешная ветка обновляет run в 512–518)")
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


@_bug("01", "несуществующий файл ответов (--answers опечатка.md) молча считается «ответов 0»: код 0, без предупреждения")
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


@_bug("01", "каталог прогонов нельзя создать (запуск из каталога только для чтения, Docker под обычным "
            "пользователем) — трейсбэк вместо отчёта: RunDir создаётся в Pipeline.__init__ вне try (pipeline.py:174)")
def test_unwritable_runs_dir_still_gives_report(tmp_path):
    blocker = tmp_path / "runs_is_a_file"
    blocker.write_text("", encoding="utf-8")
    out = tmp_path / "out" / "r.md"
    report, written = pipeline.review(OFFICIAL, out, {"provider": "offline", "runs_dir": str(blocker), "html": False})
    assert out.is_file() and report["findings"]


@_bug("01", "путь отчёта — существующая папка (python -m bcc_review тз.md out/) → трейсбэк IsADirectoryError "
            "(pipeline.write_outputs:639 пишет .md прямо в путь каталога)")
def test_output_path_that_is_a_directory(tmp_path):
    from bcc_review.v2.__main__ import main
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    code = main([str(OFFICIAL), str(out_dir), "--provider", "offline", "--runs-dir", str(tmp_path / "runs"), "-q"])
    assert code in (0, 2)
    assert code == 2 or any(p.suffix == ".md" for p in out_dir.iterdir())
