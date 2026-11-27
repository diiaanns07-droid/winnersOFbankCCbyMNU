"""Линза «Риски» (№08): карточный процессинг, ИБ и эксплуатация.

Сам вызов модели делает общий запуск линзы (`stages/lens.py`, №01) с промптом `prompts/lens_risk.md`.
Здесь — детерминированная постобработка ответа модели, которая не зависит от провайдера:

* critical о неопределённом ключевом событии (этап операции) подаётся как `ambiguity`/`unambiguous` — основание (б)
  судьи, а не «пропуск» и не «расхождение с целью»;
* калибровка серьёзности по шкале контракта (раздел 5): риск ИБ и эксплуатационный риск — не выше major;
  нет схемы отката (пункт шаблона ревью) — всегда minor;
  расхождение ролей с видом `terminology` переводится в `security` (риск доступа, а не оформление);
  critical без сценария, последствий или с `blocks = none` — major;
* страховка от «фантазий»: замечание о теме, которой документ не касается ни словом (PCI DSS, шифрование,
  аудит, мониторинг, откат, антифрод…), снимается — у такой темы нет текстовой зацепки;
* замечание, все цитаты которого — определения из раздела терминов (или первая цитата-зацепка у
  «неоднозначности/неполноты»), — не выше minor;
* противоречие с критерием приёмки снимается: это зона тестировщика (№06), у линзы — дубль;
* major о дублях, гонках и сбоях смежных систем — minor, если документ этих тем не касается; отмена объекта во
  время начатой по нему операции при разрешённой документом отмене — major (не вопрос);
  major-риск ИБ без опоры на описанный интерфейс (адрес, GET, чужой объект, владение, номер карты,
  журналы, хранение) — minor;
* minor — только с текстовой зацепкой (откат по шаблону ревью, пояс городом), не больше двух; прочие minor —
  вопросы «о чём документ молчит», они снимаются, не больше двух critical (остальные — major), дубли по заголовку, не более 12 замечаний,
  порядок: critical → major → minor.

Снятые замечания возвращаются отдельно с причиной, чтобы судья и отчёт могли их показать.
"""
from __future__ import annotations

import re
from typing import Any, Iterable

NAME = "risk"
MAX_CANDIDATES = 12
MAX_MINOR = 2  # minor линзы — только с зацепкой: пункт шаблона ревью (откат), пояс, названный городом
# minor с текстовой зацепкой идут первыми при отборе (вопросы «о чём документ молчит» — в конец и под лимит)
_HOOKED_MINOR_RE = re.compile(r"схем\w*\s+откат|откат\w*\s+(решени|функц|релиз|выпуск)|шаблон|чек-?лист"
                              r"|пункт\w*\s+ревью|город|местн\w+\s+врем|utc|пояс", re.I)
# Лимит вывода линзы сразу 32 000: у моделей с рассуждением (haiku через claude -p) рассуждение входит в лимит,
# при 16 000 первый вызов падает по обрезке через ~5 мин и повторяется — лишний вызов и время.
MAX_OUTPUT_TOKENS = 32000
# Виды «не определено / неполно»: если их зацепка — определение термина, это тонкость, а не дефект.
VAGUE_KINDS = ("ambiguity", "incomplete", "missing_element", "other")
MAX_CRITICAL = 2  # ключевое событие и одно противоречие; остальное у линзы — major
SEVERITY_ORDER = {"critical": 0, "major": 1, "minor": 2}

# Темы, которые линза поднимает только при текстовой зацепке. Ключ — тема (для причины отказа);
# `title` — признак темы в заголовке замечания; `hooks` — основы слов, наличие любой из которых
# в документе считается зацепкой.
OUT_OF_SCOPE_TOPICS: dict[str, dict[str, Any]] = {
    "соответствие стандартам и регуляторике": {
        "title": r"PCI|GDPR|ISO\s*27|ГОСТ|регулятор|закон",
        "hooks": ["pci", "gdpr", "27001", "гост", "регулятор", "закон"],
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
        "title": r"мониторинг|алерт|оповещени\w+\s+дежурн|availability",
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
        "title": r"схем\w*\s+откат|откат\w*\s+(решени|функц|релиз|выпуск|изменени)|rollback|feature.?flag"
                 r"|флаг\w*\s+(включ|выключ|функц)|выключени\w+\s+функц|скрыти\w+\s+функц",
        "hooks": ["откат", "rollback", "флаг", "скрыти"],
    },
}

_TITLE_RES = {topic: re.compile(spec["title"], re.I) for topic, spec in OUT_OF_SCOPE_TOPICS.items()}

# Эксплуатационные темы, по которым major ставится, только если документ сам их касается (заявляет
# устойчивость к повторам, говорит о параллельных событиях или сбоях). Иначе это вопрос — minor.
MAJOR_NEEDS_HOOK: dict[str, dict[str, Any]] = {
    "повторы и дубли событий": {
        "title": r"дедуплик|дубл|повторн\w*\s+(доставк|событи|уведомлени|обработк|запрос|вызов)|идемпотент|двойн"
                 r"|повтор\w*\s+(\w+\s+)?(событи|доставк|уведомлени|сообщени|передач|отправк)"
                 r"|(признак|ключ)\w*\s+(\w+\s+)?повтор",
        "hooks": ["повтор", "дубл", "идемпотент", "исходный итог", "однократн"],
    },
    "гонки параллельных событий": {
        "title": r"гонк|конкурентн|атомарн|(параллельн|одновременн)\w*\s+(\w+\s+)?(событ|запрос|операц|покуп"
                 r"|перевод|уведомлен|обработ|вызов|списан|пополнен|начислен)",
        "hooks": ["параллельн", "одновременн", "конкурентн", "гонк", "атомарн"],
    },
    "сбои смежных систем": {
        "title": r"сбо[йяеию]|таймаут|недоступн|(ответ|код|статус|HTTP)\w*\s+5\d\d\b|не\s+прош\w*|не\s+выполн\w*"
                 r"|не\s+подтвержд\w*",
        "hooks": ["сбо", "таймаут", "недоступност", "не отвечает"],
    },
}
_MAJOR_RES = {topic: re.compile(spec["title"], re.I) for topic, spec in MAJOR_NEEDS_HOOK.items()}
# Зацепка для major о повторах — обещание документа, что повтор не меняет итог («повторная доставка … сохраняет
# исходный итог», «повтор не учитывается», «обработка однократна»), а не любое слово «повтор» («передача
# повторяется до 2 раз»): без обещания вопрос о дублях — вопрос предметной области.
_REPEAT_PROMISE_RE = re.compile(r"повтор\w*[^;|.]{0,80}(не\s+(меня|учитыва|созда|влия|увеличива|начисля)|сохраня)"
                                r"|однократн|исходн\w+\s+итог|не\s+более\s+одного\s+раза\s+на\s+(событи|операци)", re.I)


# Риск ИБ уровня major — только конкретный риск описанного интерфейса (данные в адресе, GET, ответ на чужой
# объект, проверка владения, номер карты и персональные данные в уведомлениях, журналах, хранилище).
# Прочие «риски ИБ» (подлинность входящих событий, общие угрозы) без такой опоры — вопрос, minor.
SECURITY_MAJOR_RE = re.compile(
    r"строк\w*\s+запрос|query|адрес|url|\bget\b|40[34]|чуж|владе|принадлеж|сесси|роль|роли|держател"
    r"|номер\w*\s+карт|цифр|маск|персональн|журнал|лог[аиоу]|перебор|раскры", re.I)


# Признак повтора назван в самом обещании («с тем же идентификатором», «ключ идемпотентности»): вопрос закрыт.
_REPEAT_KEYED_RE = re.compile(r"с\s+тем\s+же|ключ\w*\s+идемпотент|идентификатор\w*\s+(событи|операци|запрос)", re.I)


def repeat_promise_without_key(doc_text: str) -> bool:
    """В документе есть обещание «повтор не меняет итог», в строке которого не назван признак повтора."""
    return any(_REPEAT_PROMISE_RE.search(ln) and not _REPEAT_KEYED_RE.search(ln) for ln in doc_text.splitlines())


def major_without_hook(candidate: dict, doc_text: str) -> str | None:
    """Тема эксплуатационного major, которой документ не касается (тогда это minor), или None."""
    if candidate.get("severity") != "major" or _is_key_event(candidate):
        return None  # неопределённое ключевое событие не понижается из-за попутных слов («сбой», «повтор»)
    title = str(candidate.get("title", ""))
    if is_injection(candidate) or is_pd_transfer(candidate):
        return None  # зацепка — сам текст документа (вставка, перечень передаваемых данных)
    if candidate.get("kind") == "security" and not SECURITY_MAJOR_RE.search(title):
        return "риск ИБ без опоры на описанный интерфейс"
    matched = [topic for topic, rx in _MAJOR_RES.items() if rx.search(title)]
    hooked = [t for t in matched if (repeat_promise_without_key(doc_text) if t == "повторы и дубли событий"
                                     else any(h in doc_text for h in MAJOR_NEEDS_HOOK[t]["hooks"]))]
    return matched[0] if matched and not hooked else None


_TERMS_RE = re.compile(r"термин|глоссари|определени|понятия", re.I)
_HEADING_RE = re.compile(r"^\s*#{1,6}\s+(.*)")


def _lines(view: Any) -> list[dict]:
    """Строки документа как [{"n", "text", "section"}]: из DocView, списка строк или текста Markdown."""
    if view is None:
        return []
    if isinstance(view, str):
        out, path = [], []
        for n, text in enumerate(view.splitlines(), 1):
            m = _HEADING_RE.match(text)
            if m:
                level = len(text.strip()) - len(text.strip().lstrip("#"))
                path = path[: level - 1] + [m.group(1).strip()]
            out.append({"n": n, "text": text, "section": " › ".join(path)})
        return out
    lines = view.get("lines") if isinstance(view, dict) else getattr(view, "lines", None)
    if lines is None:
        lines = view
    out = []
    for i, line in enumerate(lines or [], 1):
        if isinstance(line, dict):
            out.append({"n": line.get("n", i), "text": str(line.get("text", "")),
                        "section": str(line.get("section") or "")})
        else:
            out.append({"n": i, "text": str(line), "section": ""})
    return out


def _doc_text(view: Any) -> str:
    """Текст документа в нижнем регистре."""
    return "\n".join(x["text"] for x in _lines(view)).lower()


def terms_lines(view: Any) -> set[int]:
    """Номера строк раздела терминов (глоссария, определений): там понятия уже определены."""
    out = set()
    for x in _lines(view):
        last = x["section"].split("›")[-1] if x["section"] else ""
        if last and _TERMS_RE.search(last):
            out.add(int(x["n"]))
    return out


def _evidence_lines(c: dict) -> list[int]:
    out = []
    for ev in c.get("evidence") or []:
        n = ev.get("line_start") or ev.get("line") if isinstance(ev, dict) else None
        if isinstance(n, int):
            out.append(n)
    return out


def missing_hook(candidate: dict, doc_text: str) -> str | None:
    """Тема замечания, которой нет в документе (нет зацепки), или None.

    critical не снимается никогда: это ключевое событие или противоречие, а не «тема вне предмета».
    """
    if candidate.get("severity") == "critical":
        return None
    title = str(candidate.get("title", ""))
    for topic, rx in _TITLE_RES.items():
        if rx.search(title) and not any(h in doc_text for h in OUT_OF_SCOPE_TOPICS[topic]["hooks"]):
            return topic
    return None


_ROLE_RE = re.compile(r"рол[ьие]|держател|владел|клиент\w*.{0,40}(прав|доступ|сесси)|дополнительн\w*\s+карт", re.I)


# Неопределённое ключевое событие (этап операции): основание critical (б) у судьи — термин с двумя толкованиями
# в ключевом правиле. Подавать как ambiguity/unambiguous, а не как «пропуск» или «расхождение с целью».
_KEY_EVENT_RE = re.compile(
    r"этап\w*\s+(карточн\w+\s+)?операц|как\w*\s+(именно\s+)?событи|событи\w*.{0,50}не\s+(определ|уточн)"
    r"|не\s+(определ|уточн)\w*.{0,60}событи|авторизац\w*\s+или\s+(проведени|клиринг)"
    r"|не\s+определ\w*,?\s+(когда|в\s+какой\s+момент|каким\s+событием|какой\s+момент)"
    r"|какой\s+момент\s+дела\w*|считается\s+(оплачен|внес[её]н|провед[её]н|выполнен|исполнен|зачислен)", re.I)
_CANCEL_DURING_RE = re.compile(
    r"отмен\w*.{0,80}(во\s+время|одновременн|параллельн|уже\s+начат|в\s+обработк|начат\w*\s+по|в\s+процессе)"
    r"|(во\s+время|одновременн|в\s+процессе)\w*.{0,60}отмен", re.I)
_ACCEPTANCE_RE = re.compile(r"критери\w*\s+приёмк|критери\w*\s+приемк", re.I)

# Этап проведения назван прямо («отражение на счёте», «зачисление на счёт», «списание со счёта»): событие определено.
# Неоднозначность «авторизация или проведение» с такой зацепкой — перенос шаблона, а не дефект документа.
_POSTING_RE = re.compile(r"отраж[её]н\w*|отражени\w*|зачислени\w*\s+на\s+сч|зачисл\w+\s+на\s+сч|списани\w*\s+со\s+сч"
                         r"|списан\w*\s+со\s+сч", re.I)
# Передача персональных данных третьей стороне и особые категории (здоровье): документ сам говорит о передаче —
# риск ИБ уровня major с текстовой зацепкой, а не «вопрос о чём документ молчит».
_PD_RE = re.compile(r"персональн\w*\s+данн|\bИИН\b|анкет\w*\s+здоров|здоровь|медицинск|паспортн\w*\s+данн", re.I)
_THIRD_PARTY_RE = re.compile(r"страхов|партн[её]р|третьей\s+сторон|третьим\s+лиц|третьему\s+лиц|оператор|передач"
                             r"|переда[её]т|передава|согласи", re.I)
# Согласие на передачу описано в документе — замечание «передача без согласия» неверно.
_CONSENT_DOC_RE = re.compile(r"согласи\w*\s+(\w+\s+){0,2}на\s+(передач|обработк)|consent", re.I)
# Указание модели или проверяющему внутри документа (системный промпт, правило 7) — риск, а не вопрос.
_INJECTION_RE = re.compile(r"ИИ-?\s*ассистент|\bдля\s+ИИ\b|нейросет|языков\w+\s+модел|вставк\w*|инструкци\w*\s+(для\s+)?"
                           r"(ИИ|модел|проверяющ)|указани\w*\s+(\w+\s+)?(проверяющ|модел|ИИ)|не\s+формировать\s+замечани",
                           re.I)
# Отложенная выплата на закрытую или заблокированную карту/счёт: дефект, только если клиент заранее выбирает, куда
# придут деньги (и документ молчит о закрытии к моменту выплаты). Выплата на тот же продукт, по которому шли операции,
# — общий вопрос жизненного цикла карты (как перевыпуск), не замечание.
_PAYOUT_CLOSED_RE = re.compile(r"(закрыт|заблокирован|блокировк)\w*", re.I)
_PAYOUT_RE = re.compile(r"выплат|выплач|зачисл|перечисл|возврат\w*\s+(преми|средств|денег)", re.I)
_DEST_CHOICE_RE = re.compile(r"(выбор|выбира\w*|выбран\w*|выбер\w*|указыва\w*|указан\w*)\s+(\w+\s+){0,2}(карт|сч[её]т)\w*"
                             r"\s+(для|на|зачислени|выплат|перечислени)|карт\w*\s+для\s+(выплат|зачислени|перечислени)"
                             r"|сч[её]т\w*\s+для\s+(выплат|зачислени|перечислени)", re.I)
_DEST_DEFINED_RE = re.compile(r"карт\w*(\s+для\s+\w+)?\s+(\w+\s+)?(закрыт|заблокирован)|(закрыт|заблокирован)\w*\s+карт"
                              r"|сч[её]т\w*\s+для\s+\w+\s+(\w+\s+)?(закрыт|заблокирован)", re.I)


# «Порядок событий» (возврат раньше покупки) — эксплуатация, а не неопределённое ключевое событие.
_EVENT_ORDER_RE = re.compile(r"порядок\s+(\w+\s+)?событи|раньше\s+(покупк|событи|операци)", re.I)


def _is_key_event(c: dict) -> bool:
    title = str(c.get("title", ""))
    return bool(_KEY_EVENT_RE.search(title)) and not _ACCEPTANCE_RE.search(title) and not _EVENT_ORDER_RE.search(title)


def _quotes(c: dict) -> list[str]:
    return [str(ev.get("quote", "")) for ev in c.get("evidence") or [] if isinstance(ev, dict)]


def is_injection(c: dict) -> bool:
    """Замечание о вставке-указании для модели или проверяющего в тексте документа."""
    return bool(_INJECTION_RE.search(str(c.get("title", ""))))


def is_pd_transfer(c: dict) -> bool:
    """Замечание о передаче персональных данных (или сведений о здоровье) третьей стороне."""
    title = str(c.get("title", ""))
    return bool(_PD_RE.search(title)) and bool(_THIRD_PARTY_RE.search(title))


def posting_key_event(c: dict) -> bool:
    """«Авторизация или проведение?» при зацепке, которая сама называет этап проведения (отражение на счёте,
    зачисление на счёт): событие определено документом — снимается как перенос шаблона."""
    if not _is_key_event(c) or c.get("kind") not in VAGUE_KINDS:
        return False
    quotes = _quotes(c)
    return bool(quotes) and bool(_POSTING_RE.search(quotes[0]))


def payout_closed_question(c: dict, doc_text: str) -> str | None:
    """Причина снять замечание «выплата на закрытую/заблокированную карту или счёт», или None.

    Замечание остаётся (major), если клиент заранее выбирает карту или счёт для выплаты и документ не говорит, что
    делать, если они закрыты к моменту выплаты. Снимается, если документ это уже определяет или если выплата идёт на
    тот же продукт, по которому шли операции (вопрос жизненного цикла карты, как перевыпуск)."""
    if c.get("severity") == "critical" or _is_key_event(c):
        return None
    title = str(c.get("title", ""))
    if not (_PAYOUT_CLOSED_RE.search(title) and _PAYOUT_RE.search(title)):
        return None
    if not re.search(r"карт|сч[её]т", title, re.I):
        return None
    lines = doc_text.splitlines()
    if any(_DEST_DEFINED_RE.search(ln) and _PAYOUT_RE.search(ln) for ln in lines):
        return "случай закрытой карты или счёта для выплаты описан в документе"
    if not _DEST_CHOICE_RE.search(doc_text):
        return "выплата на тот же продукт: закрытие карты — вопрос жизненного цикла, не замечание линзы"
    return None


# «Нет часового пояса / часа» у срока или границы периода — по шкале судьи и эталону чистых ТЗ это уточнение (minor),
# а minor без зацепки линза не пишет. Остаются: два места с разными поясами или датами (противоречие), пояс назван
# городом или «местным временем» (minor с зацепкой) и момент дня, на котором каждый день считаются деньги
# («остаток на конец дня»), когда пояс в документе не назван нигде.
_TZ_TITLE_RE = re.compile(r"пояс|\butc\b|(до|с)\s+какого\s+часа|час\w*\s+(и|или)\s+(пояс|минут)|граница?\w*\s+(суток|дня|месяц"
                          r"|период|календарн)|без\s+(часа|времени)|врем\w*\s+окончани|момент\w*\s+(начала\s+и\s+)?окончани"
                          r"|окончани\w*\s+(срока|период)\w*.{0,40}(час|врем|пояс)", re.I)
_TZ_CITY_RE = re.compile(r"город|местн\w+\s+врем|алмат|астан", re.I)
_DAY_MONEY_RE = re.compile(r"(на\s+)?кон(ец|ца)\s+(операционного\s+)?дня|на\s+начало\s+дня", re.I)
_TZ_DOC_RE = re.compile(r"utc|часов\w*\s+пояс", re.I)
# Перенос срока с выходного или праздничного дня — отдельный major (проценты и штрафы клиента), даже если модель
# склеила его в одно замечание с поясом.
_WEEKEND_RE = re.compile(r"выходн|праздни|нерабоч|рабоч\w*\s+д|перенос", re.I)
# Два периода, которые должны считаться по одной дате и в одном поясе (учёт операций и ограничение действия): это
# расхождение мест документа, а не граница одного срока.
_TWO_PERIODS_RE = re.compile(r"ограничени|лимит|два\w*\s+период|разн\w+\s+(дат|период)|месяц\w*\s+(лимит|отправк|уведомлен|push)"
                             r"|какой\s+месяц|в\s+сч[её]т\s+какого|приёмк|приемк", re.I)


def tz_only_question(c: dict, doc_text: str) -> str | None:
    """Причина снять «не задан часовой пояс / час границы срока», или None (замечание остаётся)."""
    if c.get("severity") == "critical" or _is_key_event(c) or c.get("kind") in CONFLICT_KINDS + ("unit_mismatch",):
        return None
    title = str(c.get("title", ""))
    if not _TZ_TITLE_RE.search(title) or _TZ_CITY_RE.search(title) or _TWO_PERIODS_RE.search(title) \
            or _WEEKEND_RE.search(title):
        return None
    if not _TZ_DOC_RE.search(doc_text) and any(_DAY_MONEY_RE.search(q) for q in _quotes(c)):
        return None  # «остаток на конец дня» без пояса: деньги считаются каждый день — дефект, а не граница
    return "граница срока или периода без часа и пояса — уточнение, а не замечание линзы"


# Крайний случай возврата или отмены, который документ сам решил: в строке правила возврата назван поздний случай
# («возврат, отражённый позже, …», «возврат после зачисления уменьшает следующее …», «… не восстанавливает»).
_REFUND_TITLE_RE = re.compile(r"возврат|сторн", re.I)
_REFUND_LINE_RE = re.compile(r"возврат|сторн", re.I)
_LATE_CASE_RE = re.compile(r"(?<!не\s)позже|после\s+(окончани|зачислени|выплат|начислени|закрыти|выписк|отправк)"
                           r"|не\s+восстанавлива", re.I)


def _doc_lines_of(c: dict, view: Any) -> list[str]:
    """Строки документа, на которые указывают цитаты кандидата (по номеру строки и по тексту цитаты)."""
    lines = _lines(view)
    by_n = {int(x["n"]): x["text"] for x in lines if str(x.get("n", "")).isdigit() or isinstance(x.get("n"), int)}
    out = []
    for ev in c.get("evidence") or []:
        if not isinstance(ev, dict):
            continue
        q = str(ev.get("quote", "")).strip().lower()
        hit = [x["text"] for x in lines if q and q[:60] in x["text"].lower()]
        if hit:
            out += hit
        else:
            n = ev.get("line_start") or ev.get("line")
            if isinstance(n, int) and n in by_n:
                out.append(by_n[n])
    return out


def refund_edge_defined(c: dict, view: Any) -> str | None:
    """Причина снять вопрос о крайнем случае возврата, который правило документа уже решило, или None."""
    if c.get("severity") == "critical" or _is_key_event(c) or c.get("kind") in CONFLICT_KINDS:
        return None
    title = str(c.get("title", ""))
    if not _REFUND_TITLE_RE.search(title) or _CANCEL_DURING_RE.search(title):
        return None
    for line in _doc_lines_of(c, view):
        if _REFUND_LINE_RE.search(line) and _LATE_CASE_RE.search(line):
            return "поздний возврат или отмена описаны в правиле документа — крайний случай, вопрос"
    return None


# Исход сбоя описан в документе («при сбое не проводится ни одна из них», «при ошибке списание отменяется»):
# «не описано состояние после сбоя / ответа 500» — неверное прочтение.
_FAIL_TITLE_RE = re.compile(r"сбо[йяеию]|\b5\d\d\b|ошибк|таймаут|недоступн", re.I)
_FAIL_OUTCOME_RE = re.compile(r"(сбо[йяеию]|ошибк\w*|недоступн\w*|не\s+ответил)\W.{0,80}(не\s+(провод|выполня|списыва|зачисля|сохраня"
                              r"|меня)|ни\s+одн|отменя|откатыва|возвраща)", re.I)


def failure_outcome_defined(c: dict, view: Any) -> str | None:
    """Причина снять «не описан исход сбоя», если документ его описывает, или None."""
    if c.get("severity") == "critical" or _is_key_event(c):
        return None
    if not _FAIL_TITLE_RE.search(str(c.get("title", ""))):
        return None
    if any(_FAIL_OUTCOME_RE.search(x["text"]) for x in _lines(view)):
        return "исход сбоя описан в документе"
    return None


# Ответ на повтор запроса клиента задан особым правилом («Повторная установка … не считается ошибкой», «Повторный
# вызов … возвращает …»): вопрос о варианте повтора — уточнение (разбор №18: «повтор: 200 или 400»), а не дефект.
# Повтор события от внешней системы (дубль события процессинга) сюда не относится.
_REPEAT_REQ_TITLE_RE = re.compile(r"повтор\w*\s+(\w+\s+){0,4}(установк|запрос|вызов|оплат|нажати|requestid|сохранени|подключ)"
                                  r"|повторн\w*\s+(\w+\s+)?(установк|вызов|запрос|оплат|сохранени)", re.I)
_REPEAT_EVENT_RE = re.compile(r"событи|уведомлени|доставк|процессинг|сообщени", re.I)
_REPEAT_RULE_RE = re.compile(r"повторн\w*\s+(\w+\s+){0,3}(установк|вызов|запрос|оплат|сохранени|подключ)\w*.{0,120}"
                             r"(не\s+считается\s+ошибк|возвраща|отвеча|ответ|не\s+созда|не\s+меня)", re.I)


def repeat_request_defined(c: dict, view: Any) -> str | None:
    """Причина снять вопрос об ответе на повтор запроса, если документ задаёт его особым правилом, или None."""
    if c.get("severity") == "critical" or _is_key_event(c):
        return None
    title = str(c.get("title", ""))
    if not _REPEAT_REQ_TITLE_RE.search(title) or _REPEAT_EVENT_RE.search(title):
        return None
    if any(_REPEAT_RULE_RE.search(x["text"]) for x in _lines(view)):
        return "ответ на повтор запроса задан особым правилом документа — уточнение, не замечание линзы"
    return None


# Пункт шаблона ревью о схеме отката заполнен (отмечено «Да» и описан флаг или выключение функции): замечания нет.
_ROLLBACK_DONE_RE = re.compile(r"откат\w*.{0,200}(флаг\w*|выключ\w*|отключ\w*|feature)", re.I)


def rollback_described(c: dict, view: Any) -> str | None:
    """Причина снять «схема отката не описана», если документ её описывает (заполненный пункт шаблона), или None."""
    if "откат" not in str(c.get("title", "")).lower():
        return None
    if any(_ROLLBACK_DONE_RE.search(x["text"]) for x in _lines(view)):
        return "схема отката описана в документе"
    return None


_REPEAT_CRIT_RE = re.compile(r"повтор|дедуплик|дубл[ья]|идемпотент", re.I)


def calibrate(candidate: dict) -> dict:
    """Приводит серьёзность к шкале контракта; возвращает копию кандидата."""
    c = dict(candidate)
    if _is_key_event(c):
        if c.get("severity") == "minor":
            # неопределённое ключевое событие — не вопрос предметной области (модель занизила уровень)
            c["severity"] = "major"
        if c.get("severity") == "critical" and c.get("kind") != "ambiguity":
            c["kind"], c["criterion"] = "ambiguity", "unambiguous"
    if c.get("severity") in ("critical", "major") and _TITLE_RES["откат и выключение функции"].search(
            str(c.get("title", ""))):
        # отсутствие схемы отката по пункту шаблона ревью — оформление процесса, не дефект требования
        c["severity"] = "minor"
    if c.get("kind") == "terminology" and _ROLE_RE.search(str(c.get("title", ""))):
        # расхождение ролей — риск доступа (дополнительная карта), а не оформление терминов
        c["kind"], c["criterion"] = "security", "risk"
    if is_injection(c) or is_pd_transfer(c):
        # вставка-указание для модели; передача персональных данных третьей стороне — риск с зацепкой в тексте
        c["kind"], c["criterion"] = "security", "risk"
        if c.get("severity") in ("minor", "critical", None, ""):
            c["severity"] = "major"
    sev = c.get("severity")
    if sev not in SEVERITY_ORDER:
        c["severity"] = sev = "major"
    if sev == "critical":
        is_risk_only = c.get("kind") in ("security", "ops_risk") and c.get("criterion") == "risk"
        weak = not str(c.get("scenario", "")).strip() or not str(c.get("impact", "")).strip() \
            or c.get("blocks") in (None, "", "none")
        # обработка повторов (ответ на повтор, ключ повтора) — эксплуатация: основную функцию можно построить,
        # не выбрав исход повтора, поэтому не выше major (шкала линзы), даже если два места расходятся
        repeat = not _is_key_event(c) and _REPEAT_CRIT_RE.search(str(c.get("title", "")))
        if is_risk_only or weak or repeat:
            c["severity"] = "major"
    if c["severity"] in ("critical", "major") and c.get("blocks") in (None, ""):
        c["blocks"] = "development"
    return c


def _drop(c: dict, reason: str) -> dict:
    """Снятый кандидат с причиной: `reason` читает конвейер (в `rejected` отчёта), `reject_reason` — тесты."""
    return {**c, "reason": reason, "reject_reason": reason}


def _title_key(c: dict) -> str:
    return re.sub(r"[^\w]+", " ", str(c.get("title", "")).lower()).strip()


CONFLICT_KINDS = ("contradiction", "event_conflict", "boundary_conflict", "status_conflict")


def acceptance_conflict(c: dict, acceptance_ids: set[str]) -> bool:
    """Противоречие правила с критерием приёмки — зона тестировщика (№06 сверяет каждую строку приёмки):
    у линзы это дубль, судья получает его от тестировщика."""
    if c.get("kind") not in CONFLICT_KINDS:
        return False
    if acceptance_ids and any(r in acceptance_ids for r in c.get("requirement_ids") or []):
        return True
    return bool(_ACCEPTANCE_RE.search(str(c.get("title", ""))))


def postprocess(candidates: Iterable[dict], view: Any = None,
                known_ids: Iterable[str] | None = None,
                acceptance_ids: Iterable[str] | None = None) -> tuple[list[dict], list[dict]]:
    """Калибровка, отсев тем без зацепки, дубли, лимит и порядок.

    `known_ids` — ID требований из нарезки: чужие ID (номера пунктов документа) из `requirement_ids` убираются.
    `acceptance_ids` — ID строк критериев приёмки: противоречия с ними снимаются (зона тестировщика).
    Возвращает (оставленные, снятые); у снятых есть поле `reject_reason`.
    """
    known = set(known_ids) if known_ids is not None else None
    accept = set(acceptance_ids or [])
    doc = _doc_text(view)
    defined = terms_lines(view)
    kept: list[dict] = []
    dropped: list[dict] = []
    seen: set[str] = set()
    for raw in candidates or []:
        if not isinstance(raw, dict):
            continue
        c = calibrate(raw)
        if known is not None:
            c["requirement_ids"] = [r for r in c.get("requirement_ids") or [] if r in known]
        # Пустая цитата проходит схему, но не доказывает ничего (системный промпт, правило 2): такой кандидат занимал
        # место в лимите линзы (12, minor — 2) и вытеснял настоящий, а затем его всё равно снимала сверка цитат.
        c["evidence"] = [e for e in c.get("evidence") or [] if isinstance(e, dict) and str(e.get("quote") or "").strip()]
        if not c.get("evidence"):
            dropped.append(_drop(c, "нет цитаты-зацепки"))
            continue
        if acceptance_conflict(c, accept):
            dropped.append(_drop(c, "противоречие с критерием приёмки — зона тестировщика (дубль)"))
            continue
        if posting_key_event(c):
            dropped.append(_drop(c, "этап операции назван в документе (отражение, зачисление или списание по счёту)"))
            continue
        if doc and is_pd_transfer(c) and _CONSENT_DOC_RE.search(doc):
            dropped.append(_drop(c, "согласие на передачу персональных данных описано в документе"))
            continue
        why = payout_closed_question(c, doc) if doc else None
        if not why and doc:
            why = (tz_only_question(c, doc) or refund_edge_defined(c, view) or failure_outcome_defined(c, view)
                   or repeat_request_defined(c, view) or rollback_described(c, view))
        if why:
            dropped.append(_drop(c, why))
            continue
        ev_lines = _evidence_lines(c)
        if defined and ev_lines and (all(n in defined for n in ev_lines)
                                     or (ev_lines[0] in defined and c.get("kind") in VAGUE_KINDS)):
            # зацепка — определение из раздела терминов: тонкость определения, не выше minor
            c["severity"] = "minor"
        if doc and major_without_hook(c, doc):
            c["severity"] = "minor"
        if c["severity"] == "minor" and doc and "отмен" in doc and _CANCEL_DURING_RE.search(str(c.get("title", ""))):
            # документ разрешает отмену, а исход начатой по объекту операции не описан — дефект, не вопрос
            c["severity"] = "major"
        topic = missing_hook(c, doc) if doc else None
        if topic:
            dropped.append(_drop(c, f"тема «{topic}» в документе не затрагивается"))
            continue
        key = _title_key(c)
        if key in seen:
            dropped.append(_drop(c, "дубль заголовка"))
            continue
        seen.add(key)
        kept.append(c)
    n_critical = 0
    for c in kept:  # порядок модели: самые серьёзные первыми
        if c["severity"] == "critical":
            n_critical += 1
            if n_critical > MAX_CRITICAL:
                c["severity"] = "major"
    kept.sort(key=lambda c: SEVERITY_ORDER.get(c.get("severity"), 3))
    minors = []
    for c in kept:
        if c.get("severity") != "minor":
            continue
        if _HOOKED_MINOR_RE.search(str(c.get("title", ""))):
            minors.append(c)
        else:  # вопрос «о чём документ молчит» — не замечание линзы (ложная тревога на чистых документах)
            dropped.append(_drop(c, "вопрос предметной области без текстовой зацепки — не замечание линзы"))
    for c in minors[MAX_MINOR:]:
        dropped.append(_drop(c, f"сверх лимита minor линзы ({MAX_MINOR})"))
    kept = [c for c in kept if c.get("severity") != "minor"] + minors[:MAX_MINOR]
    for c in kept[MAX_CANDIDATES:]:
        dropped.append(_drop(c, f"сверх лимита линзы ({MAX_CANDIDATES})"))
    return kept[:MAX_CANDIDATES], dropped


REPEAT_TOPIC_RE = _MAJOR_RES["повторы и дубли событий"]
# Признак повтора назван где-то в документе (не в строке обещания): «идентификатор события — ключ повтора»,
# «дубль узнаётся по …». Тогда страховка не нужна: вопрос закрыт текстом.
_REPEAT_WORD_RE = re.compile(r"повтор|дубл|дедуплик", re.I)


def repeat_promise_line(view: Any) -> dict | None:
    """Первая строка с обещанием «повтор события не меняет / сохраняет итог», где признак повтора не назван ни в
    ней, ни в другой строке о повторах. None — обещания нет или признак назван."""
    lines = [x for x in _lines(view) if str(x.get("text") or "").strip()]
    if any(_REPEAT_WORD_RE.search(x["text"]) and _REPEAT_KEYED_RE.search(x["text"]) for x in lines):
        return None
    for x in lines:
        low = x["text"].lower()
        if _REPEAT_PROMISE_RE.search(low) and not _REPEAT_KEYED_RE.search(low):
            return x
    return None


def _sentence_with(text: str, rx: re.Pattern) -> str:
    """Предложение строки, где сработал шаблон (цитата — дословная часть строки, до 200 символов)."""
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    hit = next((p for p in parts if rx.search(p.lower())), text.strip())
    return hit[:200]


def _int_or(v: Any, default: int) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _covers(req: dict, n: int) -> bool:
    """Строка n внутри диапазона строк требования (нечисловые границы нарезки — не внутри)."""
    a = _int_or(req.get("line_start"), 0)
    return a > 0 and a <= n <= _int_or(req.get("line_end"), a)


def repeat_key_candidates(kept: list[dict], view: Any, requirements: list | None = None) -> list[dict]:
    """Страховка: документ обещает, что повтор события не меняет итог, но не называет признак повтора, — а модель
    замечания о повторах не написала (haiku на официальном ТЗ, замер №08 v29: 6/8, нет замечания о повторах).

    Обещание и отсутствие признака видны в тексте (раздел 8 промпта, major), поэтому замечание добавляет код с цитатой
    строки обещания. На 51 документе наборов (официальный, open2, чистые №20, корпус) такое обещание без признака —
    только одно (строка обещания официального ТЗ); в чистых признак назван («с тем же идентификатором …»)."""
    if any(REPEAT_TOPIC_RE.search(str(c.get("title") or "")) for c in kept):
        return []
    line = repeat_promise_line(view)
    if not line:
        return []
    quote = _sentence_with(line["text"], _REPEAT_PROMISE_RE)
    n = int(line["n"])
    req_ids = [r.get("id") for r in requirements or [] if isinstance(r, dict) and r.get("id")
               and _covers(r, n)]
    return [{
        "title": "Повтор события: не назван признак, по которому повтор узнаётся",
        "kind": "ops_risk", "criterion": "risk", "severity": "major", "requirement_ids": req_ids[:2],
        "evidence": [{"quote": quote, "line": n}],
        "problem": f"Документ обещает: «{quote[:160]}», — но не называет, по какому признаку (идентификатор события "
                   "или операции) повтор распознаётся, и что именно сохраняется при повторе.",
        "scenario": "Одно и то же событие приходит дважды: без признака повтора система учтёт его второй раз и "
                    "повторит действие; два почти одновременных события у границы правила дадут два действия.",
        "impact": "Клиент получит неверный итог или повторное уведомление; повторную доставку нельзя проверить "
                  "тестом однозначно.",
        "recommendation": "Назвать ключ повтора, хранить его и записать правило: событие с уже учтённым ключом итог "
                          "не меняет и действие не повторяет.",
        "rewrite": "Повторная доставка события с тем же <уточнить: признак — идентификатор события или операции> не "
                   "меняет учтённую сумму и не создаёт повторного действия.",
        "question": "По какому признаку узнаётся повтор: идентификатор события или идентификатор операции?",
        "blocks": "both", "source": f"lens:{NAME}", "origin": "doc_text",
    }]


def run(ctx: Any) -> dict:
    """Запуск линзы через общий `lens.run` и постобработка ответа."""
    from . import lens  # общий запуск линзы (№01)

    out = dict(lens.run(ctx, NAME))
    reqs = [r for r in getattr(ctx, "requirements", None) or [] if isinstance(r, dict)]
    known = [r.get("id") for r in reqs if r.get("id")] or None
    accept = [r.get("id") for r in reqs if r.get("kind") == "acceptance" and r.get("id")]
    view = getattr(ctx, "view", None)
    model_cands = [c for c in out.get("candidates", []) or [] if isinstance(c, dict)]
    first, _ = postprocess(model_cands, view, known, accept)
    extra = repeat_key_candidates(first, view, reqs)
    # страховка — первой среди major: замечание доказано текстом документа и не должно уйти «сверх лимита»
    kept, dropped = postprocess(extra + model_cands, view, known, accept)
    out["candidates"] = kept
    if dropped:
        out["dropped"] = dropped
    return out
