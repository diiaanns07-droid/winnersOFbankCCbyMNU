"""№22 — ядро v2.1: сбой этапа без ложного вердикта, --replay, --runs N, --max-cost, --interactive."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from bcc_review.v2 import pipeline

ROOT = Path(__file__).resolve().parents[2]
OFFICIAL = ROOT / "release" / "input" / "requirements.md"


def _run(tmp_path, name="r", **opts):
    out = tmp_path / "out" / f"{name}.md"
    o = {"provider": "mock", "runs_dir": str(tmp_path / "runs"), "html": False, **opts}
    report, written = pipeline.review(OFFICIAL, out, o)
    return report, written, out


def _verify(written) -> int:
    from bcc_review.v2 import verify
    return verify.main([written["json"], str(OFFICIAL)])


# --------------------------------------------------------------------------- 5. сбой этапа → «не определено»

def test_verdict_rule_incomplete_keeps_no_and_hides_yes():
    crit = {"severity": "critical", "blocks": "development"}
    assert pipeline.verdict_rule([crit], "partial", ["judge"]) == {"development": "no", "testing": "undetermined"}
    assert pipeline.verdict_rule([], "partial", ["lens_risk"]) == {"development": "undetermined",
                                                                  "testing": "undetermined"}
    majors = [{"severity": "major", "blocks": "both"}] * 3
    assert pipeline.verdict_rule(majors, "partial", ["consistency"])["testing"] == "undetermined"
    assert pipeline.verdict_rule([], "partial") == {"development": "conditional", "testing": "conditional"}


def _no_blockers(monkeypatch):
    """Судья без блокеров: иначе вердикт «нельзя» и проверка «не определено» ничего не покажет."""
    from bcc_review.v2.stages import judge
    real = judge.run

    def soft(ctx, cands):
        out = real(ctx, cands)
        for f in out.get("findings") or []:
            f["severity"], f["blocks"] = "minor", "none"
        return out
    monkeypatch.setattr(judge, "run", soft)


def test_failed_lens_gives_undetermined_not_yes(tmp_path, monkeypatch):
    from bcc_review.v2.stages import lens
    _no_blockers(monkeypatch)
    real = lens.run_named

    def boom(ctx, name):
        if name == "risk":
            raise RuntimeError("линза упала")
        return real(ctx, name)
    monkeypatch.setattr(lens, "run_named", boom)
    report, written, _ = _run(tmp_path)
    assert report["run"]["stages"]["lens_risk"] == "failed"
    assert report["run"]["incomplete_stages"] == ["lens_risk"]
    assert report["verdict"]["development"] == "undetermined"
    assert report["verdict"]["testing"] == "undetermined"
    assert any("«Риски»" in w for w in report["run"]["warnings"])
    md = Path(written["md"]).read_text(encoding="utf-8")
    assert "не определено" in md
    assert _verify(written) == 0


def test_failed_judge_gives_undetermined(tmp_path, monkeypatch):
    from bcc_review.v2.stages import judge

    def boom(ctx, cands):
        raise RuntimeError("судья упал")
    monkeypatch.setattr(judge, "run", boom)
    report, written, _ = _run(tmp_path)
    assert report["run"]["stages"]["judge"] == "failed"
    for k in ("development", "testing"):
        assert report["verdict"][k] in ("no", "undetermined")
    assert _verify(written) == 0


def test_complete_run_has_no_incomplete_marker(tmp_path):
    report, _, _ = _run(tmp_path)
    assert "incomplete_stages" not in report["run"]


# --------------------------------------------------------------------------- 1. --replay

def _strip(report: dict) -> dict:
    keep = ("findings", "rejected", "questions", "requirements", "checklist")
    return {k: report.get(k) for k in keep} | {"verdict": {k: report["verdict"].get(k)
                                                           for k in ("development", "testing")}}


def test_replay_rebuilds_same_report_without_calls(tmp_path):
    report, written, _ = _run(tmp_path, name="orig")
    src = tmp_path / "runs" / report["run"]["run_id"]
    rep2, w2, _ = _run(tmp_path, name="replay", provider="gemini", replay=str(src))  # провайдер не нужен
    assert rep2["run"]["calls"]["total"] == 0
    assert rep2["run"]["replay"]["run_id"] == report["run"]["run_id"]
    assert rep2["run"]["replay"]["calls_live"] == 0
    assert rep2["run"]["provider"] == report["run"]["provider"]
    assert rep2["run"]["models_used"] == report["run"]["models_used"]
    assert _strip(rep2) == _strip(report)
    assert rep2["run"]["status"] == report["run"]["status"]
    assert _verify(w2) == 0
    # повтор повтора: ответы этапов скопированы в новый прогон
    rep3, _, _ = _run(tmp_path, name="replay2", replay=str(tmp_path / "runs" / rep2["run"]["run_id"]))
    assert _strip(rep3) == _strip(report)


def test_replay_missing_response_fails_stage_honestly(tmp_path):
    report, _, _ = _run(tmp_path, name="orig")
    src = tmp_path / "runs" / report["run"]["run_id"]
    (src / "stages" / "lens_risk.json").unlink()
    for p in (src / "responses").glob("lens_risk*.json"):
        p.unlink()
    rep2, _, _ = _run(tmp_path, name="replay", replay=str(src))
    assert rep2["run"]["stages"]["lens_risk"] == "failed"
    assert rep2["run"]["calls"]["total"] >= 0 and rep2["run"]["replay"]["calls_live"] == 0
    assert "lens_risk" in rep2["run"]["incomplete_stages"]
    assert "yes" not in (rep2["verdict"]["development"], rep2["verdict"]["testing"])


def test_replay_cli_requires_stage_dir(tmp_path, capsys):
    from bcc_review.v2.__main__ import main
    code = main([str(OFFICIAL), str(tmp_path / "r.md"), "--replay", str(tmp_path / "nope")])
    assert code == 2
    assert "Нет сохранённых этапов" in capsys.readouterr().err


def test_replay_cli_end_to_end(tmp_path):
    from bcc_review.v2.__main__ import main
    report, _, _ = _run(tmp_path, name="orig")
    src = tmp_path / "runs" / report["run"]["run_id"]
    code = main([str(OFFICIAL), str(tmp_path / "r.md"), "--replay", str(src), "-q", "--no-html",
                 "--runs-dir", str(tmp_path / "runs")])
    assert code == 0
    data = json.loads((tmp_path / "r.json").read_text(encoding="utf-8"))
    assert data["run"]["replay"]["run_id"] == report["run"]["run_id"]


# --------------------------------------------------------------------------- 2. --runs N

def test_runs_three_mock_all_stable(tmp_path):
    report, written, _ = _run(tmp_path, runs=3)
    st = report["stability"]
    assert st["runs_counted"] == 3 and st["threshold"] == 2
    assert report["findings"] and all(f["stability"]["k"] == 3 for f in report["findings"])
    assert report["findings_unstable"] == []
    assert st["calls_total"] > report["stability"]["passes"][0]["calls"]
    assert _verify(written) == 0
    md = Path(written["md"]).read_text(encoding="utf-8")
    assert "Устойчивость: независимые проходы" in md and "3 из 3" in md


def test_runs_unstable_goes_to_appendix(tmp_path, monkeypatch):
    """Проход 2 и 3 не находят часть дефектов первого и находят один свой — он идёт в реестр, если в 2 из 3."""
    from bcc_review.v2.stages import judge
    real = judge.run
    calls = {"n": 0}

    def flaky(ctx, cands):
        calls["n"] += 1
        out = real(ctx, cands)
        fs = out.get("findings") or []
        if calls["n"] > 1 and fs:
            out["findings"] = fs[1:]  # первый дефект первого прохода больше не находится
        return out
    monkeypatch.setattr(judge, "run", flaky)
    report, written, _ = _run(tmp_path, runs=3)
    unstable = report["findings_unstable"]
    assert len(unstable) == 1 and unstable[0]["stability"] == {"k": 1, "n": 3, "passes": [1]}
    gone = unstable[0]["id"]
    assert gone not in [f["id"] for f in report["findings"]]
    for q in report.get("questions") or []:
        assert gone not in q.get("finding_ids", [])
    assert gone not in report["verdict"].get("fix_first", [])
    assert _verify(written) == 0
    assert "Неустойчивые замечания" in Path(written["md"]).read_text(encoding="utf-8")


def test_stability_group_matches_by_lines_and_kind():
    from bcc_review.v2 import stability
    a = {"id": "D-01", "kind": "ambiguity", "evidence": [{"line_start": 10, "line_end": 10}], "title": "x"}
    b = {"id": "D-07", "kind": "ambiguity", "evidence": [{"line_start": 10, "line_end": 11}], "title": "y"}
    c = {"id": "D-02", "kind": "missing", "evidence": [{"line_start": 50}], "title": "z"}
    cl = stability.group([[a, c], [b], [dict(c)]])
    assert [sorted(x["hits"]) for x in cl] == [[0, 1], [0, 2]]
    assert stability.similarity(a, c) == 0


def test_failed_pass_not_counted():
    from bcc_review.v2 import stability
    f = {"id": "D-01", "kind": "k", "evidence": [{"line_start": 3}], "title": "t"}
    base = {"run": {"status": "complete"}, "findings": [f], "requirements": [], "verdict": {}}
    bad = {"run": {"status": "failed"}, "findings": []}
    rep = stability.merge(base, [bad, {"run": {"status": "complete"}, "findings": [dict(f)]}], 3)
    assert rep["stability"]["runs_counted"] == 2
    assert rep["findings"][0]["stability"]["k"] == 2
    assert any("не удались" in w for w in rep["run"]["warnings"])


def test_runs_cli_rejects_with_answers(tmp_path, capsys):
    from bcc_review.v2.__main__ import main
    ans = tmp_path / "a.md"
    ans.write_text("Q-01: A\n", encoding="utf-8")
    assert main([str(OFFICIAL), str(tmp_path / "r.md"), "--runs", "2", "--answers", str(ans)]) == 2


# --------------------------------------------------------------------------- 3. --max-cost

def test_parse_cost():
    from bcc_review.v2.__main__ import parse_cost
    assert parse_cost("0.5") == {"max_cost_usd": 0.5}
    assert parse_cost("$1,5") == {"max_cost_usd": 1.5}
    assert parse_cost("200k") == {"max_tokens": 200000}
    assert parse_cost("1.5m") == {"max_tokens": 1500000}
    assert parse_cost("300000т") == {"max_tokens": 300000}
    assert parse_cost(None) == {}
    with pytest.raises(ValueError):
        parse_cost("дорого")


def test_estimate_cost():
    from bcc_review.v2.llm import estimate_cost
    assert estimate_cost("claude-sonnet-5-5", 1_000_000, 0) == 3.0
    assert estimate_cost("gemini-3-flash-lite", 0, 1_000_000) == 0.4
    assert estimate_cost("неизвестная", 10, 10) is None


def test_max_tokens_ceiling_gives_honest_partial(tmp_path):
    # mock считает входные токены (длина запроса / 4): потолок 1 токен — после первого вызова дальше не идём
    report, written, _ = _run(tmp_path, max_tokens=1, fast_start=False)
    run = report["run"]
    assert run["cost_limit"]["hit"] is True and run["cost_limit"]["max_tokens"] == 1
    assert run["status"] == "partial"
    assert "yes" not in (report["verdict"]["development"], report["verdict"]["testing"])
    assert "conditional" not in (report["verdict"]["development"], report["verdict"]["testing"])
    assert any("--max-cost" in w for w in run["warnings"])
    assert run["calls"]["total"] == 1
    assert _verify(written) == 0


def test_cost_ceiling_not_hit_is_recorded(tmp_path):
    report, _, _ = _run(tmp_path, max_cost_usd=5.0)
    assert report["run"]["cost_limit"] == {"max_cost_usd": 5.0, "max_tokens": None, "spent_usd": 0.0,
                                           "spent_tokens": report["run"]["cost_limit"]["spent_tokens"],
                                           "hit": False}
    assert report["run"]["status"] == "complete"


def test_max_cost_cli_bad_value(tmp_path, capsys):
    from bcc_review.v2.__main__ import main
    assert main([str(OFFICIAL), str(tmp_path / "r.md"), "--max-cost", "много"]) == 2
    assert "--max-cost" in capsys.readouterr().err


# --------------------------------------------------------------------------- 4. --interactive

QS = [{"id": "Q-01", "topic": "Метод", "question": "Каким методом?", "options": ["POST", "PUT", "GET"],
       "to": "Архитектор", "blocking": True},
      {"id": "Q-02", "topic": "Срок", "question": "Сколько хранить?", "options": ["30 дней", "90 дней"]},
      {"id": "Q-03", "topic": "", "question": "Кто владелец?", "options": []},
      {"id": "Q-04", "topic": "Лишний", "question": "?", "options": ["да", "нет"]}]


def _feed(*answers):
    it = iter(answers)

    def inp(_prompt=""):
        try:
            return next(it)
        except StopIteration:
            raise EOFError from None
    return inp


def test_ask_questions_letters_text_skip_and_eof():
    from bcc_review.v2.__main__ import ask_questions
    shown: list[str] = []
    lines = ask_questions(QS, input_fn=_feed("б", "", "  команда   платежей "), print_fn=shown.append)
    assert lines == ["Q-01 [Метод]: B — PUT", "Q-03: команда платежей"]
    assert any("A) POST" in x for x in shown) and any("Ввод закончен" in x for x in shown)
    assert ask_questions(QS[:2], input_fn=_feed("2", "a"), print_fn=lambda *_: None) == [
        "Q-01 [Метод]: B — PUT", "Q-02 [Срок]: A — 30 дней"]


def test_interactive_lines_parse_as_answers():
    from bcc_review.v2.__main__ import ask_questions
    from bcc_review.v2.stages import recheck
    lines = ask_questions(QS, input_fn=_feed("C", "свой срок 60 дней"), print_fn=lambda *_: None)
    parsed = recheck.parse_answers_text("\n".join(lines))
    got = {x["id"]: (x["choice"], x["text"]) for x in parsed["answers"]}
    assert got["Q-01"][0] is not None and got["Q-02"] == (None, "свой срок 60 дней")


def test_interactive_cli_writes_answers_and_rechecks(tmp_path, monkeypatch, capsys):
    import builtins
    from bcc_review.v2.__main__ import main
    monkeypatch.setattr(builtins, "input", _feed("A", "", "B"))
    out = tmp_path / "r.md"
    code = main([str(OFFICIAL), str(out), "--provider", "mock", "--interactive", "-q", "--no-html",
                 "--runs-dir", str(tmp_path / "runs")])
    assert code == 0
    answers = tmp_path / "r.answers.md"
    assert answers.is_file()
    text = answers.read_text(encoding="utf-8")
    assert text.startswith("# Ответы владельца") and "Q-01" in text and "SHA-256" in text
    data = json.loads((tmp_path / "r.json").read_text(encoding="utf-8"))
    assert data.get("clarification"), "пересмотр по ответам не выполнен"
    assert data["run"]["options"]["answers"] is True
    assert all(st.get("reused") for k, st in data["run"]["stage_stats"].items()
               if k in ("segment", "lens_qa", "judge"))
    assert "Пересмотр дефектов" in capsys.readouterr().out


def test_interactive_no_answers_keeps_report(tmp_path, monkeypatch):
    import builtins
    from bcc_review.v2.__main__ import main
    monkeypatch.setattr(builtins, "input", _feed())
    out = tmp_path / "r.md"
    assert main([str(OFFICIAL), str(out), "--provider", "mock", "--interactive", "-q", "--no-html",
                 "--runs-dir", str(tmp_path / "runs")]) == 0
    assert not (tmp_path / "r.answers.md").exists()
    assert not json.loads((tmp_path / "r.json").read_text(encoding="utf-8")).get("clarification")


def test_runs_cost_limit_counts_all_passes(tmp_path):
    report, _, _ = _run(tmp_path, runs=2, max_tokens=10**9)
    lim = report["run"]["cost_limit"]
    assert lim["spent_tokens"] == sum(report["stability"]["tokens_total"].values())
    assert lim["hit"] is False


# --------------------------------------------------------------------------- самопроверка 17:20

def test_cyrillic_letters_match_answers_parser():
    """В консоли и в файле ответов кириллица читается одинаково: похожие А, В, С — A, B, C; Б — B; Г — D."""
    from bcc_review.v2.__main__ import ask_questions
    from bcc_review.v2.stages import recheck
    qs = [{"id": f"Q-0{i}", "topic": "", "question": "?", "options": ["a", "b", "c", "d"]} for i in range(1, 6)]
    lines = ask_questions(qs, input_fn=_feed("А", "В", "С", "Б", "Г"), print_fn=lambda *_: None)
    assert [x.split(": ")[1][0] for x in lines] == ["A", "B", "C", "B", "D"]
    for ru in "АВСБГ":
        parsed = recheck.parse_answers_text(f"Q-01: {ru}")["answers"][0]
        line = ask_questions(qs[:1], input_fn=_feed(ru), print_fn=lambda *_: None)[0]
        assert "ABCD".index(line.split(": ")[1][0]) == parsed["choice"], ru


def test_interactive_revise_without_answers_still_revises(tmp_path, monkeypatch):
    import builtins
    from bcc_review.v2.__main__ import main
    monkeypatch.setattr(builtins, "input", _feed())
    out = tmp_path / "r.md"
    assert main([str(OFFICIAL), str(out), "--provider", "mock", "--interactive", "--revise", "-q", "--no-html",
                 "--runs-dir", str(tmp_path / "runs")]) == 0
    data = json.loads((tmp_path / "r.json").read_text(encoding="utf-8"))
    assert data["run"]["options"]["revise"] is True and data.get("revise_stats") is not None
    assert not data.get("clarification")


def test_replay_parallel_calls_get_distinct_records(tmp_path):
    """Два параллельных вызова одного этапа (деление пакета) берут ответы 1 и 2, а не оба первый."""
    import threading
    from bcc_review.v2.providers.mock import ReplayProvider
    (tmp_path / "lens_qa.json").write_text(json.dumps([{"n": 1}, {"n": 2}]), encoding="utf-8")
    prov = ReplayProvider(fixtures_dir=tmp_path)
    schema = {"type": "object", "properties": {"n": {"type": "integer"}}, "required": ["n"]}
    got, errs = [], []

    def call():
        try:
            got.append(prov.invoke(model=None, messages=[{"role": "user", "content": "x"}], schema=schema,
                                   stage="lens_qa")["data"]["n"])
        except Exception as exc:  # noqa: BLE001
            errs.append(exc)
    ts = [threading.Thread(target=call) for _ in range(3)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert sorted(got) == [1, 2] and len(errs) == 1 and getattr(errs[0], "kind", "") == "bad_request"


def test_runs_unstable_refs_dropped_everywhere():
    from bcc_review.v2 import stability
    f1 = {"id": "D-01", "kind": "k", "evidence": [{"line_start": 3}], "title": "t"}
    f2 = {"id": "D-02", "kind": "m", "evidence": [{"line_start": 9}], "title": "u"}
    base = {"run": {"status": "complete"}, "findings": [f1, f2], "requirements": [], "verdict": {"fix_first": ["D-02"]},
            "acceptance_checks": [{"finding_ids": ["D-01", "D-02"]}], "pair_checks": [{"finding_id": "D-02"}],
            "questions": [{"id": "Q-01", "finding_ids": ["D-02"]}]}
    other = {"run": {"status": "complete"}, "findings": [dict(f1)]}
    rep = stability.merge(base, [other, {"run": {"status": "complete"}, "findings": [dict(f1)]}], 3)
    assert [f["id"] for f in rep["findings"]] == ["D-01"] and rep["findings_unstable"][0]["id"] == "D-02"
    assert rep["acceptance_checks"][0]["finding_ids"] == ["D-01"]
    assert rep["pair_checks"][0]["finding_id"] == ""
    assert rep["questions"][0]["finding_ids"] == [] and rep["verdict"]["fix_first"] == []


def test_salvaged_whole_items_when_split_impossible():
    """Патч №24 (``22_llm_salvage.patch``): ответ обрезан, делить пакет нечего — целые элементы из ``partial``
    провайдера вместо потерянного этапа; без ``partial`` — по-прежнему ``Truncated``."""
    import pytest
    from bcc_review.contracts import ProviderError
    from bcc_review.v2.llm import LLMClient, Truncated
    schema = {"type": "object", "additionalProperties": False, "required": ["candidates"],
              "properties": {"candidates": {"type": "array", "items": {"type": "string"}}}}

    class Cut:
        name, handles_retries = "gemini", True

        def __init__(self, partial):
            self.partial = partial

        def invoke(self, **kw):
            exc = ProviderError("truncated", "ответ обрезан по лимиту выходных токенов")
            if self.partial is not None:
                exc.partial = self.partial
            raise exc

    def run(partial):
        llm = LLMClient(Cut(partial), model="m", provider_name="gemini", sleep=lambda s: None)
        return llm, llm.ask_split("lens_analyst", lambda items: ("система", "запрос"), ["x"], schema,
                                  merge=lambda parts: parts[0])

    llm, out = run({"candidates": ["a", "b"]})
    assert out == {"candidates": ["a", "b"]}
    assert llm.stats["salvaged"] == 1 and llm.stats["by_stage"]["lens_analyst"]["salvaged"] == 1
    with pytest.raises(Truncated):
        run(None)
    with pytest.raises(Truncated):
        run({"candidates": "не массив"})  # целые элементы не проходят схему — не берём


def test_runs_passes_on_different_models_warned_and_shown():
    """Просьба №24: на бесплатном ключе Gemini проходы ``--runs N`` идут на разных моделях (суточная квота) —
    модель каждого прохода в таблице, предупреждение в отчёте; статусы проходов — по-русски."""
    from bcc_review.v2 import stability
    f = {"id": "D-01", "kind": "k", "evidence": [{"line_start": 3}], "title": "t"}
    base = {"run": {"status": "complete", "models_used": ["gemini-3.8-flash"]}, "findings": [f], "requirements": [],
            "verdict": {}}
    same = {"run": {"status": "partial", "models_used": ["gemini-3.8-flash"]}, "findings": [dict(f)]}
    other = {"run": {"status": "complete", "models_used": ["gemini-3.7-flash"]}, "findings": [dict(f)]}
    rep = stability.merge(base, [same, other], 3)
    assert [p["models_used"] for p in rep["stability"]["passes"]] == [["gemini-3.8-flash"]] * 2 + [["gemini-3.7-flash"]]
    assert any("разных моделях" in w and "3: gemini-3.7-flash" in w for w in rep["run"]["warnings"])
    md = stability.markdown(rep)
    assert "| 2 | частично | gemini-3.8-flash | 1 |" in md and "complete" not in md and "partial" not in md
    fresh = {"run": {"status": "complete", "models_used": ["gemini-3.8-flash"]}, "findings": [dict(f)],
             "requirements": [], "verdict": {}}
    one = stability.merge(fresh, [same], 2)
    assert not any("разных моделях" in w for w in one["run"].get("warnings") or [])
