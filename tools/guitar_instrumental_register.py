"""吉他器乐低把位与指型复用：自然句音区、基础手型和真实持续音的联合规划。"""
# 吉他器乐低把位与指型复用：新增独立派生层，不读取曲名、歌词或参考谱答案，不删除任何声部。
from __future__ import annotations
from collections import Counter, defaultdict
from copy import deepcopy
from functools import lru_cache
from itertools import permutations, product
import hashlib
import json
from pathlib import Path
from workspace_location import local_path

from accompaniment_analysis import SongClock
from accompaniment_arrange import TUNING, grip_info, validate_playability
from guitar_capo import capo_at, fret_at
from guitar_grip_library import common_grips, fret_map, load_library
from score_export import PPQ, read_json, sha256

POLICY = {
    'version': 1, 'name': 'phrase_register_and_continuous_fingers',
    'scope': ['intro', 'interlude', 'outro'], 'preferred_maximum_fret': 4,
    'ordinary_maximum_fret': 12, 'exception_maximum_fret': 20,
    'melody_octave_candidates': [0, -12, -24],
    # 吉他器乐低把位与指型复用：修改，旧四分拍三分之四休止漏掉真实八分呼吸；保留旧策略值。
    # 'phrase_rest_quarters': .75, 'beam_width': 48,
    'phrase_rest_quarters': .5, 'beam_width': 48,
    'expanded_beam_width': 144, 'maximum_anchor_candidates': 5,
    'maximum_position_rate': 24., 'preferred_changed_fingers': 2,
    'retain_all_notes_and_attack_times': True,
    'reference_score_used_as_input': False,
}
# 器乐合理分句与十二品硬限制：新增独立版本，旧策略仅用于历史来源重放；新规划没有20品回退。
STRICT_POLICY = {**POLICY, 'version': 2, 'name': 'musical_motifs_hard_twelve',
                 'exception_maximum_fret': 12, 'hard_maximum_fret': 12,
                 'minimum_motif_quarters': 2, 'register_handover_semitones': 5,
                 'low_fret_priority': 'minimize_notes_above_four_before_fingering_cost',
                 'automatic_high_fret_fallback': False}
ALLOWED_FIELDS = ('pitch_midi', 'string', 'fret', 'finger', 'hand_position')
DERIVED_FIELDS = ('instrumental_register_source_pitch_midi', 'instrumental_register_octave_shift',
                  'instrumental_register_phrase_id')


# 吉他器乐低把位与指型复用：新增共同和声的规范视图，原分析／导出视图须得到同一个绑定指纹。
def register_shared_view(shared, vocal):
    from phrase_harmony_plan import arrangement_view
    return {k:v for k,v in arrangement_view(shared,vocal).items() if k!='_phrase_harmony_view'}


# 吉他器乐低把位与指型复用：新增规范指纹；来源与派生结果分别记录，避免可变对象自比。
def fingerprint(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':')).encode('utf-8')).hexdigest()


# 吉他器乐低把位与指型复用：新增半开真实段落范围，混合小节不因此解锁普通演唱音。
def editable_notes(shared, arrangement):
    sections = [s for s in shared.get('sections', []) if s['kind'] in POLICY['scope']]
    return {n['id'] for n in arrangement['notes']
            if any(s['start_tick'] <= n['start_tick'] < s['end_tick'] for s in sections)}


# 吉他器乐低把位与指型复用：新增只在真实休止或器乐段界分句，连续旋律不按排版行任意切八度。
def melodic_phrases(shared, notes, editable):
    result = []
    # 吉他器乐低把位与指型复用：新增音区动机的和声／节拍边界，持续音未结束时不能切换音区。
    bar=shared['statistics']['bar_ticks']; pulse=int(PPQ*4/shared['timing']['meter'][1])
    bass_ticks={n['start_tick'] for n in notes if n['id'] in editable and n['role']=='bass'}
    harmony={h['id']:h for h in shared.get('harmony',[])}
    for section in shared.get('sections', []):
        if section['kind'] not in POLICY['scope']:
            continue
        selected = sorted((n for n in notes if n['id'] in editable and
                           n['role'] == 'instrumental_melody' and
                           section['start_tick'] <= n['start_tick'] < section['end_tick']),
                          key=lambda n: (n['start_tick'], n['id']))
        chunks = []
        for note in selected:
            # 吉他器乐低把位与指型复用：修改，旧只靠休止会把连续的多个和声动机锁成一个极宽音区。
            # if not chunks or note['start_tick'] - chunks[-1][-1]['end_tick'] >= PPQ * POLICY['phrase_rest_quarters']:
            split=not chunks
            if chunks:
                previous=chunks[-1][-1]; span=note['start_tick']-chunks[-1][0]['start_tick']
                released=max(n['end_tick'] for n in chunks[-1])<=note['start_tick']
                before=harmony.get(previous.get('chord_id'),{}); after=harmony.get(note.get('chord_id'),{})
                changed=(before.get('root_pc'),before.get('bass_pc'))!=(after.get('root_pc'),after.get('bass_pc'))
                harmonic_anchor=note['start_tick'] in bass_ticks and note['start_tick']%pulse==0 and changed
                metric_anchor=note['start_tick']%bar==0 and span>=bar
                # 原曲器乐旋律骨干重提取：新增真实大幅音区交接；源主线释放后跳进九半音以上可另择八度。
                # 原曲器乐旋律骨干重提取：旧候选没有此字段继续原句法，不能在普通连续级进中逐音折八度。
                source_register_boundary=(released and note.get('source_backbone_section_id') and
                    previous.get('source_backbone_section_id') and
                    abs(note['source_backbone_pitch_midi']-previous['source_backbone_pitch_midi'])>=9)
                # 原曲器乐旋律骨干重提取：修改，原分句保留，仅源骨干释放后的大幅真实音区交接新增可重规划点。
                # split=(note['start_tick']-max(n['end_tick'] for n in chunks[-1])>=PPQ*POLICY['phrase_rest_quarters'] or
                #        released and (metric_anchor or harmonic_anchor and span>=bar//2))
                split=(note['start_tick']-max(n['end_tick'] for n in chunks[-1])>=PPQ*POLICY['phrase_rest_quarters'] or
                       released and (metric_anchor or harmonic_anchor and span>=bar//2) or source_register_boundary)
            if split:
                chunks.append([])
            chunks[-1].append(note)
        for chunk in chunks:
            origin = chunk[0]['start_tick']; pitch = chunk[0]['pitch_midi']
            # 吉他器乐低把位与指型复用：新增移调无关的旋律／节奏动机身份，文字和歌曲名称不参与。
            signature = tuple((n['start_tick']-origin, n['end_tick']-n['start_tick'],
                               n['pitch_midi']-pitch) for n in chunk)
            result.append({'id': f'instrumental_phrase_{len(result)+1:04}', 'section': section['kind'],
                           'start_tick': origin, 'end_tick': max(n['end_tick'] for n in chunk),
                           'note_ids': [n['id'] for n in chunk], 'signature': signature})
    return result


# 吉他器乐低把位与指型复用：新增按真实按弦单位计一次手指移动；松／按不重复算两根手指。
@lru_cache(maxsize=32768)
def units_for(geometry):
    info = grip_info(dict(geometry))
    if info is None:
        return None
    groups = defaultdict(list)
    for string, finger in info['fingers'].items():
        groups[finger].append((string, dict(geometry)[string]))
    return tuple(tuple(sorted(values)) for _, values in sorted(groups.items()))


# 吉他器乐低把位与指型复用：新增分指／横按的可行备选，不能为了少算手指强迫合并正在持续的按弦。
@lru_cache(maxsize=32768)
def unit_candidates(geometry):
    canonical=units_for(geometry)
    if canonical is None:
        return ()
    positive=tuple((s,f) for s,f in geometry if f>0)
    candidates=[canonical]
    if len(positive)<=4:
        individual=tuple(((s,f),) for s,f in positive)
        if individual not in candidates:
            candidates.append(individual)
    return tuple(candidates)


# 吉他器乐低把位与指型复用：新增实体手指连续分配，持续按住的弦／品不能悄悄改用另一手指。
@lru_cache(maxsize=65536)
def finger_transition(previous, units, held):
    best = None
    for slots in permutations(range(4), len(units)):
        current = [()] * 4
        for slot, unit in zip(slots, units):
            current[slot] = unit
        current = tuple(current)
        if any(next((i for i, u in enumerate(previous) if sf in u), None) !=
               next((i for i, u in enumerate(current) if sf in u), None) for sf in held):
            continue
        changes = sum(a != b for a, b in zip(previous, current))
        # 吉他器乐低把位与指型复用：新增轻量指序偏好，允许保持已按手指优先于重新编号。
        fretted = [(i, min(f for _, f in u)) for i, u in enumerate(current) if u]
        inversions = sum(fa > fb for i, fa in fretted for j, fb in fretted if i < j)
        rank = (changes, inversions, slots)
        if best is None or rank < best[0]:
            best = (rank, current)
    return None if best is None else (best[1], best[0][0])


# 吉他器乐低把位与指型复用：新增同调同低音常用候选与局部手型；不把持握参考形状误当发声和弦。
def anchor_candidates(shared, arrangement, editable):
    bar = shared['statistics']['bar_ticks']; by_bar = defaultdict(list)
    for note in arrangement['notes']:
        if note['id'] in editable:
            by_bar[note['start_tick']//bar].append(note)
    library = [e for e in load_library()['entries'] if e['max_fret'] <= 4]
    result = {}
    for measure, notes in by_bar.items():
        capo = capo_at(arrangement, notes[0]['start_tick']); exact = {}
        for chord in shared.get('harmony', []):
            if chord['name'] != 'N.C.' and chord['start_tick'] < (measure+1)*bar and chord['end_tick'] > measure*bar:
                exact.update({e['id']: e for e in common_grips(chord['root_pc'], chord['quality'], chord['bass_pc'], capo)
                              if e['max_fret'] <= 12})
        ranked = []
        for entry in {**{e['id']: e for e in library}, **exact}.values():
            base = fret_map(entry)
            support = sum((n['end_tick']-n['start_tick']) * (2 if n['role']=='instrumental_melody' else 1)
                          for n in notes if any((TUNING[s]+capo+f-n['pitch_midi']) % 12 == 0
                                               for s, f in base.items()))
            if not support:
                continue
            rank = (-support, entry['id'] not in exact, entry['priority'], entry['max_fret'], entry['id'])
            ranked.append((rank, entry['id'], tuple(sorted(base.items()))))
        result[measure] = [(identity, geometry) for _, identity, geometry in sorted(ranked)[:POLICY['maximum_anchor_candidates']]]
    return result


# 吉他器乐低把位与指型复用：新增固定乐句八度的全部弦品候选，低音／和声只做八度配音而不删音。
# 原曲拍轴与歌词拍位通用修复：修改签名，旧位置策略保留；新版仅用于未定稿新编配，旧工程仍用版本1。
# def locations(note, capo, melody_shift, maximum_fret, editable):
# 歌词自动加载与伴随声部音区保护：修改增加已核验伴随声部音区参数，旧调用默认完全保持。
# def locations(note, capo, melody_shift, maximum_fret, editable, voicing_version=1):
def locations(note, capo, melody_shift, maximum_fret, editable, voicing_version=1, companion_pitch=None):
    if note['id'] not in editable:
        return ((note['string'], note['fret'], note['pitch_midi'], 0),)
    # 原曲拍轴与歌词拍位通用修复：修改，旧仅降伴奏八度保留；新编配允许必要的上移八度，保留音级与声部排序和全部手部限制。
    # shifts = (melody_shift,) if note['role']=='instrumental_melody' else (0, -12, -24)
    if voicing_version not in (1,2):raise ValueError('未知器乐配音搜索版本。')
    shifts = (melody_shift,) if note['role']=='instrumental_melody' else (0,-12,-24,12) if voicing_version==2 else (0,-12,-24)
    return tuple((s, note['pitch_midi']+shift-TUNING[s]-capo, note['pitch_midi']+shift, shift)
                 for shift in shifts for s in range(6, 0, -1)
                 # 歌词自动加载与伴随声部音区保护：新增同音区候选过滤，不能靠换八度改善手型代价；无解仍失败。
                 if 0 <= note['pitch_midi']+shift-TUNING[s]-capo <= maximum_fret
                 and (companion_pitch is None or note['pitch_midi']+shift == companion_pitch))


# 吉他器乐低把位与指型复用：新增声部层级核验，低音保持底部，旋律原有的上方关系不会被降位倒置。
def role_order_valid(active, original):
    values = list(active.items())
    for identity, (_, _, pitch, _) in values:
        old = original[identity]; role = old['role']
        if role not in ('bass', 'instrumental_melody'):
            continue
        for other, (_, _, other_pitch, _) in values:
            if identity == other:
                continue
            old_other = original[other]
            if role == 'bass' and old['pitch_midi'] <= old_other['pitch_midi'] and pitch > other_pitch:
                return False
            if role == 'instrumental_melody' and old['pitch_midi'] >= old_other['pitch_midi'] and pitch < other_pitch:
                return False
    return True


# 吉他器乐低把位与指型复用：新增持续音、手指、基准手型与乐句八度组成的有限束搜索状态。
# 器乐合理分句与十二品硬限制：修改，旧签名保留；新路径优先减少高于4品的音，旧重放保持原代价。
# def solve_path(shared, vocal, arrangement, editable, phrases, maximum_fret, width, preferences=None):
# 保音持续按弦与整句八度衔接：修改签名，旧搜索作为历史重放保留；新版显式启用持续弦位前瞻与局部重新规划。
# def solve_path(shared, vocal, arrangement, editable, phrases, maximum_fret, width, preferences=None, low_fret_priority=False):
def solve_path(shared, vocal, arrangement, editable, phrases, maximum_fret, width, preferences=None, low_fret_priority=False, search_version=1):
    notes = arrangement['notes']; original = {n['id']: n for n in notes}; clock = SongClock(vocal)
    # 歌词自动加载与伴随声部音区保护：新增每次初次求解严格复核音区来源，普通新曲和旧历史重放无保护声明时原样运行。
    from guitar_companion_register import active_constraints
    companion_locks = active_constraints(shared, vocal, arrangement)
    grouped = defaultdict(list)
    for note in notes:
        grouped[note['start_tick']].append(note)
    ticks = sorted({t for n in notes for t in (n['start_tick'], n['end_tick'])})
    phrase_for = {identity: p for p in phrases for identity in p['note_ids']}
    # 吉他器乐低把位与指型复用：新增乐句结束表，过去八度选择不影响后续束搜索的可行性分层。
    phrase_end = {p['id']: p['end_tick'] for p in phrases}
    # 器乐合理分句与十二品硬限制：新增交接前句的八度保持到边界检查，短呼吸期间不能丢失旋律连接依据。
    for phrase in phrases:
        parent = phrase.get('register_handover_from_phrase_id')
        if parent:
            phrase_end[parent] = max(phrase_end[parent], phrase['start_tick'] + 1)
    anchors = anchor_candidates(shared, arrangement, editable)
    entries = {e['id']: e for e in load_library()['entries']}
    bar = shared['statistics']['bar_ticks']; preferences = preferences or {}
    source_positions = arrangement.get('grip_hand_positions', arrangement.get('hand_positions', []))
    previous_tick = None
    # 器乐合理分句与十二品硬限制：修改，旧初始化保留；新增独立低品计数，不改物理手位或历史代价。
    # nodes = [{'cost': 0., 'position': 1, 'allowed': tuple(range(1, 21)), 'fingers': ((),)*4,
    nodes = [{'cost': 0., 'above_four_cost': 0, 'position': 1, 'allowed': tuple(range(1, 21)), 'fingers': ((),)*4,
              'active': {}, 'shifts': {}, 'base_id': None, 'base': (), 'parent': None, 'tick': None}]
    # 器乐合理分句与十二品硬限制：新增字典序优先级，换指便利不能抵消一个本可避免的高品音。
    def cost_key(node):
        return (node['above_four_cost'], node['cost']) if low_fret_priority else node['cost']
    group_cache = {}
    # 保音持续按弦与整句八度衔接：修改事件循环，原顺序循环保留；新版可从真实检查点重新求解局部。
    # for tick in ticks:
    if search_version not in (1, 2):
        raise ValueError('未知器乐持续用弦搜索版本。')
    from guitar_register_search import RegisterSearch
    # 歌词自动加载与伴随声部音区保护：修改后续用弦前瞻采用同一保护音区，避免当前步能弹、后续又按另一个八度试算。
    # context = RegisterSearch(shared, arrangement, editable, phrases, ticks, maximum_fret, width) if search_version == 2 else None
    context = RegisterSearch(shared, arrangement, editable, phrases, ticks, maximum_fret, width, companion_locks) if search_version == 2 else None
    index = 0
    while index < len(ticks):
        tick = ticks[index]
        if context:
            context.remember(index, nodes, previous_tick)
        group = sorted(grouped.get(tick, []), key=lambda n: (n['role']!='instrumental_melody', n['id']))
        capo = capo_at(arrangement, tick)
        old_capo = capo_at(arrangement, previous_tick) if previous_tick is not None else capo
        target_old = next((p['position'] for p in reversed(source_positions) if p['tick']<=tick), 1)
        seconds = max(.001, clock.seconds(tick)-clock.seconds(previous_tick)) if previous_tick is not None else 1.
        fresh = {}; local_phrase = next((phrase_for[n['id']] for n in group if n['id'] in phrase_for), None)
        for node in nodes:
            held = {identity: loc for identity, loc in node['active'].items() if original[identity]['end_tick']>tick}
            shifting = (node['shifts'][local_phrase['id']],) if local_phrase and local_phrase['id'] in node['shifts'] else (
                # 器乐合理分句与十二品硬限制：修改，旧原候选保留；新合理乐句先过滤已证明不可行的整句八度。
                # tuple(POLICY['melody_octave_candidates']) if local_phrase else (0,))
                tuple(local_phrase.get('octave_candidates', POLICY['melody_octave_candidates'])) if local_phrase else (0,))
            for shift in shifting:
                # 器乐合理分句与十二品硬限制：新增有证据的新边界仍限制实际音程，防止低品目标引入任意大跳。
                if local_phrase and local_phrase.get('register_handover_from_phrase_id'):
                    parent_shift = node['shifts'].get(local_phrase['register_handover_from_phrase_id'])
                    if parent_shift is not None and abs(local_phrase['register_handover_source_interval'] +
                            shift - parent_shift) > local_phrase['register_handover_maximum_interval']:
                        continue
                cache_key = (tick, shift)
                if cache_key not in group_cache:
                    candidates = []
                    # 原曲拍轴与歌词拍位通用修复：修改，旧位置求解保留；按源种子的明确版本重放配音候选。
                    # for values in product(*(locations(n, capo, shift, maximum_fret, editable) for n in group)):
                    # 歌词自动加载与伴随声部音区保护：修改实际候选也保留来源音区，持续弦位和十二品上限照常检查。
                    # for values in product(*(locations(n,capo,shift,maximum_fret,editable,arrangement['configuration'].get('instrumental_register_voicing_version',1)) for n in group)):
                    for values in product(*(locations(n,capo,shift,maximum_fret,editable,arrangement['configuration'].get('instrumental_register_voicing_version',1),companion_locks.get(n['id'])) for n in group)):
                        if len({v[0] for v in values}) != len(values):
                            continue
                        if grip_info({v[0]: v[1] for v in values}) is None:
                            continue
                        candidates.append(values)
                    group_cache[cache_key] = candidates
                for values in group_cache[cache_key]:
                    added = {n['id']: value for n, value in zip(group, values)}
                    active = {**held, **added}
                    if len({v[0] for v in active.values()}) != len(active) or not role_order_valid(active, original):
                        continue
                    current_frets = {s: pitch-TUNING[s]-capo for s, _, pitch, _ in active.values()}
                    if any(f < 0 for f in current_frets.values()):
                        continue
                    # 保音持续按弦与整句八度衔接：新增持续占弦的后续可行性检查，整句八度在前瞻中共用，不能临时逐音折返。
                    candidate_shifts = {**node['shifts'], **({local_phrase['id']: shift} if local_phrase else {})}
                    if context and not context.future_possible(tick, active, candidate_shifts):
                        continue
                    instrumental = any(identity in editable for identity in active)
                    # 吉他器乐低把位与指型复用：新增混合边界的原唱段图式约束，器乐尾音不能挤掉已认可的按法。
                    source_region=next((r for r in arrangement.get('notation_regions',[]) if r['start_tick']<=tick<r['end_tick']),None)
                    protected_chart=next((d for d in arrangement.get('fingering_diagrams',[]) if d['start_tick']<=tick<d['end_tick']),None)
                    fixed_active=any(identity not in editable for identity in active)
                    if protected_chart and fixed_active and source_region and source_region['section'] not in POLICY['scope']:
                        bases=[(protected_chart.get('common_grip_id'),tuple(sorted((int(s),f) for s,f in protected_chart['frets'].items())))]
                    # 吉他器乐低把位与指型复用：修改，原仅判断器乐保留；先守住真实唱段的原图式。
                    # if instrumental and group:
                    elif instrumental and group:
                        bases = [(node['base_id'], node['base'])] if old_capo==capo else []
                        bases += [(None, ())] + anchors.get(tick//bar, [])
                        # 吉他器乐低把位与指型复用：新增局部持握候选，实际用过的手指可在拨其它弦时继续保持。
                        retained=tuple(sorted({s:f+old_capo-capo for unit in node['fingers'] for s,f in unit}.items()))
                        if retained and all(f>0 for _,f in retained):
                            bases.append((None,retained))
                    elif not instrumental:
                        chart = next((d for d in arrangement.get('fingering_diagrams', [])
                                      if d['start_tick']<=tick<d['end_tick']), None)
                        bases = [(chart.get('common_grip_id'), tuple(sorted((int(s), f) for s, f in chart['frets'].items())))] if chart and active else [(None, ())]
                    else:
                        bases = [(node['base_id'], node['base'])] if active else [(None, ())]
                    for base_id, base in dict.fromkeys(bases):
                        effective = dict(base); effective.update(current_frets)
                        geometry = tuple(sorted(effective.items())); units = units_for(geometry)
                        if units is None:
                            continue
                        sustained = tuple(sorted((s, pitch-TUNING[s]-capo) for s, _, pitch, _ in held.values()
                                                 if pitch-TUNING[s]-capo>0))
                        # 吉他器乐低把位与指型复用：新增跨夹位以实体品数保持手指，夹位变更不伪称原相对品位不动。
                        previous_fingers = tuple(tuple((s, f+old_capo-capo) for s, f in unit)
                                                 for unit in node['fingers'])
                        # 吉他器乐低把位与指型复用：修改，旧只允许最省指的瞬时握法保留；持续音需要可保持的分指方案。
                        # transition = finger_transition(previous_fingers, units, sustained)
                        transitions=[v for candidate in unit_candidates(geometry)
                                     if (v:=finger_transition(previous_fingers,candidate,sustained)) is not None]
                        transition=min(transitions,key=lambda v:(v[1],sum(bool(u) for u in v[0]),v[0])) if transitions else None
                        if transition is None:
                            continue
                        # 保音持续按弦与整句八度衔接：修改旧单一按指分配为多结构候选；下方逐行注释保留原实现。
                        #                         fingers, changed = transition
                        #                         positive = [f for f in effective.values() if f>0]
                        #                         allowed = tuple(range(max(1, max(positive, default=1)-5), min(positive, default=20)+1))
                        #                         positions = set(allowed)
                        #                         if not instrumental and active:
                        #                             positions &= {target_old}
                        #                         elif not positive:
                        #                             positions &= {1, node['position'], target_old}
                        #                         if not positions:
                        #                             continue
                        #                         # 器乐合理分句与十二品硬限制：修改，旧偏好初始化保留；低品计数只计本次实际器乐拨音。
                        #                         # preference = 0.
                        #                         preference = 0.; above_four = 0
                        #                         for note, loc in zip(group, values):
                        #                             if note['id'] not in editable:
                        #                                 continue
                        #                             _, fret, _, octaves = loc
                        #                             weight = 2. if note['role']=='instrumental_melody' else 1.
                        #                             # 器乐合理分句与十二品硬限制：新增低品优先目标，旋律与关键伴奏都纳入。
                        #                             above_four += int(fret > 4)
                        #                             preference += weight * (.025*fret + .7*max(0, fret-4) + 8*max(0, fret-12))
                        #                             preference += .14*abs(octaves)/12
                        #                             if base:
                        #                                 preference += 1.4*weight*(dict(base).get(loc[0])!=fret)
                        #                             if note['id'] in preferences and loc[:2]!=preferences[note['id']]:
                        #                                 preference += 4.
                        #                         if group and instrumental:
                        #                             preference += .4*changed + 2.*max(0, changed-2)
                        #                             # 吉他器乐低把位与指型复用：修改，保留旧元数据变化计费；按指没动的局部持握不罚一次换型。
                        #                             # if base != node['base']:
                        #                             if base != node['base'] and changed:
                        #                                 preference += .6 + (1.2 if previous_tick is not None and tick//bar==previous_tick//bar else 0.)
                        #                             if base_id in entries:
                        #                                 preference += .04*entries[base_id]['priority'] + .06*max(f for _,f in base)
                        #                         # 吉他器乐低把位与指型复用：修改，旧累计整首历史会挤掉当前句的可行八度，保留原式。
                        #                         # shifts = dict(node['shifts'])
                        #                         shifts = {identity: value for identity, value in node['shifts'].items()
                        #                                   if phrase_end[identity] > tick}
                        #                         if local_phrase:
                        #                             shifts[local_phrase['id']] = shift
                        #                         for position in positions:
                        #                             absolute_change = position+capo-node['position']-old_capo
                        #                             if previous_tick is not None and (position+capo-old_capo not in node['allowed'] or
                        #                                                              abs(absolute_change)>POLICY['maximum_position_rate']*seconds+1e-8):
                        #                                 continue
                        #                             cost = node['cost']+preference+.2*abs(absolute_change)+.005*position
                        #                             key = (position, tuple(sorted(active.items())), tuple(sorted(shifts.items())),
                        #                                    base_id, base, fingers)
                        #                             # 器乐合理分句与十二品硬限制：修改，旧只按总代价取最低保留；新版低品数优先，旧版排序不变。
                        #                             # if key not in fresh or cost<fresh[key]['cost']:
                        #                             #     fresh[key] = {'cost': cost, 'position': position, 'allowed': allowed,
                        #                             above_four_cost = node['above_four_cost'] + above_four
                        #                             candidate_key = (above_four_cost, cost) if low_fret_priority else cost
                        #                             if key not in fresh or candidate_key < cost_key(fresh[key]):
                        #                                 fresh[key] = {'cost': cost, 'above_four_cost': above_four_cost, 'position': position, 'allowed': allowed,
                        #                                               'fingers': fingers, 'active': active, 'shifts': shifts,
                        #                                               'base_id': base_id, 'base': base, 'parent': node, 'tick': tick,
                        #                                               'added': added, 'changed_fingers': changed, 'instrumental': instrumental}
                        # 保音持续按弦与整句八度衔接：新增分别保留横按与独立按指；真实历史重放仍只采用原最优分配。
                        transition_options = list(dict.fromkeys(transitions)) if context else [transition]
                        for transition in transition_options:
                            fingers, changed = transition
                            positive = [f for f in effective.values() if f>0]
                            allowed = tuple(range(max(1, max(positive, default=1)-5), min(positive, default=20)+1))
                            positions = set(allowed)
                            if not instrumental and active:
                                positions &= {target_old}
                            elif not positive:
                                positions &= {1, node['position'], target_old}
                            if not positions:
                                continue
                            # 器乐合理分句与十二品硬限制：修改，旧偏好初始化保留；低品计数只计本次实际器乐拨音。
                            # preference = 0.
                            preference = 0.; above_four = 0
                            for note, loc in zip(group, values):
                                if note['id'] not in editable:
                                    continue
                                _, fret, _, octaves = loc
                                weight = 2. if note['role']=='instrumental_melody' else 1.
                                # 器乐合理分句与十二品硬限制：新增低品优先目标，旋律与关键伴奏都纳入。
                                above_four += int(fret > 4)
                                preference += weight * (.025*fret + .7*max(0, fret-4) + 8*max(0, fret-12))
                                preference += .14*abs(octaves)/12
                                if base:
                                    preference += 1.4*weight*(dict(base).get(loc[0])!=fret)
                                if note['id'] in preferences and loc[:2]!=preferences[note['id']]:
                                    preference += 4.
                            if group and instrumental:
                                preference += .4*changed + 2.*max(0, changed-2)
                                # 吉他器乐低把位与指型复用：修改，保留旧元数据变化计费；按指没动的局部持握不罚一次换型。
                                # if base != node['base']:
                                if base != node['base'] and changed:
                                    preference += .6 + (1.2 if previous_tick is not None and tick//bar==previous_tick//bar else 0.)
                                if base_id in entries:
                                    preference += .04*entries[base_id]['priority'] + .06*max(f for _,f in base)
                            # 吉他器乐低把位与指型复用：修改，旧累计整首历史会挤掉当前句的可行八度，保留原式。
                            # shifts = dict(node['shifts'])
                            shifts = {identity: value for identity, value in node['shifts'].items()
                                      if phrase_end[identity] > tick}
                            if local_phrase:
                                shifts[local_phrase['id']] = shift
                            for position in positions:
                                absolute_change = position+capo-node['position']-old_capo
                                # 尾段原声局部补证：修改变调夹已接管全部旧持续按弦时，不再用已释放手指的旧范围锁手；实际新握法、换把速度及12品仍逐项验证。
                                # if previous_tick is not None and (position+capo-old_capo not in node['allowed'] or
                                #                                  abs(absolute_change)>POLICY['maximum_position_rate']*seconds+1e-8):
                                covered_hold=(arrangement['configuration'].get('capo_covered_hold_transition_version')==1
                                              and old_capo!=capo and bool(held) and not sustained)
                                if previous_tick is not None and ((not covered_hold and position+capo-old_capo not in node['allowed']) or
                                                                 abs(absolute_change)>POLICY['maximum_position_rate']*seconds+1e-8):
                                    continue
                                cost = node['cost']+preference+.2*abs(absolute_change)+.005*position
                                key = (position, tuple(sorted(active.items())), tuple(sorted(shifts.items())),
                                       base_id, base, fingers)
                                # 器乐合理分句与十二品硬限制：修改，旧只按总代价取最低保留；新版低品数优先，旧版排序不变。
                                # if key not in fresh or cost<fresh[key]['cost']:
                                #     fresh[key] = {'cost': cost, 'position': position, 'allowed': allowed,
                                above_four_cost = node['above_four_cost'] + above_four
                                candidate_key = (above_four_cost, cost) if low_fret_priority else cost
                                if key not in fresh or candidate_key < cost_key(fresh[key]):
                                    fresh[key] = {'cost': cost, 'above_four_cost': above_four_cost, 'position': position, 'allowed': allowed,
                                                  'fingers': fingers, 'active': active, 'shifts': shifts,
                                                  'base_id': base_id, 'base': base, 'parent': node, 'tick': tick,
                                                  'added': added, 'changed_fingers': changed, 'instrumental': instrumental}
        if not fresh:
            # 保音持续按弦与整句八度衔接：新增失败窗口回看，原音符与延音保持；预算用尽仍严格停止。
            if context:
                restarted = context.recover(index, nodes)
                if restarted:
                    index, nodes, previous_tick = restarted
                    continue
            # 吉他器乐低把位与指型复用：修改，旧只记录失败时间保留；增加可复查的音区／持续状态摘要。
            # return None, {'failed_tick': tick, 'maximum_fret': maximum_fret, 'beam_width': width}
            # 保音持续按弦与整句八度衔接：修改失败返回，旧字典内容保留；补充实际局部重规划证据。
            # return None, {'failed_tick': tick, 'maximum_fret': maximum_fret, 'beam_width': width,
            failure = {'failed_tick': tick, 'maximum_fret': maximum_fret, 'beam_width': width,
                          'retained_octaves': dict(Counter(str(tuple(sorted(n['shifts'].items()))) for n in nodes)),
                          'candidate_groups': {str(k): len(v) for k, v in group_cache.items() if k[0]==tick},
                          'previous_states': [{'position':n['position'],'active':n['active'],'fingers':n['fingers']}
                                              for n in nodes[:2]]}
            if context:
                failure['sustained_search'] = context.report()
            return None, failure
        # 吉他器乐低把位与指型复用：新增按音区分层保留候选，局部低价不能提前剪掉整句可行的另一八度。
        # 器乐合理分句与十二品硬限制：修改，旧排序保留；统一按当前版本的低品优先级剪枝。
        # ranked = sorted(fresh.values(), key=lambda n: n['cost'])
        ranked = sorted(fresh.values(), key=cost_key)
        strata = defaultdict(list)
        for candidate in ranked:
            strata[tuple(sorted(candidate['shifts'].items()))].append(candidate)
        # 吉他器乐低把位与指型复用：修改，旧只按八度留最低价会丢掉提前准备的高／中手位，保留原式。
        # reserved = [candidate for candidates in strata.values() for candidate in candidates[:max(2, width//max(1,len(strata))//2)]]
        reserved = []
        for candidates in strata.values():
            positions_seen=set()
            for candidate in candidates:
                if candidate['position'] not in positions_seen:
                    reserved.append(candidate); positions_seen.add(candidate['position'])
        used = {id(n) for n in reserved}
        # 吉他器乐低把位与指型复用：修改，原按总代价二次裁剪会取消分层保留；只在宽度内填充其余候选。
        # nodes = sorted(reserved + [n for n in ranked if id(n) not in used][:max(0,width-len(reserved))], key=lambda n:n['cost'])[:width]
        nodes = reserved[:width] + [n for n in ranked if id(n) not in used][:max(0,width-len(reserved))]
        # 保音持续按弦与整句八度衔接：新增不同持续用弦／按指优先保留，历史剪枝仍用于旧来源重放。
        if context:
            nodes = context.select(ranked, index)
        previous_tick = tick
        index += 1
    if not ticks:
        return [], {'maximum_fret': maximum_fret, 'beam_width': width}
    # 器乐合理分句与十二品硬限制：修改，旧获胜排序保留；新结果继续低品优先，不能末尾改回总代价。
    # winner = min(nodes, key=lambda n:n['cost']); path=[]
    winner = min(nodes, key=cost_key); path=[]
    while winner['tick'] is not None:
        path.append(winner); winner=winner['parent']
    path.reverse()
    # 保音持续按弦与整句八度衔接：修改返回报告，原结构保留；仅新版增加实际搜索证据。
    # return path, {'maximum_fret': maximum_fret, 'beam_width': width, 'cost': path[-1]['cost']}
    report = {'maximum_fret': maximum_fret, 'beam_width': width, 'cost': path[-1]['cost']}
    if context:
        report['sustained_search'] = context.report()
    return path, report


# 吉他器乐低把位与指型复用：新增真实重复动机的前次指法软参考，不强行复制不兼容的和声／夹位。
def repeated_preferences(phrases, path, notes, arrangement):
    locations_by_id = {identity: value for row in path for identity,value in row['added'].items()}
    note_map = {n['id']:n for n in notes}; seen = {}; preferences={}; groups=[]
    for phrase in phrases:
        ids=phrase['note_ids']; capos=tuple(capo_at(arrangement,note_map[i]['start_tick']) for i in ids)
        pcs=tuple(note_map[i]['pitch_midi']%12 for i in ids)
        key=(phrase['signature'], capos, pcs)
        if key in seen:
            first=seen[key]
            preferences.update({identity:locations_by_id[old][:2] for identity,old in zip(ids,first['note_ids'])})
            groups.append({'prototype_phrase_id':first['id'],'phrase_id':phrase['id']})
        else:
            seen[key]=phrase
    return preferences, groups


# 吉他器乐低把位与指型复用：新增只读统计，分别衡量低品、实际动指与源音符保留。
def fret_statistics(notes, editable):
    chosen=[n for n in notes if n['id'] in editable]
    return {'note_count':len(chosen),'roles':dict(Counter(n['role'] for n in chosen)),
            'within_four':sum(n['fret']<=4 for n in chosen),
            'five_to_twelve':sum(4<n['fret']<=12 for n in chosen),
            'above_twelve':sum(n['fret']>12 for n in chosen),
            'maximum_fret':max((n['fret'] for n in chosen),default=0),
            'within_four_fraction':sum(n['fret']<=4 for n in chosen)/max(1,len(chosen))}


# 吉他器乐低把位与指型复用：新增源音区保护入口；所有派生可确定性重建，普通编辑不会重复降八度。
# 器乐合理分句与十二品硬限制：修改，旧签名保留；历史版本参数仅供验证真实旧来源，默认一律新硬限制。
# def arrange_instrumental_register(shared, vocal, arrangement):
# 保音持续按弦与整句八度衔接：修改新规划及历史重放分开版本，旧派生不被新版指法替换。
# def arrange_instrumental_register(shared, vocal, arrangement, replay_version=None):
def arrange_instrumental_register(shared, vocal, arrangement, replay_version=None, search_version=None):
    if arrangement['instrument']!='guitar':
        raise ValueError('低把位器乐策略仅用于吉他。')
    # 吉他器乐低把位与指型复用：新增只读取实际共同和声，正常唱段计划及声学原分析不改写。
    shared=register_shared_view(shared,vocal)
    # 吉他器乐低把位与指型复用：新增幂等保护，明确重导不会以新音高再次当源音降低八度。
    if arrangement.get('instrumental_register'):
        checked=validate_instrumental_register(shared,vocal,arrangement)
        if not checked['valid']:
            raise ValueError('不能重用已改变的器乐派生：'+str(checked['errors'][:6]))
        return deepcopy(arrangement),deepcopy(arrangement['instrumental_register']['report'])
    result=deepcopy(arrangement); source=deepcopy(arrangement['notes']); editable=editable_notes(shared,arrangement)
    # 器乐合理分句与十二品硬限制：新增策略版本分离，普通新规划不得凭旧配置请求高品回退。
    version = 2 if replay_version is None else replay_version
    if version not in (1, 2):
        raise ValueError('未知器乐音区规划版本。')
    policy = POLICY if version == 1 else STRICT_POLICY
    # 保音持续按弦与整句八度衔接：新增默认新规划用新版；历史来源明确重放时仍按原搜索，版本进入可验证账本。
    search_version = (2 if replay_version is None else 1) if search_version is None else search_version
    if search_version not in (1, 2) or version == 1 and search_version != 1:
        raise ValueError('器乐音区与持续用弦搜索版本不相容。')
    # 吉他器乐低把位与指型复用：新增无器乐时完全保持旧工程，不能为了空策略改变普通伴奏派生数据。
    if not editable:
        stats=fret_statistics(source,editable)
        return result,{'valid':True,'applied':False,'before':stats,'after':deepcopy(stats),
                       # 器乐合理分句与十二品硬限制：修改，旧空结果策略保留；按本次版本报告但不改变无器乐工程。
                       # 'protected_normal_notes':len(source),'policy':deepcopy(POLICY)}
                       'protected_normal_notes':len(source),'policy':deepcopy(policy)}
    phrases=melodic_phrases(shared,source,editable)
    # 器乐合理分句与十二品硬限制：新增整句域与最少自然分句；有合法原句时不为了降每个音任意切分。
    phrase_plan = None
    if version == 2:
        from instrumental_phrase_register import plan_phrases
        # 保音持续按弦与整句八度衔接：修改新原音高请求共用完整八度域，旧来源重放仍保留原固定候选。
        # phrases, phrase_plan = plan_phrases(shared, arrangement, editable, phrases)
        from guitar_register_search import source_octave_candidates
        octave_domain = source_octave_candidates(arrangement) if search_version == 2 else None
        phrases, phrase_plan = plan_phrases(shared, arrangement, editable, phrases, octave_candidates=octave_domain)
    path=None; attempts=[]
    # 器乐合理分句与十二品硬限制：修改，旧20品回退仅保留历史重放；新策略先4品、再12品，失败就停止。
    # for maximum,width in ((12,POLICY['beam_width']),(12,POLICY['expanded_beam_width']),
    #                       (20,POLICY['expanded_beam_width'])):
    #     path,attempt=solve_path(shared,vocal,arrangement,editable,phrases,maximum,width)
    limits = ((12,48),(12,144),(20,144)) if version == 1 else ((4,48),(12,48),(12,144))
    for maximum,width in limits:
        # 保音持续按弦与整句八度衔接：修改调用，新搜索继承同一十二品和乐句约束；原调用保留。
        # path,attempt=solve_path(shared,vocal,arrangement,editable,phrases,maximum,width,
        #                         low_fret_priority=version == 2)
        path,attempt=solve_path(shared,vocal,arrangement,editable,phrases,maximum,width,
                                low_fret_priority=version == 2, search_version=search_version)
        attempts.append(attempt)
        if path is not None:
            break
    if path is None:
        # 器乐合理分句与十二品硬限制：修改，旧泛化错误保留；明确12品失败不会放宽演奏／品位限制。
        # raise ValueError('保留全部器乐声部和持续音的低把位规划未找到可行路径：'+str(attempts))
        raise ValueError('保留全部器乐声部和持续音的低把位规划未找到可行路径；不会自动放宽十二品上限：'+str(attempts))
    preferences, repeats=repeated_preferences(phrases,path,source,arrangement)
    if preferences:
        reused,_=solve_path(shared,vocal,arrangement,editable,phrases,attempts[-1]['maximum_fret'],
                            # 器乐合理分句与十二品硬限制：修改，旧重复偏好调用尾保留；复用手型也服从相同低品优先级。
                            # attempts[-1]['beam_width'],preferences)
                            # 保音持续按弦与整句八度衔接：修改复用搜索同样前瞻，原调用尾保留。
                            # attempts[-1]['beam_width'],preferences,low_fret_priority=version == 2)
                            attempts[-1]['beam_width'],preferences,low_fret_priority=version == 2,search_version=search_version)
        if reused is not None:
            # 器乐合理分句与十二品硬限制：修改，旧无条件接受复用保留；不能以更多高于4品音换手型统一。
            # path=reused
            if version == 1 or reused[-1]['above_four_cost'] <= path[-1]['above_four_cost']:
                path=reused
    by_id={n['id']:n for n in result['notes']}; phrase_by_id={identity:p['id'] for p in phrases for identity in p['note_ids']}
    audit=[]; decisions=[]; positions=[]
    for row in path:
        positions.append({'tick':row['tick'],'position':row['position']})
        if row['instrumental']:
            decisions.append({'tick':row['tick'],'position':row['position'],
                              'base_grip_id':row['base_id'],'base_frets':dict(row['base']),
                              'finger_units':[list(unit) for unit in row['fingers']],
                              'changed_fingers':row['changed_fingers']})
        for identity,(string,fret,pitch,shift) in row['added'].items():
            if identity not in editable:
                continue
            note=by_id[identity]; old=deepcopy(note)
            finger=next((i+1 for i,u in enumerate(row['fingers']) if (string,fret) in u),0)
            note.update(pitch_midi=pitch,string=string,fret=fret,finger=finger,hand_position=row['position'],
                        instrumental_register_source_pitch_midi=old['pitch_midi'],
                        instrumental_register_octave_shift=shift,
                        instrumental_register_phrase_id=phrase_by_id.get(identity))
            if any(old.get(k)!=note.get(k) for k in ALLOWED_FIELDS):
                audit.append({'type':'instrumental_register_and_grip','note_id':identity,
                              'source_pitch_midi':old['pitch_midi'],'pitch_midi':pitch,'octave_shift':shift,
                              'original_string':old['string'],'original_fret':old['fret'],
                              'string':string,'fret':fret,'phrase_id':phrase_by_id.get(identity)})
    result['hand_positions']=positions
    # 吉他器乐低把位与指型复用：新增仅清除已过期绘图派生数据；正常唱段音符及保护来源账本保留。
    for field in ('fingering_diagrams','notation_regions','exact_pitch_refingering','grip_hand_positions',
                  'grip_fingerings','tab_display','rhythm_display','time_alignment_display'):
        result.pop(field,None)
    # 器乐合理分句与十二品硬限制：修改，旧策略存储保留；新版明确保存硬限制与规划版本。
    # result['configuration']['instrumental_register_policy']=deepcopy(POLICY)
    result['configuration']['instrumental_register_policy']=deepcopy(policy)
    if version == 2:
        result['configuration']['instrumental_register_strategy_version'] = 2
    result['adjustments'].extend(audit)
    after={n['id']:n for n in result['notes']}
    for old in source:
        current=after[old['id']]
        if old['id'] not in editable and old!=current:
            raise ValueError('器乐低把位规划改变了正常唱段。')
        if any(old.get(k)!=current.get(k) for k in old if k not in ALLOWED_FIELDS):
            raise ValueError('器乐低把位规划改变了来源、拍位或声部。')
    playable=validate_playability(result,SongClock(vocal))
    if not playable['valid']:
        raise ValueError('器乐低把位实际持续音／换把核验失败：'+str(playable['errors'][:8]))
    for phrase in phrases:
        shifts={after[i]['instrumental_register_octave_shift'] for i in phrase['note_ids']}
        if len(shifts)!=1:
            raise ValueError('连续旋律内部出现了逐音八度跳变。')
        phrase['octave_shift']=next(iter(shifts))
    # 吉他器乐低把位与指型复用：修改，旧报告入口保留；明确记录是否实际应用策略。
    # report={'valid':True,'policy':deepcopy(POLICY),'before':fret_statistics(source,editable),
    # 器乐合理分句与十二品硬限制：修改，旧报告策略保留；按真实规划版本记录。
    # report={'valid':True,'applied':True,'policy':deepcopy(POLICY),'before':fret_statistics(source,editable),
    report={'valid':True,'applied':True,'policy':deepcopy(policy),'before':fret_statistics(source,editable),
            'after':fret_statistics(result['notes'],editable),'attempts':attempts,'phrases':phrases,
            'repeated_motifs':repeats,'decisions':decisions,'changes':audit,'playability':playable,
            'all_note_ids_roles_pitch_classes_and_times_preserved':True,
            'protected_normal_notes':len(source)-len(editable),
            'above_twelve_exceptions':[n['id'] for n in result['notes'] if n['id'] in editable and n['fret']>12]}
    # 器乐合理分句与十二品硬限制：修改，旧派生版本保留；新版分句域和12品断言进入来源报告。
    # result['instrumental_register']={'version':1,'policy':deepcopy(POLICY),
    if version == 2:
        if report['after']['above_twelve']:
            raise ValueError('器乐规划结果超过十二品，拒绝交付。')
        report['phrase_plan'] = phrase_plan
        report['hard_fret_limit_passed'] = True
        # 器乐合理分句与十二品硬限制：新增来源恢复摘要也由种子确定重放，不能仅在CLI运行时修改报告。
        if arrangement.get('instrumental_register_upgrade_source'):
            report['upgrade_source'] = deepcopy(arrangement['instrumental_register_upgrade_source'])
    result['instrumental_register']={'version':version,'policy':deepcopy(policy),
                                     'source_notes':source,'source_notes_sha256':fingerprint(source),
                                     'editable_note_ids':sorted(editable),'report':report,
                                     'result_notes_sha256':fingerprint(result['notes'])}
    # 保音持续按弦与整句八度衔接：新增明确搜索来源标记，旧工程没有字段时只使用原算法重放。
    if search_version != 1:
        from guitar_register_search import SEARCH_POLICY
        report['search_version'] = search_version
        report['search_policy'] = deepcopy(SEARCH_POLICY)
        result['instrumental_register']['search_version'] = search_version
        result['instrumental_register']['search_policy'] = deepcopy(SEARCH_POLICY)
        # 保音持续按弦与整句八度衔接：新增原音高请求实际候选账本，绑定最初来源，不能逐阶段累加下降。
        if arrangement['configuration'].get('source_register_input_version') == 2:
            report['source_octave_candidates'] = list(octave_domain)
            result['instrumental_register']['source_octave_candidates'] = list(octave_domain)
    # 原曲拍轴与歌词拍位通用修复：新增明确候选版本，旧版本不新增字段；新版配音也进入来源重放与报告。
    voicing_version=arrangement['configuration'].get('instrumental_register_voicing_version',1)
    if voicing_version!=1:
        report['voicing_version']=voicing_version
        result['instrumental_register']['voicing_version']=voicing_version
    # 吉他器乐低把位与指型复用：新增已认可唱段图式／按指缓存快照，器乐新增图不得重编号或替换唱段图。
    result['instrumental_register']['source_fingering_diagrams']=deepcopy(arrangement.get('fingering_diagrams',[]))
    result['instrumental_register']['source_notation_regions']=deepcopy(arrangement.get('notation_regions',[]))
    result['instrumental_register']['source_grip_fingerings']=deepcopy(arrangement.get('grip_fingerings',{}))
    return result, report


# 吉他器乐低把位与指型复用：新增明确来源文件绑定，历史升级必须来自仍有相同SHA的认可工程。
def bind_register_source(arrangement, source_path, shared, vocal):
    metadata=arrangement['instrumental_register']; metadata['source_path']=str(Path(source_path).resolve())
    metadata['source_sha256']=sha256(source_path)
    # 吉他器乐低把位与指型复用：修改，保留原整字典指纹；规范实际视图不受导出标志差异影响。
    # metadata['shared_sha256']=fingerprint(shared); metadata['vocal_sha256']=fingerprint(vocal)
    metadata['shared_sha256']=fingerprint(register_shared_view(shared,vocal)); metadata['vocal_sha256']=fingerprint(vocal)


# 吉他器乐低把位与指型复用：新增严格原始账本衔接，仅允许绑定来源中授权器乐音的确定派生字段。
def projected_source_note(source, arrangement):
    # 器乐低弦分解填充：新增真实派生链投影；旧器乐八度层先在绑定输入核查，尾部仅接受可重放同音重拨。
    if arrangement.get('instrumental_flow'):
        from guitar_instrumental_flow import flow_parent
        parent=flow_parent(arrangement)['arrangements']['guitar']
        expected=projected_source_note(source,parent)
        release=next((r for r in arrangement['instrumental_flow']['report']['release_adjustments']
                      if r['note_id']==expected['id'] and r['original_end_tick']==expected['end_tick']),None)
        return {**expected,'end_tick':release['end_tick']} if release else expected
    # 原曲器乐旋律骨干重提取：新增来源链衔接，旧低音／和声可先经过上轮八度派生，再接受本轮指型规划。
    if arrangement.get('instrumental_source_backbone'):
        from instrumental_source_melody import source_parent
        try:
            parent=source_parent(arrangement)
            source=projected_source_note(source,parent['arrangements']['guitar'])
        except (OSError,KeyError,ValueError):
            return source
    metadata=arrangement.get('instrumental_register')
    if not metadata or source['id'] not in metadata.get('editable_note_ids',[]):
        return source
    before=next((n for n in metadata['source_notes'] if n['id']==source['id']),None)
    current=next((n for n in arrangement['notes'] if n['id']==source['id']),None)
    if before is None or current is None or any(source.get(k)!=before.get(k) for k in
                                               ('pitch_midi','string','fret','start_tick','end_tick','role')):
        return source
    return {**source,**{k:current[k] for k in ALLOWED_FIELDS if k in current}}


# 吉他器乐低把位与指型复用：新增来源／保护／八度／实际演奏验证，重导不得接受篡改的音乐快照。
def validate_instrumental_register(shared, vocal, arrangement, replay=False):
    # 原声覆盖与选音归属通用修复：新增认可段落来源分层；实际12品／持续音可弹性仍另行检查。
    if arrangement.get('approved_section_preservation'):
        from approved_music_sections import validate_chain
        return validate_chain(shared,vocal,arrangement,replay,validate_instrumental_register)
    # 器乐背景休止与旋律突出：新增旧音区／手型在绑定上游核查，表现层允许范围另行完整重放。
    if arrangement.get('instrumental_expression'):
        from guitar_instrumental_expression import validate_expression_chain
        return validate_expression_chain(shared,vocal,arrangement,replay,validate_instrumental_register)
    # 器乐低弦分解填充：新增分层严格核验，不能把新增填音当成原低把位音符或关闭集合保护。
    if arrangement.get('instrumental_flow'):
        from guitar_instrumental_flow import flow_parent,validate_flow
        try:
            parent=flow_parent(arrangement)['arrangements']['guitar']
            upstream=validate_instrumental_register(shared,vocal,parent,replay=replay)
            current=validate_flow(shared,vocal,arrangement,replay=replay)
            errors=(upstream or {}).get('errors',[])+current['errors']
            return {'valid':not errors,'errors':errors,'flow':current,'upstream_register':upstream}
        except (OSError,KeyError,ValueError) as exc:
            return {'valid':False,'errors':['instrumental_flow_register_binding_invalid:'+str(exc)]}
    info=arrangement.get('instrumental_register')
    if not info:
        return None
    # 器乐乐句和声视图统一通用修复：新增与实际规划入口相同的最终和声视图，原声分析仍保存；不能用重配前和声误判乐句数。
    # 器乐乐句和声视图统一通用修复：修改原地替换视图的新增语句并保留；绑定／重放继续核原shared，分句仅用规范副本。
    # shared=register_shared_view(shared,vocal)
    planning_shared=register_shared_view(shared,vocal)
    errors=[]; originals=info.get('source_notes',[]); source={n['id']:n for n in originals}
    # 器乐乐句和声视图统一通用修复：修改范围取值，原式保留；与规划入口使用同一来源视图。
    # actual={n['id']:n for n in arrangement['notes']}; editable=editable_notes(shared,{'notes':originals})
    actual={n['id']:n for n in arrangement['notes']}; editable=editable_notes(planning_shared,{'notes':originals})
    # 器乐合理分句与十二品硬限制：修改，旧仅一个策略保留；历史来源按旧版验证，新版有独立强约束。
    # if info.get('version')!=1 or info.get('policy')!=POLICY:
    version = info.get('version')
    policy = POLICY if version == 1 else STRICT_POLICY if version == 2 else None
    if policy is None or info.get('policy') != policy:
        errors.append('unknown_instrumental_register_policy')
    # 器乐合理分句与十二品硬限制：新增绑定实际结果策略；修改版本或删除12品策略不能绕过验证。
    if version == 2:
        if (arrangement['configuration'].get('instrumental_register_strategy_version') != 2 or
                arrangement['configuration'].get('instrumental_register_policy') != STRICT_POLICY):
            errors.append('instrumental_register_strict_policy_changed')
        if any(n['fret'] > 12 for n in arrangement['notes'] if n['id'] in editable):
            errors.append('instrumental_register_above_twelve')
    # 原曲拍轴与歌词拍位通用修复：新增实际搜索版本核验，不能只改配置让旧派生自动获得新候选许可。
    voicing_version=arrangement['configuration'].get('instrumental_register_voicing_version',1)
    if voicing_version not in (1,2) or info.get('voicing_version',1)!=voicing_version:
        errors.append('instrumental_register_voicing_version_changed')
    # 保音持续按弦与整句八度衔接：新增实际搜索版本校验，不能给旧产物贴标签冒充新版执行。
    from guitar_register_search import SEARCH_POLICY
    search_version = info.get('search_version', 1)
    if search_version not in (1, 2) or (search_version == 2 and
            (info.get('search_policy') != SEARCH_POLICY or info.get('report', {}).get('search_policy') != SEARCH_POLICY or
             info.get('report', {}).get('search_version') != 2)):
        errors.append('instrumental_register_search_policy_changed')
    # 保音持续按弦与整句八度衔接：新增从真实原音高重算八度域，删除来源字段或换策略都会使新验收失效。
    from guitar_register_search import source_octave_candidates
    octave_domain = source_octave_candidates(arrangement, originals) if search_version == 2 else tuple(POLICY['melody_octave_candidates'])
    if arrangement['configuration'].get('source_register_input_version') == 2 or info.get('source_octave_candidates'):
        if info.get('source_octave_candidates') != list(octave_domain) or info.get('report', {}).get('source_octave_candidates') != list(octave_domain):
            errors.append('instrumental_register_source_octave_domain_changed')
    if info.get('source_notes_sha256')!=fingerprint(originals) or info.get('result_notes_sha256')!=fingerprint(arrangement['notes']):
        errors.append('instrumental_register_music_fingerprint_changed')
    if sorted(editable)!=info.get('editable_note_ids') or set(source)!=set(actual):
        errors.append('instrumental_register_note_identity_or_scope_changed')
    for identity,old in source.items():
        current=actual.get(identity)
        if current is None:
            continue
        if identity not in editable and current!=old:
            errors.append('protected_normal_note_changed:'+identity)
        if identity in editable:
            if any(old.get(k)!=current.get(k) for k in old if k not in ALLOWED_FIELDS):
                errors.append('instrumental_source_time_or_voice_changed:'+identity)
            shift=current['pitch_midi']-old['pitch_midi']
            # 原曲拍轴与歌词拍位通用修复：修改，旧所有声部仅下降校验保留；新版仅伴奏声部可上移，旋律保持整句原候选。
            # if shift not in POLICY['melody_octave_candidates'] or current.get('instrumental_register_octave_shift')!=shift:
            # 保音持续按弦与整句八度衔接：修改原音高旋律按完整下降域校验，伴奏仍按原可用八度，不放宽十二品。
            # allowed_shifts=tuple(POLICY['melody_octave_candidates'])+((12,) if voicing_version==2 and old['role']!='instrumental_melody' else ())
            allowed_shifts=tuple(octave_domain if old['role']=='instrumental_melody' else POLICY['melody_octave_candidates'])+((12,) if voicing_version==2 and old['role']!='instrumental_melody' else ())
            if shift not in allowed_shifts or current.get('instrumental_register_octave_shift')!=shift:
                errors.append('instrumental_non_octave_or_upward_change:'+identity)
    # 器乐合理分句与十二品硬限制：修改，旧原句直接校验保留；新版重新计算合理边界，不接受人工逐音换八度。
    # for phrase in melodic_phrases(shared,originals,editable):
    # 器乐乐句和声视图统一通用修复：修改分句核查视图，原调用保留；原分析和最终和声不混用。
    # checked_phrases = melodic_phrases(shared,originals,editable)
    checked_phrases = melodic_phrases(planning_shared,originals,editable)
    if version == 2:
        from instrumental_phrase_register import plan_phrases
        try:
            # 器乐乐句和声视图统一通用修复：修改八度句域的核查视图，原调用保留；候选、12品和持续音门槛不变。
            # checked_phrases, phrase_plan = plan_phrases(shared, {**arrangement, 'notes': originals},
            # 保音持续按弦与整句八度衔接：修改来源重验共用同一整句域，原调用保留。
            # checked_phrases, phrase_plan = plan_phrases(planning_shared, {**arrangement, 'notes': originals},
            #                                           editable, checked_phrases)
            checked_phrases, phrase_plan = plan_phrases(planning_shared, {**arrangement, 'notes': originals},
                                                      editable, checked_phrases, octave_candidates=octave_domain)
            if fingerprint(phrase_plan) != fingerprint(info.get('report', {}).get('phrase_plan')):
                errors.append('instrumental_register_phrase_plan_changed')
        except (KeyError, ValueError) as exc:
            errors.append('instrumental_register_phrase_plan_invalid:' + str(exc))
    for phrase in checked_phrases:
        if len({actual[i]['pitch_midi']-source[i]['pitch_midi'] for i in phrase['note_ids'] if i in actual})!=1:
            errors.append('instrumental_melody_contour_changed:'+phrase['id'])
    seed=None
    # 吉他器乐低把位与指型复用：新增严格重放要求真实文件来源，不能删除绑定后接受手工快照。
    if replay and not info.get('source_path'):
        errors.append('instrumental_register_missing_bound_source')
    if info.get('source_path'):
        path=Path(info['source_path'])
        if not local_path(path).is_file() or sha256(path)!=info.get('source_sha256'):
            errors.append('instrumental_register_bound_source_changed')
        else:
            seed=read_json(path)
            # 器乐合理分句与十二品硬限制：新增新版规划与真实来源配置绑定；旧文件未标版本时只按其历史账本重放。
            if seed['arrangements']['guitar']['configuration'].get('instrumental_register_strategy_version',version) != version:
                errors.append('instrumental_register_bound_strategy_version_changed')
            # 原曲拍轴与歌词拍位通用修复：新增版本与真实上游种子绑定，旧缓存不能被另指定新版候选重解。
            if seed['arrangements']['guitar']['configuration'].get('instrumental_register_voicing_version',1)!=voicing_version:
                errors.append('instrumental_register_bound_voicing_version_changed')
            if seed['arrangements']['guitar']['notes']!=originals:
                errors.append('instrumental_register_source_snapshot_differs_from_bound_file')
            # 吉他器乐低把位与指型复用：新增图式／手指来源也必须与真实缓存一致，不能另造唱段按法。
            for stored,original,default in (('source_fingering_diagrams','fingering_diagrams',[]),
                                             ('source_notation_regions','notation_regions',[]),
                                             ('source_grip_fingerings','grip_fingerings',{})):
                if info.get(stored,default)!=seed['arrangements']['guitar'].get(original,default):
                    errors.append('instrumental_register_fingering_source_changed:'+stored)
            # 吉他器乐低把位与指型复用：修改，旧原视图直接比较保留；两端使用同一实际和声视图。
            # if fingerprint(seed['shared_analysis'])!=info.get('shared_sha256') or fingerprint(shared)!=info.get('shared_sha256'):
            if fingerprint(register_shared_view(seed['shared_analysis'],seed['accepted_vocal_project']))!=info.get('shared_sha256') or fingerprint(register_shared_view(shared,vocal))!=info.get('shared_sha256'):
                errors.append('instrumental_register_shared_source_changed')
            if fingerprint(seed['accepted_vocal_project'])!=info.get('vocal_sha256') or fingerprint(vocal)!=info.get('vocal_sha256'):
                errors.append('instrumental_register_vocal_source_changed')
    # 吉他器乐低把位与指型复用：新增认可工程上游绑定，纯吉他升级的缓存快照须与真实旧交付相同。
    if info.get('upstream_project'):
        upstream=Path(info['upstream_project'])
        if not local_path(upstream).is_file() or sha256(upstream)!=info.get('upstream_project_sha256'):
            errors.append('instrumental_register_upstream_project_changed')
        elif info.get('upstream_exact_notes'):
            parent=read_json(upstream)
            if parent['arrangements']['guitar']['notes']!=originals:
                errors.append('instrumental_register_seed_differs_from_accepted_notes')
    if replay and seed is not None and not errors:
        # 器乐合理分句与十二品硬限制：修改，旧默认重放保留；旧20品历史只读重放，不能套新版改写认可音乐。
        # rebuilt,_=arrange_instrumental_register(shared,vocal,seed['arrangements']['guitar'])
        # 保音持续按弦与整句八度衔接：修改按真实账本重放搜索；原调用保留，旧版没有新字段仍原样执行。
        # rebuilt,_=arrange_instrumental_register(shared,vocal,seed['arrangements']['guitar'],replay_version=version)
        rebuilt,_=arrange_instrumental_register(shared,vocal,seed['arrangements']['guitar'],replay_version=version,search_version=search_version)
        # 吉他器乐低把位与指型复用：修改，原Python元组／JSON数组比较保留；报告按规范JSON语义重放。
        # if rebuilt['notes']!=arrangement['notes'] or rebuilt['instrumental_register']['report']!=info.get('report'):
        if rebuilt['notes']!=arrangement['notes'] or fingerprint(rebuilt['instrumental_register']['report'])!=fingerprint(info.get('report')):
            errors.append('instrumental_register_deterministic_replay_differs')
    playable=validate_playability(arrangement,SongClock(vocal))
    errors.extend(playable['errors'])
    return {'valid':not errors,'errors':errors,'source_note_count':len(source),
            'protected_normal_notes':len(source)-len(editable),
            'fret_statistics':fret_statistics(arrangement['notes'],editable),'replayed':bool(replay and seed is not None)}


# 器乐合理分句与十二品硬限制：新增最终实际音符检查；填充／绘图／表现之后仍不能交付高于12品器乐音。
def require_instrumental_fret_limit(shared, arrangement):
    editable = editable_notes(shared, arrangement)
    bad = [{'id': n['id'], 'tick': n['start_tick'], 'fret': n['fret']}
           for n in arrangement['notes'] if n['id'] in editable and n['fret'] > 12]
    if bad:
        raise ValueError('器乐最终谱超过十二品，拒绝导出且不会自动放宽：' + str(bad[:8]))
    return {'valid': True, 'hard_maximum_fret': 12,
            'statistics': fret_statistics(arrangement['notes'], editable)}


# 吉他器乐低把位与指型复用：新增器乐准备阶段候选，后续节奏整理前不以高把位原音区锁死可行性。
def prepare_instrumental_register(shared, vocal, arrangement):
    result, report=arrange_instrumental_register(shared,vocal,arrangement)
    for note in result['notes']:
        for field in DERIVED_FIELDS:
            note.pop(field,None)
    result.pop('instrumental_register',None)
    result['configuration'].pop('instrumental_register_policy',None)
    result.setdefault('instrumental_register_preparations',[]).append(report)
    return result
