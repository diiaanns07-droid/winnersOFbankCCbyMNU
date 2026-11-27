import argparse,subprocess as sp,datetime
from collections import Counter
from pathlib import Path
parser=argparse.ArgumentParser(description="Снимок всех голов Git относительно релиза и исторической сборки")
parser.add_argument("--repo",type=Path,required=True)
parser.add_argument("--out",type=Path,required=True)
parser.add_argument("--json",type=Path)
args=parser.parse_args()
R=args.repo.resolve()
baseurl="https://github.com/diiaanns07-droid/winnersOFbankCCbyMNU"
def g(*args):
 return sp.run(["git","-c","core.quotepath=false",*args],cwd=R,stdout=sp.PIPE,stderr=sp.PIPE,check=True).stdout.decode("utf8",errors="replace").strip()
def show(sha,path):return g("show",sha+":"+path)
import json,concurrent.futures as cf
from datetime import timezone,timedelta
stamp=datetime.datetime.now(timezone(timedelta(hours=5))).strftime("%Y-%m-%d %H:%M:%S +05")
entries=[(s.split('\t')+['',''])[:3] for s in g('for-each-ref','--format=%(refname)%09%(objectname)%09%(symref)','refs/heads','refs/remotes/origin').splitlines()]
heads={n:h for n,h,s in entries if not s}
syms={n:(h,s) for n,h,s in entries if s}
org='refs/remotes/origin/'
release=heads[org+'release']; integ=heads[org+'codex/integration-all-20261127-1703']
sha=set(heads.values())
graph={s.split()[0]:s.split()[1:] for s in g('rev-list','--all','--parents').splitlines()}
def parents(h):
 result=set(); stack=[h]
 while stack:
  x=stack.pop()
  if x not in result:result.add(x);stack.extend(graph.get(x,[]))
 return result
anc={h:parents(h) for h in sha}
def nm(n):return n.replace('refs/heads/','local/').replace('refs/remotes/','')
def prio(n):
 s=nm(n)
 return (next((i for i,z in enumerate(['origin/bcc/v2','origin/release','origin/bcc/','origin/codex/','origin/eval/','origin/v2/','origin/claude/','local/']) if s==z or (z.endswith('/') and s.startswith(z))),24),s)
aliases={h:sorted([n for n,v in heads.items() if v==h],key=prio) for h in sha}
def area(p):
 for x,e in [('src/bcc_review/v2/stages/','этапы v2'),('src/bcc_review/v2/providers/','провайдеры'),('src/bcc_review/v2/prompts/','промпты'),('src/bcc_review/v2/render/','рендер'),('src/bcc_review/v2/','ядро v2'),('src/','другой код'),('tests/','тесты'),('reports/','отчёты'),('evaluation/','замеры'),('docs/plan-v2/status','статус'),('docs/','документы'),('scripts/','скрипты'),('release/','сдача'),('presentation/','презентация')]:
  if p.startswith(x):return e
 return 'прочее'
config=['src','contracts','pyproject.toml','requirements.txt','constraints.txt','Dockerfile','.env.example']
def product(h):
 d={l.split('\t',1)[1]:l.split('\t',1)[0].split()[2] for l in g('ls-tree',h,'--',*config).splitlines() if l}
 count=Counter()
 if h not in anc[release]:
  b=sp.run(['git','merge-base',release,h],cwd=R,stdout=sp.PIPE,stderr=sp.PIPE).stdout.decode('ascii').strip()
  count=Counter(area(x) for x in g('diff','--name-only',b,h).splitlines()) if b else Counter({'отдельная история':1})
 return h,(d.get('src',''),tuple(d.get(k,'') for k in config),count)
with cf.ThreadPoolExecutor(max_workers=4) as pool: meta=dict(pool.map(product,sha))
outside=sha-anc[integ]; independent=[h for h in outside if not any(h!=k and h in anc[k] for k in outside)]
counts=dict(local=sum(n.startswith('refs/heads/') for n in heads),remote=sum(n.startswith(org) for n in heads),unique=len(sha),alias=len(syms),src=len(set(x[0] for x in meta.values())),rel=sum(h in anc[release] for h in sha),outs=len(outside),ind=len(independent),same_src=sum(meta[h][0]==meta[release][0] for h in sha),same_pkg=sum(meta[h][1]==meta[release][1] for h in sha))
def lk(h):return '['+h[:9]+']('+baseurl+'/commit/'+h+')'
def incl(h,r):return 'да' if h in anc[r] else 'нет'
def eq(h):
 if meta[h][1]==meta[release][1]:return 'пакет ='
 if meta[h][0]==meta[release][0]:return 'src ='
 if not meta[h][0]:return 'нет src'
 return 'иной'
c=counts
lines=['# Все ветки команды','',f'Снимок удалённых ссылок после fetch, {stamp} по Астане. Локальных веток — {c["local"]}, удалённых — {c["remote"]}, различных конечных коммитов — {c["unique"]}. Символическая ссылка origin/HEAD приведена отдельно. У вершин {c["src"]} вариантов дерева src/, включая возможное отсутствие каталога.','',f'«В релизе» означает достижимость по истории {lk(release)}, «в общей» — по истории {lk(integ)}. Проверка равенства src/ сравнивает Git tree ID. «Пакет =» дополнительно требует точного совпадения contracts/, pyproject.toml, requirements.txt, constraints.txt, Dockerfile и .env.example. Скрипты, отчёты и тесты в это определение не входят. Разные SHA могут содержать одну правку после cherry-pick.','','В последней колонке показано предпочтительное имя другой ссылки на тот же коммит или число затронутых на стороне ветки файлов по группам от общего предка с релизом. Упоминание области не доказывает уникальности кода в ней.','',f'В историю релиза входят {c["rel"]} из {c["unique"]} вершин, вместе с ним самим. У {c["same_src"]} вершин полностью совпадает src/, у {c["same_pkg"]} — перечисленный пакет. За пределами исторической общей сборки остаются {c["outs"]} вершин, из них {c["ind"]} независимых (ни одна не предок других в этой группе).','','| Ветка | Коммит | В релизе | В общей | Код к релизу | Алиас или изменения в ветке |','| --- | --- | --- | --- | --- | --- |']
bq=chr(96)
for n in sorted(heads,key=lambda x:(0 if x.startswith(org) else 1,nm(x))):
 h=heads[n]; pref=aliases[h][0]
 if n!=pref:z='= '+nm(pref)
 elif h==release:z='релизная вершина'
 elif h in anc[release]:z='предок релиза'
 else:z=', '.join(f'{key} {num}' for key,num in meta[h][2].most_common()) or 'те же файлы от общего предка'
 lines.append(f'| {bq}{nm(n)}{bq} | {lk(h)} | {incl(h,release)} | {incl(h,integ)} | {eq(h)} | {z} |')
for n,(h,s) in syms.items():lines.append(f'| {bq}{nm(n)}{bq} (символическая) | {lk(h)} | {incl(h,release)} | {incl(h,integ)} | {eq(h)} | → {nm(s)} |')
lines+=['','## Независимые продолжения после общей сборки','','| Ветка | Вершина | Коммиты вне общей сборки |','| --- | --- | ---: |']
for h in sorted(independent,key=lambda x:prio(aliases[x][0])):
 lines.append(f'| {bq}{nm(aliases[h][0])}{bq} | {lk(h)} | {len(anc[h]-anc[integ])} |')
args.out.parent.mkdir(parents=True,exist_ok=True)
args.out.write_text('\n'.join(lines)+'\n',encoding='utf8')
if args.json:
 args.json.parent.mkdir(parents=True,exist_ok=True)
 args.json.write_text(json.dumps(dict(stamp=stamp,counts=c,heads=heads,syms=syms,independent=independent,meta=meta,aliases=aliases),ensure_ascii=False),encoding='utf8')
print(stamp, c)
print('independent', sorted((nm(aliases[h][0]),h[:8]) for h in independent))
print("same source",[(h[:8],nm(aliases[h][0])) for h in sha if eq(h) in ['src =','пакет =']])
