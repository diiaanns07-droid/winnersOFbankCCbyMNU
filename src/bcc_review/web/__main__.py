"""Точка входа: ``python -m bcc_review.web``.

Примеры::

    python -m bcc_review.web                         # общий движок, http://127.0.0.1:8015
    python -m bcc_review.web --provider gemini       # явный провайдер
    python -m bcc_review.web --engine dev            # подставной движок для разработки UI
    python -m bcc_review.web --demo demo_bundle      # плюс сохранённые прогоны (только просмотр)
    python -m bcc_review.web pack RUN_ID --out demo_bundle   # сохранить прогон для демонстрации
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import webbrowser
from pathlib import Path

from .engine import load_dotenv, resolve_engine
from .service import Settings
from .store import RunStore, StoreError, utcnow


def _serve(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog="python -m bcc_review.web", description="Веб-демо ревью ТЗ для аналитика")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8015)
    p.add_argument("--data-dir", default=".bcc_web", help="хранилище запусков (по умолчанию ./.bcc_web)")
    p.add_argument("--engine", default="auto", help="auto | dev | модуль:функция (по умолчанию auto — общий движок)")
    p.add_argument("--provider", choices=["anthropic", "gemini", "mock"], default=None)
    p.add_argument("--mock-script", default=None, help="сценарий mock-провайдера движка (JSON), только с --provider mock")
    p.add_argument("--cache-dir", default=None, help="кэш ответов модели движка (по умолчанию — как у CLI)")
    p.add_argument("--export", default="html", help="экспорты движка через запятую (по умолчанию html — артефакт №13)")
    p.add_argument("--workers", type=int, default=1, help="одновременных запусков (по умолчанию 1)")
    p.add_argument("--demo", default=None, help="каталог сохранённых прогонов для режима демонстрации")
    p.add_argument("--demo-answers", default=None, help="файл демонстрационных ответов команды (формат answers.md)")
    p.add_argument("--env-file", default=".env")
    p.add_argument("--open", action="store_true", help="открыть браузер")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args(argv)

    loaded = load_dotenv(Path(args.env_file))
    engine = resolve_engine(args.engine)

    from .app import create_app, make_server

    settings = Settings(
        provider=args.provider,
        export=tuple(x.strip() for x in args.export.split(",") if x.strip()),
        demo_answers=Path(args.demo_answers) if args.demo_answers else None,
        mock_script=Path(args.mock_script) if args.mock_script else None,
        cache_dir=Path(args.cache_dir) if args.cache_dir else None,
    )
    app = create_app(args.data_dir, engine, settings=settings, workers=args.workers, demo_dir=args.demo)
    server = make_server(app, args.host, args.port, verbose=args.verbose)
    url = f"http://{args.host}:{server.server_address[1]}/"
    pf = app.service.preflight()
    print(f"bcc_review.web: {url}")
    print(f"  движок:   {engine.target if engine.available else 'НЕ НАЙДЕН — ' + (engine.error or '')}")
    print(f"  данные:   {Path(args.data_dir).resolve()}")
    print(f"  ключ:     {pf['note']}" + (f" (из {args.env_file}: {', '.join(loaded)})" if loaded else ""))
    if args.demo:
        print(f"  демо:     {Path(args.demo).resolve()} (только просмотр)")
    if args.open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("остановлено")
    finally:
        server.server_close()
    return 0


def _pack(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog="python -m bcc_review.web pack", description="Сохранить прогоны для режима демонстрации")
    p.add_argument("run_ids", nargs="+")
    p.add_argument("--data-dir", default=".bcc_web")
    p.add_argument("--out", required=True)
    args = p.parse_args(argv)
    store = RunStore(args.data_dir, read_only=True)
    out = Path(args.out)
    (out / "runs").mkdir(parents=True, exist_ok=True)
    todo, done = list(args.run_ids), []
    while todo:
        rid = todo.pop()
        if rid in done:
            continue
        try:
            rec = store.load(rid)
        except StoreError as exc:
            print(f"{rid}: {exc}", file=sys.stderr)
            return 2
        if rec["status"] not in ("complete", "partial"):
            print(f"{rid}: статус {rec['status']} — сохраняются только готовые прогоны", file=sys.stderr)
            return 2
        if rec.get("parent_run_id"):
            todo.append(rec["parent_run_id"])  # для сравнения нужна и родительская редакция
        shutil.copytree(store.run_dir(rid), out / "runs" / rid, dirs_exist_ok=True, ignore=shutil.ignore_patterns("tmp", "claims", ".*.tmp"))
        done.append(rid)
    (out / "MANIFEST.json").write_text(
        json.dumps({"packed_at": utcnow(), "runs": done, "note": "сохранённые прогоны для демонстрации; не живой анализ"}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"сохранено {len(done)} прогон(ов) в {out.resolve()}")
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["pack"]:
        return _pack(argv[1:])
    return _serve(argv)


if __name__ == "__main__":
    raise SystemExit(main())
