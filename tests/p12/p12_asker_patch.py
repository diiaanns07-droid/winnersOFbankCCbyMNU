"""Предлагаемая правка Max для ``src/bcc_review/runtime/asker.py``: гейт дополнительных запросов.

Правка задана точными заменами фрагментов текущего ``asker.py``. Тесты №12 применяют её к
настоящему файлу из ``bcc/integration`` и загружают результат как отдельный модуль, поэтому
расхождение с HEAD сразу ломает тест. Тот же текст в виде unified diff лежит в
``tests/p12/max_asker_call_gate.diff``; равенство проверяет тест.

    python -m tests.p12.p12_asker_patch > tests/p12/max_asker_call_gate.diff
"""

from __future__ import annotations

import difflib
import importlib
import sys
import types
from pathlib import Path

REL_PATH = "src/bcc_review/runtime/asker.py"

EDITS: list[tuple[str, str]] = [
    (
        '''    # ------------------------------------------------------------------ вызов
    def __call__(self, stage: str, payload: Mapping[str, Any], schema: Mapping[str, Any]) -> dict:
''',
        '''    # ------------------------------------------------------------------ запасная модель внутри invoke
    def _call_gate(self, stage: str, attempt: int) -> Optional[Callable[[str], None]]:
        """Разрешение на дополнительный физический запрос внутри одного ``invoke`` (запасная модель).

        Первый запрос ``invoke`` проверен и учтён до вызова; каждый следующий проверяет и учитывает этот
        гейт, поэтому лимит вызовов и ``run.calls.physical`` сходятся с транспортом."""
        if not getattr(self.adapter, "supports_call_gate", False):
            return None

        def gate(model_id: str) -> None:
            self.budget.check(stage)  # BudgetExhausted: адаптер не отправит запрос
            self.budget.note_call()
            self.tracer.emit("fallback_call", stage=stage, model=model_id, attempt=attempt + 1)

        return gate

    def _note_inner_attempts(self, stage: str, attempts: Any, attempt: int, *, last_is_error: bool) -> None:
        """Неудачные запросы запасной цепочки внутри ``invoke`` — отдельными вызовами в учёте этапа."""
        tried = [a for a in (attempts or []) if isinstance(a, Mapping) and a.get("kind")]
        if last_is_error:
            tried = tried[:-1]  # последняя попытка — сама ошибка, её учитывает основной код
        for a in tried:
            self.stats.call(stage, ok=False, model=a.get("model"), retry=attempt > 0)
            self.tracer.emit("call_error", stage=stage, kind=a.get("kind"), model=a.get("model"),
                             retry_after_s=a.get("retry_after_s"), attempt=attempt + 1)

    # ------------------------------------------------------------------ вызов
    def __call__(self, stage: str, payload: Mapping[str, Any], schema: Mapping[str, Any]) -> dict:
''',
    ),
    (
        '''            is_retry = attempt > 0
            try:
                res = self.adapter.invoke(model=self.model, messages=messages, schema=schema, timeout_s=timeout)
            except ProviderError as err:
                if err.kind == "not_configured":
                    # запрос не уходил (нет ключа или пакета): физическим вызовом не считается
''',
        '''            is_retry = attempt > 0
            gate = self._call_gate(stage, attempt)
            try:
                res = self.adapter.invoke(model=self.model, messages=messages, schema=schema, timeout_s=timeout,
                                          **({"call_gate": gate} if gate else {}))
            except ProviderError as err:
                if err.kind == "not_configured" or getattr(err, "physical_calls", None) == 0:
                    # запрос не уходил (нет ключа или пакета, модель уже отключена): физическим вызовом не считается
''',
    ),
    (
        '''                self.budget.note_tokens(sum(int(v or 0) for k, v in err.usage.items() if k in ("input_tokens", "output_tokens")))
''',  # noqa: E501 - строка дословно из asker.py
        '''                self._note_inner_attempts(stage, getattr(err, "attempts", None), attempt, last_is_error=True)
                self.budget.note_tokens(sum(int(v or 0) for k, v in err.usage.items() if k in ("input_tokens", "output_tokens")))
''',  # noqa: E501 - строка дословно из asker.py
    ),
    (
        '''            usage = dict(res.get("usage") or {})
            actual = res.get("model") or self.model
''',
        '''            usage = dict(res.get("usage") or {})
            self._note_inner_attempts(stage, (res.get("meta") or {}).get("attempts"), attempt, last_is_error=False)
            actual = res.get("model") or self.model
''',
    ),
]


class PatchDoesNotApply(AssertionError):
    pass


def original_source() -> str:
    module = importlib.import_module("bcc_review.runtime.asker")
    return Path(module.__file__).read_text(encoding="utf-8")


def already_applied(source: str | None = None) -> bool:
    """Max влил правку: все новые фрагменты на месте (часть замен — вставки, старый текст в них сохраняется)."""
    text = original_source() if source is None else source
    return all(new in text for _, new in EDITS)


def patched_source(source: str | None = None) -> str:
    text = original_source() if source is None else source
    if already_applied(text):
        return text
    for old, new in EDITS:
        count = text.count(old)
        if count != 1:
            raise PatchDoesNotApply(f"фрагмент asker.py найден {count} раз(а), ожидался 1: {old.splitlines()[0]!r}")
        text = text.replace(old, new)
    return text


def unified_diff(source: str | None = None) -> str:
    before = original_source() if source is None else source
    after = patched_source(before)
    return "".join(difflib.unified_diff(before.splitlines(keepends=True), after.splitlines(keepends=True),
                                        fromfile=f"a/{REL_PATH}", tofile=f"b/{REL_PATH}"))


def load_gated_module() -> types.ModuleType:
    """Пропатченный asker.py как модуль пакета bcc_review.runtime (относительные импорты работают)."""
    name = "bcc_review.runtime._asker_p12_call_gate"
    module = types.ModuleType(name)
    module.__package__ = "bcc_review.runtime"
    module.__file__ = f"<{REL_PATH} + tests/p12/p12_asker_patch.py>"
    sys.modules[name] = module
    exec(compile(patched_source(), module.__file__, "exec"), module.__dict__)  # noqa: S102 - собственный патч
    return module


def __getattr__(name: str):  # GatedAsker загружается лениво
    if name == "GatedAsker":
        return load_gated_module().Asker
    raise AttributeError(name)


if __name__ == "__main__":
    sys.stdout.write(unified_diff())
