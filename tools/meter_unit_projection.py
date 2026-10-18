"""慢拍单位与两曲最小修订：保留所有实际秒数的纯记谱单位投影。"""
# 慢拍单位与两曲最小修订：新增明确独立模式，绝不调用字头复核、音高识别、和弦分析或整曲编配。
from copy import deepcopy
import bisect
import math
from score_export import PPQ, TempoMap
from accompaniment_rebar import scale_tree, compare_sounding_time
from source_timing_revision import rebuild_events
from guitar_readability_acceptance import fingerprint

POLICY = {'version': 1, 'mode': 'preserve_existing_performance_meter_unit',
          'source_seconds_lyrics_pitch_and_frets_preserved': True,
          'old_acceptance_invalidated': True, 'minimum_guitar_ticks': 120,
          'maximum_guitar_fret': 12, 'minimum_reused_bars': 8,
          'no_pitch_chord_or_word_head_reanalysis': True}


def _scaled(value, scale, old_bar):
    # 慢拍单位与两曲最小修订：新增只缩放音乐时间字段，既有策略阈值和祖先账本保持原含义。
    result = scale_tree(value, scale, old_bar)
    def preserve(old, new):
        if isinstance(old, dict):
            for key in old:
                if key in ('policy', 'source_policy', 'minimum_note_ticks', 'minimum_chord_ticks'):
                    new[key] = deepcopy(old[key])
                elif key in ('readable_source_interval', 'source_interval_ticks') and isinstance(old[key], list):
                    new[key] = [int(round(v * scale)) for v in old[key]]
                else:
                    preserve(old[key], new[key])
        elif isinstance(old, list):
            for a, b in zip(old, new):
                preserve(a, b)
    preserve(value, result)
    return result


def projected_timing(original, scale, first_old_quarter, grouping=None):
    # 慢拍单位与两曲最小修订：新增以经核对的真实首拍为原点；秒结点原样保留，不能把页面零点冒充首拍。
    if scale not in (.5, 1., 2.):
        raise ValueError('记谱单位仅支持半速、原速或倍速')
    timing = deepcopy(original['timing'])
    old_origin = float(timing['score_start_quarter'])
    timing['knots'] = [{'seconds': r['seconds'], 'quarter': (r['quarter'] - first_old_quarter) * scale}
                       for r in timing['knots']]
    timing['score_start_quarter'] = (old_origin - first_old_quarter) * scale
    old_map, mapping = TempoMap(original['timing']['knots']), TempoMap(timing['knots'])
    timing['beat_origin_seconds'] = old_map.quarters_to_seconds(first_old_quarter)
    timing['beat_origin_source'] = 'source_verified_unit_projection_anchor'
    for key in ('steady_tempo_bpm', 'unrounded_tempo_bpm'):
        if key in timing:
            timing[key] *= scale
    timing['tempo_source'] = 'preserved_source_seconds_with_verified_meter_unit'
    total = int(math.ceil(original['statistics']['total_ticks'] * scale / 120) * 120)
    if grouping is not None:
        if grouping.get('seconds_changed') is not False or len(grouping['beats']) != len(grouping['old_quarters']):
            raise ValueError('固定拍序分组缺少可复核的原坐标')
        points = []
        for q, beat in zip(grouping['old_quarters'], grouping['beats']):
            if abs(old_map.quarters_to_seconds(q) - beat['seconds']) > 1e-7:
                raise ValueError('固定拍序分组移动了原秒坐标')
            if beat['beat'] == 1:
                tick = (q - old_origin) * scale * PPQ
                if abs(tick - round(tick)) > 1e-7:
                    raise ValueError('首拍不在可精确表示的记谱网格')
                points.append(int(round(tick)))
        if not points:
            raise ValueError('分组缺少首拍')
        first = points[0]
        while first > 0:
            first -= 1920
            points.append(first)
        last = max(points)
        while last < total:
            last += 1920
            points.append(last)
    else:
        first = round((first_old_quarter - old_origin) * scale * PPQ)
        while first > 0:
            first -= 1920
        points = list(range(first, total + 1921, 1920))
    positive = sorted({p for p in points if p > 0})
    finish = next(p for p in positive if p >= total)
    bounds = [0] + [p for p in positive if p <= finish]
    timeline = []
    for a, b in zip(bounds, bounds[1:]):
        length = b - a
        pickup = a == 0 and length != 1920
        if length not in (960, 1920) and not pickup:
            raise ValueError('固定拍序出现未经支持的小节长度')
        timeline.append({'number': len(timeline) + 1, 'start_tick': a, 'end_tick': b,
            'meter': [4, 4] if pickup else [length // PPQ, 4], 'pickup': pickup,
            'start_seconds': mapping.quarters_to_seconds(timing['score_start_quarter'] + a / PPQ),
            'end_seconds': mapping.quarters_to_seconds(timing['score_start_quarter'] + b / PPQ)})
    timing.update(measure_timeline=timeline, meter=[4, 4], initial_pickup_measure=timeline[0]['pickup'])
    return timing, finish


def project_voice_units(original, scale, first_old_quarter, grouping=None):
    # 慢拍单位与两曲最小修订：新增只改现有记谱坐标；原词音秒区间、音符身份、音高和挂词所有者逐字段保持。
    vocal = deepcopy(original)
    bar = original['statistics']['bar_ticks']
    for key in ('quantized_notes', 'notation', 'unpitched_lyric_cues'):
        if key in original:
            vocal[key] = _scaled(original[key], scale, bar)
    timing, total = projected_timing(original, scale, first_old_quarter, grouping)
    vocal['timing'] = timing
    vocal['statistics'].update(total_ticks=total, bar_ticks=1920, measure_count=len(timing['measure_timeline']))
    vocal['tempo_events'] = [{**event, 'tick': int(round(event['tick'] * scale)), 'bpm': event['bpm'] * scale}
                             for event in original['tempo_events']]
    if vocal.get('overrides', {}).get('tempo'):
        vocal['overrides']['tempo'] *= scale
    # 慢拍单位与两曲最小修订：新增旧切分只作为滑音／连奏模板，重新跨小节分割不改变音符及歌词归属。
    rebuild_events(vocal, timing['measure_timeline'])
    return vocal


def project_existing_music(project, scale, first_old_quarter, grouping=None):
    # 慢拍单位与两曲最小修订：新增公开纯投影；它是中间候选，不能凭秒坐标保持冒充节奏／复用已通过。
    revised = deepcopy(project)
    original = project['accepted_vocal_project']
    # 慢拍单位与两曲最小修订：新增先验证旧共同和声仍能使用，再做确定性单位换算；不靠改摘要掩盖旧计划过期。
    from phrase_harmony_plan import arrangement_view, shared_fingerprint, vocal_fingerprint
    arrangement_view(project['shared_analysis'], original)
    vocal = project_voice_units(original, scale, first_old_quarter, grouping)
    revised['accepted_vocal_project'] = vocal
    shared = deepcopy(project['shared_analysis'])
    bar = original['statistics']['bar_ticks']
    for key in ('sections', 'harmony_windows', 'harmony', 'arranged_harmony', 'instrumental_melody',
                # 慢拍单位与两曲最小修订：修改，认可和声覆盖层同样是实际演奏坐标，不能遗漏而沿用旧快拍区间。
                # 'notation', 'phrase_harmony_plan', 'musical_structure', 'melodic_motif_matches', 'measure_textures'):
                'notation', 'phrase_harmony_plan', 'musical_structure', 'melodic_motif_matches', 'measure_textures',
                'approved_section_preservation'):
        if key in shared:
            shared[key] = _scaled(shared[key], scale, bar)
    shared.update(timing=deepcopy(vocal['timing']), statistics=deepcopy(vocal['statistics']))
    if 'phrase_harmony_plan' in shared:
        # 慢拍单位与两曲最小修订：新增重绑已验证的确定性派生，保留原计划摘要；实际入口还会从原工程逐字段重放共享分析。
        plan = shared['phrase_harmony_plan']
        plan['meter_unit_projection'] = {'version': 1, 'quarter_scale': scale,
            'source_shared_sha256': shared_fingerprint(project['shared_analysis']),
            'source_vocal_sha256': vocal_fingerprint(original),
            'source_plan_sha256': fingerprint(project['shared_analysis']['phrase_harmony_plan']),
            'harmony_reselected': False, 'derived_plan_requires_source_project_replay': True}
        plan['source_shared_sha256'] = shared_fingerprint(shared)
        plan['source_vocal_sha256'] = vocal_fingerprint(vocal)
    revised['shared_analysis'] = shared
    arrangements = {}
    for instrument, source in project['arrangements'].items():
        result = deepcopy(source)
        for key in ('notes', 'attack_events', 'hand_positions', 'pedal', 'fingering_diagrams', 'grip_hand_positions',
                    'notation_regions', 'readable_harmony', 'section_patterns', 'section_pattern_provenance'):
            if key in source:
                result[key] = _scaled(source[key], scale, bar)
        if 'capo_segments' in source.get('configuration', {}):
            result['configuration']['capo_segments'] = _scaled(source['configuration']['capo_segments'], scale, bar)
        # 慢拍单位与两曲最小修订：新增清除已失效的读法规划；保留旧工程原件，不照搬旧小节号与通过标记。
        result.pop('readable_reuse', None)
        result.pop('guitar_readability_revision', None)
        arrangements[instrument] = result
    revised['arrangements'] = arrangements
    for key in ('guitar_readability_acceptance', 'guitar_source_bass_acceptance', 'section_pattern_acceptance',
                'guitar_readability_revision', 'reading_revision', 'guitar_score_layout'):
        revised.pop(key, None)
    check = compare_sounding_time(original, project['arrangements'], vocal, arrangements)
    if not check['valid']:
        raise ValueError('纯单位投影未保住原演奏时间：' + str(check['errors'][:10]))
    revised['meter_unit_revision'] = {'version': 1, 'policy': deepcopy(POLICY), 'quarter_scale': scale,
        'first_downbeat_old_quarter': first_old_quarter, 'input_music_sha256': fingerprint(project),
        'grouping': deepcopy(grouping), 'pure_projection_check': check, 'stage': 'local_readability_not_yet_applied'}
    revised['music_acceptance'] = {'status': 'needs_review', 'publication_allowed': False,
        'scope': 'pure_meter_unit_projection', 'unresolved': ['new_unit_rhythm_harmony_repeat_and_output_acceptance_pending']}
    return revised, check
