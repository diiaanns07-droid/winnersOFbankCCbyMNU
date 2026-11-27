"""№26, этап 2: судья сливает только то, что исправляется одной правкой в одном месте документа.

Склейка «одна правка устраняет оба» двух кандидатов одного ревьюера о разных местах документа (что хранить и
что отправить пользователю) делится кодом; законные слияния — перечень кодов одного раздела, сигнал правила
кода как место дефекта, следствия одного critical — не трогаются. Без сети."""
from __future__ import annotations

import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests" / "v2"))
sys.path.insert(0, str(ROOT / "src"))

from bcc_review.v2.stages import judge  # noqa: E402
from test_10_judge import Ctx, FakeLLM, all_placed, cand, finding, response  # noqa: E402

REQS = [{"id": f"R-{n:02d}", "kind": "functional", "line_start": n, "line_end": n, "text": "Т"}
        for n in (9, 11, 16, 29, 30, 40)]

DATA = "Часть A. Новое › Требования к данным"
FLOW = "Часть A. Новое › Схема взаимодействия"
API = "Часть B. Интерфейс › Общие параметры"
BODY = "Часть B. Интерфейс › Параметры запроса › Тело запроса"
STATUS = "Часть B. Интерфейс › Статусы"


def _c(cid, line, quote, section, *, source="lens:architect", severity="major", kind="missing_element",
       title=None, reqs=("R-11",), extra=()):
    c = cand(cid, line, quote, kind=kind, criterion="set_complete", severity=severity, reqs=reqs, source=source,
             title=title, extra=extra)
    for e in c["evidence"]:
        e["section"] = section
    c["problem"] = f"Суть кандидата {cid[2:]}."
    return c


def _store_and_send():
    """Один ревьюер прислал два отдельных кандидата: перечень хранимых данных неполон (раздел данных) и
    содержимое сообщения клиенту не из чего собрать (раздел схемы взаимодействия)."""
    return [
        _c("C-001", 49, "Хранить идентификатор карты, месяц и сумму операции", DATA,
           title="Признак включения и тип операции отсутствуют в перечне хранимых данных", reqs=("R-11",)),
        _c("C-002", 43, "передать клиенту последние цифры карты и сумму", FLOW,
           title="Для уведомления нужны последние цифры карты, их нет в данных", reqs=("R-09", "R-11")),
        _c("C-003", 104, "Метод изменяет данные запросом чтения", API, kind="api_contract", reqs=("R-16",)),
    ]


def _merged(severity="major", base="C-001", problem="В L049 нет признака включения, типа операции и "
                                                    "последних цифр карты (L043)."):
    f = finding("F01", ["C-001", "C-002"], severity=severity, kind="missing_element", criterion="set_complete",
                title="Перечень данных не покрывает поля правил и уведомления", reqs=("R-09", "R-11"))
    f["base"], f["problem"] = base, problem
    return response([f, finding("F02", ["C-003"], kind="api_contract", reqs=("R-16",))],
                    checklist=[{"n": 1, "answer": "Нет", "comment": "Данные: F01.", "finding_keys": ["F01"]}],
                    summary="Разработку начинать с условиями: F01, F02.")


def _run(resp, cands, **opts):
    return judge.run(Ctx(FakeLLM(resp), requirements=REQS, options={"judge_check": False, **opts}), cands)


def _by(res, cid):
    return next(f for f in res["findings"] if cid in f["candidate_ids"])


def test_store_and_send_glued_by_judge_become_two_findings():
    res = _run(_merged(), _store_and_send())
    all_placed(res, ["C-001", "C-002", "C-003"])
    home, apart = _by(res, "C-001"), _by(res, "C-002")
    assert home is not apart
    assert home["candidate_ids"] == ["C-001"] and apart["candidate_ids"] == ["C-002"]
    assert {e["line_start"] for e in home["evidence"]} == {49}
    assert {e["line_start"] for e in apart["evidence"]} == {43}
    # тексты судьи называли и другое место — у каждой части тексты своего кандидата
    assert "L043" not in home["problem"] and "43" not in home["title"]
    assert home["problem"] == "Суть кандидата 001." and apart["problem"] == "Суть кандидата 002."
    assert apart["title"] == "Для уведомления нужны последние цифры карты, их нет в данных"
    assert apart["severity"] == "major" and apart["requirement_ids"] == ["R-09", "R-11"]
    assert home["requirement_ids"] == ["R-11"]
    assert res["checklist"][0]["finding_ids"] == [home["id"]]  # ключ склейки — у части-хозяина
    assert any("выделен отдельный дефект" in w for w in res["warnings"])
    assert len(res["findings"]) == 3


def test_judge_texts_kept_when_they_name_only_home_place():
    res = _run(_merged(problem="В перечне хранимых данных нет признака включения и типа операции."),
               _store_and_send())
    home = _by(res, "C-001")
    assert home["problem"] == "В перечне хранимых данных нет признака включения и типа операции."
    assert home["title"] == "Перечень данных не покрывает поля правил и уведомления"


def test_split_part_not_above_judge_level():
    """Склейку судья счёл minor — выделенная часть не выше minor, даже если линза дала major."""
    res = _run(_merged(severity="minor"), _store_and_send())
    apart = _by(res, "C-002")
    assert apart["severity"] == "minor" and apart["blocks"] == "none"


def test_home_follows_judge_base():
    res = _run(_merged(base="C-002", problem="Нет полей."), _store_and_send())
    home, apart = _by(res, "C-002"), _by(res, "C-001")
    assert home["problem"] == "Нет полей." and apart["problem"] == "Суть кандидата 001."


def test_list_of_one_section_stays_one_finding():
    """Перечень кодов ответа: две пары противоречивых кодов одного раздела — один дефект (шаг 2 промпта)."""
    cs = [_c("C-001", 151, "Если результат 200 или 201 — успешный", STATUS + " › Ответ", source="consistency",
             kind="ambiguity", title="Успех сохранения: 200 или 201", reqs=("R-30",)),
          _c("C-002", 188, "Для чужой карты возвращается 404", STATUS + " › 403", source="consistency",
             kind="status_conflict", title="Чужая карта: 403 или 404", reqs=("R-40",))]
    f = finding("F01", ["C-001", "C-002"], kind="status_conflict", title="Перечень кодов ответа противоречив")
    res = _run(response([f]), cs)
    assert len(res["findings"]) == 1 and res["findings"][0]["candidate_ids"] == ["C-001", "C-002"]


def test_rule_signal_in_other_section_stays_place_of_finding():
    """Сигнал правила кода (заголовок у запроса без тела) — место дефекта о способе вызова метода."""
    cs = [_c("C-001", 104, "Метод изменяет данные запросом чтения", API, kind="api_contract", reqs=("R-16",)),
          _c("C-002", 147, "Тип содержимого указан, тело не используется", BODY, source="rules:api.content_type",
             severity="minor", kind="api_contract", reqs=("R-29",))]
    res = _run(response([finding("F01", ["C-001", "C-002"], kind="api_contract")]), cs)
    assert len(res["findings"]) == 1


def test_different_reviewers_not_split():
    cs = _store_and_send()
    cs[1]["source"] = "lens:risk"
    res = _run(_merged(), cs)
    assert _by(res, "C-001") is _by(res, "C-002")


def test_same_subject_not_split():
    """Заголовки называют один предмет (≥ 2 общих опорных слова) — это один вопрос, даже в разных разделах."""
    cs = _store_and_send()
    cs[1]["title"] = "Признак включения не входит в перечень данных схемы"
    res = _run(_merged(), cs)
    assert _by(res, "C-001") is _by(res, "C-002")


def test_shared_line_not_split():
    cs = _store_and_send()
    cs[1]["evidence"].append({**cs[0]["evidence"][0]})
    res = _run(_merged(), cs)
    assert _by(res, "C-001") is _by(res, "C-002")


def test_critical_glue_untouched():
    """Critical: следствия одного пропуска законно сливаются из разных разделов."""
    res = _run(_merged(severity="critical"), _store_and_send())
    assert _by(res, "C-001") is _by(res, "C-002")
    cs = _store_and_send()
    cs[1]["severity"] = "critical"
    res = _run(_merged(), cs)
    assert _by(res, "C-001") is _by(res, "C-002")


def test_off_switch():
    res = _run(_merged(), _store_and_send(), judge_split_places=False)
    assert _by(res, "C-001") is _by(res, "C-002") and len(res["findings"]) == 2


def test_split_is_deterministic():
    """Порядок кандидатов на входе и дефектов в ответе не меняет реестр."""
    ref = _run(_merged(), _store_and_send())
    for seed in range(5):
        cs = _store_and_send()
        random.Random(seed).shuffle(cs)
        resp = _merged()
        random.Random(seed).shuffle(resp["findings"])
        res = _run(resp, cs)
        assert [(f["id"], f["candidate_ids"], f["title"], f["severity"]) for f in res["findings"]] == \
               [(f["id"], f["candidate_ids"], f["title"], f["severity"]) for f in ref["findings"]]


# --- пожелания: случай, названный в процитированном требовании, — не строка сводки «ряд случаев» ----------

RULE = "Возврат уменьшает расходы месяца исходной покупки. Переводы и снятие наличных исключаются"


def _wishes(title_a, title_b):
    cs = [_c("C-001", 38, RULE, DATA, source="lens:risk", severity="minor", kind="incomplete", title=title_a,
             reqs=("R-11",)),
          _c("C-002", 40, "Сервис отправляет сообщение клиенту", FLOW, source="lens:risk", severity="minor",
             kind="incomplete", title=title_b, reqs=("R-40",))]
    fs = [finding("F01", ["C-001"], severity="minor", kind="incomplete", title=title_a, blocks="none"),
          finding("F02", ["C-002"], severity="minor", kind="incomplete", title=title_b, blocks="none")]
    for f in fs:
        f["wish"] = True
    reqs = [{"id": "R-11", "kind": "functional", "line_start": 38, "line_end": 38, "text": RULE},
            {"id": "R-40", "kind": "functional", "line_start": 40, "line_end": 40, "text": "Т"}]
    return cs, response(fs, checklist=[]), reqs


def test_wish_named_in_quoted_rule_stays_separate():
    """«Возврат после отправки: исход не описан» при цитате правила о возврате — неполное правило документа,
    а не случай, о котором документ молчит; два разных вопроса не сводятся в одно замечание."""
    cs, resp, reqs = _wishes("Возврат в закрытом месяце: исход для исходной покупки не описан",
                             "Не описан сбой канала доставки сообщений")
    res = judge.run(Ctx(FakeLLM(resp), requirements=reqs), cs)
    all_placed(res, ["C-001", "C-002"])
    assert len(res["findings"]) == 2
    assert _by(res, "C-001")["title"] == "Возврат в закрытом месяце: исход для исходной покупки не описан"
    assert _by(res, "C-001")["severity"] == "minor"
    assert any("не пожелание" in w for w in res["warnings"])


def test_pure_wishes_still_consolidated():
    cs, resp, reqs = _wishes("Не описана блокировка карты клиента", "Не описан сбой канала доставки сообщений")
    res = judge.run(Ctx(FakeLLM(resp), requirements=reqs), cs)
    assert len(res["findings"]) == 1 and res["findings"][0]["title"] == "Документ не рассматривает ряд случаев"


def test_wish_scope_off_switch():
    cs, resp, reqs = _wishes("Возврат в закрытом месяце: исход для исходной покупки не описан",
                             "Не описан сбой канала доставки сообщений")
    res = judge.run(Ctx(FakeLLM(resp), requirements=reqs, options={"judge_check": False,
                                                                   "judge_wish_scope": False}), cs)
    assert len(res["findings"]) == 1


def test_split_part_goes_to_finding_on_same_fragment():
    """Выделенная часть идёт к дефекту, который уже разбирает тот же фрагмент документа (одна цитата содержит
    другую, ≥ 30 знаков), а не становится вторым замечанием о том же месте."""
    cs = _store_and_send() + [
        _c("C-004", 43, "последние цифры карты и сумму", FLOW, source="lens:analyst", kind="ambiguity",
           title="Не определено, какая сумма уходит клиенту", reqs=("R-09",))]
    cs[3]["evidence"][0]["quote"] = "передать клиенту последние цифры карты и сумму"
    resp = _merged()
    resp["findings"].append(finding("F03", ["C-004"], kind="ambiguity", title="Какая сумма уходит клиенту"))
    res = _run(resp, cs)
    all_placed(res, ["C-001", "C-002", "C-003", "C-004"])
    host = _by(res, "C-004")
    assert host["candidate_ids"] == ["C-002", "C-004"] and host["title"] == "Какая сумма уходит клиенту"
    assert _by(res, "C-001")["candidate_ids"] == ["C-001"]
    assert len(res["findings"]) == 3
    assert any("перенесён в дефект о том же месте" in w for w in res["warnings"])


def test_short_shared_name_is_not_same_place():
    """Общее имя компонента (короче 30 знаков) — не одно место: часть становится отдельным дефектом."""
    cs = _store_and_send() + [
        _c("C-004", 43, "последние цифры", FLOW, source="lens:analyst", kind="terminology", reqs=("R-09",))]
    resp = _merged()
    resp["findings"].append(finding("F03", ["C-004"], kind="terminology"))
    res = _run(resp, cs)
    assert _by(res, "C-002") is not _by(res, "C-004") and len(res["findings"]) == 4


# --- critical-противоречие не поглощает неописанную ветку того же ревьюера ------------------------------

def _conflict_and_branch(branch_source="lens:architect", branch_title="Ветка логики без ответа: отказ возвращает "
                                                                       "прежнее состояние"):
    cs = [_c("C-001", 121, "Неверная сумма — ответ 400", API, kind="status_conflict", severity="critical",
             title="Неверная сумма: код 200 с ошибкой или код 400", reqs=("R-30",),
             extra=[(163, "200 с телом ERROR")]),
          _c("C-002", 121, "Неверная сумма — ответ 400", API, source=branch_source, kind="api_contract",
             title=branch_title, reqs=("R-30",), extra=[(156, "Возвращается прежнее состояние")]),
          _c("C-003", 163, "200 с телом ERROR", STATUS, source="rules:api.success_with_error",
             kind="status_conflict", reqs=("R-30",))]
    f = finding("F01", ["C-001", "C-002", "C-003"], severity="critical", kind="status_conflict",
                title="Неверная сумма: 200 с ошибкой или 400", scenario="Сумма 0: 400 или 200 ERROR.",
                impact="Разные клиенты.")
    return cs, response([f])


def test_conflict_does_not_absorb_undescribed_branch_of_same_reviewer():
    cs, resp = _conflict_and_branch()
    res = _run(resp, cs)
    all_placed(res, ["C-001", "C-002", "C-003"])
    crit, branch = _by(res, "C-001"), _by(res, "C-002")
    assert crit is not branch and crit["severity"] == "critical" and crit["candidate_ids"] == ["C-001", "C-003"]
    assert branch["severity"] == "major" and branch["title"].startswith("Ветка логики без ответа")


def test_conflict_keeps_same_subject_or_other_reviewer():
    cs, resp = _conflict_and_branch(branch_title="Неверная сумма: код 200 или код 400 без тела")
    assert len(_run(resp, cs)["findings"]) == 1
    cs, resp = _conflict_and_branch(branch_source="lens:qa")
    assert len(_run(resp, cs)["findings"]) == 1


def test_missing_critical_keeps_its_consequences():
    """Critical «обещано, но не описано» (не противоречие) законно собирает следствия из разных мест."""
    cs, resp = _conflict_and_branch()
    resp["findings"][0]["kind"] = "missing_element"
    for c in cs:
        c["kind"] = "missing_element"
    cs[1]["kind"] = "api_contract"
    assert len(_run(resp, cs)["findings"]) == 1
