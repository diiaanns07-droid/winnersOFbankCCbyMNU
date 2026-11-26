"""Штатный CLI ``bcc_review`` с журналом происхождения: что загрузил реестр модулей и были ли внешние вызовы.

    python tests/p07/offline_cli.py verify REPORT.json SOURCE [--json]

Делает то же, что ``python -m bcc_review …``, но
* записывает каждую реализацию, которую загрузил ``bcc_review.runtime.modules`` (слот, модуль и файл);
* запрещает сетевые соединения и считает попытки;
* перечисляет импортированные модули провайдеров (``bcc_review.providers.*``, ``anthropic``, ``google.*``).

Журнал идёт в stderr строками ``[p07-offline] …``; код выхода — код CLI.
"""

from __future__ import annotations

import socket
import sys


def main(argv: list[str]) -> int:
    from bcc_review.runtime import modules

    loaded: list[str] = []
    attempts: list[object] = []
    original = modules._load

    def logged_load(path: str):  # noqa: ANN202 — тот же контракт, что у modules._load
        func = original(path)
        loaded.append(f"{path} ({sys.modules[path.split(':')[0]].__file__})")
        return func

    def deny(*args: object, **kwargs: object) -> None:
        attempts.append(args[1:] if len(args) > 1 else args)
        raise OSError("p07-offline: сетевые соединения запрещены")

    modules._load = logged_load
    socket.socket.connect = deny  # type: ignore[method-assign]
    socket.socket.connect_ex = deny  # type: ignore[method-assign]
    socket.create_connection = deny  # type: ignore[assignment]
    before = set(sys.modules)
    from bcc_review.cli import main as cli_main

    code = cli_main(argv)
    providers = sorted(m for m in set(sys.modules) - before
                       if m.startswith(("bcc_review.providers", "anthropic", "google")))
    for line in loaded:
        print(f"[p07-offline] загружено: {line}", file=sys.stderr)
    print(f"[p07-offline] сетевых соединений: {len(attempts)}; модули провайдеров: {', '.join(providers) or 'нет'}; "
          f"код выхода: {code}", file=sys.stderr)
    return code


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
