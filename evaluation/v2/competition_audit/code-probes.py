"""Офлайн-проверка кода трёх валидаторов на зафиксированных Git-версиях.

Нужны git, Python 3.12+, pydantic 2 и rapidfuzz 3.14.6. Ничего не устанавливает.
python code-probes.py BCC_WORKTREE ERA_REPO AZ_REPO [--out code-probes.json]
"""
from __future__ import annotations
import argparse
import ast
import hashlib
import json
import re
import subprocess
import sys
import tempfile
import unicodedata
from collections import Counter
from pathlib import Path
from textwrap import dedent

parser=argparse.ArgumentParser(description=__doc__)
for key in ('bcc','era','az'):
    parser.add_argument(key,type=Path)
parser.add_argument('--out',type=Path)
args=parser.parse_args()
refs={'bcc':'1933b20ca2fcde39ab59c3804a6ec4438c8ddd87','experiment':'786366da0be6fa2117028e70951c18a1a6939243','measurement':'05306ab55f5d08b0306e62ae283277e527881202','era':'4755c4558e1c80974b5a9c30550656f2c44e2743','az':'c704a9e2dffe59390c7c104a517aedfa10ae4ce8'}

def show(repo,ref,path):
    return subprocess.check_output(['git','-C',str(repo),'show',ref+':'+path])

def norm(text):
    folded=unicodedata.normalize('NFKC',text).casefold().replace('ё','е')
    return ' '.join(re.findall(r'[^\W_]+',folded))

tmp=tempfile.TemporaryDirectory()
root=Path(tmp.name)
for repo,name,modules in [(args.era,'revizor',['__init__','document','verify','criteria','rules','schemas']),(args.az,'reqvalidator',['__init__','document','criteria','lint','loaders','models'])]:
    pkg=root/name
    pkg.mkdir()
    ref=refs['era' if name=='revizor' else 'az']
    for mod in modules:
        path=name+'/'+mod+'.py'
        (pkg/(mod+'.py')).write_bytes(show(repo,ref,path))
for key,mod in [('bcc','bcc_release'),('experiment','bcc_candidate')]:
    (root/(mod+'.py')).write_bytes(show(args.bcc,refs[key],'src/bcc_review/v2/quotes.py'))
# Загружаем только детерминированный метод _ground и два его локальных помощника.
raw=show(args.az,refs['az'],'reqvalidator/pipeline.py').decode('utf8')
tree=ast.parse(raw)
cls=next(x for x in tree.body if isinstance(x,ast.ClassDef) and x.name=='Pipeline')
ground=next(x for x in cls.body if isinstance(x,ast.FunctionDef) and x.name=='_ground')
clean=next(x for x in tree.body if isinstance(x,ast.FunctionDef) and x.name=='clean_text')
markup=next(x for x in tree.body if isinstance(x,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='_MD_MARKUP' for t in x.targets))
prefix='from __future__ import annotations\nimport re\nfrom reqvalidator.document import Document\nfrom reqvalidator.models import Evidence\n'
(root/'az_ground.py').write_text(prefix+'\n\n'.join(dedent(ast.get_source_segment(raw,n)) for n in (markup,clean,ground)),encoding='utf8')
sys.path.insert(0,str(root))
from revizor.document import load_document as era_load
from revizor.verify import QuoteLocator
from revizor.rules import run_rules
from reqvalidator.loaders import load_document as az_load
from reqvalidator.lint import run_lint
from az_ground import _ground
import bcc_release
import bcc_candidate

phrase='Срок выдачи — два рабочих дня.'
rows=['# Заявка',phrase,'## Сбой','При отказе составляется акт.',phrase]
duplicate_path=root/'duplicate.md'
duplicate_path.write_text('\n'.join(rows)+'\n',encoding='utf8')
edoc=era_load(duplicate_path)
adoc=az_load(duplicate_path)
def bcc_quote(module,text):
    view={'lines':[{'n':i,'text':row,'section':'','page':None} for i,row in enumerate(rows,1)]}
    found=module.verify_evidence(view,{'quote':text,'line':5})
    return [found['line_start'],found['verified'],found['quote']]

result={'refs':refs,'quotes':{},'rules':{},'published':{}}
for name,text in [('repeat',phrase),('absent','Смена поколения спутника зависит от орбиты.')]:
    er=QuoteLocator(edoc).locate(text,5)
    az=_ground(None,adoc,text,near=5,fallback=(5,5))
    result['quotes'][name]={'ERA':[er.line_start,er.verified,er.score,er.quote],'AZ':[az.line_start,az.verified,az.score,az.quote],'BCC release':bcc_quote(bcc_release,text),'BCC candidate':bcc_quote(bcc_candidate,text)}
aligned = '# Уведомление о лимите перевода\n\n## Часть A. Новый функционал\n\nФТ-1. Клиент получает СМС-подтверждение перевода со своего счёта. Максимальная допустимая сумма одного перевода составляет 12 700 тенге включительно. При превышении лимита перевод отклоняется до списания средств.\n\nНФТ-1. При нагрузке до 10 запросов в секунду ответ отправляется за 2 секунды для 95 % запросов.\n\nДанные. Сохраняются идентификатор перевода, сумма в целых тенге и статус. Сервис уведомлений получает только идентификатор и статус.\n\nКритерий приёмки. Перевод на 12 700 тенге разрешён. При 12 701 тенге сервис возвращает 422, списания и отправки СМС не происходит.\n\n## Часть B. Спецификация REST API\n\nPOST /v1/transfer-approvals принимает сумму amount в целых тенге и requestId. Для существующего requestId возвращается прежний результат.\n\nМетод разрешает и проводит перевод на любую сумму от 1 до 12 700 тенге включительно. Сумму сверх верхней границы отклоняет с кодом 422.\n'
clash = '# Уведомление о лимите перевода\n\n## Часть A. Новый функционал\n\nФТ-1. Клиент получает СМС-подтверждение перевода со своего счёта. Максимальная допустимая сумма одного перевода составляет 12 700 тенге включительно. При превышении лимита перевод отклоняется до списания средств.\n\nНФТ-1. При нагрузке до 10 запросов в секунду ответ отправляется за 2 секунды для 95 % запросов.\n\nДанные. Сохраняются идентификатор перевода, сумма в целых тенге и статус. Сервис уведомлений получает только идентификатор и статус.\n\nКритерий приёмки. Перевод на 12 700 тенге разрешён. При 12 701 тенге сервис возвращает 422, списания и отправки СМС не происходит.\n\n## Часть B. Спецификация REST API\n\nPOST /v1/transfer-approvals принимает сумму amount в целых тенге и requestId. Для существующего requestId возвращается прежний результат.\n\nМетод разрешает и проводит перевод на любую сумму от 1 до 24 500 тенге включительно. Сумму сверх верхней границы отклоняет с кодом 422.\n'

for name,data in [('aligned',aligned),('clash',clash)]:
    p=root/(name+'.md')
    p.write_bytes(data.encode('utf8'))
    era_document=era_load(p)
    result['rules'][name]={'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'ERA':len(run_rules(era_document,QuoteLocator(era_document))),'AZ':len(run_lint(az_load(p)))}

report_dir='evaluation/v2/measurements/reliz_w4_18_45_md_3e7133c_sonnet_1/'
inputs=[('BCC',args.bcc,refs['measurement'],'release/input/requirements.md',report_dir+'report.json'),('ERA',args.era,refs['era'],'examples/requirements.md','reports/report.json'),('AZ',args.az,refs['az'],'docs/requirements.md','reports/requirements-report.json')]
for name,repo,ref,source,rpath in inputs:
    p=root/(name+'-in.md')
    p.write_bytes(show(repo,ref,source))
    reported=json.loads(show(repo,ref,rpath))
    if name=='BCC':
        by_line=dict(enumerate(p.read_text(encoding='utf8').splitlines(),1))
    else:
        loaded=(era_load if name=='ERA' else az_load)(p)
        by_line={line.no:line.text for line in loaded.lines}
    findings=[f for f in reported['findings'] if f.get('status') in (None,'open','confirmed')]
    c=Counter()
    for f in findings:
        for e in f.get('evidence',[]):
            first=e['line_start']
            last=e.get('line_end') or first
            source_line=' '.join(by_line.get(n,'') for n in range(first,last+1))
            quote=e['quote']
            c['evidence']+=1
            c['literal']+=int(quote in source_line)
            c['same_words']+=int(bool(norm(quote)) and (' '+norm(quote)+' ') in (' '+norm(source_line)+' '))
            c['score_zero']+=int(e.get('score')==0)
    result['published'][name]={'source_sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'open':len(findings),**dict(c)}
rendered=json.dumps(result,ensure_ascii=False,indent=2)+'\n'
if args.out:
    args.out.write_text(rendered,encoding='utf8')
else:
    print(rendered)
