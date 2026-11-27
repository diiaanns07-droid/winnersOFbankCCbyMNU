"""№31: Gemini никогда не получает тайм-аут короче 10 с — иначе 400 «Minimum allowed deadline is 10s»
(живой ключ: `doctor --live --provider gemini` с бюджетом 9 с падал на рабочем ключе)."""
from bcc_review.v2.providers.gemini import MIN_DEADLINE_S, GeminiProvider


class _Rec:
    def __init__(self, seen):
        self.seen = seen

    def invoke(self, *, timeout_s, **_):
        self.seen.append(timeout_s)
        return {"text": "{}", "data": {}, "usage": {}}


def test_deadline_never_below_gemini_minimum():
    seen: list[float] = []
    p = GeminiProvider(api_key="k", fallback_models=[], adapter_factory=lambda *a, **k: _Rec(seen),
                       sleep=lambda s: None, env={})
    p.total_timeout_s = 6.0
    try:
        p.invoke(model=None, messages=[{"role": "user", "content": "x"}], schema={"type": "object"}, timeout_s=3)
    except Exception:
        pass
    assert seen and min(seen) >= MIN_DEADLINE_S == 10.0
