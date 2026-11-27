#!/usr/bin/env python3
"""Сверяет слова документа в кадрах с исходным ТЗ банка.

    python3 tools/verify-quotes.py                      # скачает ТЗ @ 928c1aa с GitHub
    python3 tools/verify-quotes.py путь/к/requirements.md  # или возьмёт локальный файл
                                                         # (например, release/input/requirements.md из bcc/integration)

Проверяет:
  * файл ТЗ — тот самый (SHA-256 совпадает с исходником организаторов @ 928c1aa);
  * каждый элемент data-voice="doc" в index.html дословно стоит в строке data-tz-line;
  * числа сценария кадра A (48 500, 1 500, 50 000 ₸) есть в строке 63 — первом критерии приёмки.
Только стандартная библиотека Python.
"""
import hashlib
import html.parser
import pathlib
import sys
import urllib.request

SOURCE_URL = ("https://raw.githubusercontent.com/BCC-HUB/ai-requirements-validator-task/"
              "928c1aa364265426105b69ba7a3444eac11b22db/docs/requirements.md")
SOURCE_SHA256 = "e7dae55e5453a250d93e335f5ff9c7f775f4457ccddd333f4a67e47b20d74381"
SCENARIO_LINE = 63
SCENARIO_NUMBERS = ["48 500 ₸", "1 500 ₸", "50 000 ₸"]

ROOT = pathlib.Path(__file__).resolve().parent.parent


class DocVoice(html.parser.HTMLParser):
    """Собирает текст элементов с data-voice="doc" и их data-tz-line."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.quotes = []
        self._cur = None  # [tag, line, parts, depth]

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if self._cur is None and a.get("data-voice") == "doc":
            self._cur = [tag, int(a["data-tz-line"]), [], 1]
        elif self._cur is not None and tag == self._cur[0]:
            self._cur[3] += 1

    def handle_endtag(self, tag):
        if self._cur is not None and tag == self._cur[0]:
            self._cur[3] -= 1
            if self._cur[3] == 0:
                _, line, parts, _ = self._cur
                self.quotes.append((line, " ".join("".join(parts).split())))
                self._cur = None

    def handle_data(self, data):
        if self._cur is not None:
            self._cur[2].append(data)


def main() -> int:
    if len(sys.argv) > 1:
        raw = pathlib.Path(sys.argv[1]).read_bytes()
        origin = sys.argv[1]
    else:
        with urllib.request.urlopen(SOURCE_URL, timeout=30) as r:
            raw = r.read()
        origin = SOURCE_URL
    digest = hashlib.sha256(raw).hexdigest()
    ok = True
    print(f"ТЗ: {origin}\nSHA-256: {digest}", "— совпадает с @ 928c1aa" if digest == SOURCE_SHA256 else "— НЕ совпадает с @ 928c1aa")
    ok &= digest == SOURCE_SHA256

    lines = raw.decode("utf-8-sig").splitlines()
    p = DocVoice()
    p.feed((ROOT / "index.html").read_text(encoding="utf-8"))
    if not p.quotes:
        print("В index.html нет ни одного data-voice=\"doc\"")
        return 1
    for line, text in p.quotes:
        src = lines[line - 1] if 0 < line <= len(lines) else ""
        hit = text in src
        ok &= hit
        print(f"{'OK ' if hit else 'НЕТ'} строка {line}: «{text}»")
        if not hit:
            print(f"     в исходнике: {src}")

    scen = lines[SCENARIO_LINE - 1].replace(" ", " ")
    for n in SCENARIO_NUMBERS:
        hit = n in scen
        ok &= hit
        print(f"{'OK ' if hit else 'НЕТ'} строка {SCENARIO_LINE}: число {n} (сценарий кадра A)")
    print("Итог:", "все слова документа сверены" if ok else "есть расхождения")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
