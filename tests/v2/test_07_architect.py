"""Тесты линзы «Архитектор» (№07): промпт, схема ответа, постобработка, записанные живые ответы.

Сеть не нужна: живые ответы sonnet и haiku на официальном документе записаны в
`tests/v2/fixtures/07_official/` и проверяются по схеме и по цитатам.
"""
from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path

import importlib.util

import jsonschema
import pytest

ROOT = Path(__file__).resolve().parents[2]


def _load_lens():
    """Модуль линзы по пути файла: тест не зависит от установки пакета и от каркаса №01."""
    path = ROOT / "src" / "bcc_review" / "v2" / "stages" / "lens_architect.py"
    spec = importlib.util.spec_from_file_location("lens_architect_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


la = _load_lens()
PROMPT = ROOT / "src" / "bcc_review" / "v2" / "prompts" / "lens_architect.md"
DOC = ROOT / "release" / "input" / "requirements.md"
FIX = ROOT / "tests" / "v2" / "fixtures" / "07_official"
SEGMENT = ROOT / "tests" / "v2" / "fixtures" / "official" / "segment.json"

# Слова и имена официального документа: промпт обязан работать на любом ТЗ (анти-подгонка).
OFFICIAL_WORDS = ["push", "пуш", "savelimit", "тиын", "порог", "алмат", "ф-1", "ф-2", "ф-3", "ф-4",
                  "alertscontroller", "limit_kzt", "cardid", "проверьте сумму", "карта не найдена",
                  "сервис расходов", "учёт расходов", "уведомление о расходах", "demo-42", "₸"]


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", s)
    s = re.sub(r"[«»“”„\"']", '"', s)
    s = re.sub(r"[—–‑−]", "-", s)
    s = re.sub(r"\*\*|__|`", "", s)
    return re.sub(r"\s+", " ", s).strip().lower()


def _doc_lines() -> list[str]:
    out = []
    for raw in DOC.read_text(encoding="utf-8").splitlines():
        t = re.sub(r"\*\*|__|`", "", raw).rstrip()
        t = re.sub(r"^\s*[*-]\s+", "", t)
        t = re.sub(r"^#+\s*", "", t)
        if t.strip().startswith("|") and t.strip().endswith("|"):
            cells = [c.strip() for c in t.strip().strip("|").split("|")]
            t = "" if all(set(c) <= set(":- ") for c in cells) else " | ".join(cells)
        out.append(_norm(t))
    return out


def _quote_found(lines: list[str], quote: str) -> bool:
    q = _norm(quote)
    if not q:
        return False
    if any(q in x for x in lines):
        return True
    return any(q in " ".join(lines[i:i + 3]) for i in range(len(lines)))


def _cand(**kw) -> dict:
    base = {"title": "t", "kind": "api_contract", "criterion": "correct", "severity": "major",
            "requirement_ids": ["R-01"], "evidence": [{"quote": "q", "line": 1}], "problem": "p",
            "scenario": "s", "impact": "i", "recommendation": "r", "rewrite": "", "question": "",
            "blocks": "development"}
    base.update(kw)
    return base


# --- промпт ---------------------------------------------------------------------------------------

def test_prompt_exists_and_is_russian():
    text = PROMPT.read_text(encoding="utf-8")
    assert text.startswith("## Задача")
    assert len(re.findall(r"[а-яё]", text, re.I)) > 3000
    for key in ("inventory", "operations", "promises", "codes", "fields", "branches", "missing_element", "status_conflict",
                "unit_mismatch", "api_contract", "До 12 кандидатов"):
        assert key in text, key


def test_prompt_has_no_official_document_words():
    text = PROMPT.read_text(encoding="utf-8").lower()
    leaked = [w for w in OFFICIAL_WORDS if w in text]
    assert not leaked, f"слова официального документа в промпте: {leaked}"


def test_prompt_has_no_dev_corpus_method_names():
    text = PROMPT.read_text(encoding="utf-8")
    for name in ("getTransferLimit", "setTransferLimit", "getCashback", "saveCategory", "createAutopay",
                 "getAutopay", "deleteAutopay", "blockCard", "unblockCard", "getCardStatus", "BLOCKED_BY_CLIENT"):
        assert name not in text, name


# --- схема ----------------------------------------------------------------------------------------

def test_schema_is_valid_json_schema():
    jsonschema.Draft202012Validator.check_schema(la.SCHEMA)
    assert set(la.SCHEMA["required"]) == {"inventory", "candidates"}
    assert la.SCHEMA["properties"]["candidates"]["items"]["properties"]["kind"]["enum"] == la.KINDS


def test_schema_accepts_minimal_answer_and_rejects_extra_fields():
    ok = {"inventory": la.empty_inventory(), "candidates": [_cand()]}
    jsonschema.validate(ok, la.SCHEMA)
    bad = {"inventory": la.empty_inventory(), "candidates": [_cand(extra="x")]}
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(bad, la.SCHEMA)


def test_schema_can_wrap_external_candidate_schema():
    sch = la.schema({"type": "object"})
    assert sch["properties"]["candidates"]["items"] == {"type": "object"}


# --- постобработка --------------------------------------------------------------------------------

def test_critical_without_scenario_or_blocks_is_downgraded():
    out = la.postprocess({"candidates": [
        _cand(severity="critical", kind="status_conflict", scenario="", evidence=[{"quote": "a", "line": 1}]),
        _cand(severity="critical", kind="status_conflict", blocks="none", evidence=[{"quote": "b", "line": 2}]),
        _cand(severity="critical", kind="status_conflict", evidence=[{"quote": "c", "line": 3}]),
    ]})
    assert [c["severity"] for c in out["candidates"]] == ["critical", "major", "major"]


def test_order_dedupe_limit_and_evidence_filter():
    cands = [_cand(severity="minor", evidence=[{"quote": "m", "line": 50}])]
    cands += [_cand(evidence=[{"quote": f"q{i}", "line": i}]) for i in range(1, 17)]
    cands += [_cand(evidence=[{"quote": "dup", "line": 3}])]          # дубль по виду и строкам
    cands += [_cand(evidence=[])]                                      # без цитаты
    cands += [_cand(severity="critical", kind="status_conflict", evidence=[{"quote": "k", "line": 99}])]
    out = la.postprocess({"candidates": cands})["candidates"]
    assert len(out) == la.MAX_CANDIDATES
    assert out[0]["severity"] == "critical"
    assert all(c["evidence"] for c in out)
    assert all(c["source"] == "lens:architect" for c in out)
    assert sum(1 for c in out if [e["line"] for e in c["evidence"]] == [3]) == 1


def test_unknown_requirement_ids_removed_and_input_not_mutated():
    data = {"candidates": [_cand(requirement_ids=["R-01", "Ф-9"])], "inventory": {"promises": [], "junk": 1}}
    snapshot = json.dumps(data, ensure_ascii=False, sort_keys=True)
    out = la.postprocess(data, requirement_ids={"R-01"})
    assert out["candidates"][0]["requirement_ids"] == ["R-01"]
    assert set(out["inventory"]) == {"operations", "promises", "codes", "fields", "branches"}
    assert json.dumps(data, ensure_ascii=False, sort_keys=True) == snapshot


def test_postprocess_handles_garbage():
    assert la.postprocess({}) == {"candidates": [], "inventory": la.empty_inventory()}
    assert la.postprocess({"candidates": [None, "x", {"evidence": None}]})["candidates"] == []


def test_unfulfilled_promises():
    inv = {"promises": [{"what": "показать сумму", "line": 3, "operation": ""},
                        {"what": "сохранить", "line": 4, "operation": "save"}]}
    assert [p["line"] for p in la.unfulfilled_promises(inv)] == [3]


# --- записанные живые ответы на официальном документе ---------------------------------------------

@pytest.fixture(scope="module", params=["official_architect_sonnet.json", "official_architect_haiku.json", "official_architect_opus.json"])
def recorded(request):
    return json.loads((FIX / request.param).read_text(encoding="utf-8"))


def test_recorded_answer_matches_schema(recorded):
    jsonschema.validate(recorded, la.SCHEMA)


def test_recorded_quotes_exist_in_document(recorded):
    lines = _doc_lines()
    missing = [e["quote"] for c in recorded["candidates"] for e in c["evidence"] if not _quote_found(lines, e["quote"])]
    assert not missing, missing


def test_recorded_answer_finds_key_api_defects(recorded):
    reqs = {r["id"] for r in json.loads(SEGMENT.read_text(encoding="utf-8"))["requirements"]}
    out = la.postprocess(recorded, requirement_ids=reqs)["candidates"]
    crit = [c for c in out if c["severity"] == "critical"]
    lines = lambda c: {e["line"] for e in c["evidence"]}  # noqa: E731
    # К4: обещано чтение (интеграция L52), а операции чтения нет
    assert any(c["kind"] == "missing_element" and 52 in lines(c) for c in crit)
    # К3: неверная сумма — 400 (L163) против 200 с ERROR (L171 или логика L121)
    assert any(c["kind"] == "status_conflict" and 163 in lines(c) and lines(c) & {121, 171} for c in crit)
    # С1: изменение данных методом GET (L104)
    assert any(104 in lines(c) for c in out)
    # С3: типы одного поля в запросе (L143/L144) и ответе (L156/L157)
    assert any(lines(c) & {143, 144} and lines(c) & {156, 157} for c in out)
    # С4: единицы суммы в данных (L49) и в API/приёмке
    assert any(c["kind"] == "unit_mismatch" and 49 in lines(c) for c in out)
    # 403 ↔ 404 (L175/L188/L189)
    assert any(lines(c) & {188, 189} for c in out)


def test_undefined_branches():
    inv = {"branches": [{"operation": "o", "step": "проверка не прошла", "line": 7, "outcome": ""},
                        {"operation": "o", "step": "успех", "line": 8, "outcome": "200 {ok}"}]}
    assert [b["line"] for b in la.undefined_branches(inv)] == [7]


def test_line_marks_become_plain_line_numbers():
    c = _cand(problem="Шаг L121 и пример L165 расходятся", scenario="см. L052", title="Код L163")
    out = la.postprocess({"candidates": [c]})["candidates"][0]
    assert out["problem"] == "Шаг стр. 121 и пример стр. 165 расходятся"
    assert out["scenario"] == "см. стр. 52" and out["title"] == "Код стр. 163"
    assert la.plain_line_refs("HTTP 400, L1 кэш") == "HTTP 400, L1 кэш"


def test_critical_missing_operation_needs_explicit_interface_promise():
    screen = {"quote": "После выдачи: Кредиты → кредит → «Страхование» → номер полиса и кнопка «Отказаться»", "line": 29}
    partner = {"quote": "Сервис страхования получает номер полиса от страховой компании-партнёра", "line": 54}
    promise = {"quote": "Приложение читает и сохраняет настройки через дочерний документ «X — REST API»", "line": 52}
    by_method = {"quote": "Приложение читает лимит методом getLimit", "line": 35}
    call = {"quote": "Приложение → сервис A: получить данные", "line": 45}
    code = {"quote": "3. Если запись уже есть, вернуть 409.", "line": 73}
    base = dict(severity="critical", kind="missing_element", scenario="s", impact="i", blocks="both")
    assert la.postprocess({"candidates": [_cand(evidence=[screen, partner], **base)]})["candidates"][0]["severity"] == "major"
    for ev in (promise, by_method, call, code):
        out = la.postprocess({"candidates": [_cand(evidence=[screen, ev], **base)]})["candidates"][0]
        assert out["severity"] == "critical", ev
    other = dict(base, kind="status_conflict")
    assert la.postprocess({"candidates": [_cand(evidence=[screen], **other)]})["candidates"][0]["severity"] == "critical"


def test_critical_only_for_lens_scale_kinds():
    base = dict(severity="critical", scenario="s", impact="i", blocks="both",
                evidence=[{"quote": "Приложение читает данные методом getX", "line": 3}])
    sev = {k: la.postprocess({"candidates": [_cand(kind=k, **base)]})["candidates"][0]["severity"]
           for k in ("missing_element", "status_conflict", "contradiction", "unit_mismatch", "incomplete")}
    assert sev == {"missing_element": "critical", "status_conflict": "critical", "contradiction": "major",
                   "unit_mismatch": "major", "incomplete": "major"}


def test_error_body_gap_is_minor():
    """Проверка 4а («поле без условия нет в телах ошибок») — minor; другие замечания о кодах и ветках не трогаем."""
    titles = {"Тела ошибок не содержат полей status, amount и recipientName": "minor",
              "Ответы 400/401/404/500 без поля result": "minor",
              "Ветка логики без ответа: отклонённая сумма": "major",
              "Тело ответа 200 при отказе не показано": "major"}
    for t, want in titles.items():
        out = la.postprocess({"candidates": [_cand(title=t)]})["candidates"][0]
        assert out["severity"] == want, t
    conflict = _cand(title="Ответы ошибок: 200 с признаком ошибки и 400", kind="status_conflict", severity="critical",
                     scenario="s", impact="i", blocks="both", evidence=[{"quote": "вернуть 400", "line": 3}])
    assert la.postprocess({"candidates": [conflict]})["candidates"][0]["severity"] == "critical"


def test_inventory_tolerates_model_notes_but_candidates_stay_strict():
    """Заметки модели в описи не ломают схему (иначе claude -p переписывает ответ заново); постобработка их убирает."""
    inv = dict(la.empty_inventory(), promises_check_note="все обещания сверены",
               operations=[{"name": "m", "method": "GET", "purpose": "чтение", "line": 1, "note": "x"}])
    jsonschema.validate({"inventory": inv, "candidates": [_cand()]}, la.SCHEMA)
    out = la.postprocess({"inventory": inv, "candidates": [_cand()]})
    assert set(out["inventory"]) == set(la.empty_inventory())
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({"inventory": inv, "candidates": [_cand(note="x")]}, la.SCHEMA)


def test_field_missing_from_data_list_is_minor_unless_rule_needs_it():
    """Разбор №18: «поле API нет в перечне хранимых данных» — minor; major — если названо правило или атрибут для него."""
    minor = ["Поля requestId и cardId не входят в перечень хранимых данных",
             "Поле enabled пишется в хранилище, но в перечне хранимых данных его нет"]
    major = ["Хранимые данные не содержат тип операции и ссылку возврата",
             "Момент получения события не хранится, а правило 4 его требует",
             "Чтение настроек не описано ни одной операцией"]
    for t in minor + major:
        out = la.postprocess({"candidates": [_cand(title=t, kind="missing_element")]})["candidates"][0]
        assert out["severity"] == ("minor" if t in minor else "major"), t
