"""BCC AI в терминале (№40): первое знакомство до браузера.

    from bcc_review.v2.web import tty_agent
    provider = tty_agent.greet(port, env_path)   # перед тем как открыть браузер; → 'gemini', 'anthropic', …

Одна команда — и в этом же окне появляется тот же пиксельный дрон, что в вебе (кадры сняты с
``assets/agent.js``: ``BCCAgent._pixels``), моргает и знакомится. Ключа нет — просит ключ Gemini или Claude
скрытым вводом, проверяет его тем же кодом, что ``python -m bcc_review doctor --live`` (≤ 10 с), предлагает
запомнить в ``.env``. Ключ уже есть — «С возвращением!» и сразу дальше. Без терминала (двойной щелчок, Docker,
вывод в файл) ничего не спрашивает: окно ключа ждёт в браузере, ``/welcome``.

Цвет: 24 бита (``COLORTERM=truecolor``, Windows Terminal, консоль Windows 10+ после включения VT), иначе 256
цветов, иначе маленький ASCII (``NO_COLOR``, ``TERM=dumb``, кодировка без «▀»). Без зависимостей.

Что возвращает: провайдер, которым система будет думать (``claude_cli``, ``gemini``, ``anthropic``, ``openai``),
``offline`` — человек выбрал «без ключа», ``""`` — решать будет окно ключа в браузере (нет терминала).
"""
from __future__ import annotations

import atexit
import base64
import os
import re
import shutil
import sys
import threading
import time
import zlib
from pathlib import Path
from typing import Any, Callable, Mapping, TextIO

# ─────────────────────────────── кадры дрона ───────────────────────────────
# Сетка 80×80 из agent.js, вырезана рамка дрона без луча (x 7…73, y 18…61): 67×44 px → 22 строки полублоков.
_W, _H = 67, 44
_PALETTE = (
    "#334155", "#121826", "#FFFFFF", "#CBD5E1", "#E2E8F0", "#94A3B8", "#F2C94C", "#FFF3C4",
    "#CAA166", "#64748B", "#475569", "#34D36A", "#21A049", "#8F652A", "#0E1525", "#7DD3FC",
    "#162138", "#EEFFF4", "#1E293B", "#151E2E", "#090E1A", "#38BDF8", "#F2FEFF", "#5ED6FF",
    "#E0F7FF", "#FF4D5E", "#FFF1F2", "#6B1825",
)
_FRAMES_Z = {
    "idle": (
        "eNq1lomSgyAQRHVwRbKsidf//+r2cKgYrqy1HctCaN5MJhho2sZ9iGhvN3HFvUKIrvvq+r6Xg8Id7Q59UQL6Mfp1eGE+e2kYBmrq9O59"
        "cK9kkXtKK+MlxapLI+GlllWJSHi5n/oaBlyJaPihUGWqIMBFcR89WCVG3lXDKHnMOOVVikIAfIcaLs+AFPJ0xoeX1Gpve0gVYZeSP2q8"
        "dlIFIVmIIsOuOrzJw7ukfS+8pbBw+TWMiyFZhBvlWM+4GJJleAQAQryeryikAsFxePY0TVrryYvbFmEZeQSSeJlZ8zx7hmsfaSQRKDgp"
        "MimYWZ6xt4EYrS2BIKHpjNAnhD4QJCQlEboOIdOI6xfhS5taBoiFcOXKeakFIHoOa7FAecSZoYO7IZQRNg0jxL/c9ySW7ArnOOkFnk8C"
        "CBtgZEhU41hIwjFWY42LaM0TLGNlSEIYKxDAWEPZiZe+0k4TTHB7eAit2DKDvynkzev5UPORmLBt22LPEn8SKSaAoW4hxH3Epu8h2tbU"
        "ovb0k2IstwifncCyi6T5d/0CpBcuyQ=="
    ),
    "blink": (
        "eNq1louWgyAMRHWwIl3W2qr//6ubGKyivFrPTh8HYbhJY6xWdeVeAN7jKqywVynVNLembVvdGfqmcUNzQQLN0+pt85J570XXdajKdPbe"
        "eVaz4I7iSnhhWGVpRLyoWYWIiJfn0ZYwyBWJRieKqowCArkQ9uHOyjHSrhJGzrOsI61cFBDgx1d3OCZIJk9nvK/S1rzHK6SI8JbRv6Y/"
        "TqKAEC1EliFdR1dyd5aW62K1ZBqXL8OwGJJEuFWO9QiLIUnGiiCAUsNjCEIKEByHdz/PEoQw0ghKYniGtaURRVDBYRBMYWWgF1sEAWVR"
        "gIDSiCLsHmFZbus6FoSOI7wfYl+sZaN1Y4cYQe9UOf0s7Mt9dlmMpDTCL4aV8Fsp8ghJYycKv28tIYzJDuc48QZPJ0EICdAzJKi+zyTh"
        "GNNiDQuY0gRhTAyJiNYyBGJMvmTjYS53p/E2uHu4Dy24ZXp/U5Q39/Om6iMxYZ7nUZ4lvhIME4hhLiHUdcRsryHqeqlF6dNPjDFeInz2"
        "BJZskurf9Qez/i7z"
    ),
    "look": (
        "eNq1louWgjAMRCFFSt0usjz+/1d30rQg2pfL2RE9oUxuQwlC0zb+Q0R73MQV9yqluu7W9X2vB4NfxB3GogSM4+jt8ML87KVhGKip07v3"
        "zqOaRX4vrYyXDKuujISXWlYlIuHlceprGHAlZsOFwipTBQEuivvoziox8q4aRsnjjlNepVkIgK+zhpd9QAp1euM9SFuzxwFSRdhl9LcZ"
        "XwepgpBciCJDug538vAuLfdFsBQal2/DuBiSRfijPNcjLoZkGQEBgFKTtXZPPWKqQPA8jwlZ8zzbH5GPBSGMPAJFTC4rMI74KCOJwIKT"
        "AcKl2SdEiIEYxZZAkLJUgSClKYmwdQidRpxPhM+f8+zTujjEQthyyykIuQoWG3/3lRUElEcEBpfgk13sCWWElBFpKt9aQliyHc7zpBs8"
        "XwQQMsHIkKjGsVCEZ6zOGhfRmicIY2VIQjhWIICxniWJL2OlJ80pwT/Dz9CKR+bpbwp1cz8faj4SE7ZtW+Rd4k8is6iNGeYKYrPXEVer"
        "aFu3FrVvPynGconw2RtYtkmaf9cvUuUuvg=="
    ),
    "analyzing0": (
        "eNqllouSgjAMRSFlKXV3UYan//+je9MUtdKXy+0MQnt7EmMQqrpyg4ge51VYYa9Sqmm+mrZtdWdwxHmDuSAB81j9enphfvVS13VUleno"
        "vfCsZpG7iivhJcMqSyPipZpViIh4eZ7aEgZckWj4oVBlKiDARWEfXVg5RtpVwsh57DqllYtCAHz76t6uAcnk6YyXXfrHPM53SBHhIaN/"
        "Tf8+SQWEaCGyDOk63MndUVrui92SaVy+DcNiSBLhVjnWNSyGJBk7AgClbtdbEFKA4Di8ezhKEMJII5DEbViWBZvk6EEog0DByQAxLOu6"
        "Lu7oM6gXWwRB40ghhMZ4QZDS9CliwxgsShA6jnh+Eb8WjND20yIQZ0yWUxB2+17MzUF2BJRGuDTW9VBMS8gjJA3IZnFsLSGMyQ7nOPEG"
        "TycBhAToGRJU32eScIzJWsMimtIEYUwMiQhrGQIYky/Z+DaXe9J4G9wz3IcWPDK9vynkzf38VPWRmDDP8yjvEv8SGSaAYc4g1HnEvJ1E"
        "1LWtRenbT4wxniJ89gaWbJJThK2637ec6Q/D1jF6"
    ),
    "analyzing1": (
        "eNqlloFygyAMhjVYka6z7WGVvf+LLiGoowKh8/eOQ/j5SFMQmrYJDwBs9SattFcp1XWXru97PRgssd5hW5KA7dh72b1o/uuFYRigqdPR"
        "e6VWTYLwllfBC4ZUF0bGCy2pEpHxUjv0NQx0ZWbDPwqzDBUEdEHaB1eSxCi7ahiSx/dDWdIsgICvWMPbO0KEOIPxukrfzFZfIVWETUZ/"
        "m/G9ESoI2USIDF51uJOHozTvi9UiLFzahmkRpIgIvTTXPS2CFBkrAgFKPe6PJKQCQfPQ6OdRjGBGGYFBPJ7zPOMgLiMICAhMOBhEPOdl"
        "WeZQxgwY2ZZBgLpBCqEDQDMCrIUs4pZGuABxMmL/IXEuHD4UQ0AgwBbTyQg/fE2m83G4DYEqI0IYy3JIpifICA4D5aM4Li0m2OIKp3ny"
        "C7wcBCJ4gpEgSY2jEERgTN6aFsBUJjBjIkhG2CcQkDHF4oFvbdJJEw0IZ3gMrTgyo88Uxk3foF3NRyLC6/WyfJf4l8AQARnmBEKdR1h3"
        "FtG2Phe1t58cw54ifHYDKy6SUwTX/DgnmX4BEfExig=="
    ),
    "analyzing2": (
        "eNqllo1ygyAQhPUwImlqksEoff8X7R6gKcpf6jLjICwflwsITdv4QkRbvYkr7hVCdN2l6/teDgpP1Du0RQloR+/l7YX5r5eGYaCmTkfv"
        "lVsli/xbWhkvKVZdGAkvtaxKRMLL7dTXMOBKzIY/ClmmCgJcFPfRlVVi5F01jJLH9lNepVkIgK9Qw+4dkEKc3nhdJW9qq6+QKsImJb/V"
        "uG+kCkIyEUWGW3XYycNR0u2L1VJYuLwN42JIFuF7ea57XAzJMlYEAEI87o8opALB8/Do51EO4Rh5BIJ4zPOMMe4ZQqiAQMJJATEvyzI/"
        "3XPHoNHZEggSN0ojJIpFkNaURNziCGkRBqWI2H7IM8yFsZgNAYDOptMi7PAtmcYDVgSUR7gwluWYTEsoI1wYSAcrsrQcQWdXOM+TXuD5"
        "IIBwE4wMiWocC0F4xmStcRFNeYJjTAxJCH0FAhhTKDdw11Y6aYIB/gwPoRVHZvCZQtz8DXqr+UhMeL1e2t0l/iVSTABDnUCI8whtziLa"
        "1uai9vaTYuhThM9uYNlFcopgmh9jSqZfEuUxig=="
    ),
    "analyzing3": (
        "eNqllotygyAQRXWxImlqkvGZ///R3mXRlMgr9TrjIFwO6wpCVVfuIqK9XIUV9iqlmuaradtWdwZ3lBvUBQmoR+vXywvzXy91XUdVmY7e"
        "C9dqFrmnuBJeMqyyMCJeqlmFiIiX66ktYcAVGQ0fClmmAgJcFPbRhZVjpF0ljJzHtlNauVEIgG9f3dszIJk4nfGySV/NXt4gRYRdRv+Y"
        "/r2SCgjRRGQZMuuwkrujtKyLzZKZuLwMw2JIEuFaeaxbWAxJMjYEAErdb/cgpADB43Dvx1GCEEYagSDu8zyjj9x9CGUQSDgZIOZlWeaH"
        "3Hdpy6BebBEEqSvFEeuGoGGgKOIaR2ggdB6xv8jjmIvVXhYBwJBMp0XY7jtA2xheCCiNkDCWxc+E+yLU5xESBtLBCkwtIQzJGc7jxCd4"
        "OgggZICeIUH1fSYIxxitNSyiMU0QxsiQiNCWIYAx+pKOb3W5ncbr4PZwH1qwZXq/KcTN/6CXqo/EhGmaBjlL/EtkmACGOYNQ5xHTehJR"
        "1zYXpaefGGM4RfjsBJacJKcIa/V8rjnTL/IrMYI="
    ),
    "analyzing4": (
        "eNqllolygzAMREEQjNOWJMPl/v+PdmUZJxBfKZsZBuz1kyJkoKor9yMif16FFfY2TdO2l7brOtVrHHHeYixIwDhmL08vzK9e6vueqjK9"
        "e688qljkruJKeEmzytKIeKlmFSIiXh6nroQBVyQabhSqTAUEuCjsoysrx0i7Shg5j52ntHJRCICvvfrDNSCZPJ3xukl9a3++QYoIXlr9"
        "6OE4SAWEaCGyDOk67OT+XUr2xWbJNC5vw7AYkkS4WY51C4shScaGAKBp7rd7EFKA4Di8+vEuQQgjjUAS92VZsEaOewhlECg4aSCWdV2X"
        "hxydlGPQILYIgsaRYghjIRZBjaLPEQoI4xEqjvB/5HGshXlFIM6YLKdF2OUeoBxCOQSURkga6/paCX9HaMgjJA2UgxVoLSGMyQ7nOPEG"
        "TycBhAQYGBLUMGSScIzJWsMimtIEYUwMiQhzGQIY016y8DCWe9PsFrh3+B5a8MrcPaaQN/fzU9VHYsI8z6N8S/xLpJkAhj6FaM4jZnMO"
        "Ude2FqVfPzHGeIrw2RdYsklOEUxlfk3O9AfKNTF5"
    ),
    "analyzing5": (
        "eNqllolygzAMRI0gGKctCcOZ///RrhA4NfhKWc8wYK+fFEUcqlDbICJ7rvzye8uyrKpbVde1bgyOOK8w5yVgHqu3txfmv15qmoZUns7e"
        "O89qFm1XYUW8ZFh5aQS8VLAyEQEvz1Odw4ArEA1/FKpMGQS4yO+jOyvFiLtyGCnPuk5xpaIQAF+umsM1IIk8N+N9l/429nyHZBGsjP4x"
        "7XGSMgjBQiQZ0nW4k5uztNwXuyXRuHwb+sWQKGJb5VgPvxgSZewIAMry+Xh6IRkIjsO7u7MEIYw4Akk8p2nCHjm6EEogUHAyQEzzPE+d"
        "HA8MasUWQFDfkx+hMSyCSk2fInS3YLwROoywP6Rza7GsQ+8IxOmj5VwR63ZbzMVCBAHFEZLGPJ+LuRLSCEkD5WB5WksIfbTDOU64weNJ"
        "ACEBWoZ41baJJDbGsFr9IhriBGEMDAkIawkCGIMr2XiYS71pnA3bO9yFZrwynccU8uZ+fkt9JCaM49jLt8S/RIYJYJhriPI6YlwuIYpi"
        "rUXu10+I0V8ifPYFFm0SdU3L66WWuOUXxLgxeg=="
    ),
    "verified": (
        "eNq1lolyhCAQRHUwKhviHur//2p6GDxguTZWercshObNgKA0beN+RLSXm7jiXqVU1311fd8Po8YV5Q51UQLq0fp1eGE+e2kcR2rq9O69"
        "ce3AIneXVsZLmlWXRsJLLasSkfByPfU1DLgS0fCgMMtUQYCL4j66sUqMvKuGUfLYdsqrFIUA+PY1BveAFPJ0xtumwei9vEGqCLv08KOn"
        "sJIqCMmJKDJk1WEnj+8aZF9slsLC5W0YF0OyCNfKse5xMSTL2BAAKPW4P6KQCgTH4d7Ps4zhqyCEkUcgicfTJ7xelvE80kgiMOGkKUiB"
        "CQ4BBk1iSyBIGTojzJ6DIwjC2lII4yGMjb2P4kCYNCIYiO3sEQQxE/656TwPBN09gkNAeYTPeCOUEZLGJkxHsLSEMGdXOMc5ICZY4Pkk"
        "gJAAE0OimqZCEo6xWGtcREueIIyFIQmhrUAAY/ElHYO60pfG6+C+4T604pPpvaaQN7+DDjUfiQnrus5ylviTSM+rYoa+hFjNdcTFLNrW"
        "zkXt6SfFmC8RPjuBZRdJ8+/6BfzGLz0="
    ),
    "happy": (
        "eNq1lolyhCAQRHUwKhviHur//2p6GDxguTZWercshObNgKA0beN+RLSXm7jiXqVU1311fd8Po8YV5Q51UQLq0fp1eGE+e2kcR2rq9O69"
        "ce3AIneXVsZLmlWXRsJLLasSkfByPfU1DLgS0fCgMMtUQYCL4j66sUqMvKuGUfLYdsqrFIUA+PY1BveAFPJ0xtumwei9vEGqCLv08KOn"
        "sJIqCMmJKDJk1WEnj+8aZF9slsLC5W0YF0OyCNfKse5xMSTL2BAAKPW4P6KQCgTH4d7Ps4zhqyCEkUcgicfTJ7xelvE80kgiMOGkKUiB"
        "CQ4BBk1iSyBIGTojzJ6DIwjC2lII4yGMjb2P4kCYNCIYiO3sEQQxE/656TwPBN09gkNAeYTPeCOUEZLGJkxHsLSEMGdXOMc5ICZY4Pkk"
        "gJAAE0OimqZCEo6xWGtcREueIIyFIQmhrUAAY/ElHYO60pfG6+C+4T604pPpvaaQN7+DDjUfiQnrus5ylviTSM+rYoa+hFjNdcTFLNrW"
        "zkXt6SfFmC8RPjuBZRdJ8+/6BfzGLz0="
    ),
    "alert": (
        "eNq1lumSgyAQhLUxKu6uSUr9g3n/59wZDhXDlbW2kzIczcdkRKGqK/sBsJWrsMJeIUTT3Jq2bbte0pXKDbUFCdROvbfdS+ajF33foyrT"
        "u3fg1o4FW4sr4YVklYUR8aJmFSIiXm5HW8IgV2Q2ulGUZRQQyIWwDwMrx0i7Shg5j+5HWrlZQIAvX/2pTpBMnNY4OHXfcis7SBFhk+x+"
        "5HhuRAEhmogsw6w6epL7d3XmuXCWzMLlxzAshiQRtpfnuofFkCTDIQggxOP+CEIKEDwPj36+yyAMI42gIB40QClvvK7uYUQRlHBI6BDU"
        "uh4ZtkqI0dgiCAgFh/AZrqIReL0QRagD4sjYilnE8Y+4YUonwYtiAn1T6fRzQT+rOuViIqURjqHsnVDHO4IxjzBhRGWDmJIrnOeJL/B0"
        "EIQwE4wMCWocM0FYxqytYQFzmmAYM0Mior4MgRizLzPw1JbbabwBdg/3oQVbpveaorj5HbSr+khMWJZlMmeJPwlyWgQz5CXEoq4jLkZR"
        "1zoXpaefGGO6RPjsBJZcJNW/6xcOKzJM"
    ),
}

_cache: dict[str, list[list[int]]] = {}
_OUTLINE = _PALETTE.index("#121826") + 1
_BRIGHT = {i + 1: sum(int(c[k:k + 2], 16) for k in (1, 3, 5)) for i, c in enumerate(_PALETTE)}


def frame(name: str) -> list[list[int]]:
    """Кадр как строки индексов палитры (0 — прозрачно)."""
    if name not in _cache:
        raw = zlib.decompress(base64.b64decode("".join(_FRAMES_Z[name])))
        _cache[name] = [list(raw[y * _W:(y + 1) * _W]) for y in range(_H)]
    return _cache[name]


def compact(rows: list[list[int]]) -> list[list[int]]:
    """Вдвое меньше: из каждого квадрата 2×2 — самый частый цвет (так пиксельный рисунок не рассыпается)."""
    out = []
    for y in range(0, len(rows) - 1, 2):
        line = []
        for x in range(0, len(rows[0]), 2):
            cells = [rows[y][x], rows[y + 1][x]]
            if x + 1 < len(rows[0]):
                cells += [rows[y][x + 1], rows[y + 1][x + 1]]
            solid = [c for c in cells if c]
            if len(solid) * 2 < len(cells):
                line.append(0)
            else:   # контур (#121826) уступает цвету: иначе золото рамки и глаза тонут в тёмном
                line.append(max(set(solid), key=lambda c: (solid.count(c) * (0.4 if c == _OUTLINE else 1),
                                                          _BRIGHT.get(c, 0))))
        out.append(line)
    if len(out) % 2:
        out.append([0] * len(out[0]))
    return out


# ─────────────────────────────── цвет терминала ───────────────────────────────

def _enable_vt(stream: Any) -> bool:
    """Windows: включить разбор ANSI-последовательностей в консоли (Windows 10+). Остальные системы — True."""
    if os.name != "nt":
        return True
    try:
        import ctypes
        from ctypes import wintypes
        k32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        handle = k32.GetStdHandle(-11 if stream is not sys.stderr else -12)
        mode = wintypes.DWORD()
        if not k32.GetConsoleMode(handle, ctypes.byref(mode)):
            return False
        return bool(mode.value & 0x0004) or bool(k32.SetConsoleMode(handle, mode.value | 0x0004))
    except Exception:  # noqa: BLE001 — нет консоли: без цвета
        return False


def color_mode(stream: Any = None, env: Mapping[str, str] | None = None) -> str:
    """'truecolor', '256' или 'ascii'."""
    stream = stream or sys.stdout
    env = os.environ if env is None else env
    try:
        "▀▄█⠋✓—…".encode(getattr(stream, "encoding", None) or "ascii")
    except (UnicodeEncodeError, LookupError):
        return "ascii"
    term = (env.get("TERM") or "").lower()
    if env.get("NO_COLOR") or term == "dumb":
        return "ascii"
    if os.name == "nt":
        if not _enable_vt(stream):
            return "ascii"
        return "truecolor"          # Windows Terminal и консоль Windows 10+ понимают 24 бита
    if (env.get("COLORTERM") or "").lower() in ("truecolor", "24bit") or env.get("WT_SESSION"):
        return "truecolor"
    if env.get("TERM_PROGRAM") in ("iTerm.app", "vscode", "WezTerm", "ghostty"):
        return "truecolor"
    return "256"


def _rgb(hexcolor: str) -> tuple[int, int, int]:
    return int(hexcolor[1:3], 16), int(hexcolor[3:5], 16), int(hexcolor[5:7], 16)


_LEVELS = (0, 95, 135, 175, 215, 255)


def xterm256(rgb: tuple[int, int, int]) -> int:
    """Ближайший цвет палитры xterm: куб 6×6×6 или шкала серого."""
    def near(v: int) -> int:
        return min(range(6), key=lambda i: abs(_LEVELS[i] - v))
    r, g, b = (near(v) for v in rgb)
    cube = 16 + 36 * r + 6 * g + b
    cube_rgb = (_LEVELS[r], _LEVELS[g], _LEVELS[b])
    gray = max(0, min(23, round((sum(rgb) / 3 - 8) / 10)))
    gray_rgb = (8 + 10 * gray,) * 3
    dist = lambda c: sum((a - b) ** 2 for a, b in zip(c, rgb))  # noqa: E731
    return cube if dist(cube_rgb) <= dist(gray_rgb) else 232 + gray


def _sgr(idx: int, mode: str, bg: bool) -> str:
    rgb = _rgb(_PALETTE[idx - 1])
    if mode == "truecolor":
        return f"{48 if bg else 38};2;{rgb[0]};{rgb[1]};{rgb[2]}"
    return f"{48 if bg else 38};5;{xterm256(rgb)}"


ASCII_FACES = {"idle": "o  o", "blink": "-  -", "look": "o  o", "analyzing": "=  =", "verified": "^  ^",
               "happy": "^  ^", "alert": ">  <"}


def ascii_drone(mood: str) -> list[str]:
    face = ASCII_FACES.get(re.sub(r"\d+$", "", mood), "o  o")
    return ["  -==-      -==-",
            "     \\.____./",
            f"    [  {face}  ]",
            "       (())"]


def render(name: str, mode: str, *, small: bool = False, indent: int = 2) -> list[str]:
    """Строки терминала с дроном: полублок «▀» — верхний пиксель цветом текста, нижний — фоном."""
    if mode == "ascii":
        return ascii_drone(name)
    rows = frame(name)
    if small:
        rows = compact(rows)
    lines = []
    pad = " " * indent
    for y in range(0, len(rows), 2):
        top, bot = rows[y], rows[y + 1]
        out, cur = [pad], ""
        for t, b in zip(top, bot):
            if not t and not b:
                cell, sgr = " ", "0"
            elif t and b:
                cell, sgr = "▀", _sgr(t, mode, False) + ";" + _sgr(b, mode, True)
            elif t:
                cell, sgr = "▀", "0;" + _sgr(t, mode, False)
            else:
                cell, sgr = "▄", "0;" + _sgr(b, mode, False)
            if sgr != cur:
                out.append(f"\x1b[{sgr}m")
                cur = sgr
            out.append(cell)
        out.append("\x1b[0m")
        lines.append("".join(out).rstrip() if False else "".join(out))
    return lines


# ─────────────────────────────── экран ───────────────────────────────

_ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
GREEN, RED, DIM, BOLD, RESET = "\x1b[38;2;0;185;117m", "\x1b[38;2;229;72;77m", "\x1b[2m", "\x1b[1m", "\x1b[0m"


class _Screen:
    """Вывод с учётом строк ниже дрона: так дрон можно перерисовать на месте (моргнуть, сменить настроение)."""

    def __init__(self, out: TextIO, mode: str, live: bool):
        self.out, self.mode, self.live = out, mode, live
        size = shutil.get_terminal_size((80, 24))
        self.cols, self.rows = max(20, size.columns), max(10, size.lines)
        self.small = mode != "ascii" and (self.cols < 72 or self.rows < 30)
        self.sprite_h = 0
        self.below = 0
        if mode != "ascii":
            self.ok, self.err, self.dim, self.bold, self.reset = GREEN, RED, DIM, BOLD, RESET
            self.ok_mark, self.err_mark, self.spin = "✓", "×", "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
        else:
            self.ok = self.err = self.dim = self.bold = self.reset = ""
            self.ok_mark, self.err_mark, self.spin = "OK", "x", "|/-\\"

    def write(self, s: str) -> None:
        if self.mode == "ascii":
            s = _ANSI.sub("", s)
        try:
            self.out.write(s)
        except UnicodeEncodeError:   # вывод в файл в старой кодировке: «?» вместо символа, но не трейсбэк
            enc = getattr(self.out, "encoding", None) or "ascii"
            self.out.write(s.encode(enc, "replace").decode(enc, "replace"))
        try:
            self.out.flush()
        except (OSError, ValueError):
            pass

    def _rows_of(self, text: str) -> int:
        n = len(_ANSI.sub("", text))
        return max(1, -(-n // self.cols))

    def sprite(self, name: str) -> None:
        lines = render(name, self.mode, small=self.small)
        self.write("\n")
        for ln in lines:
            self.write(ln + "\n")
        self.sprite_h, self.below = len(lines), 0
        self.write("\n")
        self.below += 1

    def swap(self, name: str) -> None:
        """Перерисовать дрона на месте (только видимые строки)."""
        if not self.live or not self.sprite_h or self.mode == "ascii":
            return
        lines = render(name, self.mode, small=self.small)
        first = max(0, self.sprite_h + self.below - (self.rows - 1))
        if first >= self.sprite_h:
            return
        up = self.sprite_h - first + self.below
        buf = [f"\x1b[{up}F"]
        for ln in lines[first:]:
            buf.append(ln + "\x1b[K\n")
        buf.append(f"\x1b[{self.below}E" if self.below else "")
        self.write("".join(buf))

    def say(self, text: str, *, style: str = "", typing: bool = True, end: str = "\n") -> None:
        body = "  " + text
        if self.live and typing and self.mode != "ascii":
            self.write(style)
            for ch in body:
                self.write(ch)
                if ch not in " ":
                    time.sleep(0.012)
            self.write(self.reset if style else "")
        else:
            self.write(f"{style}{body}{self.reset if style else ''}")
        self.write(end)
        if end.endswith("\n"):
            self.below += self._rows_of(body)

    def input_line(self, prompt: str) -> None:
        """Строка ввода заняла столько-то строк экрана (ввод и Enter — на ней же)."""
        self.below += self._rows_of("  " + prompt)

    def cursor(self, show: bool) -> None:
        if self.live and self.mode != "ascii":
            self.write("\x1b[?25h" if show else "\x1b[?25l")


# ─────────────────────────────── знакомство ───────────────────────────────

KEY_URL = "https://aistudio.google.com/apikey"
LABELS = {"gemini": "Gemini", "anthropic": "Claude API", "claude_cli": "Claude Code", "openai": "ваш сервер модели"}


def _ready() -> tuple[str, str]:
    """(провайдер, откуда) — первый готовый провайдер с моделью, как его выберет --provider auto."""
    from . import onboarding
    from .runner import provider_status
    status = {p["id"]: p for p in provider_status()}
    first = status.get("auto", {}).get("resolved", "")
    order = [first] + [p for p in onboarding.MODEL_PROVIDERS if p != first]
    for pid in order:
        if pid in onboarding.MODEL_PROVIDERS and status.get(pid, {}).get("ok"):
            if pid == "gemini":
                key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or ""
                return pid, f"ключ Gemini на месте ({onboarding.mask(key)})"
            if pid == "anthropic":
                return pid, f"ключ Claude на месте ({onboarding.mask(os.environ.get('ANTHROPIC_API_KEY', ''))})"
            if pid == "openai":
                return pid, "думаю на вашем сервере модели"
            return pid, "думаю через Claude Code, ключ не нужен"
    return "", ""


def _isatty(s: Any) -> bool:
    try:
        return bool(s.isatty())
    except Exception:  # noqa: BLE001
        return False


def _guard_terminal(stream: Any) -> None:
    """Скрытый ввод выключает эхо; если процесс оборвут посреди ввода (Ctrl+C в другом потоке) — вернуть как было."""
    if os.name != "posix":
        return
    try:
        import termios
        fd = stream.fileno()
        saved = termios.tcgetattr(fd)
        atexit.register(lambda: termios.tcsetattr(fd, termios.TCSADRAIN, saved))
    except Exception:  # noqa: BLE001
        pass


def _check_with_drone(scr: _Screen, provider: str, key: str, verify: Callable[[str, str], tuple[bool, str]]
                      ) -> tuple[bool, str]:
    """Проверка в фоне; пока ждём — дрон анализирует, рядом крутится индикатор."""
    box: dict[str, Any] = {}

    def run() -> None:
        try:
            box["res"] = verify(provider, key)
        except Exception as exc:  # noqa: BLE001
            box["res"] = (False, f"Проверка не прошла: {type(exc).__name__}.")

    t = threading.Thread(target=run, daemon=True)
    t.start()
    i = 0
    label = f"Проверяю ключ {LABELS[provider]}…"
    while t.is_alive():
        if scr.live:
            scr.swap(f"analyzing{i % 6}")
            scr.write(f"\r  {scr.dim}{scr.spin[i % len(scr.spin)]} {label}{scr.reset}\x1b[K" if scr.mode != "ascii"
                      else f"\r  {scr.spin[i % len(scr.spin)]} {label}")
        t.join(0.12)
        i += 1
    if scr.live:
        scr.write("\r\x1b[K" if scr.mode != "ascii" else "\r" + " " * (len(label) + 6) + "\r")
    return box.get("res", (False, "Проверка не прошла."))


def greet(port: int = 8014, env_path: str | Path | None = None, *, stdin: TextIO | None = None,
          stdout: TextIO | None = None, interactive: bool | None = None, mode: str | None = None,
          ask_secret: Callable[[str], str] | None = None, ask: Callable[[str], str] | None = None,
          verify: Callable[[str, str], tuple[bool, str]] | None = None, tries: int = 3) -> str:
    """Знакомство в терминале перед браузером. Возвращает провайдер (см. описание модуля)."""
    from . import onboarding
    out = stdout or sys.stdout
    inp = stdin or sys.stdin
    live = _isatty(inp) and _isatty(out) if interactive is None else interactive
    mode = mode or color_mode(out)
    scr = _Screen(out, mode, live)
    url = f"http://127.0.0.1:{port}"
    ready, where = _ready()

    if not live:   # двойной щелчок, Docker, вывод в файл — одна строка, решает окно ключа в браузере
        if ready:
            scr.write(f"BCC AI: {where}.\n")
            return ready
        scr.write(f"BCC AI: ключа модели нет — вставьте его в браузере: {url}/welcome "
                  f"(или продолжите без ключа).\n")
        return ""

    import getpass
    ask_secret = ask_secret or (lambda prompt: getpass.getpass(prompt))
    ask = ask or input
    verify = verify or onboarding.verify_key
    _guard_terminal(inp)
    try:
        scr.cursor(False)
        scr.sprite("idle")
        time.sleep(0.25)
        scr.swap("blink")
        time.sleep(0.13)
        scr.swap("idle")
        if ready:
            hello = "С возвращением!" if ready in ("gemini", "anthropic", "openai") else "Здравствуйте! Я BCC AI."
            scr.say(f"{hello} {where[0].upper() + where[1:]}.")
            scr.say("Открываю систему…", style=scr.dim, typing=False)
            return ready
        scr.say("Здравствуйте! Я BCC AI — проверяю ТЗ до начала разработки.", style=scr.bold)
        time.sleep(0.2)
        scr.swap("look")
        scr.say("Вставьте ключ Gemini или Claude. Enter — без ключа.")
        scr.say(f"Бесплатный ключ Gemini, за минуту: {KEY_URL}", style=scr.dim, typing=False)
        for attempt in range(tries):
            scr.swap("idle")
            scr.cursor(True)
            prompt = "  Ключ: "
            try:
                key = re.sub(r"\s+", "", ask_secret(prompt) or "")
            except EOFError:
                key = ""
            scr.input_line(prompt)
            scr.cursor(False)
            if not key:
                onboarding.SKIP_WELCOME = True
                scr.say("Хорошо, без ключа: только правила и готовые отчёты. Ключ можно вставить позже.",
                        style=scr.dim)
                return "offline"
            provider = onboarding.detect_provider(key)
            if not provider:
                scr.swap("alert")
                scr.say(f"{scr.err_mark} Не похоже на ключ: у Gemini он начинается с AIza, у Claude — с sk-ant-.",
                        style=scr.err, typing=False)
                continue
            ok, msg = _check_with_drone(scr, provider, key, verify)
            if not ok:
                scr.swap("alert")
                scr.say(f"{scr.err_mark} {msg}", style=scr.err, typing=False)
                if attempt + 1 < tries:
                    scr.say("Вставьте ещё раз или нажмите Enter — продолжу без ключа.", style=scr.dim, typing=False)
                continue
            scr.swap("verified")
            scr.say(f"{scr.ok_mark} {msg} · {LABELS[provider]} · {onboarding.mask(key)}", style=scr.ok, typing=False)
            scr.cursor(True)
            q = "  Запомнить на этом компьютере (файл .env)? [Д/н] "
            try:
                ans = (ask(q) or "").strip().lower()
            except EOFError:
                ans = ""
            scr.input_line(q + ans)
            remember = ans in ("", "д", "да", "y", "yes", "l", "ок", "ok")
            problem = onboarding.accept_key(provider, key, remember=remember,
                                            path=Path(env_path) if env_path else None)
            scr.swap("happy")
            if problem:
                scr.say(problem, style=scr.err, typing=False)
            elif remember:
                scr.say("Запомнил. В следующий раз спрашивать не буду. Открываю систему…")
            else:
                scr.say("Ключ — только на этот запуск. Открываю систему…")
            return provider
        scr.say(f"Продолжу без ключа. Ключ можно вставить в браузере: {url}/welcome", style=scr.dim)
        return "offline"
    except KeyboardInterrupt:
        scr.write("\n")
        raise
    finally:
        scr.cursor(True)
        if scr.mode != "ascii":
            scr.write(RESET)
