"""Длинный запуск: одна отправка формы — один run — одно задание — одна обработка движком.

Сервер поднимается штатно, отдельным процессом ``python -m bcc_review.web``; движок —
синтетический медленный ``tests/p15/slow_engine.py`` в штатном слоте (``BCC_REVIEW_ENGINE``,
только поля RunOptions). Обработки считает сам движок (``calls.jsonl``), независимо от веба.

Доказательства (счётчик до/после, run_id, job_id, run_id из report.json) пишутся в
``$P15_EVIDENCE/<тест>.json``, если переменная задана.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import socket
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pytest

from . import slow_engine
from .conftest import CASE, ROOT, Client, CountingEngine, encode_multipart

HERE = Path(__file__).parent
RUN_URL = re.compile(r"^/runs/(\d{8}-\d{6}-[0-9a-f]{6})(\?dup=1)?$")


def _env(counter: Path, plan: str, delay: float) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k not in ("ANTHROPIC_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY", "BCC_REVIEW_ENGINE")}
    env.update({
        "BCC_REVIEW_ENGINE": "tests.p15.slow_engine:run_review",  # штатный слот общего движка
        "P15_SLOW_DIR": str(counter), "P15_SLOW_PLAN": plan, "P15_SLOW_DELAY": str(delay),
        "PYTHONPATH": os.pathsep.join([str(ROOT), str(ROOT / "src"), env.get("PYTHONPATH", "")]).rstrip(os.pathsep),
        "PYTHONUNBUFFERED": "1",
    })
    return env


def _cmd(data: Path) -> list[str]:
    return [sys.executable, "-m", "bcc_review.web", "--port", "0", "--data-dir", str(data),
            "--provider", "mock", "--env-file", str(data.parent / "no.env")]


class SlowServer:
    def __init__(self, tmp: Path, *, plan: str, delay: float, data: Path | None = None):
        self.counter = tmp / "counter"
        self.data = data or tmp / "data"
        self.env = _env(self.counter, plan, delay)
        self.proc = subprocess.Popen(_cmd(self.data), cwd=ROOT, env=self.env, stdout=subprocess.PIPE,
                                     stderr=subprocess.STDOUT, text=True, encoding="utf-8")
        self.banner: list[str] = []
        url = None
        deadline = time.time() + 30
        while time.time() < deadline and url is None:
            line = self.proc.stdout.readline()
            if not line:
                break
            self.banner.append(line.rstrip())
            m = re.search(r"(http://127\.0\.0\.1:\d+)/", line)
            url = m.group(1) if m else None
        assert url, "сервер не поднялся: " + "\n".join(self.banner)
        threading.Thread(target=self.proc.stdout.read, daemon=True).start()  # не дать трубе заполниться
        self.client = Client(url)
        health = self.client.get_json("/healthz")
        assert health["engine_available"] and health["engine"]["target"] == "tests.p15.slow_engine:run_review", health

    def calls(self) -> list[dict[str, Any]]:
        return slow_engine.starts(self.counter)

    def ends(self) -> list[dict[str, Any]]:
        return [c for c in slow_engine.calls(self.counter) if c.get("event") == "end"]

    def stop(self) -> None:
        if self.proc.poll() is None:
            self.proc.terminate()
            self.proc.wait(10)


@pytest.fixture
def slow_server(tmp_path):
    started: list[SlowServer] = []

    def start(*, plan: str = "complete", delay: float = 2.0, data: Path | None = None, sub: str = "") -> SlowServer:
        srv = SlowServer(tmp_path / sub if sub else tmp_path, plan=plan, delay=delay, data=data)
        started.append(srv)
        return srv

    yield start
    for srv in started:
        srv.stop()


def evidence(name: str, data: dict[str, Any]) -> None:
    out = os.environ.get("P15_EVIDENCE")
    if out:
        Path(out).mkdir(parents=True, exist_ok=True)
        (Path(out) / f"{name}.json").write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def form_key(client: Client) -> str:
    """upload_key из настоящей формы главной страницы (тот, что отправит браузер)."""
    html = client.get("/")[2].decode()
    return re.search(r'name="upload_key" value="([^"]+)"', html).group(1)


def post_form(client: Client, key: str, data: bytes) -> tuple[int, str]:
    code, hdr, _ = client.post_form("/api/runs", {"upload_key": key}, {"file": ("case_ab.md", data)}, json_accept=False)
    return code, hdr.get("Location", "")


def run_of(location: str) -> str:
    m = RUN_URL.match(location)
    assert m, location
    return m.group(1)


def wait_final(client: Client, rid: str, timeout: float = 60) -> dict[str, Any]:
    return client.wait(rid, timeout=timeout)


def report_sha(client: Client, rid: str) -> str:
    code, _, body = client.get(f"/runs/{rid}/files/report.json")
    assert code == 200
    return hashlib.sha256(body).hexdigest()


# --------------------------------------------------------------------------- 1. одна форма
def test_one_form_twice_refresh_and_link_is_one_run_one_processing(slow_server):
    srv = slow_server(plan="complete", delay=3.0)
    c = srv.client
    case = CASE.read_bytes()
    before = {"engine_calls_counter": len(srv.calls()), "healthz_engine_calls": c.get_json("/healthz")["engine_calls"]}
    assert before == {"engine_calls_counter": 0, "healthz_engine_calls": 0}

    key = form_key(c)
    # Одна форма отправлена дважды одновременно (двойной клик / повтор запроса браузером).
    with ThreadPoolExecutor(2) as pool:
        posts = list(pool.map(lambda _: post_form(c, key, case), range(2)))
    assert [code for code, _ in posts] == [303, 303]
    rid = run_of(posts[0][1])
    assert {run_of(loc) for _, loc in posts} == {rid}
    assert sorted(loc.endswith("?dup=1") for _, loc in posts) == [False, True]

    # Обновление страницы во время обработки (и тот же POST ещё раз — «обновить» на странице ответа формы).
    refreshes, seen_running, resubmits = 0, 0, []
    while True:
        code, _, page = c.get(f"/runs/{rid}")
        assert code == 200
        refreshes += 1
        st = c.get_json(f"/api/runs/{rid}")
        assert c.request("HEAD", f"/runs/{rid}")[0] == 200
        if st["final"]:
            break
        if st["status"] == "running":
            seen_running += 1
            assert 'data-run-status="running"' in page.decode() or 'data-run-status="complete"' in page.decode()
            if seen_running == 2:
                resubmits.append(post_form(c, key, case))
        time.sleep(0.3)
    assert seen_running >= 3, "обновления должны прийтись на время обработки"
    assert resubmits and resubmits[0] == (303, f"/runs/{rid}?dup=1")
    assert st["status"] == "complete"

    # Ссылка после завершения: результат открывается, нового анализа нет.
    page = c.get(f"/runs/{rid}")[2].decode()
    assert 'data-run-status="complete"' in page and 'id="verdict"' in page and 'id="job"' in page
    assert "уже было принято" in c.get(f"/runs/{rid}?dup=1")[2].decode()
    after_link = post_form(c, key, case)
    assert after_link == (303, f"/runs/{rid}?dup=1")

    calls = srv.calls()
    st = c.get_json(f"/api/runs/{rid}")
    report = json.loads(c.get(f"/runs/{rid}/files/report.json")[2])
    health = c.get_json("/healthz")
    after = {"engine_calls_counter": len(calls), "healthz_engine_calls": health["engine_calls"]}
    assert after == {"engine_calls_counter": 1, "healthz_engine_calls": 1}
    assert calls[0]["run_id"] == rid and calls[0]["pid"] == health["server"]["pid"]
    assert [e["outcome"] for e in srv.ends()] == ["complete"]
    assert health["skipped_executions"] == 0
    job = st["job"]
    assert job["job_id"].startswith("job-") and job["engine_calls"] == 1 and job["run_id"] == rid
    assert st["execution"]["job_id"] == job["job_id"]
    assert report["run"]["run_id"] == rid
    assert [p.name for p in (srv.data / "runs").iterdir()] == [rid]
    evidence("one_form", {
        "before": before, "after": after, "posts": [list(p) for p in posts], "refreshes": refreshes,
        "refreshes_while_running": seen_running, "resubmit_while_running": list(resubmits[0]),
        "resubmit_after_done": list(after_link), "run_id": rid, "job_id": job["job_id"],
        "report_run_id": report["run"]["run_id"], "report_sha256": report_sha(c, rid), "status": st["status"],
        "engine_counter": slow_engine.calls(srv.counter),
    })


# --------------------------------------------------------------------------- 2. две формы — два анализа
def test_same_content_from_two_forms_is_two_deliberate_analyses(slow_server):
    srv = slow_server(plan="complete", delay=1.0)
    c = srv.client
    case = CASE.read_bytes()
    k1, k2 = form_key(c), form_key(c)
    assert k1 != k2  # каждая отрисовка главной — свой экземпляр формы
    r1 = run_of(post_form(c, k1, case)[1])
    r2 = run_of(post_form(c, k2, case)[1])
    assert r1 != r2
    for rid in (r1, r2):
        assert wait_final(c, rid)["status"] == "complete"
    assert sorted(x["run_id"] for x in srv.calls()) == sorted([r1, r2])
    # Осознанная вторая загрузка не скрыта: обе страницы ссылаются друг на друга.
    p2 = c.get(f"/runs/{r2}")[2].decode()
    assert 'id="same-content"' in p2 and f"/runs/{r1}" in p2 and "самостоятельный анализ" in p2
    assert c.get_json(f"/api/runs/{r1}")["same_content_runs"] == [r2]
    # Та же форма с другим файлом — не повтор, а новый анализ.
    r3 = run_of(post_form(c, k1, case + b"\n<!-- v2 -->\n")[1])
    assert r3 not in (r1, r2)
    wait_final(c, r3)
    assert len(srv.calls()) == 3
    evidence("two_forms_same_content", {"runs": [r1, r2], "same_form_other_file": r3, "engine_calls_counter": len(srv.calls())})


# --------------------------------------------------------------------------- 3. повтор после технической ошибки
def test_retry_after_technical_error_is_separate_explicit_run(slow_server):
    srv = slow_server(plan="network,complete", delay=1.0)
    c = srv.client
    r1 = run_of(post_form(c, form_key(c), CASE.read_bytes())[1])
    st1 = wait_final(c, r1)
    assert st1["status"] == "failed" and st1["error"]["kind"] == "network"
    page = c.get(f"/runs/{r1}")[2].decode()
    assert "Повторить запуск" in page and 'id="retries"' not in page
    assert len(srv.calls()) == 1

    # Явно выбранный повтор, кнопка нажата дважды: один новый запуск.
    with ThreadPoolExecutor(2) as pool:
        res = list(pool.map(lambda _: c.post_form(f"/runs/{r1}/retry", {"offline": "0"}, json_accept=False), range(2)))
    locs = [h["Location"] for _, h, _ in res]
    r2 = run_of(locs[0])
    assert {run_of(x) for x in locs} == {r2} and r2 != r1
    st2 = wait_final(c, r2)
    assert st2["status"] == "complete" and st2["retry_of"] == r1 and st2["reason"] == "retry"
    assert st2["lineage_id"] == st1["lineage_id"] and st2["revision"] == st1["revision"]
    assert st2["job"]["job_id"] != st1["job"]["job_id"]
    assert [x["run_id"] for x in srv.calls()] == [r1, r2]

    # Исходный запуск сохранил статус и причину; на его странице — ссылка на повтор, а не та же кнопка.
    st1_after = c.get_json(f"/api/runs/{r1}")
    assert st1_after["status"] == "failed" and st1_after["error"] == st1["error"]
    assert [r["run_id"] for r in st1_after["retry"]["retries"]] == [r2]
    page = c.get(f"/runs/{r1}")[2].decode()
    assert 'id="retries"' in page and f"/runs/{r2}" in page
    assert ">Повторить запуск<" not in page          # этот режим уже повторён
    assert "Проверить только по правилам" in page    # другой режим — отдельная операция, доступна
    # Тот же повтор из старой вкладки — открывается уже созданный, второго анализа нет.
    code, hdr, _ = c.post_form(f"/runs/{r1}/retry", {"offline": "0"}, json_accept=False)
    assert (code, hdr["Location"]) == (303, f"/runs/{r2}?dup=1")
    # Успешный запуск не повторяется.
    assert c.post_form(f"/runs/{r2}/retry", {"offline": "0"})[0] == 409
    assert len(srv.calls()) == 2
    evidence("retry_after_error", {
        "failed_run_id": r1, "failed_job_id": st1["job"]["job_id"], "error": st1["error"]["kind"],
        "retry_run_id": r2, "retry_job_id": st2["job"]["job_id"], "retry_of": st2["retry_of"],
        "retry_posts": [[code, h["Location"]] for code, h, _ in res], "engine_counter_run_ids": [x["run_id"] for x in srv.calls()],
    })


# --------------------------------------------------------------------------- 4. partial
def test_partial_keeps_status_and_result_through_explicit_retries(slow_server):
    srv = slow_server(plan="partial,network,complete", delay=1.0)
    c = srv.client
    r1 = run_of(post_form(c, form_key(c), CASE.read_bytes())[1])
    st1 = wait_final(c, r1)
    assert st1["status"] == "partial" and st1["report"]["mode"] == "rules_only"
    assert "LLM была недоступна" in st1["retry"]["partial_reason"]
    sha1 = report_sha(c, r1)
    for _ in range(3):  # открытия результата не запускают анализ
        page = c.get(f"/runs/{r1}")[2].decode()
    assert 'id="verdict"' in page and 'id="partial-retry"' in page and "Повторить с LLM" in page
    assert len(srv.calls()) == 1

    code, hdr, _ = c.post_form(f"/runs/{r1}/retry", {"offline": "0"}, json_accept=False)
    r2 = run_of(hdr["Location"])
    c.wait(r2, until=lambda s: s["status"] == "running")
    during = c.get_json(f"/api/runs/{r1}")
    assert during["status"] == "partial" and report_sha(c, r1) == sha1  # пока идёт повтор, результат на месте
    st2 = wait_final(c, r2)
    assert st2["status"] == "failed" and st2["retry_of"] == r1
    # Повтор упал — актуальным остаётся partial-результат первого запуска.
    st1b = c.get_json(f"/api/runs/{r1}")
    assert st1b["status"] == "partial" and st1b["latest_run_id"] == r1 and report_sha(c, r1) == sha1
    assert 'id="not-latest"' not in c.get(f"/runs/{r1}")[2].decode()

    # Следующий повтор — со страницы упавшего повтора.
    assert "Повторить запуск" in c.get(f"/runs/{r2}")[2].decode()
    r3 = run_of(c.post_form(f"/runs/{r2}/retry", {"offline": "0"}, json_accept=False)[1]["Location"])
    st3 = wait_final(c, r3)
    assert st3["status"] == "complete" and st3["retry_of"] == r2
    st1c = c.get_json(f"/api/runs/{r1}")
    assert st1c["status"] == "partial" and st1c["latest_run_id"] == r3 and report_sha(c, r1) == sha1
    page = c.get(f"/runs/{r1}")[2].decode()
    assert 'id="not-latest"' in page and "повтор этой редакции" in page and f"/runs/{r3}" in page
    assert c.get(f"/runs/{r1}/files/report.md?inline=1")[0] == 200
    assert [x["run_id"] for x in srv.calls()] == [r1, r2, r3]
    evidence("partial", {
        "partial_run_id": r1, "partial_report_sha256": sha1, "retry_failed": r2, "retry_complete": r3,
        "partial_status_after": st1c["status"], "latest_run_id": st1c["latest_run_id"],
        "engine_counter_run_ids": [x["run_id"] for x in srv.calls()],
    })


def test_partial_without_technical_cause_is_not_retried(make_server, case_bytes):
    engine = CountingEngine()
    client = make_server(engine)
    rid = client.upload("case_ab.md", case_bytes, offline="1")["run_id"]  # аналитик сам выбрал «только правила»
    st = client.wait(rid)
    assert st["status"] == "partial" and st["retry"]["partial_reason"] is None
    assert 'id="partial-retry"' not in client.get(f"/runs/{rid}")[2].decode()
    code, _, body = client.post_form(f"/runs/{rid}/retry", {"offline": "0"})
    assert code == 409 and "не из-за технического сбоя" in json.loads(body)["error"]
    assert len(engine.calls) == 1 and client.get(f"/runs/{rid}/files/report.json")[0] == 200


# --------------------------------------------------------------------------- 5. обрыв загрузки
def _raw_post(base: str, body: bytes, ctype: str, *, declared: int, send: int) -> str:
    host, port = base.split("//")[1].split(":")
    with socket.create_connection((host, int(port)), timeout=10) as sock:
        head = (f"POST /api/runs HTTP/1.1\r\nHost: {host}:{port}\r\nContent-Type: {ctype}\r\n"
                f"Content-Length: {declared}\r\nAccept: application/json\r\n\r\n")
        sock.sendall(head.encode() + body[:send])
        sock.shutdown(socket.SHUT_WR)  # клиент ушёл: обновил страницу посреди отправки
        chunks = []
        while chunk := sock.recv(65536):
            chunks.append(chunk)
    return b"".join(chunks).decode("utf-8", errors="replace")


def test_upload_cut_mid_body_starts_nothing(make_server, case_bytes):
    engine = CountingEngine()
    client = make_server(engine)
    body, ctype = encode_multipart({"upload_key": "k" * 24}, {"file": ("case_ab.md", case_bytes)})
    resp = _raw_post(client.base, body, ctype, declared=len(body), send=len(body) * 2 // 3)
    assert " 400 " in resp.splitlines()[0] and "Загрузка оборвалась" in resp
    # Длина совпала, но закрывающей границы формы нет — тоже обрыв.
    cut = body[: body.rindex(b"\r\n--")]
    resp = _raw_post(client.base, cut, ctype, declared=len(cut), send=len(cut))
    assert " 400 " in resp.splitlines()[0] and "Загрузка оборвалась" in resp
    assert client.app.store.list_runs() == [] and engine.calls == []
    # Повторная полная отправка той же формы — обычный запуск по целому файлу.
    rid = client.upload("case_ab.md", case_bytes, key="k" * 24)["run_id"]
    assert client.wait(rid)["input"]["size"] == len(case_bytes) and len(engine.calls) == 1


# --------------------------------------------------------------------------- 6. второй процесс над тем же каталогом
def test_second_server_process_on_same_data_dir_refuses(slow_server, tmp_path):
    first = slow_server(plan="complete", delay=3.0)
    c = first.client
    rid = run_of(post_form(c, form_key(c), CASE.read_bytes())[1])
    c.wait(rid, until=lambda s: s["status"] == "running")
    second = subprocess.run(_cmd(first.data), cwd=ROOT, env=first.env, capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert second.returncode == 2, second.stdout + second.stderr
    holder = json.loads((first.data / "server.json").read_text(encoding="utf-8"))
    assert "уже обслуживает другой процесс" in second.stderr and f"pid {holder['pid']}" in second.stderr
    st = wait_final(c, rid)
    assert st["status"] == "complete" and st["error"] is None  # живой прогон не помечен прерванным
    assert len(first.calls()) == 1
    # После остановки первого процесса каталог свободен: новый сервер стартует, готовый прогон не трогает.
    first.stop()
    again = slow_server(plan="complete", delay=1.0, data=first.data, sub="again")
    assert again.client.get_json(f"/api/runs/{rid}")["status"] == "complete"
    evidence("second_process", {"run_id": rid, "second_returncode": second.returncode, "second_stderr": second.stderr.strip(),
                                "holder": holder, "status": st["status"], "engine_calls_counter": len(first.calls())})


# --------------------------------------------------------------------------- 7. браузер
def test_double_submit_reload_and_link_in_browser(slow_server, tmp_path):
    from .test_browser import _node_env

    env = _node_env()
    if env is None:
        pytest.skip("нет node + playwright")
    srv = slow_server(plan="complete", delay=4.0)
    out = Path(os.environ.get("P15_SHOTS") or tmp_path / "shots")
    out.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(["node", str(HERE / "e2e_long_run.js"), srv.client.base, str(CASE), str(out)],
                          env=env, capture_output=True, text=True, timeout=180)
    result = json.loads((proc.stdout.strip().splitlines() or ["{}"])[-1])
    assert proc.returncode == 0, result.get("error") or proc.stderr
    rid = result["run_id"]
    assert result["reloads_while_running"] >= 2 and result["final_status"] == "complete"
    assert result["second_submit_url"].split("/runs/")[1].split("?")[0] == rid
    assert [x["run_id"] for x in srv.calls()] == [rid]
    assert [p.name for p in (srv.data / "runs").iterdir()] == [rid]
    evidence("browser", {**result, "engine_counter_run_ids": [x["run_id"] for x in srv.calls()]})


# --------------------------------------------------------------------------- 8. run_id исполняется один раз
def test_same_run_id_handed_to_executor_twice_calls_engine_once(tmp_path, case_bytes):
    """Заявка claims/exec.json на диске: вторая постановка того же run_id (другой поток, другой
    экземпляр исполнителя после перезапуска) до движка не доходит и итог не перетирает."""
    from bcc_review.web.engine import EngineSpec, Runner
    from bcc_review.web.store import RunStore

    engine = CountingEngine()
    spec = EngineSpec("shared", "tests.p15:CountingEngine", engine, "test")
    store = RunStore(tmp_path / "data")
    rid = store.create_run(original_name="case_ab.md", data=case_bytes, options={"exports": ["html"]}, engine=spec.describe())
    first = Runner(store, spec)
    first._execute(rid)
    done = store.load(rid)
    assert done["status"] == "complete" and len(engine.calls) == 1
    second = Runner(store, spec)  # «другой процесс» над теми же файлами
    second._execute(rid)
    assert len(engine.calls) == 1 and second.skipped_executions == 1
    after = store.load(rid)
    assert after["job"] == done["job"] and after["status"] == "complete"
    assert store.execution(rid)["job_id"] == done["job"]["job_id"]
    assert "повторная обработка не выполнена" in store.events(rid)[-1]["detail"]
