"""待校对草稿的真实来源、音乐摘要和可见标记；不赋予正式音乐认可。"""
from copy import deepcopy
from pathlib import Path
import hashlib
import json
from score_export import read_json,save_json,sha256

ROOT=Path(__file__).resolve().parents[1]
NOTICE='待校对自动草稿：请结合原唱核对拍速、首拍、歌词和伴奏。'
BANNER='<div class="draft-music-notice" style="padding:12px 18px;background:#fff3d6;color:#744b10;border-bottom:1px solid #e4c987;font:15px/1.7 Microsoft YaHei,sans-serif">'+NOTICE+'</div>'


def fingerprint(project):
    fields=('id','pitch_midi','start_tick','end_tick','string','fret','velocity','role')
    payload={'voice':project['accepted_vocal_project'],'harmony':project['shared_analysis']['harmony'],
             'timing':project['shared_analysis']['timing'],'binding':project['shared_analysis']['input_binding'],
             'notes':{name:[{k:n[k] for k in fields if k in n} for n in arr['notes']]
                      for name,arr in project['arrangements'].items()}}
    return hashlib.sha256(json.dumps(payload,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode('utf-8')).hexdigest()


def stamp_draft(project,issues=None):
    previous=project.get('automatic_draft',{})
    project['automatic_draft']={'version':1,'status':'needs_review','notice':NOTICE,
        'normal_publication_allowed':False,'musical_accuracy_verified':False,
        'issues':deepcopy(issues if issues is not None else previous.get('issues',[])),
        'music_sha256':fingerprint(project)}
    project['music_acceptance']={**project.get('music_acceptance',{}),'status':'needs_review',
                                 'reason':'user_requested_complete_automatic_draft',
                                 'normal_publication_allowed':False}
    return project


def verify_draft(project,path):
    source=Path(path).resolve();review=project.get('automatic_draft',{})
    if (not source.is_relative_to(ROOT/'test_outputs/accompaniment_runs') or
        (source.parent/'publication.json').exists() or review.get('version')!=1 or
        review.get('status')!='needs_review' or review.get('normal_publication_allowed') is not False or
        review.get('musical_accuracy_verified') is not False or review.get('music_sha256')!=fingerprint(project)):
        raise ValueError('待校对草稿的来源、隔离目录或实际音乐内容不符。')
    binding=project['shared_analysis']['input_binding']
    if sha256(binding['vocal_project'])!=binding['vocal_project_sha256']:
        raise ValueError('草稿的人声来源已改变。')
    for name,row in binding['sources'].items():
        if sha256(row['path'])!=row['sha256']:raise ValueError('草稿原曲音轨已改变：'+name)
    return {'valid':True,'status':'verified_draft_identity_only','musical_accuracy_verified':False,
            'normal_publication_allowed':False,'scope':'source_hashes_and_unchanged_draft_music_not_clock_approval'}


def annotate_delivery(output):
    output=Path(output)
    for name in ('index.html','guitar/score.html','guitar/score_full.html','vocal/score.html'):
        path=output/name
        if not path.is_file():continue
        text=path.read_text(encoding='utf-8')
        text=text.replace('人声简谱沿用已认可成果。','简谱和伴奏来自本次自动分析，尚待校对。')
        if 'class="draft-music-notice"' not in text:
            import re
            text=re.sub(r'(<body[^>]*>)',lambda m:m.group(1)+BANNER,text,count=1,flags=re.I)
            path.write_text(text,encoding='utf-8')

    manifest=output/'manifest.json'
    if manifest.is_file():
        data=read_json(manifest)
        for row in data.get('files',[]):
            path=(output/row['path']).resolve()
            if path.is_relative_to(output.resolve()) and path.is_file():
                row.update(sha256=sha256(path),bytes=path.stat().st_size)
        save_json(manifest,data)
