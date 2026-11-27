"""Сводка прогона для жюри: python jury_summary.py ОТЧЁТ.json СЕКУНД КОД_ПРОГОНА КОД_VERIFY"""
import json, sys
path, secs, code, vcode = sys.argv[1], float(sys.argv[2]), int(sys.argv[3]), int(sys.argv[4])
try:
    r = json.load(open(path, encoding="utf-8"))
except (OSError, ValueError) as exc:
    print(f"Отчёт не создан ({exc}). Смотрите сообщения выше."); sys.exit(1)
run, s = r.get("run", {}), r.get("summary", {})
f = s.get("findings") or {}
calls, tok = run.get("calls") or {}, run.get("tokens") or {}
v = r.get("verdict") or {}
ru = {"no": "нельзя", "conditional": "условно", "yes": "можно"}
status = {"complete": "полный", "partial": "неполный", "failed": "со сбоем"}.get(run.get("status"), run.get("status"))
print(f"Статус прогона:   {status} (код выхода {code})")
print(f"Время:            {secs:.0f} с (по паспорту {run.get('duration_s')} с)")
print(f"Провайдер/модель: {run.get('provider')} / {', '.join(run.get('models_used') or []) or 'модель не вызывалась'}")
print(f"Вызовов модели:   {calls.get('total', 0)} (из кэша {calls.get('cached', 0)}, неудачных {calls.get('failed', 0)}, делений {calls.get('split', 0)})")
print(f"Токены:           вход {tok.get('input', 0)}, выход {tok.get('output', 0)}; стоимость ${run.get('cost_usd') or 0:.4f}")
print(f"Дефектов:         критичных {f.get('critical', 0)}, существенных {f.get('major', 0)}, незначительных {f.get('minor', 0)}")
print(f"Вердикт:          разработка — {ru.get(v.get('development'), 'не вынесен')}, тестирование — {ru.get(v.get('testing'), 'не вынесен')}")
print(f"verify:           {'ок' if vcode == 0 else 'НЕ ПРОШЁЛ (код %d)' % vcode}; цитат сверено {s.get('quotes_verified', '—')}")
w = run.get("warnings") or []
if w:
    print(f"Первое предупреждение: {w[0].splitlines()[0]}")
ok = run.get("status") == "complete" and vcode == 0
print("ИТОГ: " + ("всё работает" if ok else "есть проблемы — см. строки выше"))
sys.exit(0 if ok else 1)
