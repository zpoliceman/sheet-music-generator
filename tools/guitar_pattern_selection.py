"""4/4可选右手与实时谱面试听：显式选型的统一动作、余音、范围及来源验收。"""
# 4/4可选右手与实时谱面试听：新增独立核心；未选择时逐字段返回原音乐，不调用识别模型。
from copy import deepcopy
from functools import lru_cache
from itertools import product
from pathlib import Path
from workspace_location import local_path
import json
import re

from accompaniment_arrange import TUNING, grip_info
from accompaniment_analysis import chord_name
from guitar_capo import capo_at
from guitar_grip_library import common_grips, fret_map
from guitar_section_patterns import fingerprint, ordinary, _editable_bars, _subtract_ranges
from guitar_variable_repeat import measure_timeline, guitar_shared_view
from score_export import read_json, sha256

TASK = '4/4可选右手与实时谱面试听'
POLICY = {'version': 1, 'meter': [4, 4], 'ppq': 480, 'minimum_action_ticks': 120,
          'maximum_fret': 12, 'selection_source': 'explicit_user_arrangement',
          'normal_entry_replacement_allowed': False, 'natural_ring_per_string': True}
VALUE_TICKS = {'quarter': 480, 'eighth': 240, 'sixteenth': 120}
NOTE_FIELDS = ('id', 'start_tick', 'end_tick', 'pitch_midi', 'string', 'fret', 'finger',
               'velocity', 'role', 'section', 'chord_id', 'selection_action_id', 'right_hand_token')


@lru_cache(maxsize=1)
def catalogue():
    # 4/4可选右手与实时谱面试听：新增版本化候选，只提供已研究的4/4动作，默认库不变。
    path = Path(__file__).parent / 'data/guitar_pattern_choices.json'
    data = read_json(path)
    if data['version'] != 1 or len({p['id'] for p in data['patterns']}) != len(data['patterns']):
        raise ValueError('右手候选库版本或标识错误')
    for row in data['patterns']:
        _validate_events(row['events'])
    return data


def has_selection(project):
    # 4/4可选右手与实时谱面试听：新增实际音符及乐器标记识别，丢顶层字段不能降级旧入口。
    guitar = project.get('arrangements', {}).get('guitar', {})
    return bool(project.get('right_hand_selection') or guitar.get('selected_pattern_actions') or
                guitar.get('configuration', {}).get('right_hand_selection') or
                any(n.get('selection_action_id') for n in guitar.get('notes', [])))


def _validate_events(events):
    # 4/4可选右手与实时谱面试听：新增动作白名单和整数拍长；未知输入明确失败。
    if not isinstance(events, list) or not 1 <= len(events) <= 64:
        raise ValueError('右手动作数量应为1至64')
    pos = 0
    for event in events:
        span = event.get('action_span_ticks')
        token = event.get('token', '')
        if type(span) is not int or span < 120 or span % 120 or event.get('onset_tick') != pos:
            raise ValueError('右手动作必须按顺序落在十六分网格，最短十六分')
        if not re.fullmatch(r'(?:B2?|[1-6])(?:\+(?:B2?|[1-6]))*|DL|DA|UH|-|空', token):
            raise ValueError('未知拨弦动作：' + str(token))
        pos += span
    if pos > 7680 or not (pos % 1920 == 0 or 1920 % pos == 0):
        raise ValueError('循环长' + str(pos / 480) + '拍；须完整覆盖4/4小节或整分小节，最长四小节')
    return pos


def normalize_choice(choice):
    # 4/4可选右手与实时谱面试听：新增时值独立选择；八音四分保留两小节，不压成一小节。
    if not isinstance(choice, dict):
        raise ValueError('右手选择格式错误')
    table = {p['id']: p for p in catalogue()['patterns']}
    key = choice.get('pattern_id')
    if key not in table:
        raise ValueError('不存在的4/4右手候选：' + str(key))
    template = deepcopy(table[key])
    value = choice.get('note_value', 'original')
    if value not in ('original', *VALUE_TICKS):
        raise ValueError('时值应为原节奏、四分、八分或十六分')
    if value != 'original' and not template['uniform']:
        raise ValueError('混合时值型请保留原节奏或逐格编辑时值')
    durations = choice.get('durations')
    if durations is not None and (not isinstance(durations, list) or len(durations) != len(template['events'])):
        raise ValueError('逐格时值数量与动作不一致')
    pos = 0
    for i, event in enumerate(template['events']):
        event['onset_tick'] = pos
        event['action_span_ticks'] = (durations[i] if durations is not None else
                                      VALUE_TICKS[value] if value != 'original' else event['action_span_ticks'])
        pos += event['action_span_ticks']
    _validate_events(template['events'])
    bass_mode = choice.get('bass_mode', 'adaptive')
    silence = choice.get('silence', 'ring')
    if bass_mode not in ('adaptive', 'fixed_5') or silence not in ('ring', 'stop'):
        raise ValueError('低音弦或空位收音选项错误')
    return {'pattern_id': key, 'note_value': value, 'durations': durations,
            'bass_mode': bass_mode, 'silence': silence, 'cycle_ticks': pos, 'template': template}


def _scope_view(project):
    # 4/4可选右手与实时谱面试听：新增局部分组只作规划视图，认可人声及时间字段不写回。
    rows = measure_timeline(project)
    voice = project['accepted_vocal_project']
    planning = {**project, 'accepted_vocal_project': {**voice, 'timing': {**voice['timing'], 'measure_timeline': rows}}}
    blocks = []
    notes = project['arrangements']['guitar']['notes']
    for row in rows:
        if not any(ordinary(n) and row['start_tick'] <= n['start_tick'] < row['end_tick'] for n in notes):
            continue
        if blocks and blocks[-1]['measures'][-1] + 1 == row['number']:
            blocks[-1]['measures'].append(row['number'])
            blocks[-1]['end_tick'] = row['end_tick']
        else:
            blocks.append({'id': f"vocal_section_{len(blocks)+1:03}", 'measures': [row['number']],
                           'start_tick': row['start_tick'], 'end_tick': row['end_tick']})
    eligible, exceptions = _editable_bars(planning, blocks)
    return rows, blocks, eligible, exceptions


def describe_source(project):
    # 4/4可选右手与实时谱面试听：新增真实演唱段及保护小节说明，供本机选择面板共用。
    rows, blocks, eligible, exceptions = _scope_view(project)
    return {'sections': [{**b, 'editable_measures': [m for m in b['measures'] if m in eligible]} for b in blocks],
            'exceptions': exceptions, 'eligible_measures': sorted(eligible), 'measure_count': len(rows)}


def normalize_plan(plan, project, scope=None):
    # 4/4可选右手与实时谱面试听：新增全局默认及段落覆盖；空计划确实保持原工程。
    if plan is None:
        return None
    if not isinstance(plan, dict) or plan.get('version', 1) != 1:
        raise ValueError('右手选择计划版本错误')
    default = normalize_choice(plan['default']) if plan.get('default') else None
    overrides = []
    known = {b['id'] for b in (scope if scope is not None else _scope_view(project))[1]}
    seen = set()
    for item in plan.get('sections', []):
        identity = item.get('section_id')
        if identity not in known or identity in seen:
            raise ValueError('演唱段不存在或重复：' + str(identity))
        seen.add(identity)
        overrides.append({'section_id': identity, 'choice': normalize_choice(item['choice']) if item.get('choice') else None})
    # 多区间右手配置与网页完整成品：保留旧空计划判据，新增按谱面号的多条区间计划。
    # if default is None and not any(o['choice'] for o in overrides):
    from guitar_pattern_ranges import normalize_ranges
    ranges = normalize_ranges(plan.get('ranges', []), (scope if scope is not None else _scope_view(project))[0], normalize_choice)
    if ranges and (default is not None or overrides):
        raise ValueError('小节区间与旧全局／段落计划请分别使用，避免范围含义冲突')
    if default is None and not any(o['choice'] for o in overrides) and not any(r['choice'] for r in ranges):
        return None
    # 多区间右手配置与网页完整成品：保留旧返回格式，只有显式区间计划才新增范围快照。
    # return {'version': 1, 'policy': deepcopy(POLICY), 'default': default, 'sections': overrides}
    return {'version': 1, 'policy': deepcopy(POLICY), 'default': default, 'sections': overrides,
            **({'ranges': ranges} if ranges else {})}


def _tokens(choice):
    # 4/4可选右手与实时谱面试听：新增固定五弦保留为实际弦号，不伪称当前根音。
    return [e['token'].replace('B2', '5').replace('B', '5') if choice['bass_mode'] == 'fixed_5' else e['token']
            for e in choice['template']['events']]


def _shape(chord, capo, tokens, old, tick, alternatives=False):
    # 4/4可选右手与实时谱面试听：新增原指型优先、常用完整指型及有限低品搜索；不替换指定弦。
    pcs = set(chord['pitch_classes']) | {int(chord['bass_pc'])}
    required = {int(s) for token in tokens for s in token.split('+') if s.isdigit()}
    if 'UH' in tokens:
        required |= {1, 2, 3}
    sweep = any(t in ('DA', 'DL', 'UH') for t in tokens)
    candidates = []
    seen = set()

    def consider(frets, rank, source):
        frets = {int(s): int(f) for s, f in frets.items() if f is not None and int(f) >= 0}
        identity = tuple(sorted(frets.items()))
        if identity in seen or not required.issubset(frets) or any(f > 12 for f in frets.values()):
            return
        seen.add(identity)
        pitches = {s: TUNING[s] + capo + f for s, f in frets.items()}
        if any(p % 12 not in pcs for p in pitches.values()):
            return
        # 4/4可选右手与实时谱面试听：新增搜索指型保留原低音及性质音，不能以一个和弦内音集冒充正确转位。
        essential=set(chord['pitch_classes'])-{(int(chord['root_pc'])+7)%12}
        if min(pitches.values())%12 != int(chord['bass_pc']) or not essential.issubset({p%12 for p in pitches.values()}):
            return
        basses = [s for s in (6, 5, 4) if s in pitches and pitches[s] % 12 == chord['bass_pc']]
        if any('B' in t for t in tokens) and not basses:
            return
        bass = max(basses, default=max(frets))
        if sweep and (max(frets) < 4 or set(frets) != set(range(min(frets), max(frets) + 1))):
            return
        if 'UH' in tokens and not {1, 2, 3}.issubset(frets):
            return
        if 'B2' in tokens and not any(s != bass and s >= 4 for s in frets):
            return
        info = grip_info(frets)
        if info is None:
            return
        positive = [f for f in frets.values() if f]
        cost = (rank, max(positive, default=0) > 4, max(positive, default=0), sum(positive))
        candidates.append((cost, {'frets': {str(s): f for s, f in frets.items()},
            'fingers': info['fingers'], 'position': 1 if max(positive, default=0) <= 4 else min(positive),
            'barre': info['barre'], 'finger_count': info['finger_count'], 'capo': capo,
            'shape_name': chord_name(chord['root_pc']-capo, chord['quality'], chord['bass_pc']-capo, chord.get('key', {'fifths':0})),
            'sounding_name': chord.get('name', ''),
            'source': source, 'simplified': False}, bass))

    for d in old.get('fingering_diagrams', []):
        if d['start_tick'] <= tick < d['end_tick']:
            consider(d.get('frets', {}), 0, 'retained_source_grip')
    for entry in common_grips(int(chord['root_pc']), chord['quality'], int(chord['bass_pc']), capo):
        consider(fret_map(entry), 1, 'common_open_grip_for_explicit_selection')
    if not candidates or alternatives:
        for bass in (6, 5, 4):
            # 扫弦延音简化与右手候选扩充：保留旧单低弦搜索；显式B2需要让搜索真正包含另一条低弦。
            # strings = sorted(required | {bass} | ({1, 2, 3} if sweep else set()))
            # if sweep:
            #     strings = list(range(1, max(strings) + 1))
            # options = [[f for f in range(13) if (TUNING[s] + capo + f) % 12 in
            #             ({chord['bass_pc']} if s == bass else pcs)] for s in strings]
            # for values in product(*options):
            #     positive = [f for f in values if f]
            #     if positive and max(positive) - min(positive) > 5:
            #         continue
            #     consider(dict(zip(strings, values)), 2, 'bounded_chord_grip_search')
            base_strings=required | {bass} | ({1,2,3} if sweep else set())
            groups=[base_strings | {other} for other in (6,5,4) if other!=bass] if 'B2' in tokens else [base_strings]
            for group in groups:
                strings=sorted(group)
                if sweep:
                    strings=list(range(1,max(strings)+1))
                options=[[f for f in range(13) if (TUNING[s]+capo+f)%12 in
                          ({chord['bass_pc']} if s==bass else pcs)] for s in strings]
                for values in product(*options):
                    positive=[f for f in values if f]
                    if positive and max(positive)-min(positive)>5:
                        continue
                    consider(dict(zip(strings,values)),2,'bounded_chord_grip_search')
    if not candidates:
        raise ValueError('当前和弦' + chord['name'] + '无法按指定弦组在12品以内演奏，请调整弦序或范围')
    if alternatives:
        buckets = {}
        for cost, shape, bass in sorted(candidates,key=lambda item:item[0]):
            minimum = min((f for f in shape['frets'].values() if f),default=1)
            bucket = buckets.setdefault(minimum,[])
            if len(bucket)<6:bucket.append((shape,bass))
        return [pair for minimum in sorted(buckets) for pair in buckets[minimum]]
    _, shape, bass = min(candidates, key=lambda item: item[0])
    return shape, bass


def _strings(token, shape, bass):
    # 4/4可选右手与实时谱面试听：新增同刻合拨与方向性弦组；一记扫弦每弦只经过一次。
    frets = {int(s): f for s, f in shape['frets'].items()}
    if token in ('-', '空'):
        return []
    if token in ('DA', 'DL', 'UH'):
        return sorted(frets, reverse=True) if token == 'DA' else sorted(frets, reverse=True)[:2] if token == 'DL' else [1, 2, 3]
    result = []
    for part in token.split('+'):
        string = (bass if part == 'B' else next((s for s in sorted(frets, reverse=True) if s >= 4 and s != bass), None)
                  if part == 'B2' else int(part))
        if string not in frets or string in result:
            raise ValueError('指定弦未在当前指型内，或同一动作重复拨同一根弦：' + token)
        result.append(string)
    return result


def _release_notes(guitar, harmony, intervals, new_action_ids):
    # 4/4可选右手与实时谱面试听：新增局部换指后的逐弦释放，旧器乐和未选音符完整保留。
    notes=[n for n in guitar['notes'] if n.get('selection_action_id') in new_action_ids]
    actions=[e for e in guitar['selected_pattern_actions'] if e['id'] in new_action_ids]
    ends={}
    for a,b in reversed(intervals):ends[a]=ends.get(b,b)
    for note in notes:
        chord=next(h for h in harmony if h['id']==note['chord_id'])
        start=next(a for a,b in intervals if a<=note['start_tick']<b)
        limit=min(chord['end_tick'],ends[start])
        next_pluck=min((n['start_tick'] for n in notes if n['string']==note['string'] and n['start_tick']>note['start_tick']),default=limit)
        stop=min((e['start_tick'] for e in actions if e['kind']=='stop' and e['start_tick']>note['start_tick']),default=limit)
        release=min((d['start_tick'] for d in guitar['fingering_diagrams'] if note['start_tick']<d['start_tick']<limit
                     and d['frets'].get(str(note['string']))!=note['fret']),default=limit)
        note['end_tick']=min(limit,next_pluck,stop,release)


def _replace_selected_shape(guitar, chart, shape, bass, new_action_ids, harmony, intervals):
    # 4/4可选右手与实时谱面试听：新增只替换新选音的和弦配音，动作拍位、弦序角色及旧音乐不变。
    trial={**guitar,'notes':deepcopy(guitar['notes']),
           'selected_pattern_actions':deepcopy(guitar['selected_pattern_actions']),
           'fingering_diagrams':deepcopy(guitar['fingering_diagrams'])}
    a,b=chart['start_tick'],chart['end_tick']
    for d in trial['fingering_diagrams']:
        if d['id']==chart['id']:
            d.update(deepcopy(shape));d['reason']='explicit_selection_boundary_voicing_handover'
    removed={n['id']:n for n in trial['notes'] if n.get('selection_action_id') in new_action_ids and a<=n['start_tick']<b}
    trial['notes']=[n for n in trial['notes'] if n['id'] not in removed]
    for event in trial['selected_pattern_actions']:
        if event['id'] not in new_action_ids or not a<=event['start_tick']<b or not event['note_ids']:continue
        template=removed[event['note_ids'][0]]
        strings=_strings(event['token'],shape,bass)
        event['strings']=strings;event['note_ids']=[]
        for string in strings:
            fret=shape['frets'][str(string)]
            note={**deepcopy(template),'id':event['id']+'_s'+str(string),'string':string,'fret':fret,
                  'pitch_midi':TUNING[string]+shape['capo']+fret,
                  'finger':shape['fingers'].get(string,shape['fingers'].get(str(string),0)),
                  'hand_position':shape['position'],'role':'bass' if string>=4 else 'harmony',
                  'velocity':76 if string>=4 else 65}
            trial['notes'].append(note);event['note_ids'].append(note['id'])
    _release_notes(trial,harmony,intervals,new_action_ids)
    trial['notes'].sort(key=lambda n:(n['start_tick'],n['string'],n['id']))
    return trial


def _handover(guitar, vocal, harmony, intervals, new_action_ids, budget=48):
    # 4/4可选右手与实时谱面试听：新增全曲持握前瞻及有限局部配音搜索，不以截短旧音或换右手型解决衔接。
    from guitar_grip_policy import grip_position_path
    current=guitar;check=grip_position_path(current,vocal);attempts=0;edits=[];seen=set()
    while not check['valid'] and attempts<budget:
        tick=check.get('tick')
        if tick is None:break
        nearby=[d for d in current['fingering_diagrams'] if d.get('choice_tokens') and d['start_tick']<=tick and d['end_tick']>=tick-1920]
        nearby.sort(key=lambda d:(d['start_tick']>=tick,abs(d['end_tick']-tick)))
        progress=None
        for chart in nearby[:3]:
            chord=next(h for h in harmony if h['id']==chart['chord_id'])
            choices=_shape(chord,chart['capo'],chart['choice_tokens'],current,chart['start_tick'],alternatives=True)
            change=capo_at(current,tick)-capo_at(current,max(0,tick-1))
            # 4/4可选右手与实时谱面试听：新增变调夹边界优先试可提前到达的相对手位，持握限制本身不变。
            if chart['end_tick']<=tick and change>0:
                choices.sort(key=lambda pair:(min((f for f in pair[0]['frets'].values() if f),default=1)<1+change,
                                              max(pair[0]['frets'].values())))
            for shape,bass in choices:
                signature=(chart['id'],tuple(sorted(shape['frets'].items())))
                if shape['frets']==chart['frets'] or signature in seen:continue
                seen.add(signature);attempts+=1
                trial=_replace_selected_shape(current,chart,shape,bass,new_action_ids,harmony,intervals)
                result=grip_position_path(trial,vocal)
                edit={'start_tick':chart['start_tick'],'end_tick':chart['end_tick'],
                      'before_frets':chart['frets'],'after_frets':shape['frets'],
                      'reason':check['reason'],'right_hand_actions_and_clock_unchanged':True}
                if result['valid']:
                    return trial,{'attempts':attempts,'budget':budget,'edits':edits+[edit],'valid':True}
                if result.get('tick',-1)>tick and progress is None:progress=(trial,result,edit)
                if attempts>=budget:break
            if attempts>=budget:break
        if progress is None:break
        current,check,edit=progress;edits.append(edit)
    return current,{'attempts':attempts,'budget':budget,'edits':edits,'valid':check['valid'],
                    'failure':{k:v for k,v in check.items() if k!='positions'} if not check['valid'] else None}


def compile_selection(project, plan):
    # 4/4可选右手与实时谱面试听：新增唯一音乐编译器；预览、另存和验收均使用同一拍位规则。
    scope=_scope_view(project) if plan is not None else None
    normalized = normalize_plan(plan, project, scope)
    if normalized is None:
        return deepcopy(project), {'status': 'unchanged_no_selection', 'arranged_measures': [], 'music_changed': False}
    rows, blocks, eligible, exceptions = scope
    choices = {o['section_id']: o['choice'] for o in normalized['sections']}
    assignments = [(b, choices.get(b['id'], normalized['default'])) for b in blocks]
    # 多区间右手配置与网页完整成品：新增区间赋值；旧段落路径不改，区间循环从指定小节首拍开始。
    from guitar_pattern_ranges import range_assignments, protect_range_boundaries, action_span
    if normalized.get('ranges'):
        assignments = range_assignments(normalized['ranges'], rows)
    selected = {m for b, choice in assignments if choice for m in b['measures'] if m in eligible}
    if normalized.get('ranges'):
        selected, exceptions = protect_range_boundaries(project, rows, selected, exceptions)
    if not selected:
        raise ValueError('所选范围没有可修改的完整4/4演唱小节；器乐、真实停顿和过渡小节已保留')
    intervals = [(r['start_tick'], r['end_tick']) for r in rows if r['number'] in selected]
    original = project['arrangements']['guitar']
    removed = {n['id'] for n in original['notes'] if ordinary(n) and any(a <= n['start_tick'] < b for a, b in intervals)}
    notes = [deepcopy(n) for n in original['notes'] if n['id'] not in removed]
    diagrams = _subtract_ranges(original.get('fingering_diagrams', []), intervals)
    regions = _subtract_ranges(original.get('notation_regions', []), intervals)
    harmony = guitar_shared_view(project)['harmony']
    actions, sections, shape_cache = [], [], {}
    generation = fingerprint([original['notes'], normalized])[:16]
    for block, choice in assignments:
        if not choice:
            continue
        tokens = _tokens(choice)
        arranged = [m for m in block['measures'] if m in selected]
        sections.append({**block, 'choice': deepcopy(choice), 'arranged_measures': arranged})
        for number in arranged:
            row = rows[number - 1]
            start, end = row['start_tick'], row['end_tick']
            relative = start - block['start_tick']
            cycle = choice['cycle_ticks']
            for base in range((relative // cycle) * cycle, relative + 1920, cycle):
                for i, spec in enumerate(choice['template']['events']):
                    tick = block['start_tick'] + base + spec['onset_tick']
                    if not start <= tick < end:
                        continue
                    token = tokens[i]
                    chord = next((h for h in harmony if h['start_tick'] <= tick < h['end_tick'] and h.get('name') != 'N.C.'), None)
                    if chord is None:
                        raise ValueError('第' + str(number) + '小节缺少已确认和弦，不能填入右手型')
                    capo = capo_at(original, tick)
                    key = (chord['id'], capo, tuple(tokens))
                    if key not in shape_cache:
                        shape_cache[key] = _shape(chord, capo, tokens, original, tick)
                    shape, bass = shape_cache[key]
                    strings = _strings(token, shape, bass)
                    identity = f"choice_{generation}_{number}_{tick-start}"
                    kind = ('stop' if choice['silence'] == 'stop' else 'air' if token == '空' else 'hold') if not strings else 'strum' if token in ('DA', 'DL', 'UH') else 'pinch' if len(strings) > 1 else 'pluck'
                    # 多区间右手配置与网页完整成品：保留旧动作时长，区间末尾仅截断占时，不制造区间外新拨弦。
                    # event = {'id': identity, 'start_tick': tick, 'action_span_ticks': spec['action_span_ticks'],
                    span = action_span(spec, tick, block, selected, rows) if normalized.get('ranges') else spec['action_span_ticks']
                    event = {'id': identity, 'start_tick': tick, 'action_span_ticks': span,
                        'kind': kind, 'token': token, 'strings': strings, 'direction': 'up' if token == 'UH' else 'down' if kind == 'strum' else None,
                        'chord_id': chord['id'], 'section_id': block['id'], 'measure': number, 'note_ids': []}
                    actions.append(event)
                    for string in strings:
                        fret = shape['frets'][str(string)]
                        note = {'id': identity + '_s' + str(string), 'start_tick': tick,
                            'end_tick': min(chord['end_tick'], end), 'string': string, 'fret': fret,
                            'pitch_midi': TUNING[string] + capo + fret,
                            'finger': shape['fingers'].get(string, shape['fingers'].get(str(string), 0)),
                            'hand_position': shape['position'], 'role': 'bass' if string >= 4 else 'harmony', 'section': 'vocal',
                            'velocity': 76 if string >= 4 else 65, 'chord_id': chord['id'],
                            'source': 'explicit_user_right_hand_choice', 'selection_action_id': identity,
                            # 多区间右手配置与网页完整成品：修改动作时值引用实际范围内的占时，保留旧写法。
                            # 'right_hand_token': token, 'right_hand_duration_ticks': spec['action_span_ticks'],
                            'right_hand_token': token, 'right_hand_duration_ticks': span,
                            'right_hand_duration_source': 'explicit_action_span_not_sounding_duration', 'texture_measure': number}
                        notes.append(note)
                        event['note_ids'].append(note['id'])
            for chord in harmony:
                a, b = max(start, chord['start_tick']), min(end, chord['end_tick'])
                if a >= b or chord.get('name') == 'N.C.':
                    continue
                key = (chord['id'], capo_at(original, a), tuple(tokens))
                if key not in shape_cache:
                    shape_cache[key] = _shape(chord, key[1], tokens, original, a)
                shape = shape_cache[key][0]
                diagrams.append({**deepcopy(shape), 'id': f'choice_grip_{number}_{a}', 'start_tick': a, 'end_tick': b,
                                 'chord_id': chord['id'], 'choice_tokens':tokens, 'reason': 'explicit_selection_actual_grip'})
            regions.append({'id': f'choice_region_{number}', 'start_tick': start, 'end_tick': end,
                            'mode': 'chord_grip', 'section': 'vocal', 'reason': 'explicit_selection'})
    actions.sort(key=lambda e: e['start_tick'])
    # 4/4可选右手与实时谱面试听：新增逐弦余音，连续可改小节内延续；和弦释放、同弦再拨或显式制音才结束。
    selected_rows = [r for r in rows if r['number'] in selected]
    ends = {}
    for row in reversed(selected_rows):
        end = ends.get(row['end_tick'], row['end_tick'])
        ends[row['start_tick']] = end
    protected_ids = {n['id'] for n in original['notes'] if n['id'] not in removed}
    new_notes = [n for n in notes if n.get('selection_action_id') and n['id'] not in protected_ids]
    for note in new_notes:
        chord = next(h for h in harmony if h['id'] == note['chord_id'])
        row = rows[note['texture_measure'] - 1]
        limit = min(chord['end_tick'], ends[row['start_tick']])
        next_pluck = min((n['start_tick'] for n in new_notes if n['string'] == note['string'] and n['start_tick'] > note['start_tick']), default=limit)
        stop = min((e['start_tick'] for e in actions if e['kind'] == 'stop' and e['start_tick'] > note['start_tick']), default=limit)
        note['end_tick'] = min(limit, next_pluck, stop)
    revised = deepcopy(project)
    guitar = revised['arrangements']['guitar']
    stale = ('section_patterns', 'right_hand_patterns', 'regular_rhythm', 'instrumental_register', 'instrumental_expression',
             'instrumental_source_backbone', 'phrase_harmony_performance', 'structure_stability', 'grip_fingerings',
             'capo_refingering', 'chord_charts', 'readability_ancestor_evidence', 'instrumental_register_preparations')
    prior = {k: guitar.pop(k) for k in stale if k in guitar}
    guitar['configuration'].pop('stable_vocal_patterns', None)
    guitar['configuration']['right_hand_selection'] = deepcopy(POLICY)
    retained_actions = [deepcopy(e) for e in original.get('selected_pattern_actions', [])
                        if not any(a <= e['start_tick'] < b for a,b in intervals)]
    guitar.update(notes=sorted(notes, key=lambda n: (n['start_tick'], n['string'], n['id'])),
        fingering_diagrams=sorted(diagrams, key=lambda d: d['start_tick']), notation_regions=sorted(regions, key=lambda d: d['start_tick']),
        selected_pattern_actions=sorted(retained_actions+actions, key=lambda e:e['start_tick']), readable_harmony=deepcopy(harmony))
    kept = [deepcopy(e) for e in original.get('attack_events', []) if not any(a <= e['start_tick'] < b for a, b in intervals)]
    guitar['attack_events'] = sorted(kept + [deepcopy(e) for e in actions if e['note_ids']], key=lambda e: e['start_tick'])
    # 4/4可选右手与实时谱面试听：新增实际持握搜索后重新建立攻击引用，预览与保存使用相同最终配音。
    new_action_ids={e['id'] for e in actions}
    # 多区间右手配置与网页完整成品：新增相邻配置换指时的逐弦释放，未选旧音继续逐字段保留。
    if normalized.get('ranges'):
        _release_notes(guitar, harmony, intervals, new_action_ids)
    guitar,handover=_handover(guitar,project['accepted_vocal_project'],harmony,intervals,new_action_ids)
    revised['arrangements']['guitar']=guitar
    guitar['attack_events']=sorted(kept+[deepcopy(e) for e in guitar['selected_pattern_actions']
        if e['id'] in new_action_ids and e['note_ids']],key=lambda e:e['start_tick'])
    guitar['selection_provenance'] = {'prior_certifications': prior, 'source_notes_sha256': fingerprint(original['notes'])}
    # 4/4可选右手与实时谱面试听：新增旧余音结束的纯记谱投影；原音符和MIDI／音频结束时间完整保持。
    guitar['natural_release_notation']=[{'note_id':n['id'],'actual_end_tick':n['end_tick'],
        'notation_end_tick':((n['end_tick']+119)//120)*120}
        for n in guitar['notes'] if n['id'] in protected_ids and n['start_tick']%120==0 and n['end_tick']%120
        and n['end_tick']-n['start_tick']>=120]
    top = ('vocal_pattern_revision', 'guitar_readability_revision', 'guitar_register_revision', 'guitar_readability_acceptance',
           'guitar_source_bass_acceptance', 'section_pattern_acceptance', 'guitar_score_layout')
    old_top = {k: revised.pop(k) for k in top if k in revised}
    revised['right_hand_selection'] = {'version': 1, 'policy': deepcopy(POLICY), 'plan': normalized,
        'sections': sections, 'arranged_measures': sorted(selected), 'exceptions': exceptions,
        'removed_note_ids': sorted(removed), 'voicing_handover':handover, 'prior_project_certifications': old_top}
    revised['music_acceptance'] = {**deepcopy(project.get('music_acceptance', {})), 'status': 'needs_review',
        'publication_allowed': False, 'scope': 'explicit_right_hand_arrangement_not_original_recording_transcription'}
    return revised, {'status': 'compiled', 'arranged_measures': sorted(selected), 'exceptions': exceptions,
                     'actions': len(actions), 'new_notes': len(new_notes), 'protected_notes': len(notes) - len(new_notes),
                     'music_changed': True, 'selection_sha256': fingerprint(normalized)}


def source_project(project):
    # 4/4可选右手与实时谱面试听：新增每版绑定真实父工程，拒绝自比、缺文件、变内容与循环。
    source = project.get('right_hand_selection_source', {})
    path = Path(source.get('project', '__missing_selection_source__'))
    if not local_path(path).is_file() or sha256(path) != source.get('project_sha256'):
        raise ValueError('右手选型原工程缺失或改变')
    baseline = read_json(path)
    if has_selection(baseline) and baseline.get('right_hand_selection_source') == source:
        raise ValueError('右手选型来源循环')
    return baseline


def legacy_source(project):
    # 4/4可选右手与实时谱面试听：新增旧时间／小节认证在原父工程重放，新型另验完整保护范围。
    current = project
    seen = set()
    while has_selection(current):
        key = fingerprint(current.get('right_hand_selection_source'))
        if key in seen or len(seen) >= 32:
            raise ValueError('右手选型来源链循环或过长')
        seen.add(key)
        current = source_project(current)
    return current


def assess_selection(project, baseline=None):
    # 4/4可选右手与实时谱面试听：新增由绑定父工程独立重建动作与实音，旧通过标记不能覆盖新音乐。
    if not has_selection(project):
        return {'valid': True, 'status': 'not_requested_for_preserved_legacy_music'}
    errors = []
    try:
        baseline = source_project(project) if baseline is None else baseline
        state = project.get('right_hand_selection', {})
        if state.get('version') != 1 or state.get('policy') != POLICY:
            raise ValueError('右手选型计划缺失或规则过期')
        expected, audit = compile_selection(baseline, state['plan'])
        if expected.get('right_hand_selection', {}).get('plan') != state['plan']:
            errors.append('selection_template_or_plan_changed')
        if project['accepted_vocal_project'] != baseline['accepted_vocal_project'] or project.get('bar_boundary_revision') != baseline.get('bar_boundary_revision'):
            errors.append('approved_voice_clock_or_measure_boundaries_changed')
        if project['shared_analysis'] != baseline['shared_analysis']:
            errors.append('approved_source_harmony_changed')
        for instrument, arrangement in baseline['arrangements'].items():
            if instrument != 'guitar' and project['arrangements'].get(instrument) != arrangement:
                errors.append('protected_other_instrument_changed:' + instrument)
        actual, wanted = project['arrangements']['guitar'], expected['arrangements']['guitar']
        fixed = {n['id']: n for n in baseline['arrangements']['guitar']['notes'] if n['id'] not in state['removed_note_ids']}
        by_id = {n['id']: n for n in actual['notes']}
        if len(by_id) != len(actual['notes']) or any(by_id.get(k) != n for k, n in fixed.items()):
            errors.append('protected_note_identity_or_complete_sustain_changed')
        def material(arr):
            return sorted((tuple(str(n.get(f)) for f in NOTE_FIELDS) for n in arr['notes']))
        if material(actual) != material(wanted):
            errors.append('actual_notes_do_not_match_selected_actions_and_releases')
        for field in ('selected_pattern_actions', 'readable_harmony', 'notation_regions', 'fingering_diagrams', 'natural_release_notation'):
            # 4/4可选右手与实时谱面试听：新增按JSON规范比较指型键，整数弦号序列化成字符串不算音乐改变。
            if fingerprint(actual.get(field)) != fingerprint(wanted.get(field)):
                errors.append('selection_' + field + '_changed')
        for field in ('arranged_measures', 'exceptions', 'removed_note_ids', 'sections'):
            if state.get(field) != expected['right_hand_selection'].get(field):
                errors.append('selection_scope_changed:' + field)
        if project.get('music_acceptance', {}).get('publication_allowed') is not False:
            errors.append('selection_cannot_inherit_normal_publication')
        from guitar_grip_policy import grip_position_path
        path = grip_position_path(actual, project['accepted_vocal_project'])
        if not path['valid']:
            errors.append('complete_grip_or_sustain_not_playable')
        return {'valid': not errors, 'status': 'passed' if not errors else 'failed', 'errors': errors,
                'scope': 'explicit_4_4_actions_actual_notes_and_protected_source_not_whole_song_listening',
                'arranged_measures': audit['arranged_measures'], 'actions': audit['actions'], 'hand_path': {k:v for k,v in path.items() if k != 'positions'}}
    except (ValueError, KeyError, TypeError, StopIteration) as exc:
        return {'valid': False, 'status': 'failed', 'errors': ['selection_invalid:' + str(exc)]}


def require_selection(project):
    # 4/4可选右手与实时谱面试听：新增所有显式选择入口的共同守卫。
    check = assess_selection(project)
    if not check['valid']:
        raise ValueError('实际右手选型验收失败：' + str(check['errors']))
    return check
