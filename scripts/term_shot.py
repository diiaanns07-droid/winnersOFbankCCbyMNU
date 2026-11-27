"""Снимок окна терминала (№42): команда в tmux заданной ширины → PNG тем же видом, что в настоящем терминале.

    python scripts/term_shot.py docs/plan-v2/wave5/shots/42-terminal.png --until "Система открыта" -- ./start.sh

Команда идёт в настоящем терминале (tmux, 24-битный цвет), ждём строку --until, снимаем экран со всеми цветами
(`tmux capture-pane -e`), рисуем окно в HTML и снимаем Playwright. Нужны tmux и Node с Playwright (в облачной
среде стоят). Сессия tmux закрывается сама — вместе с запущенным сервером. Только для разработки.
"""
from __future__ import annotations

import argparse
import html
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

SGR = re.compile(r"\x1b\[([0-9;:]*)m")
OTHER_ESC = re.compile(r"\x1b(\][^\x07]*\x07|\[[0-9;?]*[A-Za-z])")
# 16 базовых цветов — спокойная тёмная схема (как Windows Terminal «Campbell», чуть мягче)
BASE16 = ["#0c0c0c", "#c50f1f", "#13a10e", "#c19c00", "#0037da", "#881798", "#3a96dd", "#cccccc",
          "#767676", "#e74856", "#16c60c", "#f9f1a5", "#3b78ff", "#b4009e", "#61d6d6", "#f2f2f2"]
FG, BG = "#d7dee7", "#0e1420"


def c256(n: int) -> str:
    if n < 16:
        return BASE16[n]
    if n < 232:
        n -= 16
        r, g, b = n // 36, (n // 6) % 6, n % 6
        lv = [0 if v == 0 else 55 + 40 * v for v in (r, g, b)]
        return "#%02x%02x%02x" % tuple(lv)
    v = 8 + (n - 232) * 10
    return "#%02x%02x%02x" % (v, v, v)


def to_html(screen: str) -> str:
    """Экран tmux (строки с SGR) → строки HTML со span-ами цветов."""
    out_lines = []
    for raw in screen.split("\n"):
        st = {"fg": None, "bg": None, "bold": False, "dim": False, "ul": False, "rev": False}
        parts: list[str] = []
        pos = 0
        for m in list(SGR.finditer(raw)) + [None]:
            end = m.start() if m else len(raw)
            text = OTHER_ESC.sub("", raw[pos:end])
            if text:
                fg, bg = st["fg"], st["bg"]
                if st["rev"]:
                    fg, bg = (bg or BG), (fg or FG)
                style = []
                if fg:
                    style.append(f"color:{fg}")
                if bg:
                    style.append(f"background:{bg}")
                if st["bold"]:
                    style.append("font-weight:700")
                if st["dim"]:
                    style.append("opacity:.6")
                if st["ul"]:
                    style.append("text-decoration:underline")
                t = html.escape(text)
                parts.append(f'<span style="{";".join(style)}">{t}</span>' if style else t)
            if not m:
                break
            pos = m.end()
            codes = [int(x) if x.isdigit() else 0 for x in re.split("[;:]", m.group(1) or "0")]
            i = 0
            while i < len(codes):
                c = codes[i]
                if c == 0:
                    st.update(fg=None, bg=None, bold=False, dim=False, ul=False, rev=False)
                elif c == 1:
                    st["bold"] = True
                elif c == 2:
                    st["dim"] = True
                elif c == 22:
                    st["bold"] = st["dim"] = False
                elif c == 4:
                    st["ul"] = True
                elif c == 24:
                    st["ul"] = False
                elif c == 7:
                    st["rev"] = True
                elif c == 27:
                    st["rev"] = False
                elif 30 <= c <= 37 or 90 <= c <= 97:
                    st["fg"] = BASE16[c - 30 if c < 90 else c - 82]
                elif 40 <= c <= 47 or 100 <= c <= 107:
                    st["bg"] = BASE16[c - 40 if c < 100 else c - 92]
                elif c == 39:
                    st["fg"] = None
                elif c == 49:
                    st["bg"] = None
                elif c in (38, 48) and i + 1 < len(codes):
                    key = "fg" if c == 38 else "bg"
                    if codes[i + 1] == 5 and i + 2 < len(codes):
                        st[key] = c256(codes[i + 2])
                        i += 2
                    elif codes[i + 1] == 2 and i + 4 < len(codes):
                        st[key] = "#%02x%02x%02x" % tuple(codes[i + 2:i + 5])
                        i += 4
                i += 1
        out_lines.append("".join(parts))
    while out_lines and not re.sub(r"<[^>]+>", "", out_lines[-1]).strip():
        out_lines.pop()
    return "\n".join(out_lines)


PAGE = """<!doctype html><meta charset="utf-8"><style>
html,body{{margin:0;background:#e9edf1}}
.win{{display:inline-block;margin:24px;border-radius:10px;overflow:hidden;background:{bg};
  box-shadow:0 18px 50px rgba(11,18,32,.28),0 0 0 1px rgba(11,18,32,.18)}}
.bar{{height:34px;display:flex;align-items:center;justify-content:center;position:relative;background:#1b2332;
  color:#9aa7b6;font:600 13px/1 -apple-system,"Segoe UI",system-ui,sans-serif;letter-spacing:.01em}}
.dots{{position:absolute;left:14px;top:12px;display:flex;gap:8px}}
.dots i{{width:11px;height:11px;border-radius:50%;background:#3a4556;display:block}}
pre{{margin:0;padding:14px 18px 18px;color:{fg};font:15px/1.2 "DejaVu Sans Mono","Cascadia Mono",Menlo,Consolas,monospace;
  font-variant-ligatures:none;white-space:pre;width:{cols}ch}}
</style><div class="win"><div class="bar"><span class="dots"><i></i><i></i><i></i></span>{title}</div><pre>{body}</pre></div>"""

NODE = r"""
const { chromium } = require('playwright');
(async () => {
  const [page, png] = process.argv.slice(2);
  const b = await chromium.launch();
  const p = await b.newPage({ viewport: { width: 1200, height: 400 }, deviceScaleFactor: 2 });
  await p.goto('file://' + page);
  const win = await p.$('.win');
  await win.screenshot({ path: png });
  await b.close();
})();
"""


def tmux(*args: str, check: bool = True) -> str:
    return subprocess.run(["tmux", *args], capture_output=True, text=True, check=check).stdout


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("png")
    ap.add_argument("--until", default="", help="ждать эту строку на экране (регулярное выражение)")
    ap.add_argument("--cols", type=int, default=100)
    ap.add_argument("--rows", type=int, default=34)
    ap.add_argument("--timeout", type=float, default=300)
    ap.add_argument("--settle", type=float, default=1.0, help="секунд после --until (анимация)")
    ap.add_argument("--cwd", default=".")
    ap.add_argument("--title", default="BCC Review")
    ap.add_argument("--prompt", default="~/bcc-review$ ", help="как показать приглашение перед командой")
    ap.add_argument("--first", help="ещё снимок в момент --until (до --send): путь PNG")
    ap.add_argument("--send", help="после --until нажать клавиши (tmux send-keys), например Enter")
    ap.add_argument("--then", default="", help="после --send ждать эту строку и снимать уже её")
    ap.add_argument("--path", help="PATH внутри терминала (например, без claude — как у жюри)")
    argv = list(sys.argv[1:] if argv is None else argv)
    cmd = argv[argv.index("--") + 1:] if "--" in argv else []
    a = ap.parse_args(argv[:argv.index("--")] if "--" in argv else argv)
    if not cmd or not shutil.which("tmux"):
        print("нужны tmux и команда после --", file=sys.stderr)
        return 2
    name = f"shot{os.getpid()}"
    shown = " ".join(cmd)
    inner = f"printf '%s%s\\n' {shlex_quote(a.prompt)} {shlex_quote(shown)}; {' '.join(shlex_quote(c) for c in cmd)}; sleep 3600"
    extra = ["-e", f"PATH={a.path}"] if a.path else []
    tmux("new-session", "-d", "-s", name, "-x", str(a.cols), "-y", str(a.rows), "-c", str(Path(a.cwd).resolve()),
         "-e", "COLORTERM=truecolor", "-e", "LANG=C.UTF-8", *extra, "sh", "-c", inner)

    def wait_for(pattern: str) -> bool:
        end = time.monotonic() + a.timeout
        while time.monotonic() < end:
            if re.search(pattern or r"\S", tmux("capture-pane", "-p", "-t", name)):
                time.sleep(a.settle)
                return True
            time.sleep(0.3)
        print(f"не дождались «{pattern}» за {a.timeout} с; экран:\n" + tmux("capture-pane", "-p", "-t", name),
              file=sys.stderr)
        return False

    try:
        tmux("set-option", "-t", name, "status", "off")
        if not wait_for(a.until):
            return 1
        screens = []
        if a.send:
            if a.first:
                screens.append((a.first, tmux("capture-pane", "-p", "-e", "-t", name)))
            tmux("send-keys", "-t", name, *a.send.split())
            if not wait_for(a.then):
                return 1
        screens.append((a.png, tmux("capture-pane", "-p", "-e", "-t", name)))
    finally:
        tmux("kill-session", "-t", name, check=False)
    for png, screen in screens:
        _render(png, screen, a)
    return 0


def _render(png: str, screen: str, a: argparse.Namespace) -> None:
    body = to_html(screen)
    with tempfile.TemporaryDirectory() as d:
        page = Path(d) / "term.html"
        page.write_text(PAGE.format(bg=BG, fg=FG, cols=a.cols, title=html.escape(a.title), body=body), encoding="utf-8")
        js = Path(d) / "shot.js"
        js.write_text(NODE, encoding="utf-8")
        root = subprocess.run(["npm", "root", "-g"], capture_output=True, text=True).stdout.strip()
        env = dict(os.environ, NODE_PATH=root)
        Path(png).parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["node", str(js), str(page), str(Path(png).resolve())], check=True, env=env)
    print(f"снимок: {png}")


def shlex_quote(s: str) -> str:
    import shlex

    return shlex.quote(s)


if __name__ == "__main__":
    raise SystemExit(main())
