"""№52: кандидат со своей цитатой и своим вопросом не поглощается чужой склейкой судьи."""
from bcc_review.v2.stages import judge as J


def _c(cid, src, sev, lines, title, question="", kind="incomplete"):
    return {"id": cid, "source": src, "severity": sev, "kind": kind, "title": title, "question": question,
            "evidence": [{"quote": f"q{n}", "line_start": n, "line_end": n, "verified": "exact"} for n in lines]}


def test_lens_candidate_split_from_rules_signal():
    a = _c("C-001", "lens:architect", "major", [121, 156], "Ветка логики без ответа: прежнее состояние при отклонении",
           "Должно ли тело отказа содержать прежние значения?")
    b = _c("C-002", "rules:api.result_field_missing", "major", [155, 180], "Ответы 400 и 500 без поля result")
    drafts = [{"key": "F01", "ids": ["C-001", "C-002"], "raw": {"severity": "minor", "base": "C-001",
                                                                "title": "Состав полей ответа", "question": a["question"]}}]
    out = J._split_own_question(drafts, {"C-001": a, "C-002": b}, None, [])
    assert [d["ids"] for d in out] == [["C-002"], ["C-001"]]
    assert out[1]["raw"]["severity"] == "major"
    assert out[0]["raw"]["title"] == "" and "base" not in out[0]["raw"]


def test_shared_lines_or_same_subject_stay_merged():
    a = _c("C-001", "lens:analyst", "major", [40], "Изменение границы срабатывания не описано", "Что с накопленным?")
    b = _c("C-002", "consistency", "major", [40, 39], "Два правила о числе реакций")
    drafts = [{"key": "F01", "ids": ["C-001", "C-002"], "raw": {"severity": "major"}}]
    assert J._split_own_question(drafts, {"C-001": a, "C-002": b}, None, []) == drafts
    c = _c("C-003", "lens:qa", "major", [77], "Изменение границы срабатывания не описано", "Что с накопленным?")
    drafts = [{"key": "F01", "ids": ["C-001", "C-003"], "raw": {"severity": "major"}}]
    assert J._split_own_question(drafts, {"C-001": a, "C-003": c}, None, []) == drafts


def test_critical_and_terminology_untouched():
    a = _c("C-001", "lens:analyst", "major", [10], "Первое", "Вопрос один?")
    b = _c("C-002", "lens:risk", "critical", [20], "Второе другое", "Вопрос два?")
    drafts = [{"key": "F01", "ids": ["C-001", "C-002"], "raw": {"severity": "critical"}}]
    assert J._split_own_question(drafts, {"C-001": a, "C-002": b}, None, []) == drafts
    t = _c("C-003", "consistency", "major", [30], "Компоненты названы по-разному", "Какое название?", kind="terminology")
    drafts = [{"key": "F01", "ids": ["C-001", "C-003"], "raw": {"severity": "minor"}}]
    out = J._split_own_question(drafts, {"C-001": a, "C-003": t}, None, [])
    assert [d["ids"] for d in out] == [["C-003"], ["C-001"]]  # термин не выделяется, существенный — выделяется
