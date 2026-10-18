"""G大调记谱与参考谱差异分析：将简化记谱层按目标调输出，明确记录音高偏移。"""
# G大调记谱与参考谱差异分析：新增另存工具，不覆盖原稿、原录音或原音高分析。
from __future__ import annotations
import argparse
import copy
import html
import json
from pathlib import Path
import statistics
import sys
import time
import xml.etree.ElementTree as ET
import score_export as score
from export_simplified_score import validate_simplified, validate_midi

# G大调记谱与参考谱差异分析：新增显式移调；原候选调名不作为真实源调自动推断。
def revise_project(source, source_path, source_hash, target_key, semitones, reference_midi=None):
    check=validate_simplified(source)
    if not check['valid']:
        raise ValueError('; '.join(check['errors']))
    key=score.key_definition(target_key)
    result=copy.deepcopy(source)
    for layer in ('quantized_notes', 'events'):
        for n in result[layer]:
            if n.get('pitch_midi') is not None:
                n['pitch_midi']+=semitones
                if not 1 <= n['pitch_midi'] <= 127:
                    raise ValueError('移调后音高超出MIDI范围')
    result['notation']['key']=key
    result['notation']['key_source']='user_confirmed_vocal_key'
    pitches=[n['pitch_midi'] for n in result['quantized_notes']]
    if reference_midi is None:
        reference_midi=60+key['jianpu_one_pc']
        reference_midi+=12*round((statistics.median(pitches)-reference_midi-5)/12)
    if reference_midi%12 != key['jianpu_one_pc']:
        raise ValueError('简谱基准音必须与目标调的1一致')
    result['notation']['jianpu_reference_midi']=reference_midi
    result['overrides']['key']=key['label']
    result['title']=source['title']+' · G大调简化版'
    result['artifact_kind']='target_key_simplified_draft'
    result['notation_revision']={
        'task':'G大调记谱与参考谱差异分析','source_project':str(source_path),
        'source_project_sha256':source_hash,'previous_key_candidate':source['notation']['key']['label'],
        'target_key':key['label'],'pitch_shift_semitones':semitones,
        'reference_midi':reference_midi,'lyrics_and_rhythm_changed':False,
        'raw_audio_and_analysis_changed':False,
        'reason':'用户指定G人声调；原混音和分离人声首句与参考G谱相差约半音，目标稿整体降低半音。',
        'source_vocal_tonic_is_formally_verified':False,
        'user_reference_scope':'人声G大调；降B转调段为器乐间奏，不加入无人声的旋律层。'}
    return result

# G大调记谱与参考谱差异分析：新增不变量复核，确保只有明确的音高及调号/抬头修改。
def validate_revision(original, revised, semitones):
    for field in ('lyrics','timing','tempo_events','statistics','lyric_mapping','inputs','raw_analysis_preservation','simplification'):
        if revised[field]!=original[field]:
            raise ValueError('移调不应修改字段：'+field)
    for layer in ('quantized_notes','events'):
        restored=copy.deepcopy(revised[layer])
        for note in restored:
            if note.get('pitch_midi') is not None:note['pitch_midi']-=semitones
        if restored!=original[layer]:
            raise ValueError('移调不应修改音符音高以外的字段：'+layer)
    return {'valid':True,'only_declared_pitches_changed':True,'lyrics_rhythm_rests_tempo_preserved':True,
            'source_references_and_simplification_provenance_preserved':True}

# G大调记谱与参考谱差异分析：新增目标调专属显示文案，避免仍将确认的G调标为初估。
def render_g(project, first=1, last=None, excerpt=False):
    scene=score.render_jianpu(project,first,last,excerpt)
    for i,item in enumerate(scene.items):
        if item[0]=='text' and '橙色音符' in item[3]:
            value=list(item)
            value[3]='人声按用户指定G大调记谱；节奏与字音待校正。连线表示延音，下划线表示一字多音。'
            scene.items[i]=tuple(value)
    return scene

# G大调记谱与参考谱差异分析：新增XML/MIDI/全曲简谱和实际预览统一导出。
def export(args):
    started=time.perf_counter()
    source_path=args.project.resolve();output=args.output_dir.resolve()
    if source_path.parent==output:
        raise ValueError('目标稿需另存，不得覆盖源稿')
    source_hash=score.sha256(source_path);original=score.read_json(source_path)
    project=revise_project(original,source_path,source_hash,args.key,args.semitones,args.reference_midi)
    checks=validate_revision(original,project,args.semitones)
    xml=score.build_musicxml(project)
    semantic=score.validate_score(project,xml)
    if not semantic['valid']:raise ValueError('; '.join(semantic['errors']))
    output.mkdir(parents=True,exist_ok=True)
    ET.indent(xml,space='  ')
    ET.ElementTree(xml).write(output/'vocal_draft.musicxml',encoding='utf-8',xml_declaration=True)
    score.write_midi(output/'vocal_draft.mid',project)
    midi=validate_midi(output/'vocal_draft.mid',project)
    score.save_json(output/'project.json',project)
    scene=render_g(project);svg=scene.svg()
    (output/'jianpu.svg').write_text(svg,encoding='utf-8')
    first=min(e['measure'] for e in project['events'] if e['pitch_midi'] is not None)
    first=max(1,first-1);last=min(project['statistics']['measure_count'],first+11)
    preview=render_g(project,first,last,True)
    preview.png(output/'preview_first_vocal.png')
    (output/'preview_first_vocal.svg').write_text(preview.svg(),encoding='utf-8')
    notice='G大调简化草稿：原简化旋律整体降低半音，节奏与字音沿用；尚未按参考谱逐音校正。'
    page=( '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>'+html.escape(project['title'])+
          '</title><style>body{margin:24px;background:#eef2f6;font-family:"Microsoft YaHei",sans-serif;color:#14243b}'
          'main{max-width:1440px;margin:auto;background:white;padding:20px}svg{width:100%;height:auto}'
          'p{line-height:1.8}a{color:#205a98}</style><main><p>'+html.escape(notice)+
          '</p><p><a href="vocal_draft.musicxml">可编辑MusicXML</a>　<a href="vocal_draft.mid">G调MIDI试听</a></p>'+svg+'</main></html>')
    (output/'jianpu.html').write_text(page,encoding='utf-8')
    assert score.sha256(source_path)==source_hash
    checks.update(musicxml=semantic,midi=midi,source_project_sha256_unchanged=source_hash,
                  target_key=project['notation']['key']['label'],pitch_shift_semitones=args.semitones,
                  mapped_characters=project['lyric_mapping']['mapped_characters'],
                  external_editor_roundtrip='not_tested',musical_accuracy_verified=False)
    score.save_json(output/'validation.json',checks)
    report={'task':'G大调记谱与参考谱差异分析','status':'g_major_simplified_draft_exported',
            'revision':project['notation_revision'],'validation':checks,'seconds':time.perf_counter()-started,
            'artifacts':{name:str(output/name) for name in ('project.json','jianpu.html','jianpu.svg',
             'vocal_draft.musicxml','vocal_draft.mid','preview_first_vocal.png','validation.json')}}
    score.save_json(args.report,report)
    print(json.dumps({'status':report['status'],'key':args.key,'pitch_shift_semitones':args.semitones,
       'actual_midi_attacks':midi['attacks'],'lyrics':checks['mapped_characters'],'html':str(output/'jianpu.html')},ensure_ascii=False))

# G大调记谱与参考谱差异分析：新增显式目标调和半音参数，拒绝猜测移调量。
def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--project',type=Path,required=True);p.add_argument('--output-dir',type=Path,required=True)
    p.add_argument('--report',type=Path,required=True);p.add_argument('--key',default='G:major')
    p.add_argument('--semitones',type=int,required=True);p.add_argument('--reference-midi',type=int)
    args=p.parse_args();export(args)

if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8');main()
