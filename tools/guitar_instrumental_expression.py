"""器乐背景休止与旋律突出：来源绑定的休止、旋律重音和低弦力度表现层。"""
from copy import deepcopy
from functools import lru_cache
from pathlib import Path
import math
from accompaniment_analysis import SongClock
from accompaniment_arrange import validate_playability
from guitar_instrumental_register import fingerprint, register_shared_view
from score_export import read_json, save_json, sha256, split_interval, attach_lyrics

POLICY={'version':1,'sections':['intro','interlude','outro'],'melody_role':'instrumental_melody',
    'melody_velocity_add':16,'melody_velocity_max':120,'fill_velocity_ratio':.8,
    'rest_grid_ticks':120,'black_dot_is_emphasis_not_staccato':True,
    'normal_vocal_accompaniment_unchanged':True,'original_protection_ledgers_retained':True}
LEDGERS=('instrumental_flow','instrumental_register','instrumental_source_backbone','phrase_harmony_performance','regular_rhythm')


# 器乐背景休止与旋律突出：新增统一器乐归类，正文短填句不自动加重或改力度。
def instrumental(shared,note):
    return any(s['kind'] in POLICY['sections'] and s['start_tick']<=note['start_tick']<s['end_tick'] for s in shared['sections'])


# 器乐背景休止与旋律突出：新增明确源SHA的人工休止区间；通用程序不按曲名或固定前20秒猜测。
def settings_for(shared,vocal,review_path=None,clarity_plan=None):
    settings={'source_mix_sha256':shared['input_binding']['sources']['mix']['sha256'],
        'rest_intervals':[],'suppress_unlyric_reference_notes':False}
    # 器乐背景休止与旋律突出：新增自动原音频筛选优先运行，人工窗口只作为同源显式复核覆写。
    if clarity_plan is not None:
        settings.update(rest_intervals=deepcopy(clarity_plan['rest_intervals']),suppress_unlyric_reference_notes=True)
        settings['automatic_clarity_sha256']=fingerprint(clarity_plan)
    if review_path:
        review=read_json(review_path)
        if review.get('schema_version')!=1 or review.get('source_mix_sha256')!=settings['source_mix_sha256']:
            raise ValueError('器乐休止复核的版本或原曲SHA不一致。')
        if not isinstance(review.get('suppress_unlyric_reference_notes',False),bool):
            raise ValueError('无歌词参考音处理必须明确为布尔值。')
        settings.update(rest_intervals=deepcopy(review['rest_intervals']),
            suppress_unlyric_reference_notes=review.get('suppress_unlyric_reference_notes',False))
    clock=SongClock(vocal); last=clock.seconds(clock.total_ticks)
    previous=-math.inf
    for interval in settings['rest_intervals']:
        a,b=interval['start_seconds'],interval['end_seconds']
        if not all(isinstance(x,(int,float)) and not isinstance(x,bool) and math.isfinite(x) for x in (a,b)):
            raise ValueError('休止秒时间必须为有限数值。')
        if a<0 or b<=a or b>last+1e-6 or a<previous:raise ValueError('休止区间必须有序、互不重叠且在原曲范围内。')
        previous=b
        # 器乐背景休止与旋律突出：新增防止休止复核越过正文，保留已认可演唱伴奏。
        covered=0.
        for section in shared['sections']:
            if section['kind'] in POLICY['sections']:
                covered+=max(0.,min(b,clock.seconds(section['end_tick']))-max(a,clock.seconds(section['start_tick'])))
        if covered<b-a-1e-6:raise ValueError('当前休止表现层只处理前奏、间奏、尾奏，不能覆盖正常唱段。')
        if settings['suppress_unlyric_reference_notes'] and any(n.get('lyric_index') is not None and
                clock.seconds(n['start_tick'])<b and clock.seconds(n['end_tick'])>a for n in vocal['quantized_notes'] if not n.get('grace')):
            raise ValueError('复核休止区间含有挂歌词的真实人声，不能作为无歌词背景音删除。')
    return settings


# 器乐背景休止与旋律突出：新增谱面边界向外落到十六分网格；音源另按真实秒窗口静音，不制造微小时值。
def rest_ticks(vocal,settings):
    clock=SongClock(vocal); step=POLICY['rest_grid_ticks']; ranges=[]
    for r in settings['rest_intervals']:
        # 器乐背景休止与旋律突出：修改，自动音乐边界按计划保护首音，不能向外取整覆盖首个真实音。
        # a=max(0,int(math.floor(clock.tick(r['start_seconds'])/step))*step)
        # b=min(clock.total_ticks,int(math.ceil(clock.tick(r['end_seconds'])/step))*step)
        a=r['start_tick'] if r.get('origin')=='automatic_clarity' else max(0,int(math.floor(clock.tick(r['start_seconds'])/step))*step)
        b=r['end_tick'] if r.get('origin')=='automatic_clarity' else min(clock.total_ticks,int(math.ceil(clock.tick(r['end_seconds'])/step))*step)
        if a<b:ranges.append((a,b))
    return ranges


# 器乐背景休止与旋律突出：新增确定性表现，不重新猜音高、和弦或左右手型，只处理授权休止和器乐力度。
def derive_expression(shared,vocal,guitar,settings):
    result=deepcopy(guitar); ranges=rest_ticks(vocal,settings)
    notes=[]; removed=[]; shortened=[]; accents=[]; softened=[]; originals={n['id']:n for n in guitar['notes']}
    for old in guitar['notes']:
        eligible=instrumental(shared,old); parts=[(old['start_tick'],old['end_tick'])]
        if eligible:
            for a,b in ranges:
                following=[]
                for start,end in parts:
                    if end<=a or start>=b:following.append((start,end));continue
                    if start<a:following.append((start,a))
                    if end>b:following.append((b,end))
                parts=following
            # 器乐背景休止与旋律突出：修改，旧无条件过滤会误删区间外原有短音，原行保留。
            # parts=[(a,b) for a,b in parts if b-a>=POLICY['rest_grid_ticks']]
            if parts!=[(old['start_tick'],old['end_tick'])]:
                parts=[(a,b) for a,b in parts if b-a>=POLICY['rest_grid_ticks']]
        if not parts:
            removed.append(old['id']);continue
        for serial,(a,b) in enumerate(parts):
            note=deepcopy(old)
            if serial:note['id']=old['id']+'_expression_part_'+str(serial+1)
            if (a,b)!=(old['start_tick'],old['end_tick']):
                note.update(start_tick=a,end_tick=b)
                note['expression_source_note_id']=old['id'];shortened.append({'id':note['id'],'source_id':old['id'],'start_tick':a,'end_tick':b})
            if eligible and note['role']==POLICY['melody_role']:
                # 器乐背景休止与旋律突出：修改，旧上限对已极强音会反而减弱，原行保留。
                # note['velocity']=min(POLICY['melody_velocity_max'],old['velocity']+POLICY['melody_velocity_add'])
                note['velocity']=max(old['velocity'],min(POLICY['melody_velocity_max'],old['velocity']+POLICY['melody_velocity_add']))
                note['melody_accent']=True;note['expression_original_velocity']=old['velocity'];accents.append(note['id'])
            elif eligible and note.get('instrumental_flow_fill'):
                note['velocity']=max(1,round(old['velocity']*POLICY['fill_velocity_ratio']))
                note['expression_original_velocity']=old['velocity'];softened.append(note['id'])
            notes.append(note)
    result['notes']=sorted(notes,key=lambda n:(n['start_tick'],n['id']))
    by_source={}
    for n in notes:by_source.setdefault(n.get('expression_source_note_id',n['id']),[]).append(n)
    events=[]; starts={}
    for event in guitar['attack_events']:
        clone=deepcopy(event)
        # 器乐背景休止与旋律突出：修改，原仅按note_ids保留会丢失以源攻击身份记录的正常模板；保留旧行。
        # clone['note_ids']=[n['id'] for i in event.get('note_ids',[]) for n in by_source.get(i,[]) if n['start_tick']==event['start_tick']]
        # if clone['note_ids']:events.append(clone);starts.setdefault(clone['start_tick'],set()).update(clone['note_ids'])
        tick=event['start_tick'];original_at=[n for n in guitar['notes'] if n['start_tick']==tick]
        current_at=[n for n in notes if n['start_tick']==tick]
        if original_at and not current_at:continue
        if not current_at and any(a<=tick<b for a,b in ranges):continue
        if 'note_ids' in event:
            clone['note_ids']=[n['id'] for i in event['note_ids'] for n in by_source.get(i,[]) if n['start_tick']==tick]
        events.append(clone);starts.setdefault(tick,set()).update(n['id'] for n in current_at)
    for n in notes:
        if n['id'] in starts.get(n['start_tick'],set()):continue
        events.append({'start_tick':n['start_tick'],'kind':'arpeggio','chord_id':n.get('chord_id'),
            'note_ids':[n['id']],'stroke':None,'source':'reviewed_rest_continuation',
            'right_hand_duration_ticks':min(240,n['end_tick']-n['start_tick'])})
    result['attack_events']=sorted(events,key=lambda e:e['start_tick'])
    # 器乐背景休止与旋律突出：新增清除可重建的显示缓存；原来源／音区／织体保护账本完整保留。
    for field in ('tab_display','rhythm_display','time_alignment_display'):
        result.pop(field,None)
    report={'valid':True,'removed_note_ids':removed,'shortened_notes':shortened,'melody_accent_ids':accents,
        'softened_fill_ids':softened,'rest_tick_intervals':[list(r) for r in ranges],
        'source_note_count':len(originals),'result_note_count':len(notes),
        'normal_note_count':sum(not instrumental(shared,n) for n in guitar['notes'])}
    return result,report


# 器乐背景休止与旋律突出：新增只读、实际SHA核验的上游读取；缓存不能掩盖同名文件被改写。
@lru_cache(maxsize=8)
def cached_parent(path,digest,mtime,size):
    if sha256(path)!=digest:raise ValueError('器乐表现层的源工程已改变。')
    return read_json(path)


def expression_parent(guitar):
    info=guitar['instrumental_expression'];path=Path(info['upstream_project'])
    if sha256(path)!=info['upstream_sha256']:raise ValueError('器乐表现层的源工程已改变。')
    stat=path.stat();return cached_parent(str(path),info['upstream_sha256'],stat.st_mtime_ns,stat.st_size)


# 器乐背景休止与旋律突出：新增显式升级及幂等重导，重复执行不会叠加重音或继续降低填充力度。
def apply_expression(shared,vocal,guitar,upstream_path,review_path=None,clarity_dir=None):
    if guitar.get('instrumental_expression'):
        check=validate_expression(shared,vocal,guitar)
        if not check['valid']:raise ValueError('既有器乐表现层来源不符：'+str(check['errors'][:6]))
        info=guitar['instrumental_expression']
        if review_path is None or fingerprint(settings_for(shared,vocal,review_path))==fingerprint(info['settings']):
            return deepcopy(guitar),deepcopy(info['report'])
        upstream_path=info['upstream_project'];guitar=expression_parent(guitar)['arrangements']['guitar']
    # 器乐背景休止与旋律突出：修改，旧仅人工复核保留；正式生成默认构建并绑定自动清晰度计划。
    # settings=settings_for(shared,vocal,review_path)
    clarity=None;clarity_path=None
    if clarity_dir is not None:
        from instrumental_clarity import build_clarity_plan
        clarity,clarity_path=build_clarity_plan(shared,vocal,guitar,clarity_dir)
    settings=settings_for(shared,vocal,review_path,clarity)
    parent=read_json(upstream_path)
    # 器乐背景休止与旋律突出：修改，旧多行条件加括号确保Python续行合法，原式保留。
    # if fingerprint(parent['arrangements']['guitar'])!=fingerprint(guitar) or fingerprint(parent['accepted_vocal_project'])!=fingerprint(vocal) or
    #         fingerprint(register_shared_view(parent['shared_analysis'],vocal))!=fingerprint(register_shared_view(shared,vocal)):
    if (fingerprint(parent['arrangements']['guitar'])!=fingerprint(guitar) or fingerprint(parent['accepted_vocal_project'])!=fingerprint(vocal) or
            fingerprint(register_shared_view(parent['shared_analysis'],vocal))!=fingerprint(register_shared_view(shared,vocal))):
        raise ValueError('器乐表现层必须绑定当前实际吉他、人声和共同拍轴。')
    result,report=derive_expression(shared,vocal,guitar,settings)
    result['instrumental_expression']={'version':1,'policy':deepcopy(POLICY),'settings':settings,
        'upstream_project':str(Path(upstream_path).resolve()),'upstream_sha256':sha256(upstream_path),
        'source_notes_sha256':fingerprint(guitar['notes']),'result_notes_sha256':fingerprint(result['notes']),
        'review_path':str(Path(review_path).resolve()) if review_path else None,'review_sha256':sha256(review_path) if review_path else None,
        'shared_sha256':fingerprint(register_shared_view(shared,vocal)),'vocal_sha256':fingerprint(vocal),'report':report}
    result['instrumental_expression']['clarity_plan_path']=str(clarity_path.resolve()) if clarity_path else None
    result['instrumental_expression']['clarity_plan_sha256']=sha256(clarity_path) if clarity_path else None
    check=validate_playability(result,SongClock(vocal))
    if not check['valid']:raise ValueError('器乐休止／表现处理破坏实际演奏：'+str(check['errors'][:6]))
    return result,report


# 器乐背景休止与旋律突出：新增实际上游、人工复核来源、全部音符及既有账本的严格重放。
def validate_expression(shared,vocal,guitar,replay=False):
    # 原声覆盖与选音归属通用修复：新增认可音乐的来源分层；力度和黑点也在确定合并比对范围内。
    if guitar.get('approved_section_preservation'):
        from approved_music_sections import validate_chain
        return validate_chain(shared,vocal,guitar,replay,validate_expression)
    info=guitar.get('instrumental_expression')
    if not info:return None
    errors=[]
    try:
        parent=expression_parent(guitar);base=parent['arrangements']['guitar']
        if base.get('instrumental_expression'):raise ValueError('不能形成重复的器乐表现来源链。')
        if info['version']!=1 or info['policy']!=POLICY:errors.append('unknown_instrumental_expression_policy')
        if info['review_path'] and sha256(info['review_path'])!=info['review_sha256']:errors.append('instrumental_rest_review_changed')
        # 器乐背景休止与旋律突出：修改，自动决定需对真实原音频重新判别，不能只相信已写好的休止时段。
        # settings=settings_for(shared,vocal,info['review_path'])
        clarity=None
        if info.get('clarity_plan_path'):
            path=Path(info['clarity_plan_path'])
            if sha256(path)!=info['clarity_plan_sha256']:errors.append('instrumental_clarity_plan_changed')
            from instrumental_clarity import analyze_sections,aggregate_background
            clarity=aggregate_background(analyze_sections(shared,vocal,base),shared,vocal,base)
            if fingerprint(clarity)!=fingerprint(read_json(path)):errors.append('instrumental_clarity_source_replay_changed')
        settings=settings_for(shared,vocal,info['review_path'],clarity)
        if fingerprint(settings)!=fingerprint(info['settings']):errors.append('instrumental_expression_settings_changed')
        if fingerprint(register_shared_view(shared,vocal))!=info['shared_sha256'] or fingerprint(register_shared_view(parent['shared_analysis'],vocal))!=info['shared_sha256']:
            errors.append('instrumental_expression_harmony_or_clock_changed')
        if fingerprint(vocal)!=info['vocal_sha256'] or fingerprint(parent['accepted_vocal_project'])!=info['vocal_sha256']:
            errors.append('instrumental_expression_vocal_changed')
        rebuilt,report=derive_expression(shared,vocal,base,settings)
        if fingerprint(base['notes'])!=info['source_notes_sha256'] or fingerprint(guitar['notes'])!=info['result_notes_sha256']:
            errors.append('instrumental_expression_note_fingerprint_changed')
        if fingerprint(rebuilt['notes'])!=fingerprint(guitar['notes']) or fingerprint(rebuilt['attack_events'])!=fingerprint(guitar['attack_events']) or fingerprint(report)!=fingerprint(info['report']):
            errors.append('instrumental_expression_deterministic_music_changed')
        for field in LEDGERS:
            if fingerprint(base.get(field))!=fingerprint(guitar.get(field)):errors.append('instrumental_expression_source_ledger_changed:'+field)
        for field in ('capo_fret','capo_segments','maximum_fret','tuning_midi','instrumental_register_policy','structure_policy'):
            if fingerprint(base['configuration'].get(field))!=fingerprint(guitar['configuration'].get(field)):
                errors.append('instrumental_expression_configuration_changed:'+field)
        errors.extend(validate_playability(guitar,SongClock(vocal))['errors'])
    except (OSError,KeyError,TypeError,ValueError) as exc:
        errors.append('instrumental_expression_binding_invalid:'+str(exc))
    return {'valid':not errors,'errors':errors,'replayed':True,'changed':True,
        'removed_notes':len(info.get('report',{}).get('removed_note_ids',[])),
        'accent_notes':len(info.get('report',{}).get('melody_accent_ids',[])),
        # 器乐背景休止与旋律突出：新增可审阅的自动判别状态，区分原音频筛选与人工复核。
        'softened_fills':len(info.get('report',{}).get('softened_fill_ids',[])),
        'automatic_clarity':bool(info.get('clarity_plan_path')),
        'automatic_rest_intervals':len([r for r in info['settings']['rest_intervals'] if r.get('origin')=='automatic_clarity'])}


# 器乐背景休止与旋律突出：新增旧保护逐层在真实上游核查，当前变化另按表现层完整重放，不关闭任何旧保护。
def validate_expression_chain(shared,vocal,guitar,replay,validator):
    try:
        parent=expression_parent(guitar)['arrangements']['guitar']
        upstream=validator(shared,vocal,parent,replay=replay) or {'valid':True,'errors':[]}
        current=validate_expression(shared,vocal,guitar,replay=replay)
        errors=upstream['errors']+current['errors']
        return {**upstream,'valid':not errors,'errors':errors,'expression':current}
    except (OSError,KeyError,ValueError,TypeError) as exc:
        return {'valid':False,'errors':['instrumental_expression_parent_invalid:'+str(exc)]}


# 器乐背景休止与旋律突出：新增兼容旧双参数节奏验收，同样严格验证真实上游及当前完整派生，不清空保护。
def validate_expression_rhythm(shared,guitar,validator):
    try:
        parent=expression_parent(guitar);base=parent['arrangements']['guitar'];vocal=parent['accepted_vocal_project']
        previous=validator(shared,base) or {'valid':True,'errors':[]};current=validate_expression(shared,vocal,guitar)
        errors=previous['errors']+current['errors'];return {**previous,'valid':not errors,'errors':errors,'expression':current}
    except (OSError,KeyError,TypeError,ValueError) as exc:
        return {'valid':False,'errors':['instrumental_expression_rhythm_parent_invalid:'+str(exc)]}


# 器乐背景休止与旋律突出：新增仅在谱面／参考MIDI消除复核背景段无歌词候选，认可人声与原唱音频不改。
def reference_vocal(vocal,guitar):
    info=guitar.get('instrumental_expression')
    if not info or not info['settings']['suppress_unlyric_reference_notes']:return vocal
    ranges=rest_ticks(vocal,info['settings'])
    excluded={n['id'] for n in vocal['quantized_notes'] if n.get('lyric_index') is None and not n.get('grace') and
        any(a<=n['start_tick'] and n['end_tick']<=b for a,b in ranges)}
    excluded.update(n['id'] for n in vocal['quantized_notes'] if n.get('grace') and n.get('anchor_id') in excluded)
    if not excluded:return vocal
    result=deepcopy(vocal);result['quantized_notes']=[n for n in result['quantized_notes'] if n['id'] not in excluded]
    touched=set()
    for event in result['events']:
        if event.get('piece_id') not in excluded:continue
        touched.add(event['measure'])
        event.update(piece_id=None,pitch_midi=None,grace=False,ties=[],lyric_index=None)
        for field in ('slurs','tuplet','tuplet_start','tuplet_stop','anchor_id','accidental'):
            event.pop(field,None)
    bar=vocal['statistics']['bar_ticks'];events=[]
    for measure in range(1,vocal['statistics']['measure_count']+1):
        group=[e for e in result['events'] if e['measure']==measure]
        if measure in touched and all(e.get('pitch_midi') is None for e in group):
            for index,part in enumerate(split_interval((measure-1)*bar,measure*bar,bar)):
                events.append(dict(part,id=f'expression_reference_rest_{measure}_{index}',measure=measure,
                    offset_ticks=part['start_tick']-(measure-1)*bar,piece_id=None,pitch_midi=None,grace=False,ties=[],lyric_index=None))
        else:events.extend(group)
    result['events']=events;result['lyric_mapping']=attach_lyrics(events,result['lyrics']['characters'])
    result['statistics']['main_notes']=sum(n.get('role')=='main' for n in result['quantized_notes'])
    result['statistics']['turn_notes']=sum(n.get('role')=='turn' for n in result['quantized_notes'])
    result['instrumental_expression_reference']={'excluded_unlyric_note_ids':sorted(excluded),
        'accepted_vocal_sha256':fingerprint(vocal),'source_audio_unchanged':True,'rest_intervals':deepcopy(info['settings']['rest_intervals'])}
    return result


# 器乐背景休止与旋律突出：新增只显示演奏者需要的力度与复核休止说明，不暴露内部模型或绑定实现。
def expression_caption(guitar):
    info=guitar.get('instrumental_expression')
    if not info:return ''
    # 器乐背景休止与旋律突出：修改，原秒范围简明保留两位小数，模型窗口精度不混入演奏说明。
    # rest='；'.join(f"原曲{r['start_seconds']:g}–{r['end_seconds']:g}秒吉他声部休止" for r in info['settings']['rest_intervals'])
    rest='；'.join(f"原曲{r['start_seconds']:.2f}–{r['end_seconds']:.2f}秒吉他声部休止" for r in info['settings']['rest_intervals'])
    if rest:rest+='。'
    return rest+'六线谱上方的黑点标记器乐主旋律重音：弹得更突出，并保持原时值连贯演奏；低弦填充轻弹。'
