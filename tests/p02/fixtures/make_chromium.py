"""PDF «как напечатал браузер» для проверки №02 на реалистичном производителе.

    python tests/p02/fixtures/make_chromium.py path/to/requirements.md

Нужны пакет ``markdown`` и Node с ``playwright`` (Chromium). Пишет два файла:

* ``case_requirements_chromium.pdf`` — выданный кейс (docs/requirements.md из
  BCC-HUB/ai-requirements-validator-task@928c1aa) в вёрстке GitHub-подобного CSS, с
  колонтитулами Chromium (дата, заголовок, адрес, «N/M») — как его печатают из браузера;
* ``chromium_layouts.pdf`` — две CSS-колонки, таблица без линеек «ключ — значение»,
  таблица с объединёнными ячейками.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

import markdown

HERE = Path(__file__).resolve().parent
CSS = """
body { font-family: 'DejaVu Sans', sans-serif; font-size: 10.5pt; line-height: 1.45; margin: 0; }
h1 { font-size: 18pt; } h2 { font-size: 14pt; } h3 { font-size: 12pt; } h4 { font-size: 11pt; }
table { border-collapse: collapse; margin: 6pt 0; }
th, td { border: 0.6pt solid #444; padding: 3pt 5pt; vertical-align: top; text-align: left; }
th { background: #eee; }
pre { background: #f4f4f4; padding: 6pt; white-space: pre-wrap; }
code { font-family: 'DejaVu Sans Mono', monospace; font-size: 9.5pt; }
.cols { column-count: 2; column-gap: 24pt; }
.plain td, .plain th { border: none; background: none; padding: 2pt 18pt 2pt 0; }
"""
LAYOUTS = """
<h1>Раскладки Chromium</h1>
<h2>Две колонки</h2>
<div class="cols">
<p>Первая колонка начинается здесь. Держатель карты задаёт месячный порог в тенге, и сервис считает покупки
за календарный месяц по времени Алматы. Когда сумма достигает порога, клиент получает одно уведомление.</p>
<p>Возвраты уменьшают сумму расходов, а переводы между своими счетами не считаются покупками и не увеличивают
счётчик. Изменение порога сохраняет накопленные расходы текущего месяца.</p>
<p>Вторая колонка продолжает текст. Порог уведомления составляет 60 000 ₸ для зарплатной карты, и он может
быть изменён держателем в любой момент без потери накопленной суммы.</p>
</div>
<h2>Ключ — значение без линеек</h2>
<table class="plain">
<tr><td>Наименование задачи</td><td>Месячный порог расходов по карте</td></tr>
<tr><td>Продукт</td><td>Мобильный банк, учебный кейс</td></tr>
<tr><td>Тип работы</td><td>Новый функционал</td></tr>
<tr><td>Задача в JIRA</td><td>Практикум без Jira-задачи</td></tr>
</table>
<h2>Объединённые ячейки</h2>
<table>
<tr><th rowspan="2">Сценарий</th><th colspan="2">Сумма, ₸</th></tr>
<tr><th>до</th><th>после</th></tr>
<tr><td>Покупка</td><td>48 500</td><td>50 000</td></tr>
<tr><td>Перевод</td><td>19 900</td><td>19 900</td></tr>
</table>
"""

PRINT_JS = r"""
const { chromium } = require('playwright');
(async () => {
  const [html, pdf, header] = process.argv.slice(2);
  const browser = await chromium.launch();
  const page = await browser.newPage();
  await page.goto('file://' + html);
  await page.pdf({ path: pdf, format: 'A4', printBackground: true,
    margin: { top: '18mm', bottom: '18mm', left: '16mm', right: '16mm' },
    displayHeaderFooter: header === '1',
    headerTemplate: '<div style="font-size:7pt;width:100%;padding:0 16mm;display:flex;justify-content:space-between">'
      + '<span>27.11.2026, 10:00</span><span class="title"></span></div>',
    footerTemplate: '<div style="font-size:7pt;width:100%;padding:0 16mm;display:flex;justify-content:space-between">'
      + '<span>file:///requirements.html</span><span><span class="pageNumber"></span>/<span class="totalPages"></span></span></div>' });
  await browser.close();
})();
"""


def _print(body_html: str, title: str, out: Path, header: bool) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        html = Path(tmp) / 'doc.html'
        html.write_text(f'<!doctype html><meta charset="utf-8"><title>{title}</title><style>{CSS}</style>{body_html}',
                        encoding='utf-8')
        script = Path(tmp) / 'print.js'
        script.write_text(PRINT_JS, encoding='utf-8')
        subprocess.run(['node', str(script), str(html), str(out), '1' if header else '0'], check=True)


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    source = Path(sys.argv[1]).read_text(encoding='utf-8')
    body = markdown.markdown(source, extensions=['tables', 'fenced_code'])
    _print(body, 'Месячный порог расходов по карте', HERE / 'case_requirements_chromium.pdf', header=True)
    _print(LAYOUTS, 'Раскладки Chromium', HERE / 'chromium_layouts.pdf', header=False)
    print(json.dumps({'ok': [str(HERE / 'case_requirements_chromium.pdf'), str(HERE / 'chromium_layouts.pdf')]},
                     ensure_ascii=False))


if __name__ == '__main__':
    main()
