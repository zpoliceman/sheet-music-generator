"""吉他编配规则闭环修复：真实可变小节的长段反复适配及独立路线验收。"""
# 吉他编配规则闭环修复：新增只读适配层，复用已有长段规划／路线解释器，不修改来源音乐。
from bisect import bisect_right
from copy import deepcopy
from collections import defaultdict

from accompaniment_analysis import SongClock
from guitar_capo import capo_at
from guitar_repeat_plan import fingerprint, block_label
from guitar_repeat_readability import build_plan, validate_plan, expand_printed_bars, POLICY
from phrase_harmony_plan import arrangement_view


def guitar_shared_view(project):
    # 吉他编配规则闭环修复：新增乐器专用编配视图，声学共享分析／钢琴保持原样。
    harmony = project['arrangements']['guitar'].get('readable_harmony')
    shared = project['shared_analysis'] if harmony is not None else arrangement_view(project['shared_analysis'], project['accepted_vocal_project'])
    return {**shared, 'harmony': harmony if harmony is not None else shared['harmony'], '_phrase_harmony_view': True}


def measure_timeline(project):
    # 局部两拍过渡听辨修订：新增实际读谱／复用共用的来源复核边界，原演奏时钟不动；入口和验收独立核验来源。
    if project.get('bar_boundary_revision'):
        return deepcopy(project['bar_boundary_revision']['measure_timeline'])
    # 吉他编配规则闭环修复：新增兼容固定小节的派生边界；原始拍轴与秒映射不改变。
    vocal = project['accepted_vocal_project']
    if vocal['timing'].get('measure_timeline'):
        return deepcopy(vocal['timing']['measure_timeline'])
    bar = vocal['statistics']['bar_ticks']
    clock = SongClock(vocal)
    return [{'number': i + 1, 'start_tick': i * bar, 'end_tick': (i + 1) * bar,
             'meter': vocal['timing']['meter'],
             'pickup': bool(i == 0 and vocal['timing'].get('initial_pickup_measure')),
             'start_seconds': clock.seconds(i * bar), 'end_seconds': clock.seconds((i + 1) * bar)}
            for i in range(vocal['statistics']['measure_count'])]


def bar_signature(project, measure, shared=None):
    # 吉他编配规则闭环修复：新增从实际演奏重建签名；不相信复制来的attack_events或旧完成标记。
    vocal = project['accepted_vocal_project']; arrangement = project['arrangements']['guitar']
    shared = guitar_shared_view(project) if shared is None else shared
    start = measure['start_tick']; end = measure['end_tick']
    notes = sorted((n['start_tick'] - start, n['end_tick'] - start, n['pitch_midi'], n['string'], n['fret'],
                    n.get('finger'), n.get('role'), bool(n.get('melody_accent')))
                   for n in arrangement['notes'] if n['start_tick'] < end and n['end_tick'] > start)
    chords = []
    for h in shared['harmony']:
        if h['start_tick'] >= end or h['end_tick'] <= start:
            continue
        item = (max(0, h['start_tick'] - start), min(end - start, h['end_tick'] - start),
                h.get('root_pc'), h.get('quality'), h.get('bass_pc'))
        if chords and chords[-1][1] == item[0] and chords[-1][2:] == item[2:]:
            chords[-1] = (chords[-1][0], item[1], *item[2:])
        else:
            chords.append(item)
    diagrams = []
    for d in arrangement.get('fingering_diagrams', []):
        if d['start_tick'] >= end or d['end_tick'] <= start:
            continue
        item = (max(0, d['start_tick'] - start), min(end - start, d['end_tick'] - start),
                d.get('shape_name'), d.get('sounding_name'), d.get('position'), d.get('capo'),
                tuple(sorted(d.get('frets', {}).items())), d.get('barre'), bool(d.get('simplified')))
        if diagrams and diagrams[-1][1] == item[0] and diagrams[-1][2:] == item[2:]:
            diagrams[-1] = (diagrams[-1][0], item[1], *item[2:])
        else:
            diagrams.append(item)
    # 吉他编配规则闭环修复：新增相同显示模式连续区间合并，元数据切段不制造不存在的演奏差异。
    regions = []
    for region in arrangement.get('notation_regions', []):
        if region['start_tick'] >= end or region['end_tick'] <= start:
            continue
        item = (max(0, region['start_tick'] - start), min(end - start, region['end_tick'] - start), region['mode'])
        if regions and regions[-1][1] == item[0] and regions[-1][2] == item[2]:
            regions[-1] = (regions[-1][0], item[1], item[2])
        else:
            regions.append(item)
    clock = SongClock(vocal)
    key_points = {start} | {s['start_tick'] for s in vocal['notation'].get('key_segments', []) if start < s['start_tick'] < end}
    capo_points = {start} | {s['start_tick'] for s in arrangement['configuration'].get('capo_segments', []) if start < s['start_tick'] < end}
    # 4/4可选右手与实时谱面试听：新增真实手势签名；只在显式动作存在时扩展，旧默认签名保持。
    from guitar_pattern_performance import action_signature
    actions = action_signature(arrangement,start,end)
    if actions:
        return fingerprint([end-start,measure['meter'],measure['pickup'],notes,chords,diagrams,regions,
                            [(t-start,clock.key(t)) for t in sorted(key_points)],
                            [(t-start,capo_at(arrangement,t)) for t in sorted(capo_points)],actions])
    return fingerprint([end - start, measure['meter'], measure['pickup'], notes, chords, diagrams, regions,
                        [(t - start, clock.key(t)) for t in sorted(key_points)],
                        [(t - start, capo_at(arrangement, t)) for t in sorted(capo_points)]])


def indexed_view(project):
    # 吉他编配规则闭环修复：新增仅供索引规划的等宽坐标；签名与导出仍使用真实音值和小节长度。
    timeline = measure_timeline(project); begins = [m['start_tick'] for m in timeline]
    def mapped(tick):
        index = min(len(timeline) - 1, max(0, bisect_right(begins, tick) - 1))
        measure = timeline[index]
        return round((index + (tick - measure['start_tick']) / (measure['end_tick'] - measure['start_tick'])) * 1920)
    def rows(items):
        result = deepcopy(items)
        for item in result:
            for field in ('start_tick', 'end_tick'):
                if field in item:
                    item[field] = mapped(item[field])
        return result
    # 吉他编配规则闭环修复：新增只复制规划所需音乐，几十MB声学审计不参与逐小节布局／签名。
    original = project['accepted_vocal_project']
    vocal = deepcopy({k: original[k] for k in ('statistics', 'timing', 'notation', 'quantized_notes')})
    vocal['statistics'] = {**vocal['statistics'], 'bar_ticks': 1920, 'measure_count': len(timeline), 'total_ticks': len(timeline) * 1920}
    vocal['timing']['initial_pickup_measure'] = timeline[0]['pickup']
    vocal['quantized_notes'] = rows(vocal.get('quantized_notes', []))
    effective = guitar_shared_view(project)
    shared = {'harmony': deepcopy(effective['harmony']), '_phrase_harmony_view': True,
              'phrase_harmony_plan': deepcopy(effective.get('phrase_harmony_plan', {}))}
    shared['harmony'] = rows(shared['harmony']); shared['harmony_windows'] = []
    shared['statistics'] = vocal['statistics']; shared['notation'] = vocal['notation']
    arrangement = project['arrangements']['guitar']
    phrases = arrangement.get('readable_reuse', {}).get('phrases')
    if phrases is None:
        phrases = shared.get('phrase_harmony_plan', {}).get('phrases', [])
    phrases = rows(phrases)
    # 吉他编配规则闭环修复：新增真实歌词乐句／段落边界后备，不把排版每四小节当音乐候选。
    if not phrases:
        anchors = defaultdict(list)
        for note in project['accepted_vocal_project'].get('quantized_notes', []):
            if note.get('lyric_index') is not None and not note.get('grace'):
                anchors[note.get('line_index', 0)].append(note)
        starts = {0, len(timeline) * 1920}
        for notes in anchors.values():
            tick = min(n['start_tick'] for n in notes)
            nearest = min(range(len(timeline)), key=lambda i: abs(timeline[i]['start_tick'] - tick))
            if abs(timeline[nearest]['start_tick'] - tick) <= 480:
                starts.add(nearest * 1920)
        for section in project['shared_analysis'].get('sections', []):
            for key in ('start_tick', 'end_tick'):
                position = mapped(section[key])
                if position % 1920 == 0:
                    starts.add(position)
        points = sorted(starts)
        phrases = [{'id': 'boundary_' + str(i), 'start_tick': a, 'end_tick': b, 'action': 'actual_phrase_boundaries'}
                   for i, (a, b) in enumerate(zip(points, points[1:])) if b > a]
    shared['phrase_harmony_plan'] = {'phrases': phrases}
    shared['measure_textures'] = [{'section': next((s['kind'] for s in project['shared_analysis'].get('sections', [])
                                                   if s['start_tick'] <= m['start_tick'] < s['end_tick']), 'vocal')}
                                  for m in timeline]
    return shared, vocal, timeline


def build_repeat_plan(project):
    # 吉他编配规则闭环修复：新增实际执行旧长段规则，完整路线／符号语义继续由同一规划器生成。
    shared, vocal, timeline = indexed_view(project)
    effective = guitar_shared_view(project)
    signatures = [bar_signature(project, m, effective) for m in timeline]
    source_hash = fingerprint({'signatures': signatures, 'timeline': timeline,
                               'phrases': shared['phrase_harmony_plan']['phrases'],
                               'vocal_notes': [{k: n.get(k) for k in ('id', 'start_tick', 'end_tick', 'pitch_midi', 'lyric_index', 'line_index', 'grace')}
                                               for n in project['accepted_vocal_project'].get('quantized_notes', [])]})
    # 相似长段复用与默认阅读修复：修改真实小节路线加入少量明确变奏候选；所有音乐签名仍按完整实际材料计算。
    # plan = build_plan(shared, vocal, project['arrangements']['guitar'],
    #                   lambda s, v, g, number: signatures[number - 1], lambda value: source_hash, block_label)
    from guitar_repeat_variants import propose_with_variants,VARIANT_POLICY
    candidate_fn=lambda s,v,values:propose_with_variants(s,v,values,project,timeline)
    # 完整乐句与实际时长复用：修改显式传入真实小节秒轴，保留索引视图仅用于定位。
    # plan = build_plan(shared, vocal, project['arrangements']['guitar'],
    #                   lambda s, v, g, number: signatures[number - 1], lambda value: source_hash, block_label,candidate_fn)
    plan = build_plan(shared, vocal, project['arrangements']['guitar'],
                      lambda s, v, g, number: signatures[number - 1], lambda value: source_hash, block_label,candidate_fn,
                      actual_timeline=timeline)
    # 全曲目固定右手预览：新增按各遍人声联合时间列实测共用小节宽度，再只重排显示行；音乐候选和8小节门槛不变。
    arrangement=project['arrangements']['guitar'];config=arrangement.get('configuration',{})
    stacked_widths={}
    if plan['repeat_groups'] and config.get('reading_maximum_native_width') and config.get('reading_measure_widths'):
        from export_timing_revision import render_row
        import xml.etree.ElementTree as ET
        for group in plan['repeat_groups']:
            for offset in range(group['length_bars']):
                first=group['canonical_first']+offset;second=group['second_first']+offset
                layers=[[timeline[first-1]],[timeline[second-1]]]
                width=float(ET.fromstring(render_row(project,layers[0],True,vocal_measures=layers)).get('width'))
                stacked_widths[str(first)]=width
        widths=deepcopy(config['reading_measure_widths'])
        for number,width in stacked_widths.items():widths[number]=max(float(widths.get(number,0)),width)
        layout_arrangement={**arrangement,'configuration':{**config,'reading_measure_widths':widths}}
        # 相似长段复用与默认阅读修复：修改显示再分行沿用同一变奏候选，不退回旧精确候选而丢失长段。
        # plan=build_plan(shared,vocal,layout_arrangement,
        #                 lambda s,v,g,number:signatures[number-1],lambda value:source_hash,block_label)
        # 完整乐句与实际时长复用：修改联合叠词分行也传递同一真实时间表，不回退到等宽小节时长。
        # plan=build_plan(shared,vocal,layout_arrangement,
        #                 lambda s,v,g,number:signatures[number-1],lambda value:source_hash,block_label,candidate_fn)
        plan=build_plan(shared,vocal,layout_arrangement,
                        lambda s,v,g,number:signatures[number-1],lambda value:source_hash,block_label,candidate_fn,
                        actual_timeline=timeline)
    plan['stacked_reading_measure_widths']=stacked_widths
    # 相似长段复用与默认阅读修复：新增真实策略及书写量说明，非逐音相同的变奏必须在主谱实际输出。
    plan['variant_policy']=deepcopy(VARIANT_POLICY)
    plan['variant_printed_bars']=sum(len(g.get('variant_bars',[])) for g in plan['repeat_groups'])
    plan['shared_span_bars']=sum(g['length_bars'] for g in plan['repeat_groups'])
    # 完整乐句与实际时长复用：修改未折叠说明为真实候选审计，不再一概归因于长度或必须精确相同。
    # plan.update(adapter_version=1, source_music_sha256=source_hash, actual_measure_timeline=timeline,
    #             evaluated_boundaries=shared['phrase_harmony_plan']['phrases'], planning_executed=True,
    #             no_fold_reason=None if plan['repeat_groups'] else 'no_exact_source_supported_long_section',
    #             actual_measure_signatures=signatures)
    plan.update(adapter_version=2, source_music_sha256=source_hash, actual_measure_timeline=timeline,
                evaluated_boundaries=shared['phrase_harmony_plan']['phrases'], planning_executed=True,
                no_fold_reason=None if plan['repeat_groups'] else 'no_supported_complete_phrase_with_positive_reading_gain',
                actual_measure_signatures=signatures)
    return plan


def validate_repeat_plan(plan, project):
    # 吉他编配规则闭环修复：新增独立真实小节／连续时长验证，任何签名／路线变更均使旧验收失效。
    shared, vocal, timeline = indexed_view(project)
    result = validate_plan(plan, shared, vocal, project['arrangements']['guitar'], lambda s, v, a: build_repeat_plan(project))
    errors = result['errors']
    effective = guitar_shared_view(project)
    # 相似长段复用与默认阅读修复：修改旧全部小节必须相同式；按印刷路线独立选择共用或明确变奏的来源，再比实际音乐。
    # for group in plan['repeat_groups']:
    #     first = group['canonical_first'] - 1; second = group['second_first'] - 1
    #     for offset in range(group['length_bars']):
    #         if bar_signature(project, timeline[first + offset], effective) != bar_signature(project, timeline[second + offset], effective):
    #             errors.append('共用段实际弦品／起音／持续／指型／拍号不相同。')
    #             break
    from guitar_repeat_variants import printed_music_sources
    try:
        for item in printed_music_sources(plan):
            source=timeline[item['printed_source_measure']-1];actual=timeline[item['performed_measure']-1]
            if bar_signature(project,source,effective)!=bar_signature(project,actual,effective):
                errors.append('印刷共用／变奏来源的实际音乐与原曲不一致。');break
    except (ValueError,KeyError,IndexError,TypeError) as exc:errors.append('印刷变奏无法展开：'+str(exc))
    try:
        expanded = expand_printed_bars(plan)
        if sum(timeline[i - 1]['end_tick'] - timeline[i - 1]['start_tick'] for i in expanded) != sum(m['end_tick'] - m['start_tick'] for m in timeline):
            errors.append('实际反复展开时值与来源总长不符。')
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        errors.append('实际反复路线无法展开：' + str(exc))
    result.update(valid=not errors, planning_executed=True, variable_measure_lengths_preserved=not errors)
    return result
