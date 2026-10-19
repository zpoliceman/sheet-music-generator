"""历史扫弦图只读升级：按原动作重画箭头，不覆盖旧工程、音乐和缓存谱页。"""
from pathlib import Path
import json,os,subprocess,sys,uuid
import xml.etree.ElementTree as ET
HTML=Path(__file__).resolve().parents[1];ROOT=HTML.parent;NS='{http://www.w3.org/2000/svg}'

def notation_source(source,output,project):
    events=project['arrangements']['guitar'].get('selected_pattern_actions',[])
    swept={identity for event in events if event['kind']=='strum' for identity in event['note_ids']}
    if not swept:return source,False
    legacy=False
    for path in (source/'guitar/rows').glob('repeat_*.svg'):
        for e in ET.parse(path).getroot().iter():
            if e.get('data-action-kind')=='strum' and (e.find(NS+"line[@class='strum-shaft']") is None or e.find(NS+'text') is not None):legacy=True
            if e.get('data-sustain-note-id') in swept:legacy=True
            if e.get('data-note-id') in swept and e.get('data-continuation')!='true':legacy=True
    if not legacy:return source,False
    python=ROOT/'.venv-gpu/Scripts/python.exe'
    if not python.is_file():raise ValueError('旧扫弦谱需要主项目环境进行只读记谱更新，请先准备主环境。')
    destination=output/'notation_source'
    if not destination.resolve().is_relative_to(HTML/'runtime'):destination=HTML/'runtime/notation_adaptations'/uuid.uuid4().hex
    env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1','PYTHONIOENCODING':'utf-8'}
    with (output/'evidence/notation_adapter.log').open('w',encoding='utf-8') as log:
        subprocess.run([str(python),'-B','-X','utf8',str(HTML/'scripts/prepare_print_source.py'),'--source',str(source),'--output',str(destination)],cwd=HTML,env=env,stdout=log,stderr=subprocess.STDOUT,check=True,timeout=600,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
    assert (destination/'project.json').read_bytes()==(source/'project.json').read_bytes(),'记谱更新改变源工程。'
    return destination,True
