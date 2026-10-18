"""主旋律简化版：另存主音与重要转音层，保留歌词、休止、原时间轴及详细谱。"""
from __future__ import annotations
# 主旋律简化版：新增标准库派生处理，复用原制谱语义函数，不运行声学模型。
import argparse
from collections import Counter
import copy
import hashlib
import itertools
import json
import math
from pathlib import Path
import statistics
import sys
from score_export import PPQ, TempoMap, attach_lyrics, save_json, sha256, split_interval

ROOT=Path(__file__).resolve().parents[1]
PARAMETERS={"normal_secondary_min_quarters":0.75,"cadence_secondary_min_quarters":0.5,
            "secondary_min_fraction":0.25,"semitone_secondary_min_quarters":1.0,
            "balanced_leap_min_semitones":3,"balanced_leap_min_raw_seconds":0.18,
            "balanced_leap_min_fraction":0.30,"three_step_min_raw_seconds":0.22,
            "three_step_min_range_semitones":3,"neighbor_return_min_quarters":1.0,
            "stable_two_min_raw_seconds":0.25,"stable_two_min_fraction":0.30,
            "stable_two_min_semitones":2,"main_pitch_basis":"raw_duration_then_ticks_then_support"}

# 主旋律简化版：新增只读输入验证和持续时间统计，零时值倚音单独记录不承载新歌词。
def raw_seconds(note):
    return max(0.0,float(note.get('end_seconds',0))-float(note.get('start_seconds',0)))

def duration(note): return int(note['end_tick'])-int(note['start_tick'])

def coalesce_identical(notes):
    runs=[]
    for note in notes:
        if runs and runs[-1]['pitch']==note['pitch_midi'] and runs[-1]['end']==note['start_tick']:
            run=runs[-1]; run['end']=note['end_tick']; run['notes'].append(note)
            run['raw_duration']+=raw_seconds(note)
        else:
            runs.append({'pitch':int(note['pitch_midi']),'start':int(note['start_tick']),
                         'end':int(note['end_tick']),'notes':[note],'raw_duration':raw_seconds(note)})
    return runs

def select_runs(runs, cadence=False):
    weights=Counter()
    # 主旋律简化版：新增原始持续时间作为主音权重，防止量化平局让极短音压过长主音。
    raw_weights=Counter()
    support=Counter()
    for r in runs:
        weights[r['pitch']]+=r['end']-r['start']
        raw_weights[r['pitch']]+=r['raw_duration']
        support[r['pitch']]+=sum(duration(n)*float(n.get('confidence') or 0) for n in r['notes'])
    # 主旋律简化版：修改主音选择，原按量化时值和confidence平手排序的语句保留如下。
    # main=max(weights,key=lambda pitch:(weights[pitch],support[pitch],-pitch))
    main=max(weights,key=lambda pitch:(raw_weights[pitch],weights[pitch],support[pitch],-pitch))
    total=sum(weights.values()); chosen={i for i,r in enumerate(runs) if r['pitch']==main}
    reasons={i:'main_sustained_pitch' for i in chosen}
    # 主旋律简化版：新增真实稳定三段/大跳例外，不用边界小残片制造重要转音。
    continuous=all(a['end']==b['start'] for a,b in zip(runs,runs[1:]))
    distinct=[r['pitch'] for r in runs]
    stable_three=(len(runs)==3 and continuous and len(set(distinct))==3
                  and min(r['raw_duration'] for r in runs)>=PARAMETERS['three_step_min_raw_seconds']
                  and max(distinct)-min(distinct)>=PARAMETERS['three_step_min_range_semitones'])
    balanced_leap=(len(runs)==2 and continuous and abs(distinct[0]-distinct[1])>=PARAMETERS['balanced_leap_min_semitones']
                   and min(r['raw_duration'] for r in runs)>=PARAMETERS['balanced_leap_min_raw_seconds']
                   and min((r['end']-r['start'])/total for r in runs)>=PARAMETERS['balanced_leap_min_fraction'])
    # 主旋律简化版：新增稳定双音全音例外，只保护两个较长转折，不放宽短回摆。
    raw_total=sum(r['raw_duration'] for r in runs)
    stable_two=(len(runs)==2 and continuous and abs(distinct[0]-distinct[1])>=PARAMETERS['stable_two_min_semitones']
                and min(r['raw_duration'] for r in runs)>=PARAMETERS['stable_two_min_raw_seconds']
                and min(r['raw_duration']/raw_total for r in runs)>=PARAMETERS['stable_two_min_fraction']
                and min((r['end']-r['start'])/total for r in runs)>=PARAMETERS['stable_two_min_fraction'])
    # 主旋律简化版：修改转音例外集合，原二类返回保留注释，加入稳定双音。
    # if stable_three or balanced_leap:
    #     return main,set(range(len(runs))),{i:'stable_three_step_contour' if stable_three else 'balanced_large_leap' for i in range(len(runs))}
    if stable_three or balanced_leap or stable_two:
        reason='stable_three_step_contour' if stable_three else ('balanced_large_leap' if balanced_leap else 'stable_two_step_contour')
        return main,set(range(len(runs))),{i:reason for i in range(len(runs))}
    for i,r in enumerate(runs):
        if i in chosen: continue
        length=r['end']-r['start']; fraction=length/total; distance=abs(r['pitch']-main)
        threshold=(PARAMETERS['cadence_secondary_min_quarters'] if cadence else PARAMETERS['normal_secondary_min_quarters'])*PPQ
        if distance==1: threshold=max(threshold,PARAMETERS['semitone_secondary_min_quarters']*PPQ)
        returning=any(x['pitch']==main for x in runs[:i]) and any(x['pitch']==main for x in runs[i+1:])
        if returning and distance<=2: threshold=max(threshold,PARAMETERS['neighbor_return_min_quarters']*PPQ)
        if distance and length>=threshold and fraction>=PARAMETERS['secondary_min_fraction']:
            chosen.add(i); reasons[i]='sustained_cadence_turn' if cadence else 'sustained_important_turn'
    return main,chosen,reasons

# 主旋律简化版：新增短片归入最近保留音的归并，始终不跨字合并或填平休止。
def simplify_group(notes, lyric_index, cadence=False):
    runs=coalesce_identical(notes)
    main,chosen,reasons=select_runs(runs,cadence)
    assigned=[]
    for i,r in enumerate(runs):
        if i in chosen: target=i
        else:
            center=(r['start']+r['end'])/2
            target=min(chosen,key=lambda k:(abs(center-(runs[k]['start']+runs[k]['end'])/2),runs[k]['pitch']!=main,k))
        assigned.append((r,runs[target]['pitch'],reasons[target]))
    merged=[]
    for r,pitch,reason in assigned:
        if merged and merged[-1]['pitch_midi']==pitch and merged[-1]['end_tick']==r['start']:
            merged[-1]['end_tick']=r['end']; merged[-1]['source_members'].extend(r['notes'])
            merged[-1]['retention_reasons']=list(dict.fromkeys(merged[-1]['retention_reasons']+[reason]))
        else:
            merged.append({'start_tick':r['start'],'end_tick':r['end'],'pitch_midi':pitch,'lyric_index':lyric_index,
                           'source_members':list(r['notes']),'retention_reasons':[reason]})
    action={'lyric_index':lyric_index,'main_pitch_midi':main,'cadence':cadence,
            'before':[{'id':n['id'],'pitch_midi':n['pitch_midi'],'start_tick':n['start_tick'],'end_tick':n['end_tick']} for n in notes],
            'after':[{'pitch_midi':n['pitch_midi'],'start_tick':n['start_tick'],'end_tick':n['end_tick'],'reasons':n['retention_reasons']} for n in merged]}
    return merged,action

# 主旋律简化版：新增事件重建，继承所有节拍/拍号/休止位置，XML和MIDI共用同一简化层。
def rebuild_events(notes,bar_ticks,total_ticks):
    events=[];cursor=0
    for note in notes:
        start,end=note['start_tick'],note['end_tick']
        if not 0<=cursor<=start<end<=total_ticks: raise ValueError('简化音符时间非法或有重叠')
        if start>cursor:
            events.extend(dict(p,piece_id=None,pitch_midi=None,grace=False,ties=[],lyric_index=None) for p in split_interval(cursor,start,bar_ticks))
        parts=split_interval(start,end,bar_ticks)
        for i,p in enumerate(parts):
            ties=(['stop'] if i else [])+(['start'] if i<len(parts)-1 else [])
            events.append(dict(p,piece_id=note['id'],pitch_midi=note['pitch_midi'],grace=False,ties=ties,lyric_index=note['lyric_index'],review=None))
        cursor=end
    if cursor<total_ticks:
        events.extend(dict(p,piece_id=None,pitch_midi=None,grace=False,ties=[],lyric_index=None) for p in split_interval(cursor,total_ticks,bar_ticks))
    for i,e in enumerate(events):
        e.update(id=f'simple_score_n{i+1}',measure=e['start_tick']//bar_ticks+1,offset_ticks=e['start_tick']%bar_ticks)
    return events

# 主旋律简化版：新增完整项目派生与可审计动作，原分析/f0和原字稿不覆盖。
def simplify_project(original,source_path='',source_hash=''):
    if original.get('active_notation_layer')=='corrected_score': raise ValueError('当前入口需自动详细记谱层，不能忽略已有人工校正层')
    original_notes=original['quantized_notes'];characters=original['lyrics']['characters']
    positive=[n for n in original_notes if duration(n)>0]
    if any(duration(n)<0 for n in original_notes): raise ValueError('原音符有负时值')
    if any(a['end_tick']>b['start_tick'] for a,b in zip(positive,positive[1:])): raise ValueError('原音符不是单声部非重叠序列')
    indices={c['index'] for c in characters}
    if len(indices)!=len(characters): raise ValueError('歌词索引重复')
    cadence={c['index'] for i,c in enumerate(characters) if i==len(characters)-1 or c.get('line_index')!=characters[i+1].get('line_index')}
    if {n['lyric_index'] for n in positive if n['lyric_index'] is not None}!=indices: raise ValueError('原正时值字音映射不完整，不能靠丢字简化')
    mapping=TempoMap(original['timing']['knots']);score_start=original['timing']['score_start_quarter']
    simplified=[];actions=[]
    for index,items in itertools.groupby(positive,key=lambda n:n['lyric_index']):
        group=list(items)
        if index is None:
            # 主旋律简化版：新增无歌词段的逐片保留，避免将前后句残余旋律强塞到歌词。
            groups=[([n],None) for n in group]
        else: groups=[(group,index)]
        for part,idx in groups:
            merged,action=simplify_group(part,idx,idx in cadence);actions.append(action)
            for n in merged:
                members=n.pop('source_members');first,last=members[0],members[-1]
                n.update(id=f'simple_note_{len(simplified)+1:04d}',source_note_id=first['source_note_id'],
                         source_note_ids=list(dict.fromkeys(x['source_note_id'] for x in members)),
                         source_piece_ids=[x['id'] for x in members],start_seconds=first['start_seconds'],end_seconds=last['end_seconds'],
                         confidence=None,review_flags=list(dict.fromkeys(f for x in members for f in x.get('review_flags',[]))),
                         boundary_source='main_melody_simplification_existing_tick_boundaries',collapsed_to_grace=False)
                n['quantized_start_seconds']=mapping.quarters_to_seconds(n['start_tick']/PPQ+score_start)
                n['quantized_end_seconds']=mapping.quarters_to_seconds(n['end_tick']/PPQ+score_start)
                n['start_error_seconds']=n['quantized_start_seconds']-n['start_seconds']
                n['end_error_seconds']=n['quantized_end_seconds']-n['end_seconds']
                simplified.append(n)
    project=copy.deepcopy(original)
    project['artifact_kind']='simplified_real_audio_draft';project['quantized_notes']=simplified
    stats=project['statistics'];bar,total=stats['bar_ticks'],stats['total_ticks']
    project['events']=rebuild_events(simplified,bar,total)
    project['lyric_mapping']=attach_lyrics(project['events'],project['lyrics']['characters'])
    if project['lyric_mapping']['unmapped_character_indices'] or project['lyric_mapping']['issues']: raise ValueError('简化后歌词丢失或顺序异常')
    errors=sorted(abs(n[k]) for n in simplified for k in ('start_error_seconds','end_error_seconds'))
    stats.update(lyric_split_pieces=len(simplified),grace_notes_from_collapsed_grid=0,
                 quantization_error_seconds={'median_abs':statistics.median(errors) if errors else 0,
                 'p95_abs':errors[min(len(errors)-1,int(.95*len(errors)))] if errors else 0,'max_abs':max(errors,default=0)})
    counts={'detailed_pieces':len(original_notes),'detailed_positive_pieces':len(positive),'simplified_pieces':len(simplified),
            'removed_grace_pieces':len(original_notes)-len(positive),'detailed_notation_events':len(original['events']),
            'simplified_notation_events':len(project['events']),'mapped_characters':project['lyric_mapping']['mapped_characters'],
            'important_multi_pitch_characters':sum(len({n['pitch_midi'] for n in simplified if n['lyric_index']==i})>1 for i in indices)}
    project['simplification']={'task':'主旋律简化版','profile':'main_melody_with_important_turns',
          'source_project':source_path,'source_project_sha256':source_hash,'parameters':PARAMETERS,
          'counts':counts,'actions':actions,'removed_zero_tick_pieces':copy.deepcopy([n for n in original_notes if duration(n)==0]),
          'original_statistics':copy.deepcopy(original['statistics']),
          'policy':'每字保留主音；长转音/稳定三段/平衡大跳例外；同字短回摆归并；不跨字合并、不改变休止及总时值。',
          'importance_is_verified':False,'musical_accuracy_verified':False,
          'raw_analysis_preserved':copy.deepcopy(original['raw_analysis_preservation'])}
    return project

# 主旋律简化版：新增另存CLI，拒绝覆盖详细源，记录源SHA和派生数量。
def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--report',type=Path,required=True);args=parser.parse_args()
    source=args.project.resolve();target=args.output.resolve()
    if source==target: raise ValueError('简化版必须另存，不能覆盖详细谱')
    before=sha256(source);project=simplify_project(json.loads(source.read_text(encoding='utf-8-sig')),str(source),before)
    if sha256(source)!=before: raise ValueError('详细源在处理期间发生变化')
    save_json(target,project)
    report={'status':'simplified_project_generated_requires_review','source':str(source),'source_sha256_unchanged':True,
            'output':str(target),'counts':project['simplification']['counts'],'parameters':PARAMETERS}
    save_json(args.report,report)
    print(json.dumps(report,ensure_ascii=False));return 0

if __name__=='__main__':
    if hasattr(sys.stdout,'reconfigure'):sys.stdout.reconfigure(encoding='utf-8')
    raise SystemExit(main())
