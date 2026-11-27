"""BCC AI в терминале (№40): первое знакомство до браузера.

    from bcc_review.v2.web import tty_agent
    provider = tty_agent.greet(port, env_path)   # перед тем как открыть браузер; → 'gemini', 'anthropic', …

Одна команда — и в этом же окне появляется тот же AIshka, что в вебе (кадры сняты с ``assets/agent.js``:
``BCCAgent._pixels``, пустые поля обрезаны, рисунок уменьшен вдвое по цвету большинства в квадрате 2×2),
моргает, подмигивает и знакомится. Ключа нет — просит ключ Gemini или Claude
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

# ─────────────────────────────── кадры AIshka ───────────────────────────────
# Сетка 96×96 из agent.js без пустых полей (x 9…88, y 10…81): 80×72 px. На экран — вдвое меньше: 40×36 px,
# 18 строк полублоков «▀»; в тесном окне — ещё вдвое.
_W, _H = 80, 72
_PALETTE = (
    "#161E31", "#1F2E4A", "#21A049", "#9C7136", "#34D36A", "#CAA166", "#E6BD74", "#F58DA8",
    "#5ED6FF", "#B9CBE0", "#9EEBFF", "#DCE7F2", "#FFF3C4", "#E4FDE9", "#F2FEFF", "#FFFFFF",
)
_FRAMES_Z = {
    "idle": (
        "eNqt2It2gyAMBmCDqNWWM9//aReC3AIoCDk7m6zttz8ixW6aagoApoEFSikYyW1yGwdqDgaCsG1gvo2LN40LCMQpBGFMvFVzq4IhAVHS8Ta5"
        "KvyCUd3iBEs67OYwnjHluq69IHGUEQuPe0GfbKV0nR2DDkTJDGfi9vUbV2+/klfvhFy12IMhS2QcRdhpaghpsYscy50/GMqdvz6Qc+j1gAmn"
        "vfeg5+hysd5rEBymdGmyx7Oc8tUDZjgLHtDHbaYIJO8FCI5DiebDiPDOCzn71gIWPJrBoFvPIegCNoKQ5UIQujghRAS2BeTdnkJYcLsumibQ"
        "xTNzcX5FAOKm1Ngx69ZyF7gasD4g476OewmybkHkvdqOGRfGexOQdyviagYvb0ubjcHKjj334NUFZNxXiD4QHtKlIDScvK+4BR8Dpidv1xVQ"
        "NK7s+NoSI+5PlwevMes4f5uEn4BMPP28kPOgG7OOcx9LMpx+PbYXedf4GQTPRZ5gnog8C5a8iLvxDEj30+YUluY25O48B5bmGFLu5vxxMOct"
        "OS8/v8xbUg/jzeRF66xw/QXLhLw5DYje4uKx9YA/zICtFxdwyXpnxrOxyPnb03VM3lHnfT75vu3vq720drfKWJW8R3Avc/nrBfeDkx5vqQpP"
        "tnGFdl+BshzPeG2gvFm+GjwOC8pKTd6+44dgXT3sSAiiaP/2IwY0Fbcb3EHir+r0HabuN2D7LFbzMucfePwXAJTILFZ3B1hbuRf/AylxPvg="
    ),
    "blink": (
        "eNqt2IuSgyAMBVCDCKstU///azcEQZ4CQqbT0WrP3oAtdpelpQBgmViglIKZnORyHqg5mAiClGCe5sVb5gUE4hSCMCee0JxQMCUgSjqe5ELh"
        "A2Z1ixPMaXOYw3jG5EKIUZA4yoiF26PgnUxQusGOQQeiZIYzccf6DWu0Xx7X6IRctdmNKR+ReRRhp6kppMUuci53fmEqd37HwJhDbwRMOO29"
        "B2+OLhfrvQbBYUqXJkc8y6m7RsAMZ8EDxjhpikDyXoDgOJRoPowI7zyfs18tYMGjG/S6vTkEXcBOELKcD8IQxxgLwL6AcbcnYxaU10XTBbp4"
        "Zi7OD/NAXJQ6O466tdwFCgO2B4y4j+NeglG3wPJea8cR58d7EzDuloXVDV6eTJsNwcaOb67itQWMuA9jYyBU0qUgdAzehz2C1YDVwevq+FoS"
        "q1zScf42CX8BmXj6vEcu6Tj3s6SHawHh5m5vN+UYtx8PYcmLuJ8pC3r7dA7dT5shLM1t2O0ecMG+BUtzDNnBC9sN9gMw522tk5F4W+phvJW8"
        "Vs6B6K1pQPQ2Fy956+49hyAF3LLeWfT2H43bby94R5v395eZV+/1Zi8tDe65AyWvCu5lLn+94Hpw0vGeavB4H1do9xXIy/GM1wfyh4+vBo/D"
        "grxR44/f+D7YVpUVCUEU7d+uYkBT8bjAHSR+m4bvMPW8ANuzolq3NX+g+i8AKJFZrO0OsLVyb/4Hrq86aA=="
    ),
    "wink": (
        "eNqt2It2gyAMBmCDKNXWM9//aRfCRQwgIOTstPayb39Ait001RQATAMLjuOAkZySahyoORgIglJgbsbFm8YFBOIOBGFMvFVz6wFDAqKk4ym5"
        "HvgDo7rFCZZ02M1hPGPKdV17QeIoIxYe94JXspXSdXYMOhAlM5yJ29fvvXr7lbx6J8TW4g6GLJFxFGGnqSGkwyw5ljt/MJQ7f30g59DrASNO"
        "e+/Bi6PTxXmvQfDYoUuTPZ7jjqt6wATnwB36OGWKQPJegOA5lGg+jAjvvJBzHy3gwL0ZDLq9OAR9wEYQklwIQhcnhLiBbQF5t6cQDlT2pGkC"
        "fTwzF+dXBCBuSo0ds24dZ8HVgPUBGff13EuQdQsi7dV2zLgw3puAvFtxr2bQeipu9g5WdnxxBa8uIOO+QvSBUEgXg9AweF/xCBYDRoO3bYza"
        "dFV2bLfEkPv7u4P4BBYDM5dJ+A3IxNPvs4PHQMMFoA2Y+lqS4jioH230VBmEiwu8O0gPbp4Dcx7n7uDlGZCup80Q5ub2iQs9D+bmGMpcMH4c"
        "THlL7OXml3lL7GG8mbwHzp9/wTIhb44Dorf4eMFysPfultZHuO4o4JL0ztjzschhYS9vr/M+n2Sf/vlqL67NrzJWOa8Ibnkufb7gfnDS6y1V"
        "4ck2LtPuK1Dm4xmvDZQPy1eD++5AWanJx0/8EKyrwo6EIIrubxcxoKl43OB2En9Vw7ebet6A3btYzcucfqH4LwDIkUms7gqwtlK//A9/Bz0o"
    ),
    "look": (
        "eNqt2A1zgyAMBmCDqNPWq///1y4EEAgfgpDb7WRtn70RKbbTVFMAMA0sOM8TRnKb3MaBioOBIGwb6F/j4k3jAgJxJ4IwJt6quPWEIQFRUvE2"
        "uZ74A6O6xQmWdNjNYTxtynVde0HiKCMWHveCLtlK6To7BhWIkmlOx+3rN6zefiWv3gkxtdiDIUtkHEXYpWsIaTFDjuWuLwzlrm8fyDn0esCI"
        "U9570HF0uVjvNQg3dqpSZI9nudNVD5jgLHhAH7fpIpC8FyDcHEo0H1qEd57P2bcWsODRDHrdOg7BO2AjCEnOB6GLE0IEYFtA3u0lhAU3c9E0"
        "gXc8PRfXR3ggbkqNHbNuLWfAVYP1ARn3ubmXIOsWRNqr7Zhxfrw3AXm3Iqxm0Hhb3GwIVnbsuAevLiDjPkL0gfCQLgah4eTtqjzJjL1TWA7I"
        "ut1/qhxox5Udmy2RcQ50Y9Zx+jYJPwHpeOp5xsP2As+OWcepjyURR68XzLPjZxAc1+BZMOd5XNHTIN1P61OYm1vHicL588DcHAPnRH5+YzDl"
        "LcwTuesv8pbYw3gzef46M+tBC/s9DkH05jggessdL1yv+4+c355ayBRwSXpX6P39pft0f7+9o8YLEv7idA1eVNgupCvnPYBQ4tLXC+4HFz0+"
        "2JNtXKbdV6DMx9NeGygLy1eBx2FBWanJ4ju+D9bVw46EIIr2fz9iQFNR3OAOEr9Vp+/QVd6A7bNYzcucfuDxKwDIkUms7g6wtlIv/gdSyD7s"
    ),
    "analyzing0": (
        "eNqt2IGOgyAMBmCLTDM3Od//aa+0FCsyBaFZFsm27/4KynbDUFIAMHQsWNcVenKznfuBnoOOIMwz8FO/eEO/gEDciiD0iTd5blqhS0CUfLzZ"
        "Tis+oFe3OMGWDps5jMemnaapFSSOMmLhcSu4J5soXWPH4ANRMuY4blu/x2rt16bVOiGhXnLQ5RLpRxG2cXUhBQtkX277Qldu+7aBKYdeC3ji"
        "vPcc3DlaLuI9BiFiqy9PtnjCrXu1gBlOwAXauJmLQPIegBA5lGg+WIRnnubk1gICLtWg6nbnEIwBK0HIchqEJs4YcwDrAqbdbsYIOIdFUwXG"
        "eDwX28coEDelyo6TboUL4MRgecCE+0TuIZh0CybvlXaccDrek4Bpt+ZY1WDw5nOzR7Cw45278coCJtzHmDYQbtKdQag4eR9zCd4GvD15VR2H"
        "LfHIvbEiJIOk4/zXJPwFxPH8+5jDj/9hCcgDTyYd536W5Lg/roPH40vQ+QfsnPIoofJknJ5CYIRrHIZX8DR35TFI36f5FKLgHeWl3V72u4My"
        "x+I57R04AdT86vEBFM/5p+C5k0cL5K1Wnh4rz0VvFA/jjeRdLOR3ZlmTN2LAs+divBPE9ZcBKaBTnove9stL5+XkLdFzMr9XnuQz996Q9Soq"
        "5/H18Qjc14u6Pvj6xf1go9efeaf7gXi2jgvtDj1A+zsee3WgVZdvDlwWAW2hZi/v+Bosq5sdCUEU5W/fYkBTcbnBLSR+i07fwnW9Acu7khpf"
        "Y/6F238BwC8yi5V9Ayyt3If/AYh3Pk4="
    ),
    "analyzing1": (
        "eNqt2IuugyAMBmCLKJnOzfd/2pXWIrcpCI050Wz7zl9BcRuGkgKAoWPBtm3QkzPa9AMtBx1BMAb4T794Q7+AQNyGIPSJN1tu3qBLQJRsPKPn"
        "DTfo1S0OsKbdZg7jsanneW4FiaOMWLjfCp7JZkrX2DHYQJSMOY7b1m9Yrf3quFoH5KhJdrpcIv0ownauLqRgB9mX29/QldvfbWDModcCJpz1"
        "noMnR9NFvMcgOGyzZckWT7jtrBYwwwm4QBtnuAgk7wEIjkOJxoNFeOb5nNxaQMClGvS6PTkEXcBKELKcD0ITp5QKwLqAcbe7UgKaY9JUgS4e"
        "j8W+Kg/ERamy46hb4Q5wZrA8YMStjnsIRt2CynulHUecH+9JwLhbFVY1eHgmbTYECzs+uRuvLGDErUq1gXCTLgWh4uSt6hK8DXh78qo6PpbE"
        "kHthOUgOoo7zj0n4DYjj2fcxhx//YgnIB5aMOs59LclxX67A4+P/4Ic2263jPI8Sep4cx6cQHDUOdvscns9deQzS8zSfQosRxd40JN1e9nuC"
        "MsZTzgs4Abzx9Y8DMOdNiUcT5OXNPP/Y86bUw3gjeRcT+ZWZ1uSNGDD1Jhcvgbi+GZACTllv/+fF45J4S50n+VS59wmHt7ycJ/PPXR+PwHO+"
        "eJcaX7+4Huz0+mMvvB+Ip+u4o92hB6j/x2OvDtTe5ZsDl0VAXajpyzu+D5bVzYqEIIryv28xoKG4XOAWEt9Fp2/hul6A5V1RjdOYf+H2JwD4"
        "R2axsifA0sp9+AchQz46"
    ),
    "analyzing2": (
        "eNqt2IuSgyAMBVCDqFNbrf//tQ2JYHgUQcjs7Mi0PXsD+OgOQ0kBwNCxYNs26MkteukHGg46grAswL/6xRv6BQTiNgShT7zZcPMGXQKiZOIt"
        "et7wB3p1iwus6bCZw3hs6nmeW0HiKCMWHreCV7KZ0jV2DCYQJWOO47b161drvzqs1gU5a7IHXU6RfhRhB1cX0mIn2Zc7PtCVOz5tYMih1wJG"
        "nPGegxdH28V6j0Fw2GbKkC2e5barWsAEZ8EV2riFi0DyHoDgOJRoPViEZ57k7KUFLLhWg6Lbi0PQBawEIclJEJo4pZQH1gUMuz2UsuBybpoq"
        "0MXjtTjeSoB4U6rsOOjWcic4M1geMODejnsIBt2CSnulHQecjPckYNit8qsaPL0lbtYHCzu+uBuvLGDAvZVqA+EmXQxCxeS9VRa8DXg7eVUd"
        "n7dEn3thOcgOgo7Tj0n4DYjjmfcxhx//YlmQB4YMOk59LUlxXy7P4/F/cHfdOk54lFB4dhxOIThtPMlz8gSX8xik52mewjPaaLxRrK3gcv1e"
        "oFjj8fL2ASLOAmJ95dgDgcM5b0JvijzaIC+x8+RYeBN6k+9hvJG8zEZ+JbY1eSMGjL3JxYsgrm8CpIBT5O3e9IVcsC6RZxbEn78h59l8KueJ"
        "9d1Dr6KkRxF378pXC177xT/b0MP7wUGvt3hD7Ok67mq3HdT/47FXB2r/9I3AdbWgLtR09oovwbK6uSMhiKL927cY0FJkb3AriZ+i6Vu58jdg"
        "+66gxmlMv3D7LwD4RyaxsifA0kp9+AcU4D4G"
    ),
    "analyzing3": (
        "eNqt2IuSgyAMBVCDVKe2Uv//azck8oqsgJDZ2ZFpe/YG8NGdppoCgGlgwb7vMJJb9ToOtBwMBGFdgX+NizeNCwjE7QjCmHiL5ZYdhgREycZb"
        "9bLjD4zqFhdY02E3h/HY1Muy9ILEUUYsPO4FQ7KF0nV2DDYQJWOO4/b1m1Zvv1pW74Kc9XIHQ06RcRRhB9cQ0mEnOZY7vjCUO759oOTQ6wEv"
        "nPWeg4Gj7eK8xyB4bLdlyR7PcXuoHjDDOXCDPm7lIpC8ByB4DiVaDxbhmRdz7tICDtyawajbwCHoAzaCkOViELo4pVQCtgWU3R5KOXA9N00T"
        "6OPxWhwfFYF4U2rsWHTruBNcGKwPKLiP5x6ColtQea+2Y8HF8Z4ElN2qtJrB01uvzaZgZceBK3h1AQX3UaoPhEK6KwgNk/dRt2AxYHHymjo+"
        "b4kp98bykBuIjvOPSfgNiOPZ9zGHH/9hOZAHlhQd576W5LgfV+LxuAxC4CKPEkaeG8spDJ5JvJi78xik52meQq/N6dpG3F2/AUzXeLaeCTs5"
        "5hwQrW88TkA4WyWPSDjMxaMN8o52XjyOPIMeYd57YbyZvJuN/M5sa/JmDPhKPIOe8fEuENcvA1JAg16Uz8jpk5xYl4t3Loibv6nguXyq4NH6"
        "mozXUMIz4srXCib7JT3f8H5w0OuDPd3GJe12gvr/eOy1gfpy+qbgtjlQV2r69oofg3VVuCMhiKL720UMaClub3Abid+q6du47m/A7l2i5tec"
        "f6H4LwD4j8xidU+AtZX78B+tnT3y"
    ),
    "analyzing4": (
        "eNqt2AGSgyAMBVCDqFOt1vuftiExiIAIQqazq9P27Q9Qsdt1OQUAXcOCdV2hJTfpqR1oOGgIwjQB/2gXr2sXEIhbEYQ28UbDjSs0CYiSiTfp"
        "ccUHtOoWJ1jTYTWH8djU4zjWgsRRRiw8rgXPZCOlq+wYTCBKxhzHrev3WrX9ar9qJ+SoQQ6afETaUYTtXE1IwQ6yLbd/oSm3f+tAn0OvBgw4"
        "470HT46Wi3ivQbDYasqQNZ5w61k1YIQTcIY6buIikLwXIFgOJZoPFuGd53JyaQEB52LQ6fbkELQBC0GIci4IVZxS6gKWBfS73ZUScDoWTRFo"
        "4/Fc7ItyQNyUCjv2uhXuAEcG8wN63GK5l6DXLai4l9uxx7nx3gT0u1XXKgYPbwqbvYKZHZ/cg5cX0OMWpepAeEgXglAweItKgo8BHwevqONj"
        "S7xyHywLyYnXcfw2Cb8BcTzzOubw7T8sAfnEkF7Hsa8lMe7HdfH4/BmEk3M8Suh4cu4P4Z3ncimPQbqf5iH0tK0Luk32e4Iyx5uVTA0dBJwA"
        "zvy65xcQUGCtJ9J4W+DRAvk4K889d7yNPXR64+FjwHg9eYmF/Iksa/J6DDh0TB350NtsvADi+kVACrixR/mO8bsMn8958xJ4M3t2NvB3ypN8"
        "KuVtsQuVTEd+WS9+5SsFz/USeLgf7PR8Y0+XcTftvgL1fTz2ykDtfHxj4DwLqDM1nbziu2BePexICKIof/sRA5qK5AY3k/jNGr6ZK70By6u8"
        "6oc+/sTjvwDgjoxieXeAuRV78x/CQT32"
    ),
    "analyzing5": (
        "eNqt2IGOgyAMBmCLTDM3Pd//aa+0FAsyBaG5LJpt3/0FHG7DUFIAMHQsWNcVenKznfuBjoOOIMwz8EO/eEO/gEDciiD0iTc5blqhS0CUXLzZ"
        "Tiv+Qa9ucYItHTZzGI9NO01TK0gcZcTC41bwSDZRusaOwQWiZMxx3LZ+42rt16bVOiG+XnLQ5RLpRxG2c3UhBfNkX27/Qldu/7aBKYdeC3ji"
        "nPccPDhaLuI9BiFgqytHtnjCrUe1gBlOwAXauJmLQPIegBA4lGg+WIRnnubkowUEXKpB1e3BIRgCVoKQ5TQITZwxJgLrAqbd7sYIOPtFUwWG"
        "eDwX+8coEDelyo6TboXz4MRgecCE+wTuIZh0CybvlXaccDrek4BptyauatB787nZGCzs+OBuvLKACfcxpg2Em3RnECoG72MuwduAt4NX1bHf"
        "EmPujRUgOUk6zt8m4Tcgjudexxy+/Q9LQD5xZNJx7mtJjvvjijw+vwO3AQ5OeZRQeXKeDiGgoOvlPc1deQzS/TQPIQoqnPPSbi/7PUCZ49cQ"
        "Io7BizgB1Pzq8wgkb/ThvLedPFogb7Xy9LnytuBt7sF5GG8k72IhvzPLmrwRA7I3Sj70thDvBHH9ZUAKuAVvk/GLhi/lknk5eUvwwvxeeZLP"
        "3HhqCcZeRWkvvj4egcd62dLrF/eDnZ5/5g2/PFvH+XaHHqD9HY+9OtCqyzcHLouAtlCzl5/4Giyrmx0JQRTlf99iQFNxucEtJH6Lhm/hut6A"
        "5VVJja8x/8TtTwDwi8xiZXeApZV78z/OpD4q"
    ),
    "speak0": (
        "eNqt2IuSgyAMBVCDrFat1v//2g1BHoaHIGR2OlrbszcixXYYSgoAho4F+75DT26Wcz9QcdARhHkG/dAv3tAvIBC3Iwh94k2Km3boEhAlFW+W"
        "045/0KtbHGBJm80cxtOmnKapFSSOMmLhdivokk2UrrFjUIEomeZ03LZ+79Xar+TVOiBX/ZmNLlOkH0XYqasLabCL7MudX+jKnd82kHPotYAB"
        "p7z3oOPocjHeaxAstqtSZItnuN1VCxjhDLhCGzfrIpC8FyBYDiUaDy3CO8/nzEcLGHCtBr1uHYegDVgJQpTzQWjihBA3sC4g7/YUwoDzddFU"
        "gTaeHotzEx6Ii1Jlx6xbw13gpMHygIzbLPcSZN2CiHulHTPOj/cmIO9W3KsavLw5bPYOFnbsuAevLCDjNiHaQHhIF4JQcfI2kQUfAwYnb1Hl"
        "SXq/sONrSfS5nyoHmn3Wcfw2Cb8B6XjqdR7nQLfPOo59LQk59X5s7+aZ/WcQHOd7gnni7hkw5flcztMg3U/rU5gaW4/LehZMjTEEXO78cTDm"
        "HREvMb7MO0IP443k+fMsdf0JH0RvDAOid9h4bD4ILSyCzRcb8Ih6Z+iZWOT8lsg8Jm8t8j6feJ/2+WIvKAUu0SMp7wlcMlz8esH14KTjNVXg"
        "yTou0e4rUKbjaa8OlJnpq8B1NaAs1GT2E98Hy+phRUIQRfO/HzGgocgucCuJ36LTt+rKL8DmVazGvzF+4PEnAEiRUazsDrC0Ym/+B+rvPxw="
    ),
    "speak1": (
        "eNqt2It2gyAMBmCDVFstne//tAtBLoaLIOT0bDrbr39Ai9001RQATAMLlFIwklvlOg7UHAwEYV3B/BgXbxoXEIhTCMKYeIvmFgVDAqKk461y"
        "UfiAUd3iBEva7OYwnjHlsiy9IHGUEQu3e0GfbKF0nR2DDkTJDGfi9vV7rd5+Ja/eCTnrZTeGXCLjKMIOU0NIi53kWO74wlDu+PaBnEOvB4w4"
        "7T0HPUeni/Ueg+AwpUuTPZ7llK8eMMFZcIM+bjVFIHkPQHAcSjQfRoRnXsjZjxaw4NYMBt16DkEXsBGEJBeC0MUJIS5gW0De7SGEBdfzpGkC"
        "XTwzF8cuAhAXpcaOWbeWO8HFgPUBGbc77iHIugWR9mo7ZlwY70lA3q24VjN4emvc7BWs7NhzN15dQMbtQvSBcJMuBqFh8HZRBG8DRoP30RVI"
        "Zr+y43NJDLk/XR60+6zj9G0SfgMy8fTzAs6Dfp91nPpaEnP69djexbP79yB4LvQE88TVs2DOC7mSZ0C6nzZDmJvbgCt6DszNMURcafw4mPJ+"
        "CS8zv8z7xR7Gm8kLr7Pc+SdCEL05Dojez8Vj10P824MU8Jf0jtjL5OTeVuW9397T82A99/dqLyod8JM8kvPuwE+BS58vuB4cdLylKjzZxmXa"
        "fQTKfDzjtYGycPlqcNssKCs1WfzED8G6ulmREETRvvctBjQVxQVuI/FbNXybqfICbJ/Fan7N6QO3/wKAHJnE6u4Aayv14n8W7T8j"
    ),
    "speak2": (
        "eNqt2It2gyAMBmCDTFutre//tAtBLoaAKOT0bDrbr39Eit0w1BQADB0Ltm2Dntys536g4aAjCPMM9ke/eEO/gEDchiD0iTcZbtqgS0CUTLxZ"
        "Txs+oFe3OMCaNps5jGdNPU1TK0gcZcTC7VYwJJsoXWPHYAJRMsvZuG39nqu1X82rdUCO+nMbXaZIP4qw3VYX0mEH2ZfbP9CV2z9tIOfQawET"
        "znjPwcDR5eK8xyB4bDNlyBbPcVuoFlDgHLhAGzfbIpC8ByB4DiUaDyvCMy/m3EcLOHC5DUbdBg5BH/AmCCIXg9DEKaVO4L2AvNtdKQfOx0Vz"
        "C/Tx7Fjsq4pAXJRudsy6ddwBThasD8i41XMPQdYtKNmr7ZhxcbwnAXm36ly3wcOb02bPYGXHgbvw6gIyblWqDYSLdCkIN07eqorgZcDk5L1N"
        "RZLdr+z4WBJj7mcqgG6fdSzfJuE3IBvPPC/iAhj2WcfS15KUM6/H9k6e278GIXCxp5inzp4Dc17MlTwL0v20PYW5sY24oufB3BhDwpXOHwcl"
        "7yt4mfFl3jf1MN5IXjzPctefikH0xjQgel8fj80H+8tvnOYdBfyK3p56Suw78ZYq7/XyHuVynv97tceLwN9bOpTzrsBfgZOvF1wPdjougm+R"
        "q/FkEHJcpt1HoM7Hs949UBemrwGXxYG6UtPFT/wYrKuLFQlBFN17X2JAQ1Fc4BYSP1Wnb7FVXoDds1iNf6N84PJfAJAjRazuDrC2pBf/A/wm"
        "P50="
    ),
    "speak3": (
        "eNqt2It2gyAMBmCDqK2WM9//aReCXAwXQcjp2XS2X/+AFrtpqikAmAYWKKVgJLfJbRyoORgIwraB+TEu3jQuIBCnEIQx8VbNrQqGBERJx9vk"
        "qvABo7rFCZa02c1hPGPKdV17QeIoIxZu94I+2UrpOjsGHYiSGc7E7ev3Xr39Sl69E3LVYjeGXCLjKMJOU0NIi13kWO78wVDu/PWBnEOvB4w4"
        "7b0HPUeni/Veg+AwpUuTPZ7llK8eMMFZcIc+bjNFIHkvQHAcSjQfRoR3XsjZjxaw4N4MBt16DkEXsBGEJBeC0MUJIW5gW0De7SmEBbfrpGkC"
        "XTwzF+chAhAXpcaOWbeWu8DVgPUBGXc47iXIugWR9mo7ZlwY701A3q24VzN4eVvc7B2s7NhzD15dQMYdQvSB8JAuBqFh8A5RBB8DRoP31RVI"
        "Zr+y42tJDLk/XR60+6zj9G0SfgMy8fTzAs6Dfp91nPpaEnP69djezbP7zyB4LvQE88Tds2DOC7mSZ0C6nzZDmJvbgCt6DszNMURcafw4mPKW"
        "hJeZX+YtsYfxZvLC6yx3/okQRG+OA6K3uHjseoh/e5ACLknvjL1MTu7tVd7n4z09D9Zzf6/2otIBv8kjOe8J/Ba49PmC68FJx1uqwpNtXKbd"
        "V6DMxzNeGygLl68G992CslKTxU/8EKyrhxUJQRTtez9iQFNRXOB2En9Vw7ebKi/A9lms5mVOH3j8FwDkyCRWdwdYW6kX/wNdGj7/"
    ),
    "verified": (
        "eNqt2IFygyAMBmCDKKvWq+//tAsJoERQEHK7na722x9QsR2GkgKAoWPBtm3QkzPa9AMtBx1BMAb4V794Q7+AQNyGIPSJN1tu3qBLQJRsPKPn"
        "DX+gV7c4wZo2mzmMx6ae57kVJI4yYuF2K3gkmyldY8dgA1Ey5jhuW79xtfarZbVOiKvJb3S5RPpRhO1cXUiPObIvt3+hK7d/20DJodcCXjjr"
        "vQcPjk4X770GIWCbLUu2eJ7bjmoBE5wHF2jjDBeB5L0AIXAo0XywCO+8M+dvLeDBpRo8dXtwCIaAlSAkuTMITZxSKgLrAspud6U8aNxJUwWG"
        "eDwX+6pOIC5KlR2Lbj3nwJnB8oCCWwP3EhTdgkp7pR0L7hzvTUDZrYqrGnSeuTYbg4UdH9yDVxZQcKtSbSA8pLuCUDF4q7oFHwPKwftwBcjt"
        "F3bslsQT9+PyYNgXHacfk/ATEMezx/HgZfJdOk59LElxuXwlIByc92wefHeUz+3LIcx5EceRPuepDft0DD1P8xDm5jbm8l4Ac3MMKe7Gi8GU"
        "N732pquH8UbyxHVmRz/Mr9uPQfTGa0D0phAvvrw+P3fexVEZpIBT0tuF9/d3Pe+ivwdvKfKiUfv9ZLoK71LHbUBWznsAc3VzvuB6sNPrnT1d"
        "x2XafQXqfDz26kB9c/lacFk8qAs1fXvHP4Nl9bAiIYii/9+PGNBU3C5wC4nfouFbuO4XYH+UqHEa0y88fgUAOTKJlT0Bllbqzf9IyDzb"
    ),
    "happy": (
        "eNqt2IFygyAMBmCDqFPr6fs/7UIQhAACQm631Wm//QFa7IahpABg6FhwHAf05Ba59AMVBx1BWBbQ3/rFG/oFBOIOBKFPvFlx8wFdAqKk4i1y"
        "PvALenWLEyzpYTOH8bQp53luBYmjjFj4uBV8ks2UrrFjUIEomeZ03LZ+/WrtV/JqnZC7JvOgy0ukH0XYpasLabCb7MtdP+jKXb82kHPotYAB"
        "p7zv4MPRcjHeZxAsdqhSZItnuOOpFjDCGXCDNm7RRSB5H0CwHEo0H1qEb57LmbcWMOBWDTrdPhyCNmAlCFHOBaGJE0J4YF1A3u0lhAGXe9FU"
        "gTaenotrFw6Im1Jlx6xbw93grMHygIzbLfcRZN2CiHulHTPOjfclIO9W+FUN3t4SNuuDhR0/XMYrC8i4XYg2EDLpQhAqBm8Xr2A2YHbwqjq+"
        "t0SfW5m1RjqO3ybhJyAdT11nudMH72PWcexjSYI7PdAe50F4OOvh01cXfI75EKa8gBMO6B7TNXQ/rYcwNbfh4K2Ot7IhNN6W8DzOTO7qT645"
        "9sCYNwXeazneFHoYbyQvwq3spw+iN4YB0ZtsPMHXnK4zAlLAKepdzPv7c1bd+axE+3vrbUWev4xPnq7CC4rajZ5JeRkwVS/rBfeDi8539mQd"
        "l2j3EyjT8bRXB8qXl68Ct82AslCTr+/4LlhWmR0JQRTN385iQFPxusFtJP6Khm/T9b4Bm6tYjdMYP5H9FwCkyChWdgdYWrEn/wMY2TsF"
    ),
    "alert": (
        "eNqt2A1zgyAMBmCDqNXWm///1y4kfIMIQm7X07U+eyMidtNUUwAwDSw4zxNGcpvcxoGKg4EgbBvwy7h407iAQNyJIIyJtypuPWFIQJRUvE2u"
        "J/7AqG5xgCVtdnMYj025rmsvSBxlxMLtXtAlWyldZ8egAlEy5jhuX79h9fYr4+odEF2L2RgyRcZRhF1cQ0iDaXIsd/1gKHf9+sCYQ68HTDjl"
        "vQcdR5eL8V6DYLFTlSJ7PMOdrnrADGfAA/q4jYtA8l6AYDmUaDxYhHeez5lbCxjwaAa9bh2HoA3YCEKW80Ho4oQQAdgWMO72EsKAm75omkAb"
        "j8fi+goPxEWpseOoW8NpcGWwPmDEfS33Eoy6BZH3ajuOOD/em4BxtyKsZlB7W9psCFZ27LgHry5gxH2F6AMhTLer8izaD0FoOHn7nyoH6n3v"
        "FJYDRt3y4Q60+3Ud6yXR6xYP3ffA4/2o4/xjEn4D4njqczS0REUev0Qd576WpFzBqwDBcQ2eAe88nyt5DNLzNJ/Cu7H1uKJnwbsxhoQTt+Mr"
        "EjDnLRkvf/3F3pJ6GG8mz78LuPnB0y6cLxpEb04DorfYeOF81dDu7TuQAi5Z74q8z8fNW3XeDGR/b72jyvNuK4GX5nvyktrtbSWuO+8J3Atc"
        "/nrB9eCi91uqwpNt3E27r0B5H4+9NlAWpq8Cj8OAslKTxTu+D9bVw4qEIIrmbz9iQENRXOAOEn9Vp+/gKi/A5lNRzcucf+PxXwBwR2axuifA"
        "2sod/A8X+kBN"
    ),
}

_cache: dict[str, list[list[int]]] = {}
_sleep = time.sleep                      # тесты подменяют, чтобы не ждать анимацию
_OUTLINE = _PALETTE.index("#161E31") + 1
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
            else:   # контур (#161E31) уступает цвету: иначе золото, глаза и румянец тонут в тёмном
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


# системные переменные терминала (как TERM у любой консольной программы), не настройки агента для .env.example
_TERM_VARS = ("TERM", "COLORTERM", "NO_COLOR", "TERM_PROGRAM", "WT_SESSION")


def color_mode(stream: Any = None, env: Mapping[str, str] | None = None) -> str:
    """'truecolor', '256' или 'ascii'."""
    stream = stream or sys.stdout
    env = os.environ if env is None else env
    v = {name: (env.get(name) or "") for name in _TERM_VARS}
    try:
        "▀▄█⠋✓—…".encode(getattr(stream, "encoding", None) or "ascii")
    except (UnicodeEncodeError, LookupError):
        return "ascii"
    if v["NO_COLOR"] or v["TERM"].lower() == "dumb":
        return "ascii"
    if os.name == "nt":
        if not _enable_vt(stream):
            return "ascii"
        return "truecolor"          # Windows Terminal и консоль Windows 10+ понимают 24 бита
    if v["COLORTERM"].lower() in ("truecolor", "24bit") or v["WT_SESSION"]:
        return "truecolor"
    if v["TERM_PROGRAM"] in ("iTerm.app", "vscode", "WezTerm", "ghostty"):
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


ASCII_FACES = {"idle": "oo", "blink": "--", "wink": ">o", "look": "oo", "analyzing": "==", "speak": "oo",
               "verified": "^^", "happy": "^^", "alert": "OO"}


def ascii_drone(mood: str) -> list[str]:
    """AIshka без цвета: треугольный корпус, лицо внутри."""
    face = ASCII_FACES.get(re.sub(r"\d+$", "", mood), "oo")
    return ["      /\\",
            "     /  \\",
            f"    / {face} \\",
            "   /  --  \\",
            "  '--------'"]


def render(name: str, mode: str, *, small: bool = False, indent: int = 2) -> list[str]:
    """Строки терминала с AIshka: полублок «▀» — верхний пиксель цветом текста, нижний — фоном."""
    if mode == "ascii":
        return ascii_drone(name)
    rows = compact(frame(name))          # вдвое: 40×36 px → 18 строк
    if small:
        rows = compact(rows)                # тесное окно: ещё вдвое
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
        self.small = mode != "ascii" and (self.cols < 50 or self.rows < 28)
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

    def say(self, text: str, *, style: str = "", typing: bool = True, end: str = "\n", talk: str = "") -> None:
        """Строка реплики. talk — пока печатает, AIshka говорит (рот двигается), потом принимает этот кадр."""
        body = "  " + text
        if self.live and typing and self.mode != "ascii":
            self.write(style)
            for i, ch in enumerate(body):
                self.write(ch)
                if talk and i % 4 == 2:
                    self._mouth(f"speak{(i // 4) % 4}", style)
                if ch not in " ":
                    _sleep(0.012)
            if talk:
                self._mouth(talk, style)
            self.write(self.reset if style else "")
        else:
            self.write(f"{style}{body}{self.reset if style else ''}")
        self.write(end)
        if end.endswith("\n"):
            self.below += self._rows_of(body)

    def _mouth(self, name: str, style: str) -> None:
        """Сменить кадр посреди печати: запомнить курсор (ESC 7), перерисовать AIshka, вернуться (ESC 8)."""
        self.write("\x1b7")
        self.swap(name)
        self.write("\x1b8" + style)

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
        _sleep(0.25)
        scr.swap("blink")
        _sleep(0.13)
        scr.swap("idle")
        if ready:
            hello = "С возвращением!" if ready in ("gemini", "anthropic", "openai") else "Здравствуйте! Я BCC AI."
            scr.say(f"{hello} {where[0].upper() + where[1:]}.", talk="wink")
            scr.say("Открываю систему…", style=scr.dim, typing=False)
            return ready
        scr.say("Здравствуйте! Я BCC AI — проверяю ТЗ до начала разработки.", style=scr.bold, talk="idle")
        _sleep(0.2)
        scr.swap("look")
        scr.say("Вставьте ключ Gemini или Claude. Enter — без ключа.", talk="look")
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
                scr.swap("wink")
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
        scr.swap("wink")
        scr.say(f"Продолжу без ключа. Ключ можно вставить в браузере: {url}/welcome", style=scr.dim)
        return "offline"
    except KeyboardInterrupt:
        scr.write("\n")
        raise
    finally:
        scr.cursor(True)
        if scr.mode != "ascii":
            scr.write(RESET)
