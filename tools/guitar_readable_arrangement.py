"""吉他既有规则闭环修复：在认可拍轴上整理实音和弦、右手与可共用乐句。"""
# 吉他既有规则闭环修复：新增独立派生编配；不解码音高、不改人声/钢琴/原声和声分析。
from __future__ import annotations

from collections import Counter, defaultdict
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
from workspace_location import local_path
from itertools import combinations

import numpy as np

from accompaniment_analysis import SongClock, chord_name
from accompaniment_arrange import TUNING, grip_info, shape_candidates
from phrase_harmony_plan import arrangement_view
from phrase_harmony_plan import melody_signature, similarity

# 吉他既有规则闭环修复：升级低音逐攻击约束版本；旧策略产物不得幂等绕过本轮原音检查。
# POLICY = {'version': 1, 'minimum_note_ticks': 120, 'minimum_chord_ticks': 480,
POLICY = {'version': 2, 'minimum_note_ticks': 120, 'minimum_chord_ticks': 480,
          'preferred_chords_per_measure': 2, 'maximum_fret': 12,
          'preferred_maximum_fret': 4, 'maximum_instrumental_onset_shift_ticks': 240,
          'common_source_loss_limit': .20, 'whole_song_recognition': False,
          'minimum_clear_bass_mass': .20, 'minimum_changed_bass_relative_support': .25,
          'minimum_existing_bass_relative_support': .65, 'bass_attack_window_seconds': .25,
          'minimum_common_upper_relative_support': .35,
          'minimum_common_upper_above_bass_semitones': 7, 'maximum_common_upper_string': 3,
          'allow_source_supported_noninitial_bass_omission': True}
TASK = '吉他既有规则闭环修复'


def _fingerprint(value):
    # 吉他既有规则闭环修复：新增实际输入/输出签名，旧策略标记不能证明新数据通过。
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(',', ':')).encode('utf8')).hexdigest()


def measure_timeline(vocal):
    # 吉他既有规则闭环修复：新增固定/可变小节共用视图，绝不改写认可拍轴。
    if vocal['timing'].get('measure_timeline'):
        return deepcopy(vocal['timing']['measure_timeline'])
    total, bar = vocal['statistics']['total_ticks'], vocal['statistics']['bar_ticks']
    return [{'number': i + 1, 'start_tick': a, 'end_tick': min(total, a + bar),
             'meter': deepcopy(vocal['timing']['meter']),
             'pickup': i == 0 and vocal['timing'].get('initial_pickup_measure', False)}
            for i, a in enumerate(range(0, total, bar))]


def guitar_shared_view(project):
    # 吉他既有规则闭环修复：新增吉他专用有效和声，原共享分析与钢琴不会被吉他简化覆盖。
    # 吉他既有规则闭环修复：修改派生视图优先级；旧计划在修订入口已验证，导出增加小节视图不能反向伪造旧SHA。
    # shared = arrangement_view(project['shared_analysis'], project['accepted_vocal_project'])
    guitar = project['arrangements']['guitar']
    shared = (project['shared_analysis'] if 'readable_harmony' in guitar else
              arrangement_view(project['shared_analysis'], project['accepted_vocal_project']))
    return {**shared, 'harmony': guitar.get('readable_harmony', shared['harmony']),
            '_phrase_harmony_view': True}


def _identity(chord):
    return (int(chord['root_pc']), chord['quality'], int(chord.get('bass_pc', chord['root_pc'])))


def _overlap(a, b, c, d):
    return max(0, min(b, d) - max(a, c))


def _capo(guitar, tick):
    value = guitar['configuration'].get('capo_fret', 0)
    for row in guitar['configuration'].get('capo_segments', []):
        if row['start_tick'] <= tick < row.get('end_tick', float('inf')):
            value = row['capo_fret']
    return int(value)


class SourceEvidence:
    # 吉他既有规则闭环修复：新增只读来源证据采样，窗口按原音秒取样，旧tick不混入新拍轴。
    def __init__(self, project, features):
        self.shared = project['shared_analysis']
        self.clock = SongClock(project['accepted_vocal_project'])
        self.features = features or {}
        self.cache = {}
        self.bass_cache = {}
        self.original_bass = [n for n in project['arrangements']['guitar']['notes'] if n.get('role') == 'bass']
        # 吉他既有规则闭环修复：新增只读原实音与指型，用于证明共同上声部确实来自既有材料。
        self.original_guitar = project['arrangements']['guitar']
        self.pattern_periods = []

    def at(self, start, end):
        key = (start, end)
        if key in self.cache:
            return self.cache[key]
        a, b = self.clock.seconds(start), self.clock.seconds(end)
        # 吉他既有规则闭环修复：新增负来源秒为空证据，不能把音源0秒首帧外推到未录制的弱起。
        if b <= 0:
            result = {'chroma': np.zeros(12), 'bass': np.zeros(12), 'seconds': [a, b],
                      'available': False, 'source': 'outside_recording'}
            self.cache[key] = result
            return result
        a = max(0., a)
        chroma, bass = np.zeros(12), np.zeros(12)
        energy = 0.
        total = 0.
        for row in self.shared.get('harmony_windows', []):
            weight = _overlap(a, b, row['start_seconds'], row['end_seconds'])
            if weight:
                chroma += weight * np.asarray(row.get('harmonic_mid_chroma', row.get('chroma', np.zeros(12))))
                bass += weight * np.asarray(row.get('bass_chroma', np.zeros(12)))
                energy += weight * float(row.get('accompaniment_rms', 0.))
                total += weight
        if total:
            chroma /= total
            bass /= total
            energy /= total
        direct = self.features.get('accompaniment')
        if direct is not None:
            chroma = .5 * chroma + .5 * np.asarray(direct.chroma(a, b, 48, 84)) if total else np.asarray(direct.chroma(a, b, 48, 84))
            energy = float(np.mean(direct.rms[direct.window(a, b)]))
        if self.features.get('bass') is not None:
            bass = np.asarray(self.features['bass'].chroma(a, b, 24, 59))
        result = {'chroma': chroma, 'bass': bass, 'seconds': [a, b],
                  'accompaniment_rms': energy,
                  'available': bool(total or direct is not None),
                  'source': 'bound_audio_features' if direct is not None else 'bound_original_seconds_windows'}
        self.cache[key] = result
        return result

    def score(self, chord, start, end):
        row = self.at(start, end)
        pcs = set(chord['pitch_classes']) | {chord.get('bass_pc', chord['root_pc'])}
        # 吉他既有规则闭环修复：新增同集合候选比较；不用高音经过音重新发明和弦。
        return float(2.0 * sum(row['chroma'][p] for p in pcs) / max(1, math.sqrt(len(pcs)))
                     + 1.6 * row['bass'][chord.get('bass_pc', chord['root_pc'])])

    def bass_anchor(self, tick, end, span=None):
        # 吉他既有规则闭环修复：新增拍头前半拍低音证据，后半拍的新根音不能以整拍平均提前覆盖旧根音。
        # 吉他既有规则闭环修复：修改单个半拍窗为实际拨弦短窗与半拍持续窗；不能平均掉短音头的真实低音。
        # key = (tick, end)
        span = self.bass_period(tick) // 4 if span is None else span
        key = (tick, end, span)
        if key in self.bass_cache:
            return self.bass_cache[key]
        # finish = min(end, tick + 240)
        # 吉他既有规则闭环修复：新增固定原音起音窗，长八分音尾不能稀释刚拨弦时仍在延续的转位低音。
        finish = min(end, self.clock.tick(self.clock.seconds(tick) + POLICY['bass_attack_window_seconds'])) if span == 'attack' else min(end, tick + span)
        begin_seconds, end_seconds = self.clock.seconds(tick), self.clock.seconds(finish)
        observation = self.at(tick, finish)
        values = observation['bass']
        feature = self.features.get('bass')
        if feature is not None and end_seconds > 0:
            begin_seconds = max(0., min(end_seconds - .01, begin_seconds + .03))
            values = np.asarray(feature.chroma(begin_seconds, end_seconds, 24, 59))
        peak = float(max(values))
        dominant = int(np.argmax(values))
        relatives = (values / max(peak, 1e-9)).tolist()
        local = [n for n in self.original_bass if n['start_tick'] < finish and n['end_tick'] > tick - 120]
        # 吉他既有规则闭环修复：修改必须恰好为最大峰的旧门槛；既有实低音仍强时不能被略高的滑音峰掩盖。
        # source_ids = [n['id'] for n in local if n['pitch_midi'] % 12 == dominant]
        # matching_harmony = [h['id'] for h in self.shared['harmony'] if h.get('bass_pc') == dominant
        #                     and _overlap(tick, finish, h['start_tick'], h['end_tick'])]
        local_harmony = [h for h in self.shared['harmony'] if _overlap(tick, finish, h['start_tick'], h['end_tick'])]
        known = {n['pitch_midi'] % 12 for n in local} | {h['bass_pc'] for h in local_harmony}
        supported_pcs = [pc for pc in known if relatives[pc] >= POLICY['minimum_existing_bass_relative_support']]
        if supported_pcs:
            dominant = max(supported_pcs, key=lambda pc: relatives[pc])
        source_ids = [n['id'] for n in local if n['pitch_midi'] % 12 == dominant]
        matching_harmony = [h['id'] for h in local_harmony if h['bass_pc'] == dominant]
        result = {'tick': tick, 'end_tick': finish, 'source_seconds': [begin_seconds, end_seconds],
                  'dominant_pc': dominant, 'relative_support': relatives, 'peak_mass': peak,
                  'existing_bass_note_ids': source_ids, 'existing_harmony_ids': matching_harmony,
                  'observation_window': span,
                  'supported': bool(peak >= POLICY['minimum_clear_bass_mass'] and supported_pcs)}
        self.bass_cache[key] = result
        return result

    def bass_allowed(self, chord, tick, end):
        # 吉他既有规则闭环修复：新增硬边界仅拦截强源证据相反的低音；原低音错而新低音强时仍可纠正。
        # anchor = self.bass_anchor(tick, end)
        # return (not anchor['supported'] or
        #         anchor['relative_support'][chord['bass_pc']] >= POLICY['minimum_changed_bass_relative_support'])
        return all(not anchor['supported'] or anchor['relative_support'][chord['bass_pc']] >=
                   POLICY['minimum_changed_bass_relative_support'] for anchor in self.bass_anchors(tick, end))

    def bass_anchors(self, tick, end):
        # 吉他既有规则闭环修复：新增双窗分别约束；短攻击与持续低音证据不得相互平均抵消。
        return [self.bass_anchor(tick, end, span) for span in [*sorted({self.bass_period(tick) // 4, 240}), 'attack']]

    def bass_period(self, tick):
        # 吉他既有规则闭环修复：新增实际右手循环的低音周期；未拨低音的弱拍不强制换和弦。
        return next((period for start, end, period in self.pattern_periods if start <= tick < end), 960)


def _source_phrases(project, timeline):
    # 吉他既有规则闭环修复：新增来源绑定自然乐句迁移，只取结构证据，绝不复制祖先旧tick到新谱。
    source = project
    provenance = 'current_bound_phrase_plan'
    path = project.get('time_only_revision', {}).get('ancestor_project_path')
    if path:
        file = Path(path)
        raw = local_path(file).read_bytes()
        expected = project['time_only_revision'].get('ancestor_project_sha256')
        if expected and hashlib.sha256(raw).hexdigest() != expected:
            raise ValueError('祖先工程签名已改变，不能借用旧乐句族')
        source = json.loads(raw.decode('utf-8-sig'))
        provenance = 'verified_ancestor_seconds'
    plan = source['shared_analysis'].get('phrase_harmony_plan', {})
    old_clock = SongClock(source['accepted_vocal_project'])
    clock = SongClock(project['accepted_vocal_project'])
    boundaries = sorted({m['start_tick'] for m in timeline} | {timeline[-1]['end_tick']})
    phrases = []
    for row in plan.get('phrases', []):
        if row.get('action') == 'preserve_source_insufficient_evidence':
            continue
        seconds = [old_clock.seconds(row['start_tick']), old_clock.seconds(row['end_tick'])]
        observed = [clock.tick(s) for s in seconds]
        aligned = [min(boundaries, key=lambda x: abs(x - t)) for t in observed]
        if aligned[1] <= aligned[0] or max(abs(a - b) for a, b in zip(aligned, observed)) > 960:
            continue
        phrases.append({'id': row['id'], 'start_tick': aligned[0], 'end_tick': aligned[1],
                        'family_id': row.get('family_id', row['id']), 'source_seconds': seconds,
                        'source_mapped_ticks': observed, 'boundary_source': provenance,
                        'ancestor_action': row.get('action'), 'ancestor_variants': deepcopy(row.get('variants', []))})
    if not phrases:
        # 吉他既有规则闭环修复：新增无旧乐句计划时的来源段落后备，不按歌词内容猜相同段。
        for index, row in enumerate(project['shared_analysis'].get('sections', [])):
            if row.get('kind') != 'vocal':
                continue
            aligned = [min(boundaries, key=lambda x: abs(x - row[t])) for t in ('start_tick', 'end_tick')]
            if aligned[1] > aligned[0]:
                phrases.append({'id': f'section_phrase_{index}', 'family_id': f'section_family_{index}',
                                'start_tick': aligned[0], 'end_tick': aligned[1], 'boundary_source': 'source_section'})
    return phrases


def _align_phrase_families(project, phrases, timeline):
    # 吉他既有规则闭环修复：新增旧快拍分句换轴后的同旋律边界校验，只移动候选范围、不改音乐。
    families = defaultdict(list)
    for row in phrases:
        families[row['family_id']].append(row)
    vocal, shared = project['accepted_vocal_project'], project['shared_analysis']
    starts = [m['start_tick'] for m in timeline] + [timeline[-1]['end_tick']]
    cache = {}
    def signature(first, size):
        key = (first, size)
        if key not in cache:
            cache[key] = melody_signature(shared, vocal, starts[first], starts[first + size])
        return cache[key]
    for members in families.values():
        if len(members) < 2:
            continue
        first = members[0]
        index = starts.index(first['start_tick'])
        size = starts.index(first['end_tick']) - index
        if size < 2:
            continue
        base = signature(index, size)
        for row in members[1:]:
            current = starts.index(row['start_tick'])
            candidates = []
            for shifted in range(max(0, current - 2), min(len(timeline) - size, current + 2) + 1):
                check = similarity(base, signature(shifted, size))
                if check.get('accepted'):
                    score = check['pitch_support'] + check['activity_support'] + check['onset_support'] - .025 * abs(shifted - current)
                    candidates.append((score, shifted, check))
            if candidates:
                _, chosen, check = max(candidates)
                row['unaligned_source_phrase_ticks'] = [row['start_tick'], row['end_tick']]
                row.update(start_tick=starts[chosen], end_tick=starts[chosen + size], current_melody_alignment=check)
    return phrases


def _violating_measures(harmony, notes, measures):
    # 吉他既有规则闭环修复：新增最小修改范围；已符合真实硬约束的旧唱段不被全曲重编配。
    result = {}
    for m in measures:
        start, end = m['start_tick'], m['end_tick']
        reasons = []
        local = [h for h in harmony if h.get('name') != 'N.C.' and _overlap(start, end, h['start_tick'], h['end_tick'])]
        # 慢拍单位与两曲最小修订：修改同时检查和弦释放边界，转入无和弦区也不能留下半拍控制碎片。
        # if any(start < h['start_tick'] < end and (h['start_tick'] - start) % 480 for h in local):
        if any(start < h[key] < end and (h[key] - start) % 480 for h in local for key in ('start_tick', 'end_tick')):
            reasons.append('chord_change_between_beats')
        if any(h['end_tick'] - h['start_tick'] < 480 for h in local):
            reasons.append('chord_hold_shorter_than_beat')
        # 吉他既有规则闭环修复：新增时值与实际拨弦共同核对，不只看节奏字段写着什么版本。
        ns = [n for n in notes if start <= n['start_tick'] < end]
        if any(n['start_tick'] % 120 or n['end_tick'] % 120 or n['end_tick'] - n['start_tick'] < 120 for n in ns):
            reasons.append('actual_notes_below_sixteenth_grid')
        if reasons:
            result[m['number']] = reasons
    return result


def _candidate_rows(harmony, start, end):
    # 吉他既有规则闭环修复：新增局部候选池，仅使用已有和弦身份；不会整曲重识别和声。
    choices = {}
    for row in harmony:
        if row.get('name') == 'N.C.':
            continue
        if _overlap(start, end, row['start_tick'], row['end_tick']):
            identity = _identity(row)
            if identity not in choices or row['end_tick'] - row['start_tick'] > choices[identity]['end_tick'] - choices[identity]['start_tick']:
                choices[identity] = row
    return choices


def _plan_bar(harmony, measure, evidence, available=None):
    # 吉他既有规则闭环修复：新增整拍动态规划，三四和弦需额外证据收益，半拍换和弦没有候选通路。
    start, end = measure['start_tick'], measure['end_tick']
    choices = available or _candidate_rows(harmony, start, end)
    if not choices:
        return [], {'status': 'no_existing_harmony', 'measure': measure['number']}
    ticks = list(range(start, end, 480))
    choices = dict(choices)
    bass_events = []
    # 吉他既有规则闭环修复：新增来源支持的同和弦转位及前拍延续，候选仍来自既有和声和已存在低音。
    # 吉他既有规则闭环修复：修改单一半拍候选扩展，实际音头和持续窗都可引用已有转位材料。
    # for tick in ticks:
    #     anchor = evidence.bass_anchor(tick, min(end, tick + 480))
    for tick, anchor in [(t, a) for t in ticks for a in evidence.bass_anchors(t, min(end, t + 480))]:
        if not anchor['supported'] or all(evidence.bass_allowed(c, tick, min(end, tick + 480)) for c in choices.values()):
            continue
        dominant = anchor['dominant_pc']
        previous = _candidate_rows(harmony, max(0, tick - 480), tick)
        for ident, chord in previous.items():
            if chord['bass_pc'] == dominant:
                choices.setdefault(ident, chord)
        created = []
        for chord in list(choices.values()):
            if dominant not in chord['pitch_classes'] or chord['bass_pc'] == dominant:
                continue
            inversion = deepcopy(chord)
            inversion.update(bass_pc=dominant, name=chord_name(chord['root_pc'], chord['quality'], dominant, chord['key']))
            inversion['readable_bass_derivation'] = {'existing_chord_id': chord['id'], 'previous_bass_pc': chord['bass_pc'],
                                                     'source_anchor': deepcopy(anchor), 'operation': 'existing_chord_tone_inversion'}
            choices.setdefault(_identity(inversion), inversion)
            created.append(list(_identity(inversion)))
        bass_events.append({**deepcopy(anchor), 'derived_existing_tone_inversions': created})
    states = {None: (0., [])}
    for tick in ticks:
        finish = min(end, tick + 480)
        following = {}
        for ident, chord in choices.items():
            prior = sum(_overlap(tick, finish, h['start_tick'], h['end_tick']) for h in harmony if _identity(h) == ident)
            source = evidence.score(chord, tick, finish)
            emission = source + 1.25 * min(1., prior / max(1, finish - tick))
            best = None
            for state, (value, path) in states.items():
                # 吉他既有规则闭环修复：修改仅按和弦计数的旧状态，保存循环起点以验证真实低音拨弦时刻。
                # old, changes = state if state else (None, 0)
                old, changes, origin = state if state else (None, 0, tick)
                changed = old is not None and ident != old
                origin = tick if changed else origin
                actual_bass_attack = old is None or changed or (tick - origin) % evidence.bass_period(start) == 0
                if actual_bass_attack and not evidence.bass_allowed(chord, tick, finish):
                    continue
                count = changes + int(changed)
                penalty = (.46 if (tick - start) == (end - start) // 2 else .65) if changed else 0.
                if changed and count >= 2:
                    penalty += 1.10
                candidate = (value + emission - penalty, path + [ident])
                # 吉他既有规则闭环修复：修改候选状态签名，避免相同和弦不同循环相位被错误合并。
                # key = (ident, count)
                key = (ident, count, origin)
                if key not in following or candidate[0] > following[key][0]:
                    following[key] = candidate
        states = following
        if not states:
            raise ValueError('既有和弦与强来源低音在整拍约束下无可行编配，停止并保留未决')
    value, selected = max(states.values(), key=lambda x: x[0])
    rows = []
    for tick, ident in zip(ticks, selected):
        if rows and _identity(rows[-1]) == ident:
            rows[-1]['end_tick'] = min(end, tick + 480)
        else:
            rows.append({**deepcopy(choices[ident]), 'start_tick': tick, 'end_tick': min(end, tick + 480),
                         'readable_source_chord_id': choices[ident]['id']})
    return rows, {'status': 'planned', 'measure': measure['number'], 'chord_count': len(rows),
                  'score': value, 'candidate_identities': [list(i) for i in choices],
                  'source_bass_constraints': bass_events,
                  'source_seconds': evidence.at(start, end)['seconds']}


def _common_upper_only(bars, plans, evidence):
    # 吉他既有规则闭环修复：新增受限共同上声部简化，仅同一基础和弦的非首拍转位可省略重复拨低音。
    rows = [plans[m['number']] for m in bars]
    if not rows or any(not r for r in rows):
        return None
    identities = {(h['root_pc'], h['quality']) for r in rows for h in r}
    basses = {h['bass_pc'] for r in rows for h in r}
    first_basses = {r[0]['bass_pc'] for r in rows}
    if len(identities) != 1 or len(first_basses) != 1 or len(basses) < 2:
        return None
    if len({evidence.bass_period(m['start_tick']) for m in bars}) != 1:
        return None
    selected, observations, shapes = [], [], []
    for bar, existing in zip(bars, rows):
        start, end = bar['start_tick'], bar['end_tick']
        chord = deepcopy(existing[0])
        if chord['start_tick'] != start or not evidence.bass_allowed(chord, start, min(end, start + 480)):
            return None
        shape = _shape(chord, evidence.original_guitar, start, {})
        pitches = {int(s): TUNING[int(s)] + shape['capo'] + f for s, f in shape['frets'].items()}
        bass_string = min(pitches, key=pitches.get)
        # 吉他既有规则闭环修复：新增真实高声部物理边界，低音换角色名或近低音弦不能借简化绕过守卫。
        upper_strings = [s for s in _pattern_strings(shape, chord)[1:4]
                         if s <= POLICY['maximum_common_upper_string'] and
                         pitches[s] - pitches[bass_string] >= POLICY['minimum_common_upper_above_bass_semitones']]
        upper_pcs = {pitches[s] % 12 for s in upper_strings}
        essential = set(chord['pitch_classes']) - {chord['root_pc'], (chord['root_pc'] + 7) % 12}
        old_upper = {n['pitch_midi'] % 12 for n in evidence.original_guitar['notes']
                     if start <= n['start_tick'] < end and n.get('role') != 'bass'}
        observation = evidence.at(start, end)
        chroma = observation['chroma']
        relative = chroma / max(float(max(chroma)), 1e-9)
        if (not observation['available'] or len(set(upper_strings)) < 2 or not essential <= upper_pcs or not upper_pcs <= old_upper or
                min((float(relative[pc]) for pc in upper_pcs), default=0.) < POLICY['minimum_common_upper_relative_support']):
            return None
        shapes.append((shape['capo'], shape['frets']))
        chord.update(start_tick=start, end_tick=end, readable_bass_pattern='first_attack_only',
                     readable_common_upper_strings=upper_strings)
        chord['readable_bass_simplification'] = {
            'operation': 'omit_noninitial_inversion_bass_keep_common_upper',
            'original_selected_harmony': [{k: h[k] for k in ('name', 'start_tick', 'end_tick', 'bass_pc')} for h in existing],
            'first_bass_pc_preserved': chord['bass_pc'], 'upper_pitch_classes': sorted(upper_pcs),
            'source_seconds': observation['seconds'],
            'upper_source_relative_support': {str(pc): float(relative[pc]) for pc in sorted(upper_pcs)},
            'source_existing_upper_pitch_classes': sorted(old_upper),
            'musical_purpose': '同和弦唱段的共同上声部伴奏简化；非原录音低音行进逐音复制'}
        observations.append(deepcopy(chord['readable_bass_simplification']))
        selected.append(chord)
    if any(s != shapes[0] for s in shapes[1:]):
        return None
    return selected, observations


def _share_harmony(phrases, measures, plans, harmony, evidence):
    # 吉他既有规则闭环修复：新增相似句的共同和声选择，局部声学损失超限或低音有异即保留变体。
    families = defaultdict(list)
    for phrase in phrases:
        phrase['measures'] = [m['number'] for m in measures if phrase['start_tick'] <= m['start_tick'] < phrase['end_tick']]
        families[phrase['family_id']].append(phrase)
    shared, variants = [], []
    by_number = {m['number']: m for m in measures}
    for family, members in families.items():
        if len(members) < 2 or len({len(p['measures']) for p in members}) != 1:
            continue
        for position in range(len(members[0]['measures'])):
            bars = [by_number[p['measures'][position]] for p in members]
            if len({m['end_tick'] - m['start_tick'] for m in bars}) != 1:
                continue
            pools = [_candidate_rows(harmony, m['start_tick'], m['end_tick']) for m in bars]
            common = set.intersection(*(set(p) for p in pools)) if pools else set()
            if not common:
                variants.append({'family_id': family, 'bar_position': position, 'reason': 'different_existing_harmonic_material'})
                # 吉他既有规则闭环修复：新增同族必要变体的子组复用；首遍不同不能阻止后两遍真实相同的长段。
                subgroups = defaultdict(list)
                for member, pool in zip(members, pools):
                    subgroups[tuple(sorted(pool))].append(member)
                for subgroup in subgroups.values():
                    if 2 <= len(subgroup) < len(members):
                        preceding_plans = deepcopy(plans)
                        subset_shared, subset_variants = _share_harmony(subgroup, measures, plans, harmony, evidence)
                        subset_numbers = {p['measures'][position] for p in subgroup}
                        for number in plans:
                            if number not in subset_numbers:
                                plans[number] = preceding_plans[number]
                        # 吉他既有规则闭环修复：新增只接纳当前失败位置；其它位置仍由全族共同候选统一决定。
                        for item in subset_shared:
                            if item['bar_position'] == position:
                                item['subset_member_ids'] = [p['id'] for p in subgroup]
                                shared.append(item)
                continue
            proposals = [_plan_bar(harmony, m, evidence, {i: p[i] for i in common})[0] for m, p in zip(bars, pools)]
            for pool, rows in zip(pools, proposals):
                for row in rows:
                    pool.setdefault(_identity(row), row)
            sequences = []
            for rows, bar in zip(proposals, bars):
                sequence = tuple((_identity(h), h['start_tick'] - bar['start_tick'], h['end_tick'] - bar['start_tick']) for h in rows)
                if sequence not in sequences:
                    sequences.append(sequence)
            scores = []
            for sequence in sequences:
                loss, valid = [], True
                for m, pool in zip(bars, pools):
                    for ident, a, b in sequence:
                        if ident not in pool:
                            valid = False
                            continue
                        start, end = m['start_tick'] + a, m['start_tick'] + b
                        # 吉他既有规则闭环修复：修改每拍一律换低音的旧判定，仅联合核对共用模板真正拨根音处。
                        # if any(not evidence.bass_allowed(pool[ident], tick, min(end, tick + 480))
                        #        for tick in range(start, end, 480)):
                        if any(not evidence.bass_allowed(pool[ident], tick, min(end, tick + 480))
                               for tick in range(start, end, evidence.bass_period(start))):
                            valid = False
                        best = max(evidence.score(c, start, end) for c in pool.values())
                        current = evidence.score(pool[ident], start, end)
                        loss.append(best - current)
                        bass = evidence.at(start, end)['bass']
                        if float(max(bass)) >= .60 and ident[2] != int(np.argmax(bass)):
                            valid = False
                if valid and max(loss, default=0.) <= POLICY['common_source_loss_limit']:
                    scores.append((sum(loss), sequence))
            if not scores:
                # 吉他既有规则闭环修复：新增真实重写双方完整上声部模板，不靠改role或删除和弦标签绕开低音验收。
                upper_only = _common_upper_only(bars, plans, evidence)
                if upper_only is not None:
                    selected, observations = upper_only
                    for m, chord in zip(bars, selected):
                        chord['shared_template_id'] = family
                        plans[m['number']] = [chord]
                    shared.append({'family_id': family, 'bar_position': position,
                                   'measures': [m['number'] for m in bars], 'source_loss_sum': 0.,
                                   'source_loss_limit': POLICY['common_source_loss_limit'],
                                   'common_upper_simplification': observations,
                                   'pattern_id': 'one_initial_bass_then_common_upper'})
                    continue
                variants.append({'family_id': family, 'bar_position': position, 'reason': 'source_harmony_or_bass_variant_preserved'})
                # 吉他既有规则闭环修复：新增强源低音使一遍不同的子组处理；后两遍可相同的演奏仍逐遍验证后共享。
                if len(members) > 2:
                    accepted_subsets = []
                    initial_plans = deepcopy(plans)
                    for subset in combinations(members, 2):
                        subset_shared, _ = _share_harmony(list(subset), measures, plans, harmony, evidence)
                        position_shared = [r for r in subset_shared if r['bar_position'] == position]
                        if position_shared:
                            numbers = {p['measures'][position] for p in subset}
                            accepted_subsets.append((sum(r['source_loss_sum'] for r in position_shared),
                                                     list(subset), position_shared,
                                                     {number: deepcopy(plans[number]) for number in numbers}))
                        plans.clear()
                        plans.update(deepcopy(initial_plans))
                    if accepted_subsets:
                        _, subset, subset_shared, selected_plans = min(accepted_subsets, key=lambda row: row[0])
                        plans.update(selected_plans)
                        for item in subset_shared:
                            item['subset_member_ids'] = [p['id'] for p in subset]
                            shared.append(item)
                continue
            loss, sequence = min(scores, key=lambda row: row[0])
            for m, pool in zip(bars, pools):
                plans[m['number']] = [{**deepcopy(pool[i]), 'start_tick': m['start_tick'] + a,
                                      'end_tick': m['start_tick'] + b, 'readable_source_chord_id': pool[i]['id'],
                                      'shared_template_id': family} for i, a, b in sequence]
            shared.append({'family_id': family, 'bar_position': position, 'measures': [m['number'] for m in bars],
                           'source_loss_sum': loss, 'source_loss_limit': POLICY['common_source_loss_limit']})
    return shared, variants


def _quantize_instrumental(notes, total):
    # 吉他既有规则闭环修复：新增逐弦有界顺序量化，全部器乐音符身份/音高/弦品原样保留。
    output = deepcopy(notes)
    changes = []
    for string in range(1, 7):
        items = sorted((n for n in output if n['string'] == string), key=lambda n: (n['start_tick'], n['id']))
        states = {None: (0., ())}
        for note in items:
            observed = note['start_tick']
            choices = [t for t in range(max(0, round(observed / 120) * 120 - 240),
                                       min(total - 120, round(observed / 120) * 120 + 240) + 1, 120)
                       if abs(t - observed) <= POLICY['maximum_instrumental_onset_shift_ticks']]
            following = {}
            for tick in choices:
                paths = [(cost + (tick - observed) ** 2, path + (tick,)) for old, (cost, path) in states.items()
                         if old is None or tick >= old + 120]
                if paths:
                    following[tick] = min(paths, key=lambda row: row[0])
            if not following:
                raise ValueError('器乐音符在十六分网格无法保持弦序及有界位移：' + note['id'])
            states = following
        selected = min(states.values(), key=lambda row: row[0])[1]
        for index, (note, tick) in enumerate(zip(items, selected)):
            before = [note['start_tick'], note['end_tick']]
            end = min(total, max(tick + 120, round(note['end_tick'] / 120) * 120))
            if index + 1 < len(items):
                end = min(end, selected[index + 1])
            # 保音持续按弦与整句八度衔接：新增已经合规时完全保留音符，不重写显示字段导致既有表现／来源摘要失效。
            if before == [tick, end]:
                continue
            note.update(start_tick=tick, end_tick=end, right_hand_duration_ticks=end - tick,
                        right_hand_duration_source='protected_instrumental_sixteenth_grid')
            note['readable_source_interval'] = before
            if before != [tick, end]:
                changes.append({'id': note['id'], 'before': before, 'after': [tick, end],
                                'pitch_string_fret_preserved': True})
    return output, changes


def _shape(chord, guitar, tick, cache):
    # 吉他既有规则闭环修复：新增已有低品指型优先的同和弦配音，最多12品且保留性质音。
    capo = _capo(guitar, tick)
    key = (_identity(chord), capo)
    if key in cache:
        return cache[key]
    allowed = set(chord['pitch_classes']) | {chord['bass_pc']}
    essential = set(chord['pitch_classes']) - {(chord['root_pc'] + 7) % 12}
    options = []
    for chart in guitar.get('fingering_diagrams', []):
        frets = {int(s): f for s, f in chart.get('frets', {}).items() if f >= 0}
        pitches = {s: TUNING[s] + capo + f for s, f in frets.items()}
        pcs = {p % 12 for p in pitches.values()}
        info = grip_info(frets)
        if (info and len(frets) >= 3 and max(frets.values()) <= 12 and pcs <= allowed and essential <= pcs
                and min(pitches.values()) % 12 == chord['bass_pc']):
            options.append({**deepcopy(chart), **info, 'frets': {str(s): f for s, f in frets.items()},
                            'cost': sum(max(0, f - 4) * 4 + f * .1 for f in frets.values())})
    # 吉他既有规则闭环修复：修改只按总品数偏好高音三弦形状的旧排序；同为0–4品时保住既有实低音音区。
    # if not options:
    #     options = list(shape_candidates(chord['root_pc'], chord['quality'], chord['bass_pc'], capo, max_fret=12))
    # shape = deepcopy(min(options, key=lambda x: (sum(max(0, f - 4) for f in x['frets'].values()), x.get('cost', 0))))
    previous_bass = [n['pitch_midi'] for n in guitar['notes'] if n.get('role') == 'bass'
                     and n['pitch_midi'] % 12 == chord['bass_pc']]
    target = float(np.median(previous_bass)) if previous_bass else None
    def bass_pitch(option):
        return min(TUNING[int(s)] + capo + f for s, f in option['frets'].items())
    if not options or (target is not None and min(bass_pitch(o) for o in options) > target + 6):
        options.extend(shape_candidates(chord['root_pc'], chord['quality'], chord['bass_pc'], capo, max_fret=12))
    shape = deepcopy(min(options, key=lambda x: (sum(max(0, f - 4) for f in x['frets'].values()),
                                                abs(bass_pitch(x) - target) if target is not None else 0,
                                                x.get('cost', 0))))
    shape['readable_bass_register'] = {'source_same_pitch_class_median': target,
                                      'selected_pitch_midi': bass_pitch(shape)}
    # 吉他既有规则闭环修复：新增所有来源候选统一为实际指型图schema，不能把内部配音对象直接交给绘图器。
    shape['position'] = max(1, int(shape.get('position', 1)))
    shape['simplified'] = bool(shape.get('simplified', False))
    actual_grip = grip_info({int(s): int(f) for s, f in shape['frets'].items()})
    if actual_grip is None:
        raise ValueError('可读编配候选未形成可实际持握的完整图式')
    shape['barre'] = actual_grip['barre']
    shape['finger_count'] = actual_grip['finger_count']
    shape['fingers'] = actual_grip['fingers']
    shape.update(capo=capo, sounding_name=chord['name'],
                 shape_name=chord_name((chord['root_pc'] - capo) % 12, chord['quality'],
                                       (chord['bass_pc'] - capo) % 12, chord['key']))
    cache[key] = shape
    return shape


def _pattern_strings(shape, chord):
    # 吉他既有规则闭环修复：新增稳定环绕分解；三音/七音等必要音优先覆盖，不只弹同一根高弦。
    pitches = {int(s): TUNING[int(s)] + shape['capo'] + f for s, f in shape['frets'].items()}
    bass = min(pitches, key=pitches.get)
    upper = sorted((s for s in pitches if s != bass), reverse=True)
    essential = set(chord['pitch_classes']) - {(chord['root_pc'] + 7) % 12, pitches[bass] % 12}
    chosen = []
    for pc in sorted(essential):
        places = [s for s in upper if pitches[s] % 12 == pc]
        if places:
            chosen.append(min(places))
    for s in upper:
        if s not in chosen:
            chosen.append(s)
    chosen = chosen[:3]
    if len(chosen) < 2:
        raise ValueError('和弦没有足够的可演奏分解弦')
    # 吉他既有规则闭环修复：修改三弦和弦退成三格循环的旧式；仍保持四格一组，不能每3个十六分重拨根音。
    # return [bass, *chosen, bass, *reversed(chosen)]
    while len(chosen) < 3:
        chosen.append(chosen[-1])
    return [bass, *chosen, bass, *reversed(chosen)]


def _merge_diagrams(diagrams):
    # 吉他既有规则闭环修复：新增连续同一指型合并，实际没有换握就不重复画多个图。
    result = []
    for chart in sorted(diagrams, key=lambda d: (d['start_tick'], d['end_tick'])):
        if (result and result[-1]['end_tick'] == chart['start_tick']
                and result[-1]['frets'] == chart['frets']
                and result[-1].get('shape_name') == chart.get('shape_name')
                and result[-1].get('capo') == chart.get('capo')):
            result[-1]['end_tick'] = chart['end_tick']
            result[-1].setdefault('merged_source_chord_ids', [result[-1].get('chord_id')]).append(chart.get('chord_id'))
        else:
            result.append(deepcopy(chart))
    return result


# 慢拍单位与两曲最小修订：修改增加明确的现有演奏和声输入模式；旧调用维持原语义。
# def revise_guitar_arrangement(project, source_features=None):
def revise_guitar_arrangement(project, source_features=None, preserve_performed_harmony=False):
    # 吉他既有规则闭环修复：新增唯一核心入口；所有结果另存，原工程深拷贝后才编配。
    revised = deepcopy(project)
    if 'guitar' not in project.get('arrangements', {}):
        return revised, {'status': 'not_applicable', 'reason': 'no_guitar'}
    old = project['arrangements']['guitar']
    if any(n['fret'] > POLICY['maximum_fret'] for n in old['notes']):
        # 吉他既有规则闭环修复：新增输入高品冲突即显式停止，不能绕过已认可乐句八度规划或自动放宽20品。
        raise ValueError('输入仍含12品以上音，必须先完成通用乐句低把位规划，不能由可读性路线放宽')
    for name, feature in (source_features or {}).items():
        bound = project['shared_analysis'].get('input_binding', {}).get('sources', {}).get(name)
        if bound and feature.source.get('sha256') != bound['sha256']:
            # 吉他既有规则闭环修复：新增来源身份冲突硬拒绝，别的录音特征不能作为当前编配证据。
            raise ValueError('声学特征与当前工程绑定音源不一致：' + name)
    # 吉他既有规则闭环修复：修改只验音符的旧复用判定，拍轴/原和声/音源也必须完全相同。
    # if old.get('guitar_readability_revision', {}).get('input_material_sha256') == _fingerprint(old.get('readability_ancestor_evidence', {}).get('notes', [])):
    source_binding = {name: feature.source for name, feature in (source_features or {}).items()}
    # 吉他既有规则闭环修复：修改幂等上下文加入全部策略参数，版本升级必须从明确祖先重新编配。
    # context_signature = _fingerprint({'vocal': project['accepted_vocal_project'], 'shared': project['shared_analysis'],
    #                                   'features': source_binding})
    context_signature = _fingerprint({'vocal': project['accepted_vocal_project'], 'shared': project['shared_analysis'],
                                      'features': source_binding, 'policy': POLICY})
    # 慢拍单位与两曲最小修订：新增实际和声视图绑定，避免派生模式与旧基础和声模式误用同一幂等摘要。
    if preserve_performed_harmony:
        context_signature = _fingerprint({'context': context_signature,
            'performed_harmony': guitar_shared_view(project)['harmony'], 'preserve_performed_harmony': True})
    if old.get('guitar_readability_revision', {}).get('input_material_sha256') == _fingerprint(old.get('readability_ancestor_evidence', {}).get('notes', [])):
        # 吉他既有规则闭环修复：新增旧策略明确拒绝；不从未知人工修改工程静默恢复旧祖先。
        if old['guitar_readability_revision'].get('version') != POLICY['version']:
            raise ValueError('旧编配策略版本已过期，必须从明确祖先重新修订，不能复用旧通过标记')
        if (old['guitar_readability_revision'].get('output_note_sha256') == _fingerprint(old['notes'])
                and old['guitar_readability_revision'].get('context_sha256') == context_signature):
            return revised, deepcopy(old['guitar_readability_revision']['audit'])
        raise ValueError('编配后的音符/源拍轴/和声证据已改变，必须从明确祖先重新修订，不能复用旧通过标记')
    guitar = revised['arrangements']['guitar']
    vocal = project['accepted_vocal_project']
    timeline = measure_timeline(vocal)
    total = vocal['statistics']['total_ticks']
    if any(m['start_tick'] % 120 or m['end_tick'] % 120 for m in timeline):
        raise ValueError('认可小节边界不在十六分网格，须显式处理冲突，禁止更改拍轴')
    shared = arrangement_view(project['shared_analysis'], vocal)
    # 慢拍单位与两曲最小修订：新增从已认可的实际吉他进行局部整理，不能因单位变换退回较早基础和弦计划。
    if preserve_performed_harmony:
        shared = guitar_shared_view(project)
    harmony = shared['harmony']
    evidence = SourceEvidence(project, source_features)
    # 吉他既有规则闭环修复：修改旧新分句仅贴小节线的不足，额外校验相似旋律的当前音乐相位。
    # phrases = _source_phrases(project, timeline)
    phrases = _align_phrase_families(project, _source_phrases(project, timeline), timeline)
    violations = _violating_measures(harmony, old['notes'], timeline)
    # 吉他既有规则闭环修复：修改只查换位起点的旧式，同时阻止一拍以内的和弦区间。
    # chord_bad = {number for number, reasons in violations.items() if 'chord_change_between_beats' in reasons}
    chord_bad = {number for number, reasons in violations.items()
                 if 'chord_change_between_beats' in reasons or 'chord_hold_shorter_than_beat' in reasons}
    if not chord_bad:
        # 吉他既有规则闭环修复：新增已认可合规路线的保留通路，仅修实际离网的音尾/起音，仍执行后续反复规划。
        fixed, edits = _quantize_instrumental(old['notes'], total)
        guitar['notes'] = fixed
        guitar['readable_harmony'] = deepcopy(harmony)
        guitar['readable_reuse'] = {'phrases': phrases, 'shared_bars': [], 'variants': [],
                                   'rhythm_plans': [], 'existing_source_backed_performance_preserved': True}
        audit = {'status': 'preserved_compliant_material_requires_acceptance', 'policy': deepcopy(POLICY),
                 'requirements': ['R10', 'R17', 'R24', 'R25', 'R34', 'R37', 'R39'],
                 'changed_bars': [{'measure': number, 'reasons': reasons} for number, reasons in violations.items()],
                 'instrumental_timing_edits': [r for r in edits if any(n['id'] == r['id'] and n.get('section') != 'vocal' for n in old['notes'])],
                 'all_local_timing_edits': edits, 'whole_vocal_rearrangement': False,
                 'protected_instrumental_count': sum(n.get('section') != 'vocal' or n.get('role') == 'instrumental_melody' for n in old['notes']),
                 'source_vocal_note_count': sum(n.get('section') == 'vocal' for n in old['notes']),
                 'new_vocal_note_count': sum(n.get('section') == 'vocal' for n in fixed),
                 'shared_bars': [], 'preserved_variants': [], 'grip_path': {'valid': True, 'status': 'retained_requires_actual_revalidation'},
                 'source_evidence_mode': 'bound_audio_features' if source_features else 'bound_original_seconds_windows',
                 'accepted_vocal_unchanged': True, 'shared_analysis_unchanged': True, 'piano_unchanged': True}
        # 吉他既有规则闭环修复：新增保留完整旧证据为祖先，发生实际时序变更时撤销相应过期认证。
        guitar['readability_ancestor_evidence'] = {'notes': deepcopy(old['notes'])}
        if edits:
            for key in ('regular_rhythm', 'right_hand_patterns', 'phrase_harmony_performance', 'attack_events'):
                if key in guitar:
                    guitar['readability_ancestor_evidence'][key] = guitar.pop(key)
        # 吉他既有规则闭环修复：修改版本固定值为实际策略版本；保留路线也必须重新核验升级策略。
        # guitar['guitar_readability_revision'] = {'version': 1, 'input_material_sha256': _fingerprint(old['notes']),
        guitar['guitar_readability_revision'] = {'version': POLICY['version'], 'input_material_sha256': _fingerprint(old['notes']),
                                               'context_sha256': context_signature,
                                               'output_note_sha256': _fingerprint(fixed), 'audit': audit}
        # revised['guitar_readability_revision'] = {'version': 1, 'normal_entry_replacement_allowed': False,
        revised['guitar_readability_revision'] = {'version': POLICY['version'], 'normal_entry_replacement_allowed': False,
                                                'previous_music_acceptance_invalidated': bool(edits)}
        revised['music_acceptance'] = {**deepcopy(project.get('music_acceptance', {})), 'status': 'needs_review',
                                       'guitar_readability': 'requires_actual_product_validation'}
        return revised, audit
    # 吉他既有规则闭环修复：新增和弦选取前即绑定实际循环密度，声学低音约束不能凭空增加换握。
    source_vocal_for_density = [n for n in old['notes'] if n.get('section') == 'vocal' and n.get('role') != 'instrumental_melody']
    density_before_plan = defaultdict(list)
    for phrase in phrases:
        starts = {n['start_tick'] for n in source_vocal_for_density if phrase['start_tick'] <= n['start_tick'] < phrase['end_tick']}
        density_before_plan[phrase['family_id']].append(len(starts) / max(1, (phrase['end_tick'] - phrase['start_tick']) / 480))
    planned_steps = {family: 120 if float(np.median(values)) >= 3.25 else 240 for family, values in density_before_plan.items()}
    evidence.pattern_periods = [(p['start_tick'], p['end_tick'], planned_steps[p['family_id']] * 4) for p in phrases]
    plans, bar_audit = {}, []
    for measure in timeline:
        # 慢拍单位与两曲最小修订：新增明确保留模式只规划违规和弦小节；好小节不因模型低音冲突被整曲重配。
        if preserve_performed_harmony and measure['number'] not in chord_bad:
            plans[measure['number']] = [{**deepcopy(h), 'start_tick': max(measure['start_tick'], h['start_tick']),
                'end_tick': min(measure['end_tick'], h['end_tick']), 'readable_source_chord_id': h['id']}
                for h in harmony if h.get('name') != 'N.C.' and
                _overlap(measure['start_tick'], measure['end_tick'], h['start_tick'], h['end_tick'])]
            bar_audit.append({'status': 'preserved_existing_compliant_harmony', 'measure': measure['number']})
            continue
        plans[measure['number']], audit = _plan_bar(harmony, measure, evidence)
        bar_audit.append(audit)
    # 慢拍单位与两曲最小修订：修改保留模式不为共享乐句牵连好小节；真正长段复用在最终实音上另行规划。
    # shared_bars, variants = _share_harmony(phrases, timeline, plans, harmony, evidence)
    shared_bars, variants = ([], []) if preserve_performed_harmony else _share_harmony(phrases, timeline, plans, harmony, evidence)
    recompose = set(violations)
    for row in shared_bars:
        recompose.update(row['measures'])
    for measure in timeline:
        if measure['number'] not in recompose:
            # 吉他既有规则闭环修复：新增合规旧实音必须沿用同一有效和弦，不能只改标注。
            plans[measure['number']] = [{**deepcopy(h), 'start_tick': max(measure['start_tick'], h['start_tick']),
                                         'end_tick': min(measure['end_tick'], h['end_tick']),
                                         'readable_source_chord_id': h['id']} for h in harmony
                                        if h.get('name') != 'N.C.' and _overlap(measure['start_tick'], measure['end_tick'], h['start_tick'], h['end_tick'])]
    readable_harmony = []
    for measure in timeline:
        for row in plans[measure['number']]:
            row['id'] = f'readable_harmony_{len(readable_harmony) + 1:04d}'
            row['start_seconds'], row['end_seconds'] = evidence.clock.seconds(row['start_tick']), evidence.clock.seconds(row['end_tick'])
            row['readable_measure'] = measure['number']
            readable_harmony.append(row)
    protected = [n for n in old['notes'] if n.get('section') != 'vocal' or n.get('role') == 'instrumental_melody']
    rendered, timing_edits = _quantize_instrumental(protected, total)
    occupied = defaultdict(list)
    for note in rendered:
        occupied[note['string']].append(note)
    source_vocal = [n for n in old['notes'] if n.get('section') == 'vocal' and n.get('role') != 'instrumental_melody']
    kept_vocal = [n for n in source_vocal if not any(m['number'] in recompose and m['start_tick'] <= n['start_tick'] < m['end_tick'] for m in timeline)]
    rendered.extend(deepcopy(kept_vocal))
    for note in kept_vocal:
        # 吉他既有规则闭环修复：新增跨入修改小节的合规持续音占弦，不能在同弦叠加新模板。
        occupied[note['string']].append(note)
    # 吉他既有规则闭环修复：新增每自然乐句选择一次密度，相似句族共用，独立音头不触发换型。
    density = {}
    for phrase in phrases:
        starts = {n['start_tick'] for n in source_vocal if phrase['start_tick'] <= n['start_tick'] < phrase['end_tick']}
        rate = len(starts) / max(1, (phrase['end_tick'] - phrase['start_tick']) / 480)
        density.setdefault(phrase['family_id'], []).append(rate)
    steps = {f: 120 if float(np.median(values)) >= 3.25 else 240 for f, values in density.items()}
    diagrams, regions, cache, rhythms = [], [], {}, []
    source_intervals = [(s['start_tick'], s['end_tick']) for s in shared.get('sections', []) if s.get('kind') == 'vocal']
    for row in readable_harmony:
        start, end = row['start_tick'], row['end_tick']
        if row['readable_measure'] not in recompose:
            # 吉他既有规则闭环修复：新增合规小节保留实际演奏和指型，不因为进入新路线重排它。
            for old_chart in old.get('fingering_diagrams', []):
                if _overlap(start, end, old_chart['start_tick'], old_chart['end_tick']):
                    diagrams.append({**deepcopy(old_chart), 'start_tick': max(start, old_chart['start_tick']),
                                     'end_tick': min(end, old_chart['end_tick']), 'id': f'readable_kept_grip_{len(diagrams)}'})
            regions.append({'id': f'readable_region_{len(regions)}', 'start_tick': start, 'end_tick': end,
                            'mode': 'chord_grip' if diagrams and diagrams[-1]['start_tick'] < end and diagrams[-1]['end_tick'] > start else 'solo_tab',
                            'section': 'vocal', 'chord_id': row['id'], 'reason': 'already_compliant_material_preserved'})
            continue
        # 吉他既有规则闭环修复：新增真实唱段活动约束，原有整段休止不得被模板机械填满。
        local = [n for n in source_vocal if _overlap(start, end, n['start_tick'], n['end_tick'])]
        if not local:
            regions.append({'id': f'readable_region_{len(regions)}', 'start_tick': start, 'end_tick': end,
                            'mode': 'solo_tab', 'section': 'instrumental', 'chord_id': row['id'], 'reason': 'preserve_instrumental'})
            continue
        phrase = next((p for p in phrases if p['start_tick'] <= start < p['end_tick']), None)
        family = phrase['family_id'] if phrase else 'unclassified_source_vocal'
        step = steps.get(family, 240)
        shape = deepcopy(_shape(row, old, start, cache))
        strings = _pattern_strings(shape, row)
        # 吉他既有规则闭环修复：新增整拍起止的持握，不把声母或段落标签的细边界当成换和弦。
        active_start = max(start, math.ceil(min(n['start_tick'] for n in local) / 120) * 120)
        active_end = min(end, max(n['end_tick'] for n in local))
        active_end = max(active_start + 120, min(end, round(active_end / 120) * 120))
        if row.get('shared_template_id'):
            # 吉他既有规则闭环修复：新增原伴奏连续活动见证后统一完整循环，真实静默槽仍保留。
            quarter_energy = [evidence.at(t, min(end, t + 480)).get('accompaniment_rms', 0.) for t in range(start, end, 480)]
            if quarter_energy and min(quarter_energy) >= max(.001, float(np.median(quarter_energy)) * .15):
                active_start, active_end = start, end
                row['shared_full_pattern_evidence'] = {'minimum_source_rms': min(quarter_energy),
                                                      'median_source_rms': float(np.median(quarter_energy))}
        count = 0
        for tick in range(start, end, step):
            if tick < active_start or tick >= active_end:
                continue
            string = strings[(tick - start) // step % len(strings)]
            # 吉他既有规则闭环修复：新增上声部共用型的实拨弦重写；首拍后每个槽弹实际不同高弦，非改低音角色名。
            if row.get('readable_bass_pattern') == 'first_attack_only' and tick > start:
                upper_cycle = row['readable_common_upper_strings']
                string = upper_cycle[((tick - start) // step - 1) % len(upper_cycle)]
            finish = min(end, tick + step)
            if any(_overlap(tick, finish, n['start_tick'], n['end_tick']) for n in occupied[string]):
                continue
            fret = shape['frets'][str(string)]
            note = {'id': f'readable_guitar_{row["id"]}_{tick}', 'pitch_midi': TUNING[string] + shape['capo'] + fret,
                    'string': string, 'fret': fret, 'finger': shape.get('fingers', {}).get(string, 0 if fret == 0 else 1),
                    'hand_position': max(1, shape.get('position', 1)), 'role': 'bass' if string == strings[0] else 'harmony',
                    'section': 'vocal', 'start_tick': tick, 'end_tick': finish,
                    'velocity': 76 if string == strings[0] else 62, 'chord_id': row['id'],
                    'source': 'existing_harmony_source_bounded_readable_pattern',
                    'source_attack_seconds': evidence.clock.seconds(tick),
                    'readable_source_note_ids': [n['id'] for n in local], 'readable_template_family': family,
                    'right_hand_duration_ticks': finish - tick, 'right_hand_duration_source': 'readable_phrase_pattern'}
            rendered.append(note)
            count += 1
        if count:
            # 吉他既有规则闭环修复：修改整行图式持握不能越过真实器乐过门，旧固定范围保留。
            # chart = {**shape, 'id': f'readable_grip_{len(diagrams) + 1}', 'start_tick': start, 'end_tick': end,
            chart = {**shape, 'id': f'readable_grip_{len(diagrams) + 1}', 'start_tick': start, 'end_tick': active_end,
                     'chord_id': row['id'], 'source': 'existing_low_position_or_same_harmony_shape',
                     'reason': 'readable_beat_aligned_actual_notes'}
            diagrams.append(chart)
            regions.append({'id': f'readable_region_{len(regions)}', 'start_tick': start, 'end_tick': end,
                            'mode': 'chord_grip', 'section': 'vocal', 'chord_id': row['id'], 'reason': 'actual_stable_grip'})
            # 吉他既有规则闭环修复：修改审计区分实际的一次低音共用型与正常循环型。
            # rhythms.append({'start_tick': start, 'end_tick': end, 'family_id': family, 'step_ticks': step,
            #                 'pattern_id': 'bass_upper_return', 'actual_note_count': count})
            rhythms.append({'start_tick': start, 'end_tick': end, 'family_id': family, 'step_ticks': step,
                            'pattern_id': 'one_initial_bass_then_common_upper' if row.get('readable_bass_pattern') == 'first_attack_only' else 'bass_upper_return',
                            'actual_note_count': count})
    rendered.sort(key=lambda n: (n['start_tick'], n['string'], n['id']))
    # 吉他既有规则闭环修复：新增保留祖先审计资料但撤销陈旧的“当前已通过”字段。
    stale = ('attack_events', 'chord_charts', 'regular_rhythm', 'right_hand_patterns', 'phrase_harmony_performance',
             'structure_stability', 'grip_fingerings', 'grip_hand_positions', 'grip_position_rate', 'source_rhythm_evidence')
    guitar['readability_ancestor_evidence'] = {k: deepcopy(old[k]) for k in stale if k in old}
    guitar['readability_ancestor_evidence']['notes'] = deepcopy(old['notes'])
    for key in stale:
        guitar.pop(key, None)
    # 吉他既有规则闭环修复：修改直接保存图式的旧式，合并真实连续相同持握。
    # guitar.update(notes=rendered, readable_harmony=readable_harmony, fingering_diagrams=diagrams,
    guitar.update(notes=rendered, readable_harmony=readable_harmony, fingering_diagrams=_merge_diagrams(diagrams),
                  notation_regions=regions, readable_reuse={'phrases': phrases, 'shared_bars': shared_bars,
                  'variants': variants, 'rhythm_plans': rhythms, 'source_evidence_required': True})
    guitar['configuration']['maximum_fret'] = 12
    guitar['quality_status'] = 'readable_arrangement_requires_source_and_music_review'
    # 吉他既有规则闭环修复：新增新数据的实际持握路径，无法覆盖时停止，不删图掩盖不合格编配。
    from guitar_grip_policy import grip_position_path
    path = grip_position_path(guitar, vocal)
    if path['valid']:
        guitar['hand_positions'] = path['positions']
    audit = {'status': 'arranged_requires_acceptance', 'policy': deepcopy(POLICY),
             'requirements': ['R10', 'R11', 'R15', 'R17', 'R18', 'R24', 'R25', 'R34', 'R37', 'R39'],
             'measure_harmony': bar_audit, 'instrumental_timing_edits': timing_edits,
             'changed_bars': [{'measure': number, 'reasons': violations.get(number, []) +
                              (['source_compatible_shared_phrase'] if any(number in r['measures'] for r in shared_bars) else [])}
                             for number in sorted(recompose)],
             'preserved_compliant_vocal_note_count': len(kept_vocal), 'whole_vocal_rearrangement': False,
             'protected_instrumental_count': len(protected), 'source_vocal_note_count': len(source_vocal),
             'new_vocal_note_count': len(rendered) - len(protected), 'shared_bars': shared_bars,
             'preserved_variants': variants, 'grip_path': {k: v for k, v in path.items() if k != 'positions'},
             'source_evidence_mode': 'bound_audio_features' if source_features else 'bound_original_seconds_windows',
             'accepted_vocal_unchanged': revised['accepted_vocal_project'] == project['accepted_vocal_project'],
             'shared_analysis_unchanged': revised['shared_analysis'] == project['shared_analysis'],
             'piano_unchanged': revised['arrangements'].get('piano') == project['arrangements'].get('piano')}
    # 吉他既有规则闭环修复：修改实际修订版本，与参数上下文签名共同防止旧策略假幂等。
    # guitar['guitar_readability_revision'] = {'version': 1, 'input_material_sha256': _fingerprint(old['notes']),
    guitar['guitar_readability_revision'] = {'version': POLICY['version'], 'input_material_sha256': _fingerprint(old['notes']),
                                           'context_sha256': context_signature,
                                           'output_note_sha256': _fingerprint(rendered), 'audit': audit}
    # revised['guitar_readability_revision'] = {'version': 1, 'normal_entry_replacement_allowed': False,
    revised['guitar_readability_revision'] = {'version': POLICY['version'], 'normal_entry_replacement_allowed': False,
                                            'previous_music_acceptance_invalidated': True}
    revised['music_acceptance'] = {**deepcopy(project.get('music_acceptance', {})), 'status': 'needs_review',
                                   'guitar_readability': 'requires_actual_product_validation'}
    return revised, audit
