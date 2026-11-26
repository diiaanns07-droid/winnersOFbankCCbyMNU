"""Линза «Риски» (№08): карточный процессинг, ИБ и эксплуатация.

Сам вызов модели делает общий запуск линзы (`stages/lens.py`, №01) с промптом `prompts/lens_risk.md`.
Здесь — детерминированная постобработка ответа модели, которая не зависит от провайдера:

* калибровка серьёзности по шкале контракта (раздел 5): риск ИБ и эксплуатационный риск — не выше major;
  critical без сценария, последствий или с `blocks = none` — major;
* страховка от «фантазий»: замечание о теме, которой документ не касается ни словом (PCI DSS, шифрование,
  аудит, мониторинг, откат, антифрод…), снимается — у такой темы нет текстовой зацепки;
* дубли по заголовку, не более 12 замечаний, порядок: critical → major → minor.

Снятые замечания возвращаются отдельно с причиной, чтобы судья и отчёт могли их показать.
"""
from __future__ import annotations

import re
from typing import Any, Iterable

NAME = "risk"
MAX_CANDIDATES = 12
SEVERITY_ORDER = {"critical": 0, "major": 1, "minor": 2}

# Темы, которые линза поднимает только при текстовой зацепке. Ключ — тема (для причины отказа);
# `title` — признак темы в заголовке замечания; `hooks` — основы слов, наличие любой из которых
# в документе считается зацепкой.
OUT_OF_SCOPE_TOPICS: dict[str, dict[str, Any]] = {
    "соответствие стандартам и регуляторике": {
        "title": r"PCI|GDPR|ISO\s*27|ГОСТ|регулятор|закон|персональн\w*\s+данн|ПДн",
        "hooks": ["pci", "gdpr", "27001", "гост", "регулятор", "закон", "персональн", "пдн"],
    },
    "шифрование": {
        "title": r"шифр|TLS|HTTPS",
        "hooks": ["шифр", "tls", "https", "сертификат"],
    },
    "многофакторная аутентификация": {
        "title": r"двухфактор|многофактор|2FA|MFA|OTP|одноразов\w+\s+код",
        "hooks": ["двухфактор", "многофактор", "2fa", "mfa", "otp", "одноразов", "код подтвержд"],
    },
    "ограничение частоты запросов": {
        "title": r"rate.?limit|частот\w*\s+запрос|троттл|throttl|brute|брутфорс|DoS",
        "hooks": ["rate", "частот", "запросов в секунду", "троттл", "throttl", "rps"],
    },
    "антифрод": {
        "title": r"антифрод|фрод|fraud|мошенн",
        "hooks": ["фрод", "fraud", "мошенн"],
    },
    "аудит и журналирование": {
        "title": r"аудит|журнал\w*\s+(изменени|действи|операци|аудит)|audit",
        "hooks": ["аудит", "audit", "журнал", "истори", "логир", "инициатор"],
    },
    "мониторинг и доступность": {
        "title": r"мониторинг|алерт|оповещени\w+\s+дежурн|SLA|доступност|availability",
        "hooks": ["мониторинг", "алерт", "sla", "доступност"],
    },
    "резервирование и восстановление": {
        "title": r"резервн\w*\s+коп|бэкап|backup|катастроф|disaster|восстановлени\w+\s+после",
        "hooks": ["резерв", "бэкап", "backup", "катастроф", "восстановлен"],
    },
    "нагрузка и производительность": {
        "title": r"нагрузк|производительн|RPS|пиков",
        "hooks": ["нагрузк", "производительн", "rps", "запросов в секунду"],
    },
    "откат и выключение функции": {
        "title": r"откат|rollback|feature.?flag|флаг\w*\s+(включ|выключ|функц)|выключени\w+\s+функц|скрыти\w+\s+функц",
        "hooks": ["откат", "rollback", "флаг", "скрыти"],
    },
}

_TITLE_RES = {topic: re.compile(spec["title"], re.I) for topic, spec in OUT_OF_SCOPE_TOPICS.items()}


def _doc_text(view: Any) -> str:
    """Текст документа в нижнем регистре: из DocView (`lines`), списка строк или строки."""
    if view is None:
        return ""
    if isinstance(view, str):
        return view.lower()
    if isinstance(view, dict):
        lines = view.get("lines") or []
    else:
        lines = getattr(view, "lines", None) or view
    parts = []
    for line in lines:
        parts.append(str(line.get("text", "")) if isinstance(line, dict) else str(line))
    return "\n".join(parts).lower()


def missing_hook(candidate: dict, doc_text: str) -> str | None:
    """Тема замечания, которой нет в документе (нет зацепки), или None."""
    title = str(candidate.get("title", ""))
    for topic, rx in _TITLE_RES.items():
        if rx.search(title) and not any(h in doc_text for h in OUT_OF_SCOPE_TOPICS[topic]["hooks"]):
            return topic
    return None


def calibrate(candidate: dict) -> dict:
    """Приводит серьёзность к шкале контракта; возвращает копию кандидата."""
    c = dict(candidate)
    sev = c.get("severity")
    if sev not in SEVERITY_ORDER:
        c["severity"] = sev = "major"
    if sev == "critical":
        is_risk_only = c.get("kind") in ("security", "ops_risk") and c.get("criterion") == "risk"
        weak = not str(c.get("scenario", "")).strip() or not str(c.get("impact", "")).strip() \
            or c.get("blocks") in (None, "", "none")
        if is_risk_only or weak:
            c["severity"] = "major"
    if c["severity"] in ("critical", "major") and c.get("blocks") in (None, ""):
        c["blocks"] = "development"
    return c


def _title_key(c: dict) -> str:
    return re.sub(r"[^\w]+", " ", str(c.get("title", "")).lower()).strip()


def postprocess(candidates: Iterable[dict], view: Any = None) -> tuple[list[dict], list[dict]]:
    """Калибровка, отсев тем без зацепки, дубли, лимит и порядок.

    Возвращает (оставленные, снятые); у снятых есть поле `reject_reason`.
    """
    doc = _doc_text(view)
    kept: list[dict] = []
    dropped: list[dict] = []
    seen: set[str] = set()
    for raw in candidates or []:
        if not isinstance(raw, dict):
            continue
        c = calibrate(raw)
        if not c.get("evidence"):
            dropped.append({**c, "reject_reason": "нет цитаты-зацепки"})
            continue
        topic = missing_hook(c, doc) if doc else None
        if topic:
            dropped.append({**c, "reject_reason": f"тема «{topic}» в документе не затрагивается"})
            continue
        key = _title_key(c)
        if key in seen:
            dropped.append({**c, "reject_reason": "дубль заголовка"})
            continue
        seen.add(key)
        kept.append(c)
    kept.sort(key=lambda c: SEVERITY_ORDER.get(c.get("severity"), 3))
    for c in kept[MAX_CANDIDATES:]:
        dropped.append({**c, "reject_reason": f"сверх лимита линзы ({MAX_CANDIDATES})"})
    return kept[:MAX_CANDIDATES], dropped


def run(ctx: Any) -> dict:
    """Запуск линзы через общий `lens.run` и постобработка ответа."""
    from . import lens  # общий запуск линзы (№01)

    out = dict(lens.run(ctx, NAME))
    kept, dropped = postprocess(out.get("candidates", []), getattr(ctx, "view", None))
    out["candidates"] = kept
    if dropped:
        out["dropped"] = dropped
    return out
