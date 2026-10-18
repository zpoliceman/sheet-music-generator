"""小节划分与拍速层级纠错：对既有音乐重记谱，保留源工程与实际发声秒时间。"""
# 小节划分与拍速层级纠错：新增独立派生层，处理人声、和声、两套伴奏、换夹与模板的统一时间轴。
from collections import defaultdict
from copy import deepcopy
import math
from pathlib import Path

from score_export import PPQ, TempoMap, read_json, sha256
from metrical_timing import rebase_timing, reviewed_beat_level


# 小节划分与拍速层级纠错：新增明确的时间字段转换；不把弦品、音高、秒、门槛与音频帧号当tick缩放。
def scale_tree(value, scale, old_bar, key=''):
    # 强拍相位与伴奏同步纠错：新增循环起点列表按时间坐标缩放，避免重导时继承旧列表拍单位。
    if key=='cycle_origins' and isinstance(value,list):
        return [round(t*scale) for t in value]
    tick_lists = {'attack_grid_ticks', 'protected_silence_gaps', 'relative_onsets'}
    measure_lists = {'measures', 'changed_measures', 'applied_this_run', 'observed_measures'}
    measure_fields = {'measure', 'start_measure', 'end_measure', 'texture_measure', 'first_measure', 'last_measure'}
    if isinstance(value, dict):
        return {k: scale_tree(v, scale, old_bar, k) for k, v in value.items()}
    if isinstance(value, list):
        if key in tick_lists:
            return [scale_tree(v, scale, old_bar, 'tick') for v in value]
        if key in measure_lists and all(isinstance(v, int) for v in value):
            return sorted({int(math.floor((v - 1) * scale)) + 1 for v in value})
        return [scale_tree(v, scale, old_bar, key) for v in value]
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if key in measure_fields:
            return int(math.floor((value - 1) * scale)) + 1
        if key == 'bar_ticks':
            return old_bar
        if key == 'quarter':
            return value * scale
        if key == 'tick' or key.endswith('_tick') or key.endswith('_ticks'):
            return int(round(value * scale))
        if key in {'grid_quarters', 'duration_measures'}:
            return value * scale
    return deepcopy(value)


# 小节划分与拍速层级纠错：新增重新切分人声持续音和休止；旧小节处不残留无意义的切分。
def rebuild_vocal_events(original, vocal):
    from musical_decode import split_notation
    bar = vocal['statistics']['bar_ticks']
    old_by_piece = defaultdict(list)
    for event in original['events']:
        if event.get('piece_id') is not None:
            old_by_piece[event['piece_id']].append(event)
    events = []
    cursor = 0

    def rests(a, b):
        return [dict(p, piece_id=None, pitch_midi=None, grace=False, ties=[], lyric_index=None)
                for p in split_notation(a, b, bar)]

    notes_by_id = {n['id']: n for n in vocal['quantized_notes']}
    for note in vocal['quantized_notes']:
        start, end = note['start_tick'], note['end_tick']
        if start > cursor:
            events.extend(rests(cursor, start))
            cursor = start
        old = old_by_piece[note['id']]
        if note.get('grace'):
            anchor = notes_by_id[note['anchor_id']]
            first_length = split_notation(anchor['start_tick'], anchor['end_tick'], bar)[0]['duration_ticks']
            length = note['playback_end_tick'] - note['playback_start_tick']
            note['grace_steal_percent'] = 100 * length / first_length
            event = deepcopy(old[0])
            event.update(start_tick=start, grace_steal_percent=note['grace_steal_percent'])
            events.append(event)
            continue
        parts = split_notation(start, end, bar)
        for i, part in enumerate(parts):
            event = deepcopy(old[0])
            for field in ('id', 'measure', 'offset_ticks', 'lyric', 'slurs'):
                event.pop(field, None)
            event.update(part, ties=(['stop'] if i else []) + (['start'] if i < len(parts)-1 else []))
            # 小节划分与拍速层级纠错：新增原挂词和连奏端点迁移；字音归属及原文不重识别。
            if i == 0 and old[0].get('lyric'):
                event['lyric'] = deepcopy(old[0]['lyric'])
            slurs = ([s for e in old for s in e.get('slurs', []) if s['type'] == 'start'] if i == 0 else [])
            if i == len(parts)-1:
                slurs += [s for e in old for s in e.get('slurs', []) if s['type'] == 'stop']
            if slurs:
                event['slurs'] = deepcopy(slurs)
            events.append(event)
        cursor = end
    events.extend(rests(cursor, vocal['statistics']['total_ticks']))
    for i, event in enumerate(events):
        event.update(id=f'music_n{i+1}', measure=event['start_tick']//bar+1, offset_ticks=event['start_tick']%bar)
    # 小节划分与拍速层级纠错：新增重建挂词延长的start/continue/stop及新事件索引，避免沿用旧切分的尾标。
    from score_export import attach_lyrics
    characters=original.get('lyrics',{}).get('characters')
    if characters is None:
        fallback={}
        for event in original['events']:
            lyric=event.get('lyric') or {}
            if lyric.get('text'):
                index=event['lyric_index']
                fallback[index]={'index':index,**{k:lyric.get(k) for k in ('text','method','confidence')}}
        characters=list(fallback.values())
    vocal['lyric_mapping']=attach_lyrics(events,characters)
    vocal['events'] = events


# 小节划分与拍速层级纠错：新增可验证的人声时间派生，不改原文件，且不重新量化或重选音高。
def derive_vocal(original, correction):
    scale = correction['quarter_scale']
    if scale not in (.5, 2.):
        raise ValueError('本入口用于明确的半速/倍速记谱纠正。')
    old_bar = original['statistics']['bar_ticks']
    vocal = scale_tree(original, scale, old_bar)
    vocal['timing'] = rebase_timing(original['timing'], scale, correction)
    vocal['grid_correction'] = deepcopy(correction)
    vocal['overrides']['tempo'] = original['overrides'].get('tempo') * scale if original['overrides'].get('tempo') else None
    stats = vocal['statistics']
    stats['total_ticks'] = math.ceil(original['statistics']['total_ticks']*scale/old_bar)*old_bar
    stats['measure_count'] = stats['total_ticks']//old_bar
    # 小节划分与拍速层级纠错：新增拒绝当前渲染器尚未支持的小节中途调号，防止提前显示整小节新调。
    if any(s['start_tick'] % old_bar for s in vocal['notation'].get('key_segments', [])):
        raise ValueError('重记谱后调号位于小节中途；需复核小节起点或增加局部调号支持，不能静默提前转调。')
    vocal['tempo_events'] = [dict(e, tick=round(e['tick']*scale), bpm=e['bpm']*scale) for e in original['tempo_events']]
    rebuild_vocal_events(original, vocal)
    return vocal


# 小节划分与拍速层级纠错：新增严格源快照核验；允许确定性的拍层级派生，不放开人声任意编辑。
def validate_vocal_snapshot(vocal, binding):
    # 首拍与首尾局部补证：新增最高层局部词音先重放，不能拿纯时间祖先误判新版，也不能仅复制标记绕过来源。
    if vocal.get('first_source_word_correction'):
        try:
            from first_generation_words import replay_words
            return vocal==replay_words(vocal['first_source_word_correction'],binding)
        except (ValueError,KeyError,OSError):
            return False
    # 首次生成自动拍轴交接：新增最高层来源重放；不能只复制新passed标记或改写人声。
    if vocal.get('first_source_meter_correction'):
        try:
            from first_generation_source import replay_first_voice
            return vocal == replay_first_voice(read_json(binding['vocal_project']), binding, vocal['first_source_meter_correction'])
        except (ValueError, KeyError, OSError):
            return False
    # 慢拍单位与两曲最小修订：新增最高层纯单位派生重放；旧拍轴来源不能替代新首拍验收。
    if vocal.get('meter_unit_correction'):
        try:
            from meter_unit_entry import replay_unit_voice
            return vocal == replay_unit_voice(vocal['meter_unit_correction'], binding)
        except (ValueError, KeyError, OSError):
            return False
    # 原曲拍轴与歌词拍位通用修复：新增独立源拍轴与字音的顶层来源重放；旧派生分支原样保持。
    # 原曲拍轴与歌词拍位通用修复：修改，旧新层优先条件保留；若后续显式连续性层存在，先重建真正最高层。
    # if vocal.get('source_meter_rebuild_correction'):
    if vocal.get('source_meter_rebuild_correction') and not vocal.get('vocal_continuity_correction'):
        try:
            from source_meter_project import derive_source_vocal
            return vocal == derive_source_vocal(read_json(binding['vocal_project']), binding, vocal['source_meter_rebuild_correction'])
        except (ValueError, KeyError, OSError):
            return False
    # 人声连续音值与长休止漏音通用修复：新增最高层声学派生严格重放，旧各版本校验保持原路径。
    if vocal.get('vocal_continuity_correction'):
        try:
            from vocal_continuity_project import derive_continuity_vocal
            return vocal == derive_continuity_vocal(read_json(binding['vocal_project']), binding, vocal['vocal_continuity_correction'])
        except (ValueError, KeyError, OSError):
            return False
    # 连续源拍序与人声联合重解通用修复：新增最高层版本化重建；下方历史所有派生分支仍原样保留。
    if vocal.get('continuous_meter_correction'):
        try:
            from continuous_meter_project import derive_continuous_vocal
            return vocal == derive_continuous_vocal(read_json(binding['vocal_project']), binding, vocal['continuous_meter_correction'])
        except (ValueError, KeyError, OSError):
            return False
    original = read_json(binding['vocal_project'])
    # 跨曲低音与强拍复用通用修复：新增优先严格重建独立首拍层，历史版本1/2/3按以下旧路径核验。
    if vocal.get('source_meter_correction'):
        try:
            from source_meter_harmony import derive_source_meter_vocal
            return vocal == derive_source_meter_vocal(original, binding, vocal['source_meter_correction'])
        except (ValueError, KeyError, StopIteration, OSError):
            return False
    # 连续唱段拍轴与原唱同步修复：新增优先核验连续演奏时间层，历史结构/局部拍轴分支继续严格保留。
    if vocal.get('performance_clock_correction'):
        try:
            from performance_beat_clock import derive_performance_vocal
            return vocal == derive_performance_vocal(original, binding, vocal['performance_clock_correction'])
        except (ValueError, KeyError, StopIteration, OSError):
            return False
    # 通用段落强拍与乐句节奏修复：新增先核最新派生层，仍须由原音轨/原人声工程逐字段确定重建。
    if vocal.get('structural_clock_correction'):
        try:
            from structure_beat_clock import derive_structural_vocal
            return vocal==derive_structural_vocal(original,binding,vocal['structural_clock_correction'])
        except (ValueError,KeyError,StopIteration,OSError):
            return False
    # 局部拍轴与原唱同步纠错：新增源音轨可确定重建的局部拍轴派生，原有快照与旧策略校验继续保留。
    if vocal.get('local_clock_correction'):
        try:
            from local_beat_clock import derive_local_vocal
            return vocal == derive_local_vocal(original, binding, vocal['local_clock_correction'])
        except (ValueError, KeyError, StopIteration, OSError):
            return False
    # 强拍相位与伴奏同步纠错：新增可确定重建的节拍派生；仍拒绝任意改音、改词或篡改源指纹。
    phase = vocal.get('beat_phase_correction')
    if phase:
        if (phase.get('version') != 1 or phase.get('source_vocal_project_sha256') != binding['vocal_project_sha256']
                or phase.get('source_audio_sha256') != binding['sources']['mix']['sha256']):
            return False
        try:
            from beat_phase_alignment import derive_phase_vocal
            return vocal == derive_phase_vocal(original, phase)
        except (ValueError, KeyError, StopIteration):
            return False
    correction = vocal.get('grid_correction')
    if not correction:
        return vocal == original
    if (correction.get('version') != 1 or correction.get('source_vocal_project_sha256') != binding['vocal_project_sha256']
            or correction.get('source_audio_sha256') != binding['sources']['mix']['sha256']):
        return False
    try:
        return vocal == derive_vocal(original, correction)
    except (ValueError, KeyError, StopIteration):
        return False


# 小节划分与拍速层级纠错：新增对旧模板的拍单位解释；两拍循环可在四拍小节内重复，实际拨弦不重编。
def notation_pattern(guitar, pattern):
    scale = guitar.get('grid_correction', {}).get('quarter_scale', 1.)
    result = deepcopy(pattern)
    result['step_ticks'] = int(round(pattern['step_ticks']*scale))
    return result


# 小节划分与拍速层级纠错：新增旧选择审计的范围起点；保留两个半小节的循环，不冒充重算选型。
def rebase_pattern_plans(old_guitar, guitar, scale, old_bar):
    for key in ('right_hand_patterns', 'regular_rhythm'):
        if key not in guitar:
            continue
        for field in ('measures', 'fragments'):
            for old, row in zip(old_guitar[key].get(field, []), guitar[key].get(field, [])):
                row['pattern_start_tick'] = round((old['measure']-1)*old_bar*scale)
                row['pattern_end_tick'] = row['pattern_start_tick'] + round(old_bar*scale)
                # 小节划分与拍速层级纠错：修改，原只转换显式片段保留；全部已选循环按原作用范围核查。
                # if 'regular_beats' in old:
                #     row['regular_tick_ranges'] = [[round(((old['measure']-1)*old_bar+b*PPQ)*scale),
                #                                   round(((old['measure']-1)*old_bar+(b+1)*PPQ)*scale)]
                #                                  for b in old['regular_beats']]
                row['regular_tick_ranges'] = [[round(((old['measure']-1)*old_bar+b*PPQ)*scale),
                                              round(((old['measure']-1)*old_bar+(b+1)*PPQ)*scale)]
                                             for b in old.get('regular_beats',range(old_bar//PPQ))]
    # 小节划分与拍速层级纠错：修改，原假定已有规整策略保留；早期仅常用模板工程也可正常重记谱。
    # guitar['configuration']['regular_rhythm_policy']['timing_rebased_without_reselection'] = True
    if 'regular_rhythm_policy' in guitar['configuration']:
        guitar['configuration']['regular_rhythm_policy']['timing_rebased_without_reselection'] = True
    # 小节划分与拍速层级纠错：新增由实际新起音重算影响小节集合，兼容一旧小节映射到两个新小节。
    measures=sorted({n['start_tick']//old_bar+1 for n in guitar['notes'] if n.get('right_hand_pattern_id')})
    guitar['right_hand_patterns']['changed_measures']=measures
    if 'regular_rhythm' in guitar:
        guitar['regular_rhythm']['changed_measures']=measures
    if 'structure_stability' in guitar:
        guitar['structure_stability']['selection_timebase'] = 'source_grid_before_metrical_review'
        guitar['structure_stability']['music_rearranged_during_rebar'] = False


# 小节划分与拍速层级纠错：新增从完整秒域缓存重新采样小节织体，和声候选与已编配发声保留。
def rebase_shared(original, vocal, scale, cache_dir):
    from accompaniment_analysis import SongClock, extract_features, measure_textures
    from accompaniment_texture_policy import add_block_support
    shared = scale_tree(original, scale, original['statistics']['bar_ticks'])
    shared['timing'] = deepcopy(vocal['timing'])
    shared['statistics'] = deepcopy(vocal['statistics'])
    shared['notation']['key_segments'] = deepcopy(vocal['notation'].get('key_segments', []))
    clock = SongClock(vocal)
    features = {name: extract_features(source, cache_dir, name)
                for name, source in shared['input_binding']['sources'].items()
                if name in ('six_guitar', 'six_piano', 'other')}
    shared['measure_textures'] = measure_textures(features, clock, vocal, shared['sections'])
    shared = add_block_support(shared, vocal, cache_dir)
    shared['grid_correction'] = deepcopy(vocal['grid_correction'])
    shared['method']['metrical_grid'] = 'reviewed_quarter_level_seconds_preserved'
    shared['method']['harmony_window_ticks'] = round(PPQ*scale)
    return shared


# 小节划分与拍速层级纠错：新增公共升级接口；未知曲默认候选复核，显式参数用于其它曲的人工纠正。
def correct_accompaniment_grid(shared, vocal, arrangements, cache_dir, bar_length_factor=None):
    from accompaniment_analysis import SongClock
    from accompaniment_arrange import piano_hand_positions
    from guitar_structure_patterns import collect_rhythm_evidence, ornament_aliases
    # 尾段原声局部补证：新增首次来源已验拍轴保护；后置旧推断不得覆盖已通过小节及拍点秒数。
    if vocal.get('first_source_meter_correction'):
        if bar_length_factor not in (None,1):
            raise ValueError('已验证首次来源拍轴不能在编配阶段再次缩放小节')
        if not validate_vocal_snapshot(vocal,shared['input_binding']):
            raise ValueError('首次来源拍轴或词音快照已变')
        return shared,vocal,arrangements
    if vocal.get('grid_correction'):
        if bar_length_factor not in (None, 1):
            raise ValueError('工程已纠正拍层级；请从原工程重新选择，避免重复缩放。')
        return shared, vocal, arrangements
    old_clock = SongClock(vocal)
    binding = shared['input_binding']
    bpm = old_clock.mapping.tempo_at(old_clock.origin)
    decision = reviewed_beat_level(vocal.get('audio_analysis', {}), bpm, vocal['timing']['meter'])
    if bar_length_factor is not None:
        decision.update(quarter_scale=1./bar_length_factor, status='explicit_bar_length_review',
                        basis='explicit_bar_length_factor', source_audio_sha256=binding['sources']['mix']['sha256'])
    scale = decision['quarter_scale']
    if scale == 1:
        return shared, vocal, arrangements
    # 小节划分与拍速层级纠错：新增源身份交叉校验，防止人声旧缓存的SHA复核套到另一个伴奏音源。
    if decision.get('source_audio_sha256') != binding['sources']['mix']['sha256']:
        raise ValueError('拍层级复核的混音SHA与实际绑定不一致。')
    correction = {**decision, 'source_vocal_project_sha256': binding['vocal_project_sha256'],
                  'method': 'notation_rebase_preserve_seconds', 'source_measure_count': vocal['statistics']['measure_count'],
                  'source_bar_ticks': old_clock.bar_ticks, 'source_quarter_bpm': bpm}
    original_vocal = deepcopy(vocal)
    vocal = derive_vocal(original_vocal, correction)
    new_clock = SongClock(vocal)
    shared = rebase_shared(shared, vocal, scale, cache_dir)
    converted = {}
    for name, original in arrangements.items():
        arrangement = scale_tree(original, scale, old_clock.bar_ticks)
        arrangement['grid_correction'] = deepcopy(correction)
        # 小节划分与拍速层级纠错：新增删除可重建显示缓存，旧缓存保留在输入工程。
        for field in ('fingering_diagrams', 'notation_regions', 'grip_hand_positions', 'grip_fingerings', 'tab_display', 'rhythm_display'):
            arrangement.pop(field, None)
        if name == 'guitar':
            # 小节划分与拍速层级纠错：新增沿用用户四小节一行的最新偏好，覆盖旧两小节显示配置。
            arrangement['configuration']['rows_measures']=4
            if 'right_hand_patterns' in arrangement:
                rebase_pattern_plans(original, arrangement, scale, old_clock.bar_ticks)
            if 'source_rhythm_evidence' in arrangement:
                arrangement['source_rhythm_evidence'] = collect_rhythm_evidence(shared, vocal, cache_dir)
            if 'ornament_display' in arrangement:
                arrangement['ornament_display']['aliases'] = ornament_aliases(shared)
            for s in arrangement['configuration'].get('capo_segments', []):
                s['start_measure'] = s['start_tick']//new_clock.bar_ticks+1
            # 小节划分与拍速层级纠错：新增谱面总长补足只延伸夹位配置，不延长实际音符。
            if arrangement['configuration'].get('capo_segments'):
                arrangement['configuration']['capo_segments'][-1]['end_tick'] = new_clock.total_ticks
        else:
            arrangement['hand_positions'] = piano_hand_positions(arrangement['notes'], new_clock)
        converted[name] = arrangement
    return shared, vocal, converted


# 小节划分与拍速层级纠错：新增独立语义核查，比较ID、音高、按法和绝对秒，防止只并小节线或拉慢音频。
def compare_sounding_time(before_vocal, before_arrangements, vocal, arrangements):
    from accompaniment_analysis import SongClock
    a, b = SongClock(before_vocal), SongClock(vocal)
    errors = []
    max_error = 0.
    counts = {}
    groups = {'vocal': (before_vocal['quantized_notes'], vocal['quantized_notes'])}
    groups.update({name: (old['notes'], arrangements[name]['notes']) for name, old in before_arrangements.items()})
    for name, (old, new) in groups.items():
        lookup = {n['id']: n for n in new}
        if len(old) != len(new) or set(lookup) != {n['id'] for n in old}:
            errors.append(name+':note_identity_changed')
        counts[name] = len(new)
        for n in old:
            m = lookup.get(n['id'])
            if not m:
                continue
            for key in ('pitch_midi', 'velocity', 'string', 'fret', 'lyric_index', 'anchor_id'):
                if n.get(key) != m.get(key):
                    errors.append(name+':music_field_changed:'+key+':'+n['id'])
            for key in ('start_tick', 'end_tick', 'playback_start_tick', 'playback_end_tick'):
                if key not in n:
                    continue
                delta = abs(a.seconds(n[key])-b.seconds(m[key]))
                max_error = max(max_error, delta)
                if delta > .0011:
                    errors.append(name+':sounding_seconds_changed:'+n['id'])
    return {'valid': not errors, 'errors': errors, 'note_counts': counts,
            'maximum_onset_release_error_seconds': max_error,
            'old_bar_seconds': a.seconds(a.bar_ticks)-a.seconds(0),
            'new_bar_seconds': b.seconds(b.bar_ticks)-b.seconds(0)}
