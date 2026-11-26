"""Стык с движком bcc/integration: run_review → read_docx (№03) → … → resolve_hint (№07) → write_docx (№03).

Транспорт -- провайдер ``mock`` со сценарием ниже (без сети и ключей). Слоты
``review_individual`` и ``review_set`` переключены на резерв движка
(``BCC_FORCE_FALLBACK``), чтобы сценарий не зависел от схем №05/№06; чтение,
инвентарь (№04), привязка цитат (№07) и экспорт DOCX (№03) -- командные модули.
Пока в ветке нет ``bcc_review.engine`` (до слияния с bcc/integration), тест пропускается.
"""

from __future__ import annotations

import hashlib
import json

import pytest

engine = pytest.importorskip("bcc_review.engine", reason="движок bcc/integration ещё не влит в эту ветку")

import p03_ooxml as ox  # noqa: E402
from p03_fixtures import TWIN, twin_phrase_doc  # noqa: E402

from bcc_review.contracts import RunOptions  # noqa: E402
from bcc_review.readers.docx import locate, read_docx  # noqa: E402

CAUSE = {"object": "порог уведомления", "condition": "ввод суммы", "outcomes": ["тенге", "неизвестно"]}


def mock_script(doc):
    para = next(b.id for b in doc.blocks if b.kind == "paragraph" and TWIN in b.text)
    row = next(b.id for b in doc.blocks if b.kind == "table_row" and TWIN in b.text)
    header = next(b.id for b in doc.blocks if b.kind == "table_header")
    tail = [b.id for b in doc.blocks if b.text == "Конец раздела."]
    return row, para, {
        "inventory": {
            "items": [
                {"source_id": None, "kind": "functional", "text": f"Клиент задаёт {TWIN} включительно",
                 "evidence": [{"block_id": para, "quote": TWIN}]},
                {"source_id": None, "kind": "contract", "text": f"amount: {TWIN} включительно",
                 "evidence": [{"block_id": row, "quote": TWIN}]}],
            "excluded": [{"category": "structure", "reason": "шапка таблицы", "block_ids": [header]},
                         {"category": "fragment", "reason": "служебная строка", "block_ids": tail}],
            "facts": [], "done": True},
        "individual": {"requirements": []},
        "cross": {
            "conflicts": [{
                "title": "Порог задан дважды: в тексте Ф-1 и в таблице API", "severity": "major",
                "criterion": "set_consistent", "impact": "При изменении границы одну из копий забудут поправить.",
                "blocked_decision": "Какую запись считать источником истины", "recommendation": "Сослаться на Ф-1.",
                "req_ids": ["R-001", "R-002"], "input": "верхняя граница меняется на 2 000 000 ₸",
                "outcome_a": "абзац обновлён", "outcome_b": "таблица со старой границей",
                "quote_a": {"block_id": para, "quote": TWIN}, "quote_b": {"block_id": row, "quote": TWIN},
                "cause": CAUSE}],
            "issues": [{
                "kind": "ambiguity", "criterion": "unambiguous", "severity": "major",
                "title": "В таблице API граница порога без валюты", "impact": "Сумму могут принять в тиынах.",
                "blocked_decision": "Единица поля amount", "recommendation": "Указать «целое число тенге».",
                "quotes": [{"block_id": row, "quote": TWIN}], "cause": CAUSE, "req_ids": ["R-002"],
                "inspected_block_ids": []}],
            "coverage": [], "facts": []},
        "verify_meaning": {"__verdicts__": "confirmed"},
    }


def test_engine_export_puts_each_comment_on_its_own_copy(tmp_path, monkeypatch):
    for var in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "GEMINI_API_KEY", "GOOGLE_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("BCC_FORCE_FALLBACK", "review_individual,review_set")
    monkeypatch.setattr(engine, "load_dotenv", lambda *a, **k: None)
    src = twin_phrase_doc(tmp_path / "twin.docx")
    row, para, script = mock_script(read_docx(src))
    (tmp_path / "mock.json").write_text(json.dumps(script, ensure_ascii=False), encoding="utf-8")
    opts = RunOptions.coerce({"provider": "mock", "mock_script": str(tmp_path / "mock.json"), "exports": ["docx"],
                              "cache_dir": str(tmp_path / "cache"), "use_cache": False,
                              "artifacts_dir": str(tmp_path / "artifacts")})
    engine.run_review(src, tmp_path / "report.md", options=opts)
    rep = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))

    mods = rep["run"]["modules"]
    assert mods["read_docx"].startswith("team:bcc_review.readers.docx")
    assert mods["resolve_candidate"].startswith("team:") and mods["provider"].endswith("MockAdapter")
    out = tmp_path / "report.annotated.docx"
    assert rep.get("exports", {}).get("docx") == str(out) and out.exists()
    assert hashlib.sha256(src.read_bytes()).hexdigest() == rep["document"]["id"]

    evs = [(f["id"], ev) for f in rep["findings"] for ev in f["evidence"]]
    assert {ev["block_id"] for _, ev in evs} == {para, row}, "сценарий mock не дал опор на обе копии"
    blocks = {b["id"]: b for b in rep["document"]["blocks"]}
    doc_out = read_docx(out)
    new = {cid: text for cid, (_, text) in ox.comments(out).items() if cid not in ox.comments(src)}
    root = ox.part(out)
    for fid, ev in evs:
        mine = [cid for cid, text in new.items() if text.startswith(f"[{fid}]")
                and ox.block_span(out, cid, doc_out)[:3] == (ev["block_id"], ev["start"], ev["end"])]
        assert len(mine) == 1, (fid, ev)
        place = locate(blocks[ev["block_id"]], ev["start"], ev["end"])
        mk = ox.marker(root, mine[0], "start")
        node = ox.ancestor(mk, "tc") if place["anchor"] == "cell" else ox.ancestor(mk, "p")
        assert ox.full_path(node) == place["path"]
        assert ox.covered_text(out, mine[0]) == ev["quote"] == TWIN
    summary = [cid for cid, text in new.items() if text.startswith("Сводка ревью")]
    assert len(summary) == 1 and ox.covered_text(out, summary[0]) == ""
    assert ox.comments(out)[0] == ox.comments(src)[0] and ox.hyperlinks(out) == ox.hyperlinks(src)


# ------------------------------------------------- сумма в тексте и две такие же в таблице


def _engine_env(monkeypatch, force_fallback: str | None):
    for var in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "GEMINI_API_KEY", "GOOGLE_API_KEY", "BCC_FORCE_FALLBACK"):
        monkeypatch.delenv(var, raising=False)
    if force_fallback:
        monkeypatch.setenv("BCC_FORCE_FALLBACK", force_fallback)
    monkeypatch.setattr(engine, "load_dotenv", lambda *a, **k: None)


def _check_engine_docx(src, outdir):
    """Каждая опора отчёта -- ровно один комментарий своего замечания на том же диапазоне."""
    rep = json.loads((outdir / "report.json").read_text(encoding="utf-8"))
    out = outdir / "report.annotated.docx"
    assert rep.get("exports", {}).get("docx") == str(out)
    assert hashlib.sha256(src.read_bytes()).hexdigest() == rep["document"]["id"]
    before = ox.comments(src)
    new = sorted(set(ox.comments(out)) - set(before))
    rmap = ox.range_map(out, new, read_docx(out))
    blocks = {b["id"]: b for b in rep["document"]["blocks"]}
    placed = {}
    for f in rep["findings"]:
        for ev in f["evidence"]:
            hits = [cid for cid, r in rmap.items() if r["head"].startswith(f"[{f['id']}]")
                    and (r["block_id"], r["start"], r["end"]) == (ev["block_id"], ev["start"], ev["end"])]
            assert len(hits) == 1, (f["id"], ev, hits)
            r = rmap[hits[0]]
            assert r["start_node"] == r["end_node"] == locate(blocks[ev["block_id"]], ev["start"], ev["end"])["path"]
            assert r["covered"] == ev["quote"]
            placed[(f["id"], r["start_node"])] = r
    for uid, value in before.items():  # комментарий пользователя цел
        assert ox.comments(out)[uid] == value
    out_doc = read_docx(out)
    assert [b.loc["list"]["label"] for b in out_doc.blocks if b.kind == "list_item"] == ["1.", "2.", "3."]
    assert out_doc.blocks[0].text == "3. Уведомление о расходах" and out_doc.blocks[0].loc["style"] == "Heading 1"
    return rep, out, rmap, placed


@pytest.mark.parametrize("user_comment", [False, True], ids=["clean", "with_user_comment"])
def test_engine_offline_lint_amounts_real_rules(tmp_path, monkeypatch, user_comment):
    """Без модели: детерминированные правила движка → опоры №07 → write_docx → повторное открытие."""
    from p03_fixtures import amounts_doc

    _engine_env(monkeypatch, None)
    src = amounts_doc(tmp_path / "amounts.docx", user_comment=user_comment)
    opts = RunOptions.coerce({"offline_lint": True, "exports": ["docx"], "cache_dir": str(tmp_path / "cache"),
                              "use_cache": False, "artifacts_dir": str(tmp_path / "artifacts")})
    engine.run_review(src, tmp_path / "out" / "report.md", options=opts)
    rep, out, rmap, placed = _check_engine_docx(src, tmp_path / "out")
    assert rep["run"]["mode"] == "rules_only" and rep["findings"], "правила не дали ни одного замечания"
    assert rep["run"]["modules"]["read_docx"].startswith("team:")


@pytest.mark.parametrize("user_comment", [False, True], ids=["clean", "with_user_comment"])
def test_engine_two_table_amounts_two_anchors_and_skip_counters(tmp_path, monkeypatch, user_comment):
    """Записанные ответы модели (mock): два замечания на две одинаковые суммы в таблице,
    пропуск без цитаты и выдуманная цитата. Каждое тело -- на своём диапазоне; пропуски
    видны в счётчике движка, а сводка DOCX считает только дошедшие замечания."""
    from p03_fixtures import AMOUNT, amounts_doc, amounts_mock_script

    _engine_env(monkeypatch, "review_individual,review_set")
    src = amounts_doc(tmp_path / "amounts.docx", user_comment=user_comment)
    doc = read_docx(src)

    script = amounts_mock_script(doc)
    (tmp_path / "mock.json").write_text(json.dumps(script, ensure_ascii=False), encoding="utf-8")
    opts = RunOptions.coerce({"provider": "mock", "mock_script": str(tmp_path / "mock.json"), "exports": ["docx"],
                              "cache_dir": str(tmp_path / "cache"), "use_cache": False,
                              "artifacts_dir": str(tmp_path / "artifacts")})
    engine.run_review(src, tmp_path / "out" / "report.md", options=opts)
    rep, out, rmap, placed = _check_engine_docx(src, tmp_path / "out")

    cell2 = "/w:document/w:body/w:tbl[1]/w:tr[2]/w:tc[2]"
    cell3 = "/w:document/w:body/w:tbl[1]/w:tr[3]/w:tc[2]"
    by_title = {f["title"]: f["id"] for f in rep["findings"]}
    fa, fb = by_title["Порог по умолчанию повторяет сумму пункта 2"], by_title["Лимит суммы push совпадает с порогом без объяснения"]
    assert placed[(fa, cell2)]["covered"] == placed[(fb, cell3)]["covered"] == AMOUNT
    assert placed[(fa, cell2)]["body"].startswith(f"[{fa}] Существенный")
    assert placed[(fb, cell3)]["body"].startswith(f"[{fb}] Незначительный")
    # пропуски отсечены движком до экспорта и видны в его счётчике
    titles_rejected = {x["candidate"]["title"] for x in rep.get("rejected", [])}
    assert {"Нет правила для суммы ниже 1 000 ₸", "Опора, которой нет в документе"} <= titles_rejected
    assert rep["run"]["evidence_audit"]["rejected"] >= 1
    # сводка DOCX считает дошедшие до экспорта замечания; пропусков на уровне DOCX нет
    summary = [r for r in rmap.values() if r["head"].startswith("Сводка ревью")]
    n_ev = sum(len(f["evidence"]) for f in rep["findings"])
    assert len(summary) == 1
    assert f"Отмечено в тексте: {len(rep['findings'])} из {len(rep['findings'])} замечаний (опор {n_ev} из {n_ev})." \
        in summary[0]["body"]
    assert not [w for w in rep["warnings"] if w.get("code") == "docx_export_unanchored"]
    mods = rep["run"]["modules"]
    assert mods["read_docx"].startswith("team:") and mods["resolve_candidate"].startswith("team:")
    assert mods["provider"].endswith("MockAdapter")
