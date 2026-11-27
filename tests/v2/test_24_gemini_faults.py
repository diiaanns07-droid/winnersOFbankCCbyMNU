"""№24: отказы Gemini на уровне провайдера — настоящий адаптер v1 и SDK, настоящий HTTP к поддельному серверу.

В отличие от ``test_02_gemini_sdk`` (подменён клиент SDK) здесь подменён только адрес сервера: разбор ответов
и ошибок HTTP, заголовок Retry-After, обрыв сокета и тайм-аут клиента проходят через httpx и google-genai.
"""
from __future__ import annotations

import importlib.util
import threading
import time
from pathlib import Path

import pytest

from bcc_review.contracts import ProviderError

pytest.importorskip("google.genai")

from bcc_review.v2.providers import gemini  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("fake_gemini_24f", ROOT / "tests/v2/fixtures/24_gemini/fake_gemini.py")
fake_gemini = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fake_gemini)

SCHEMA = {"type": "object", "additionalProperties": False, "required": ["questions"],
          "properties": {"questions": {"type": "array", "items": {"type": "string"}}}}
# Текст запроса с маркером этапа clarify: сервер отвечает фикстурой этапа, приведённой к схеме
MARK = next(m for m, s in fake_gemini._markers() if s == "clarify")
MESSAGES = [{"role": "system", "content": "Система"}, {"role": "user", "content": f"{MARK}\nДокумент."}]


@pytest.fixture
def server(monkeypatch):
    holder = {}

    def start(faults=None, **kw):
        fake = fake_gemini.FakeGemini(faults, **kw).__enter__()
        holder["fake"] = fake
        monkeypatch.setenv("GOOGLE_GEMINI_BASE_URL", fake.url)
        monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
        monkeypatch.setenv("no_proxy", "127.0.0.1,localhost")
        return fake

    yield start
    if "fake" in holder:
        holder["fake"].__exit__(None, None, None)


def provider(sleeps=None, **kw):
    env = {"GEMINI_API_KEY": "fake-key", "GEMINI_RPM": "0"}
    env.update(kw.pop("env", {}))
    record = sleeps.append if sleeps is not None else (lambda s: None)
    return gemini.GeminiProvider(env=env, sleep=record, **kw)


def ask(p, timeout_s=30.0):
    return p.invoke(model=None, messages=MESSAGES, schema=SCHEMA, timeout_s=timeout_s, stage="clarify")


def kinds(fake):
    return [(r["model"], r["kind"]) for r in fake.log]


def test_ok_through_real_http(server):
    fake = server()
    out = ask(provider())
    assert isinstance(out["data"]["questions"], list)
    assert out["model"] == "gemini-3.8-flash"
    assert out["usage"]["input_tokens"] > 0 and out["usage"]["output_tokens"] > 0
    assert kinds(fake) == [("gemini-3.8-flash", "ok")]


def test_429_waits_retry_after_header_then_same_model(server):
    fake = server([{"kind": "429", "retry_after": 7}])
    sleeps = []
    out = ask(provider(sleeps))
    assert out["model"] == "gemini-3.8-flash"
    assert kinds(fake) == [("gemini-3.8-flash", "429"), ("gemini-3.8-flash", "ok")]
    assert sleeps and 7 <= sleeps[0] <= 8, sleeps     # ждали Retry-After из ответа, а не наугад


def test_429_longer_than_limit_goes_to_fallback(server):
    fake = server([{"kind": "429", "retry_after": 300, "model": "gemini-3.8-flash", "times": 9}])
    out = ask(provider())
    assert out["model"] == "gemini-3.7-flash"
    assert out["meta"]["fallback_used"] is True


@pytest.mark.parametrize("kind", ["503", "500", "504", "drop", "truncated_json", "empty", "no_candidates"])
def test_single_fault_is_retried_on_same_model(server, kind):
    fake = server([{"kind": kind}])
    out = ask(provider())
    assert isinstance(out["data"]["questions"], list)
    assert kinds(fake) == [("gemini-3.8-flash", kind), ("gemini-3.8-flash", "ok")]


@pytest.mark.parametrize("kind, max_same", [("503", 4), ("empty", 2), ("truncated_json", 2), ("404", 1),
                                            ("429_day", 1)])
def test_persistent_fault_on_primary_goes_to_next_model(server, kind, max_same):
    fake = server([{"kind": kind, "model": "gemini-3.8-flash", "times": 99}])
    out = ask(provider())
    assert out["model"] == "gemini-3.7-flash"
    assert sum(1 for m, _ in kinds(fake) if m == "gemini-3.8-flash") == max_same


def test_client_timeout_is_retried(server):
    # тайм-аут клиента не короче 10 с — меньше Gemini отвергает (400 «Minimum allowed deadline is 10s», №31)
    fake = server([{"kind": "slow", "delay": 14}])
    t0 = time.monotonic()
    out = ask(provider(), timeout_s=5)
    assert isinstance(out["data"]["questions"], list)
    assert [k for _, k in kinds(fake)] == ["slow", "ok"]
    assert time.monotonic() - t0 < 20   # тайм-аут клиента сработал, ответ через 14 с не ждали до конца


def test_schema_too_large_switches_to_schema_as_text(server):
    fake = server([{"kind": "400_schema"}])
    out = ask(provider())
    assert isinstance(out["data"]["questions"], list)
    assert [r["schema_mode"] for r in fake.log] == ["native", "text"]
    assert out["meta"]["schema_mode"] == "text"


@pytest.mark.parametrize("kind, err", [("safety", "refusal"),
                                       ("max_tokens", "truncated"), ("401", "auth"), ("403", "auth")])
def test_non_retryable_faults_raise_clean_error_once(server, kind, err):
    fake = server([{"kind": kind, "times": 99}])
    with pytest.raises(ProviderError) as e:
        ask(provider())
    assert e.value.kind == err
    assert len(fake.log) == 1          # повтор не поможет — второй запрос не тратим (у бесплатного ключа 20 в сутки)
    assert e.value.message and not e.value.message.isascii()   # объяснение по-русски


def test_network_down_raises_network_after_few_retries(server):
    fake = server([{"kind": "drop", "times": 99}])
    with pytest.raises(ProviderError) as e:
        ask(provider())
    assert e.value.kind == "network"
    assert len(fake.log) == 3          # 1 + 2 повтора, другая модель от обрыва сети не спасёт


def test_rpm_window_holds_under_parallel_lenses(server, monkeypatch):
    """Пять параллельных этапов при окне 2 запроса за 1,5 с: на сервер не больше 2 запросов за любое окно."""
    monkeypatch.setattr(gemini, "RATE_WINDOW_S", 1.5)
    fake = server()
    p = gemini.GeminiProvider(env={"GEMINI_API_KEY": "fake-key", "GEMINI_RPM": "2"})
    errors = []

    def worker():
        try:
            ask(p)
        except Exception as exc:  # pragma: no cover - видно в assert ниже
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)
    assert not errors, errors
    times = sorted(r["t"] for r in fake.log)
    assert len(times) == 5
    for i, t in enumerate(times):
        in_window = [x for x in times[i:] if x - t < 1.5 - 0.2]   # запас на дрожание потоков
        assert len(in_window) <= 2, times
    assert times[-1] - times[0] >= 2 * 1.5 - 0.5                  # 5 запросов при 2 за окно — минимум 2 окна


def test_schema_rejected_once_keeps_other_schemas_native(server):
    """v2.1: 400 «схема слишком сложная» у одного этапа не переводит остальные этапы модели в режим «текстом»."""
    fake = server([{"kind": "400_schema"}])
    p = provider()
    ask(p)                                            # схема A: 400 → текстом
    other = {"type": "object", "required": ["questions", "note"],
             "properties": {"questions": {"type": "array", "items": {"type": "string"}}, "note": {"type": "string"}}}
    p.invoke(model=None, messages=MESSAGES, schema=other, timeout_s=30, stage="clarify")   # схема B
    ask(p)                                            # снова A — сразу текстом, без второго 400
    assert [r["schema_mode"] for r in fake.log] == ["native", "text", "native", "text"]


@pytest.mark.parametrize("kind", ["finish_recitation", "finish_safety", "finish_spii"])
def test_output_filter_stop_is_retried_once(server, kind):
    """v2.1: ответ остановлен фильтром на выходе (зависит от выборки) — повтор той же модели (было: этап падал)."""
    fake = server([{"kind": kind}])
    out = ask(provider())
    assert isinstance(out["data"]["questions"], list)
    assert kinds(fake) == [("gemini-3.8-flash", kind), ("gemini-3.8-flash", "ok")]


def test_output_filter_stop_twice_goes_to_fallback(server):
    fake = server([{"kind": "finish_recitation", "model": "gemini-3.8-flash", "times": 99}])
    out = ask(provider())
    assert out["model"] == "gemini-3.7-flash"
    assert [m for m, _ in kinds(fake)] == ["gemini-3.8-flash", "gemini-3.8-flash", "gemini-3.7-flash"]


def test_persistent_output_filter_stop_spends_at_most_three_requests(server):
    fake = server([{"kind": "finish_safety", "times": 99}])
    with pytest.raises(ProviderError) as e:
        ask(provider())
    assert e.value.kind == "refusal" and "фильтр" in e.value.message
    assert len(fake.log) == 3      # не перебираем всю цепочку из шести моделей (у каждой 20 запросов в сутки)
