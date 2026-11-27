"""Подключение модулей команды с резервом.

Для каждого слота движок сначала ищет модуль владельца (после слияния ветки ``bcc/pNN-…``),
иначе берёт резервную реализацию из ``runtime/fallback``. Паспорт фиксирует, что отработало.
``BCC_FORCE_FALLBACK=slot1,slot2`` (или ``all``) принудительно включает резерв — для сравнения.
"""

from __future__ import annotations

import importlib
import os
from dataclasses import dataclass
from typing import Any, Callable, Optional

# слот: (модуль владельца, резерв или None)
SLOTS: dict[str, tuple[str, Optional[str]]] = {
    "read_text": ("bcc_review.readers.text:read_text", "bcc_review.runtime.fallback.text_reader:read_text"),
    "read_pdf": ("bcc_review.readers.pdf:read_pdf", "bcc_review.runtime.fallback.pdf_reader:read_pdf"),
    "read_docx": ("bcc_review.readers.docx:read_docx", None),
    "build_inventory": ("bcc_review.analysis.inventory:build_inventory",
                        "bcc_review.runtime.fallback.inventory:build_inventory"),
    "load_criteria": ("bcc_review.criteria:load_criteria", "bcc_review.runtime.fallback.criteria:load_criteria"),
    "review_individual": ("bcc_review.analysis.individual:review_individual",
                          "bcc_review.runtime.fallback.llm_stages:review_individual"),
    "review_set": ("bcc_review.analysis.cross:review_set", "bcc_review.runtime.fallback.llm_stages:review_set"),
    "reconcile_facts": ("bcc_review.analysis.facts:reconcile_facts", None),
    "resolve_hint": ("bcc_review.analysis.evidence:resolve_hint", "bcc_review.runtime.fallback.evidence:resolve_hint"),
    "resolve_candidate": ("bcc_review.analysis.evidence:resolve_candidate",
                          "bcc_review.runtime.fallback.evidence:resolve_candidate"),
    "verify_report": ("bcc_review.verification:verify_report",
                      "bcc_review.runtime.fallback.verification:verify_report"),
    "build_questions": ("bcc_review.decisions.clarify:build_questions",
                        "bcc_review.runtime.fallback.decisions:build_questions"),
    "parse_answers": ("bcc_review.decisions.answers:parse_answers",
                      "bcc_review.runtime.fallback.decisions:parse_answers"),
    "propose_patch": ("bcc_review.decisions.patches:propose_patch",
                      "bcc_review.runtime.fallback.decisions:propose_patch"),
    "write_revision": ("bcc_review.decisions.patches:write_revision",
                       "bcc_review.runtime.fallback.decisions:write_revision"),
    "compare_reports": ("bcc_review.decisions.diff:compare_reports", "bcc_review.runtime.fallback.diff:compare_reports"),
    "build_bank_pack": ("bcc_review.bank.checklist:build_bank_pack", "bcc_review.runtime.fallback.bank:build_bank_pack"),
    "write_markdown": ("bcc_review.exports.markdown:write_markdown",
                       "bcc_review.runtime.fallback.markdown:write_markdown"),
    "write_jira_csv": ("bcc_review.exports.jira:write_jira_csv", "bcc_review.runtime.fallback.jira:write_jira_csv"),
    "write_html": ("bcc_review.exports.html:write_html", "bcc_review.runtime.fallback.html:write_html"),
    "write_pdf": ("bcc_review.exports.pdf:write_pdf", None),
    "write_docx": ("bcc_review.exports.word:write_docx", None),
    "anthropic": ("bcc_review.providers.anthropic:AnthropicAdapter",
                  "bcc_review.runtime.fallback.anthropic:AnthropicAdapter"),
    "gemini": ("bcc_review.providers.gemini:GeminiAdapter", "bcc_review.runtime.fallback.gemini:GeminiAdapter"),
    # Claude Code CLI (`claude -p`) без API-ключа: адаптер v2/02 с тем же invoke(model, messages, schema, timeout_s)
    "claude_cli": ("bcc_review.v2.providers.claude_cli:ClaudeCLIProvider", None),
}


@dataclass
class Resolved:
    slot: str
    func: Optional[Callable[..., Any]]
    origin: str          # team | fallback | missing
    path: Optional[str]
    error: Optional[str] = None

    @property
    def label(self) -> str:
        return f"{self.origin}:{self.path}" if self.path else self.origin


def _load(path: str) -> Callable[..., Any]:
    mod_name, attr = path.split(":")
    module = importlib.import_module(mod_name)
    return getattr(module, attr)


def _forced() -> set[str]:
    raw = os.environ.get("BCC_FORCE_FALLBACK", "")
    return {x.strip() for x in raw.split(",") if x.strip()}


class Modules:
    def __init__(self) -> None:
        self._cache: dict[str, Resolved] = {}

    def get(self, slot: str, *, prefer_fallback: bool = False) -> Resolved:
        if slot in self._cache and not prefer_fallback:
            return self._cache[slot]
        team, fallback = SLOTS[slot]
        forced = _forced()
        errors = []
        if not prefer_fallback and slot not in forced and "all" not in forced:
            try:
                res = Resolved(slot, _load(team), "team", team)
                self._cache[slot] = res
                return res
            except ModuleNotFoundError as exc:
                if not (exc.name and team.split(":")[0].startswith(exc.name)):
                    errors.append(f"{team}: {exc}")
            except (ImportError, AttributeError) as exc:
                errors.append(f"{team}: {exc}")
        if fallback:
            try:
                res = Resolved(slot, _load(fallback), "fallback", fallback, "; ".join(errors) or None)
            except (ImportError, AttributeError) as exc:
                errors.append(f"{fallback}: {exc}")
                res = Resolved(slot, None, "missing", None, "; ".join(errors))
        else:
            res = Resolved(slot, None, "missing", None, "; ".join(errors) or "модуль ещё не влит")
        if not prefer_fallback:
            self._cache[slot] = res
        return res

    def used(self) -> dict[str, str]:
        return {slot: r.label for slot, r in sorted(self._cache.items())}
