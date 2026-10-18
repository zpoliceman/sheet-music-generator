"""相似乐句和弦框架复用：从音乐骨干与多轨证据共同选择实际伴奏进行。"""
# 相似乐句和弦框架复用：新增通用派生层；不读取曲名、歌词文本、参考图或人工和弦表。
from __future__ import annotations
from collections import defaultdict
from copy import deepcopy
import hashlib
import json
import math
import numpy as np
from accompaniment_analysis import CHORD_TYPES, SongClock, chord_name
from score_export import PPQ

POLICY = {'version': 1, 'name': 'joint_melodic_phrase_harmony',
          'pitch_close_semitones': 3, 'minimum_pitch_support': .85,
          'minimum_activity_support': .68, 'minimum_onset_support': .64,
          'minimum_shared_cells': 6, 'maximum_phrase_bars': 8,
          # 相似乐句和弦框架复用：新增短句严格音高门槛，避免不同音级的一小节句误归同组。
          'coarse_similarity_minimum_quarters': 12, 'short_phrase_pitch_tolerance': 1,
          # 相似乐句和弦框架复用：修改，旧统一换弦代价过度跨小节持有；按音乐强弱边界分层。
          # 'change_cost': .85, 'weak_boundary_cost': .25,
          # 'reuse_root_cost': .65, 'reuse_quality_cost': .18,
          'change_cost': .85, 'bar_change_cost': .28, 'half_bar_change_cost': .48, 'weak_boundary_cost': .25,
          'reuse_root_cost': .38, 'reuse_quality_cost': .18,
          # 相似乐句和弦框架复用：新增持续性质音的软约束，共同先验不能抹掉已独立见证的三音/七音。
          'supported_character_omission_cost': .25,
          'maximum_variant_positions_per_four_bars': 2,
          'bass_hold_support': .60, 'raw_evidence_is_accuracy': False,
          'reference_score_used_as_input': False}
QUALITY_COST = {'': 0., 'm': 0., '7': .12, 'm7': .10, 'maj7': .14,
                'sus2': .28, 'sus4': .20, '5': .20, 'dim': .14, 'aug': .20,
                'm7b5': .26, 'dim7': .26, '6': .25, 'm6': .25,
                'add9': .38, 'madd9': .38, '9': .55, 'maj9': .58,
                'm9': .55, '7sus4': .38}


# 相似乐句和弦框架复用：新增确定性指纹；源和声、拍轴、段落或人声改变时禁止沿用旧计划。
def fingerprint(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                   separators=(',', ':')).encode('utf-8')).hexdigest()


def shared_fingerprint(shared):
    # 相似乐句和弦框架复用：修改，旧证据集合保留；源文件绑定和音乐地标变化同样使计划过期。
    # return fingerprint({k: shared.get(k) for k in
    #                     ('harmony', 'harmony_windows', 'sections', 'timing', 'statistics', 'notation')})
    return fingerprint({k: shared.get(k) for k in
                        # 相似乐句和弦框架复用：修改，旧字段行保留。
                        # ('harmony', 'harmony_windows', 'sections', 'timing', 'statistics', 'notation')})
                        ('harmony', 'harmony_windows', 'sections', 'timing', 'statistics', 'notation',
                         'input_binding', 'melodic_motif_matches')})


# 相似乐句和弦框架复用：新增认可旋律、拍轴与调性联合指纹，改标题/歌词文本不会重配音乐。
def vocal_fingerprint(vocal):
    return fingerprint({k: vocal.get(k) for k in ('quantized_notes', 'timing', 'notation')})


# 相似乐句和弦框架复用：新增统一实际和声视图；原shared.harmony保持声学审计。
def arrangement_view(shared, vocal=None):
    # 原声覆盖与选音归属通用修复：新增来源绑定的认可和声视图；原声学分析与基础共同计划仍保存。
    if shared.get('approved_section_preservation'):
        return {**shared, 'harmony': shared['approved_section_preservation']['harmony'], '_phrase_harmony_view': True}
    if shared.get('_phrase_harmony_view') or 'arranged_harmony' not in shared:
        return shared
    plan = shared.get('phrase_harmony_plan', {})
    if plan.get('version') != POLICY['version'] or plan.get('source_shared_sha256') != shared_fingerprint(shared):
        raise ValueError('乐句和弦计划的源证据/拍轴已改变，必须明确重新编配。')
    # 相似乐句和弦框架复用：修改，原仅音符摘要保留；物理拍轴及调性也必须与方案一致。
    # if vocal is not None and plan.get('source_vocal_sha256') != fingerprint(vocal['quantized_notes']):
    # 人声连续音值与长休止漏音通用修复：修改，旧直接拒绝保留；仅来源严格重建的局部修复可明确保留已认可伴奏。
    # if vocal is not None and plan.get('source_vocal_sha256') != vocal_fingerprint(vocal):
    #     raise ValueError('乐句和弦计划的人声骨干已改变，禁止沿用。')
    if vocal is not None and plan.get('source_vocal_sha256') != vocal_fingerprint(vocal):
        from vocal_continuity_project import accompaniment_revision_compatible
        if not accompaniment_revision_compatible(plan, vocal):
            raise ValueError('乐句和弦计划的人声骨干已改变，禁止沿用。')
    return {**shared, 'harmony': shared['arranged_harmony'], '_phrase_harmony_view': True}


# 相似乐句和弦框架复用：新增主音/转音的音乐活动；装饰不作为短和弦强制依据。
def melodic_notes(vocal):
    return [n for n in vocal.get('quantized_notes', [])
            if n.get('lyric_index') is not None and not n.get('grace')]


def line_anchors(vocal, bar):
    grouped = defaultdict(list)
    for note in melodic_notes(vocal):
        grouped[note.get('line_index', 0)].append(note)
    # 相似乐句和弦框架复用：新增弱起归属；后半小节的句头定位到接下来的音乐小节。
    return {i: {'tick': math.floor(min(n['start_tick'] for n in ns)/bar+.5)*bar,
                'span': max(n['end_tick'] for n in ns)-min(n['start_tick'] for n in ns)}
            for i, ns in grouped.items()}


def key_at(shared, tick):
    window = next((w for w in shared.get('harmony_windows', [])
                   if w['start_tick'] <= tick < w['end_tick']), None)
    if window:
        return window['key']
    chord = next((h for h in shared['harmony'] if h['start_tick'] <= tick < h['end_tick']), None)
    return chord['key'] if chord else shared['notation']['key']


# 相似乐句和弦框架复用：新增相对调性的有声/休止/起音轮廓，允许正常经过音与移调。
def melody_signature(shared, vocal, start, end):
    grid = max(1, PPQ//4)
    notes = [n for n in melodic_notes(vocal) if n['start_tick'] < end and n['end_tick'] > start]
    pitch, activity, onset = [], [], []
    for tick in range(start, end, grid):
        found = [n for n in notes if n['start_tick'] < tick+grid and n['end_tick'] > tick]
        if not found:
            pitch.append(None); activity.append(0); onset.append(0)
            continue
        main = max(found, key=lambda n: (n.get('role') == 'main',
                   min(tick+grid, n['end_tick'])-max(tick, n['start_tick'])))
        pitch.append((main['pitch_midi']-key_at(shared, tick)['tonic_pc']) % 12)
        activity.append(1)
        onset.append(int(any(tick <= n['start_tick'] < tick+grid for n in found)))
    return {'pitch': pitch, 'activity': activity, 'onset': onset}


def similarity(left, right):
    if len(left['pitch']) != len(right['pitch']):
        return {'accepted': False, 'reason': 'different_musical_duration'}
    pairs = [(a, b) for a, b in zip(left['pitch'], right['pitch']) if a is not None and b is not None]
    if (len(pairs) < POLICY['minimum_shared_cells']
            or min(len({p[0] for p in pairs}), len({p[1] for p in pairs})) < 3):
        return {'accepted': False, 'reason': 'insufficient_distinct_melody'}
    # 相似乐句和弦框架复用：修改，旧全句三半音门槛保留；短句不能以邻近音级替代精确骨干。
    # close = sum(min(abs(a-b), 12-abs(a-b)) <= POLICY['pitch_close_semitones'] for a, b in pairs)/len(pairs)
    tolerance = POLICY['pitch_close_semitones'] if len(left['pitch'])/4 >= POLICY['coarse_similarity_minimum_quarters'] else POLICY['short_phrase_pitch_tolerance']
    close = sum(min(abs(a-b), 12-abs(a-b)) <= tolerance for a, b in pairs)/len(pairs)
    activity = sum(a == b for a, b in zip(left['activity'], right['activity']))/len(left['pitch'])
    onset = sum(a == b for a, b in zip(left['onset'], right['onset']))/len(left['pitch'])
    return {'accepted': close >= POLICY['minimum_pitch_support']
            and activity >= POLICY['minimum_activity_support'] and onset >= POLICY['minimum_onset_support'],
            'pitch_support': close, 'activity_support': activity, 'onset_support': onset,
            'shared_cells': len(pairs), 'confidence_is_accuracy': False}


# 相似乐句和弦框架复用：新增相邻重复地标间隔推断句长；不以排版或固定四小节分句。
# 跨曲低音与强拍复用通用修复：修改，原函数签名保留；新策略显式回退，避免递归和历史改写。
# def phrase_ranges(shared, vocal):
def phrase_ranges(shared, vocal, source_aware=True):
    # 跨曲低音与强拍复用通用修复：新增仅有效低音新版启用完整终止乐句，历史音乐地标策略保留。
    if source_aware and shared.get('method', {}).get('harmonic_source_quality', {}).get('version') == 2:
        from phrase_harmony_source import phrase_ranges as source_ranges
        return source_ranges(shared, vocal)
    bar = shared['statistics']['bar_ticks']; anchors = line_anchors(vocal, bar)
    matches = defaultdict(list)
    for match in shared.get('melodic_motif_matches', []):
        a = anchors.get(match['reference_line']); b = anchors.get(match['target_line'])
        if a and b and b['tick'] > a['tick']:
            matches[(b['tick']-a['tick'], round(match.get('transpose', 0)))].append((a, b))
    seeds = set()
    for pairs in matches.values():
        pairs = sorted(pairs, key=lambda pair: pair[0]['tick'])
        for i, (a, b) in enumerate(pairs):
            length = bar
            if a['span'] > bar and i+1 < len(pairs):
                gap = pairs[i+1][0]['tick']-a['tick']
                if bar <= gap <= POLICY['maximum_phrase_bars']*bar:
                    length = gap
            for item in (a, b):
                seeds.add((item['tick'], item['tick']+length))
    sections = [s for s in shared.get('sections', []) if s['kind'] == 'vocal']
    bounds = [k['start_tick'] for k in vocal.get('notation', {}).get('key_segments', [])[1:]]
    result = []
    for section in sections:
        # 跨歌曲和弦复用与器乐准备：修改，旧任意发声边界保留；倚音借时／源秒不作为整句换弦的周期原点。
        # start, end = section['start_tick'], section['end_tick']
        pulse = int(PPQ*4/shared['timing']['meter'][1])
        start = math.ceil(section['start_tick']/pulse)*pulse
        # 跨歌曲和弦复用与器乐准备：修正唱段尾拍，原向下取整会冻结旧合成伴奏碎片；有源伴奏的最后拍由共同框架重编。
        # end = math.floor(section['end_tick']/pulse)*pulse
        end = min(shared['statistics']['total_ticks'], math.ceil(section['end_tick']/pulse)*pulse)
        if end <= start:
            continue
        chosen = []
        for a, b in sorted(seeds, key=lambda ab: (-(ab[1]-ab[0]), ab[0])):
            if start <= a < b <= end and not any(a < y and b > x for x, y in chosen):
                chosen.append((a, b))
        cursor = start; ranges = []
        for a, b in sorted(chosen)+[(end, end)]:
            if cursor < a:
                # 相似乐句和弦框架复用：新增未匹配前缀/桥段，按实际空隙成句，长空隙才用歌词音乐锚点细分。
                cuts = [cursor]
                while a-cuts[-1] > POLICY['maximum_phrase_bars']*bar:
                    possible = [x['tick'] for x in anchors.values()
                                if cuts[-1] < x['tick'] <= cuts[-1]+POLICY['maximum_phrase_bars']*bar]
                    cuts.append(max(possible, default=cuts[-1]+POLICY['maximum_phrase_bars']*bar))
                cuts.append(a); ranges.extend(zip(cuts, cuts[1:]))
            if a < b:
                ranges.append((a, b))
            cursor = b
        for a, b in ranges:
            cuts = sorted({a, b} | {k for k in bounds if a < k < b})
            result.extend(zip(cuts, cuts[1:]))
    return [{'id': f'phrase_{i+1:03}', 'start_tick': a, 'end_tick': b,
             'measures': list(range(a//bar+1, math.ceil(b/bar)+1)),
             'boundary_source': 'repeated_musical_landmarks_and_source_sections'}
            for i, (a, b) in enumerate(sorted(result))]


# 相似乐句和弦框架复用：新增每个成员对同一原型核查，不用相似关系的无条件传递闭包。
def phrase_families(shared, vocal, phrases):
    signatures = {p['id']: melody_signature(shared, vocal, p['start_tick'], p['end_tick']) for p in phrases}
    # 相似乐句和弦框架复用：新增字音核心序列，借拍/弱起改变采样格位时仍比较音乐单位。
    anchors = line_anchors(vocal, shared['statistics']['bar_ticks'])
    units = {}
    for phrase in phrases:
        grouped = defaultdict(list)
        included = {i for i, a in anchors.items() if phrase['start_tick'] <= a['tick'] < phrase['end_tick']}
        tonic = key_at(shared, phrase['start_tick'])['tonic_pc']
        for note in melodic_notes(vocal):
            if note.get('line_index', 0) in included:
                grouped[note['lyric_index']].append(note)
        units[phrase['id']] = [{'pitch': max(ns, key=lambda n: (n.get('role') == 'main', n['end_tick']-n['start_tick']))['pitch_midi']-tonic,
                               'onset_seconds': min(n.get('start_seconds', n['start_tick']/PPQ) for n in ns)}
                              for _, ns in sorted(grouped.items())]
    def check_pair(left, right):
        dense = similarity(signatures[left['id']], signatures[right['id']])
        if dense['accepted'] or left['end_tick']-left['start_tick'] != right['end_tick']-right['start_tick']:
            return dense
        # 跨曲低音与强拍复用通用修复：修改，原仅短句允许字音序列互核会漏掉完整重复长句；新来源策略复核实际音序而非放宽阈值。
        # if left['end_tick']-left['start_tick'] > 2*shared['statistics']['bar_ticks']:
        if (left['end_tick']-left['start_tick'] > 2*shared['statistics']['bar_ticks']
                and shared.get('method', {}).get('harmonic_source_quality', {}).get('version') != 2):
            return dense
        from melodic_structure import align_motifs
        match = align_motifs(units[left['id']], units[right['id']])
        # 相似乐句和弦框架复用：新增已按各句调性归一后的零/八度移位，禁止同调邻近音级冒充转调。
        if match and abs(match['transpose'] % 12) < .01:
            return {**match, 'accepted': True, 'method': 'source_unit_sequence', 'confidence_is_accuracy': False}
        return dense
    families = []
    for phrase in phrases:
        options = []
        for family in families:
            # 相似乐句和弦框架复用：修改，旧固定采样比较保留；短句增加核心序列互核，仍不做无条件传递。
            # checks = [similarity(signatures[p['id']], signatures[phrase['id']]) for p in family['members']]
            checks = [check_pair(p, phrase) for p in family['members']]
            if checks and all(check['accepted'] for check in checks):
                options.append((min(c['pitch_support'] for c in checks), family, checks))
        if options:
            _, family, checks = max(options, key=lambda item: item[0])
            family['members'].append(phrase); family['matches'].append({'phrase_id': phrase['id'], 'checks': checks})
        else:
            families.append({'id': f'phrase_family_{len(families)+1:03}', 'members': [phrase], 'matches': []})
    return families


# 相似乐句和弦框架复用：新增长主音/重拍辅助权重，允许短非和弦经过音而不逐音换弦。
# 相似乐句和弦框架复用：修改，保留旧入口；增加独立长主音证据，短经过音不打开整句变体。
# def voice_profile(vocal, start, end, tonic):
def voice_profile(vocal, start, end, tonic, stable=False):
    vector = np.zeros(12)
    for note in melodic_notes(vocal):
        # 相似乐句和弦框架复用：新增变体见证只使用真正持续主音，正常评分仍保留短旋律。
        if stable and (note.get('role') != 'main' or note['end_tick']-note['start_tick'] < PPQ):
            continue
        overlap = min(end, note['end_tick'])-max(start, note['start_tick'])
        if overlap <= 0:
            continue
        weight = 1. if note.get('role') == 'main' else .2
        if note['end_tick']-note['start_tick'] >= PPQ:
            weight *= 1.3
        vector[(note['pitch_midi']-tonic) % 12] += overlap*weight
    return vector/max(1e-9, vector.sum())


def phrase_evidence(shared, vocal, phrase, unit):
    rows = []
    for start in range(phrase['start_tick'], phrase['end_tick'], unit):
        end = min(phrase['end_tick'], start+unit); key = key_at(shared, start); tonic = key['tonic_pc']
        ws = [w for w in shared.get('harmony_windows', []) if w['start_tick'] < end and w['end_tick'] > start]
        chroma = np.zeros(12); bass = np.zeros(12); mass = 0.
        for window in ws:
            weight = min(end, window['end_tick'])-max(start, window['start_tick'])
            chroma += weight*np.roll(np.asarray(window.get('decoding_chroma', window['chroma']), dtype=float), -tonic)
            bass += weight*np.roll(np.asarray(window['bass_chroma'], dtype=float), -tonic); mass += weight
        if mass:
            chroma /= mass; bass /= mass
        # 相似乐句和弦框架复用：修改，旧记录注释保留；短音匹配与持续主音见证分开保存。
        # rows.append({'start_tick': start, 'end_tick': end, 'key': key,
        #              'chroma': chroma, 'bass': bass, 'voice': voice_profile(vocal, start, end, tonic)})
        rows.append({'start_tick': start, 'end_tick': end, 'key': key,
                     'chroma': chroma, 'bass': bass, 'voice': voice_profile(vocal, start, end, tonic),
                     'stable_voice': voice_profile(vocal, start, end, tonic, stable=True)})
    return rows


def basic_kind(quality):
    if quality in ('dim', 'dim7', 'm7b5'):
        return 'diminished'
    if quality == 'aug':
        return 'augmented'
    return 'minor' if quality.startswith('m') and not quality.startswith('maj') else 'major'


# 相似乐句和弦框架复用：新增调式敏感的通用和弦评分，短扩展与非常用复杂类型有记忆成本。
def candidate_scores(rows, candidates):
    scores = np.zeros((len(rows), len(candidates)))
    for i, row in enumerate(rows):
        mode = row['key'].get('mode', 'major')
        scale = {0, 2, 4, 5, 7, 9, 11} if mode == 'major' else {0, 2, 3, 5, 7, 8, 10} if mode == 'minor' else set(range(12))
        for j, (root, quality) in enumerate(candidates):
            intervals = CHORD_TYPES[quality]; pcs = [(root+x) % 12 for x in intervals]
            selected = row['chroma'][pcs]
            missing = sum(.14 if interval not in (0, 7) else .025
                          for interval, value in zip(intervals, selected) if value < .03)
            scores[i, j] = (2.3*selected.sum()+.6*selected.mean()-missing
                -.24*max(0, len(intervals)-3)-QUALITY_COST[quality]
                -.075*sum(pc not in scale for pc in pcs)
                +.35*row['bass'][root]+.65*row['bass'][pcs].sum()+.30*row['voice'][pcs].sum())
    return scores


# 相似乐句和弦框架复用：新增整句路径与可变拍位；小节/半小节是软偏好，真实短变化仍能胜出。
# 跨曲低音与强拍复用通用修复：修改，原函数签名保留；来源有效的新策略单独设置音乐边界代价。
# def decode_phrase(scores, candidates, ticks, bar, unit):
def decode_phrase(scores, candidates, ticks, bar, unit, source_aware=False):
    if not len(scores):
        return []
    count = len(candidates)
    transition = np.full((count, count), -POLICY['change_cost'])
    for i, (a, qa) in enumerate(candidates):
        for j, (b, qb) in enumerate(candidates):
            if i == j:
                transition[i, j] = 0.
            elif a == b:
                transition[i, j] -= .1
            elif (b-a) % 12 in (5, 7):
                transition[i, j] += .06
            # 跨曲低音与强拍复用通用修复：新增通用调内功能/五度运动先验，只在有真实低音的新版规划启用。
            if source_aware and i != j and ((a, b) in ((5, 7), (2, 7), (7, 0)) or (b-a) % 12 == 5):
                transition[i, j] += .18
            # 跨曲低音与强拍复用通用修复：新增分解低音歧义代价；拨到原和弦三/五/七音且没有新三音的挂留候选，不能轻易另立根音。
            if (source_aware and a != b and qb in ('sus2','sus4','5')
                    and (b-a)%12 in {x for x in CHORD_TYPES[qa] if x in (3,4,7,10,11)}):
                transition[i,j] -= .7
    costs = scores[0].copy(); traces = []
    for i in range(1, len(scores)):
        weak = 0. if ticks[i] % bar == 0 else .05 if ticks[i] % max(unit, bar//2) == 0 else POLICY['weak_boundary_cost']
        # 相似乐句和弦框架复用：修改，旧统一代价注释保留；小节边界允许有据换弦，避免吞并真实进行。
        # matrix = costs[:, None]+transition-weak*(~np.eye(count, dtype=bool))
        boundary_cost = POLICY['bar_change_cost'] if ticks[i] % bar == 0 else POLICY['half_bar_change_cost'] if ticks[i] % max(unit, bar//2) == 0 else POLICY['change_cost']
        # 跨曲低音与强拍复用通用修复：新增有效低音下的小节/半小节变化代价，弱位置仍按旧强稳定要求。
        if source_aware:
            boundary_cost = .14 if ticks[i] % bar == 0 else .12 if ticks[i] % max(unit, bar//2) == 0 else boundary_cost
        matrix = costs[:, None]+transition+(POLICY['change_cost']-boundary_cost-weak)*(~np.eye(count, dtype=bool))
        best = np.argmax(matrix, axis=0)
        costs = matrix[best, np.arange(count)]+scores[i]; traces.append(best)
    winner = int(np.argmax(costs)); selected = [winner]
    for trace in reversed(traces):
        winner = int(trace[winner]); selected.append(winner)
    return list(reversed(selected))


def bass_for(rows, candidate):
    # 相似乐句和弦框架复用：修改，原含静音平均注释保留；退出投票的弱窗不是新的低音。
    # root, quality = candidate; vector = np.mean([r['bass'] for r in rows], axis=0)
    root, quality = candidate; active = [r['bass'] for r in rows if r['bass'].sum() > .1]
    vector = np.mean(active, axis=0) if active else np.zeros(12)
    strongest = int(np.argmax(vector)); pcs = {(root+x) % 12 for x in CHORD_TYPES[quality]}
    # 相似乐句和弦框架复用：新增持续斜杠低音门槛，单拍经过低音不自动产生新和弦。
    # 相似乐句和弦框架复用：修改，旧只看平均保留；至少两个有效窗才把短经过低音写成整段转位。
    # return strongest if strongest in pcs and vector[strongest] >= POLICY['bass_hold_support'] else root
    return strongest if len(active) >= 2 and strongest in pcs and vector[strongest] >= POLICY['bass_hold_support'] else root


# 相似乐句和弦框架复用：新增局部变化的独立音乐见证；不能只凭同一评分器的少量分差变体。
def variant_witnesses(rows, joint_stable, prototype, candidates, index):
    root, quality = candidates[prototype[index]]
    pcs = {(root+x) % 12 for x in CHORD_TYPES[quality]}
    stable = rows[index]['stable_voice']
    voice = [pc for pc in range(12) if pc not in pcs and stable[pc] >= .45
             and stable[pc]-joint_stable[index][pc] >= .2]
    # 相似乐句和弦框架复用：新增连续至少两个实际低音窗，单拍/零质量低音不迫使换根音。
    neighbors = rows[max(0, index-1):min(len(rows), index+2)]
    active = [r['bass'] for r in neighbors if r['bass'].sum() > .1]
    bass = []
    if len(active) >= 2:
        vector = np.mean(active, axis=0)
        bass = [pc for pc in range(12) if pc not in pcs and vector[pc] >= POLICY['bass_hold_support']]
    # 相似乐句和弦框架复用：修改，旧仅人声/低音见证保留；同旋律同低音的真实大小和弦也可能不同。
    # return {'stable_melody_pitch_classes': voice, 'sustained_bass_pitch_classes': bass,
    #         'supported': bool(voice or bass)}
    opposing_third = (root+4) % 12 if basic_kind(quality) == 'minor' else (root+3) % 12
    current_third = (root+3) % 12 if basic_kind(quality) == 'minor' else (root+4) % 12
    thirds = []
    if current_third in pcs and basic_kind(quality) in ('major', 'minor'):
        clear = [r for r in neighbors if r['chroma'][root] >= .15 and r['chroma'][(root+7) % 12] >= .10
                 and r['chroma'][opposing_third] >= .23 and r['chroma'][current_third] <= .08]
        if len(clear) >= 2:thirds = [opposing_third]
    # 相似乐句和弦框架复用：新增重复根/三/五支持的持续七音见证，同旋律同低音的属七/大七不能被共用强抹平。
    sevenths = []
    if current_third in pcs and basic_kind(quality) in ('major', 'minor'):
        for interval, opponent in ((10, 11), (11, 10)):
            pc = (root+interval) % 12; other_pc = (root+opponent) % 12
            if pc in pcs:continue
            clear = [r for r in neighbors if r['chroma'][root] >= .15 and r['chroma'][current_third] >= .10
                     and r['chroma'][(root+7) % 12] >= .10 and r['chroma'][pc] >= .23
                     and (other_pc not in pcs or r['chroma'][other_pc] <= .08)]
            if len(clear) >= 2:sevenths.append(pc)
    return {'stable_melody_pitch_classes': voice, 'sustained_bass_pitch_classes': bass,
            # 相似乐句和弦框架复用：修改，旧只包含三音保留；长七音同样作为独立声学见证。
            # 'sustained_accompaniment_third_pitch_classes': thirds, 'supported': bool(voice or bass or thirds)}
            'sustained_accompaniment_third_pitch_classes': thirds,
            'sustained_accompaniment_seventh_pitch_classes': sevenths, 'supported': bool(voice or bass or thirds or sevenths)}


def path_segments(shared, phrase, rows, candidates, path, family, prototype):
    spans = []
    for i, choice in enumerate(path):
        if spans and spans[-1]['choice'] == choice:
            spans[-1]['indices'].append(i)
        else:
            spans.append({'choice': choice, 'indices': [i]})
    result = []
    for span in spans:
        indices = span['indices']; first, last = rows[indices[0]], rows[indices[-1]]
        relative_root, quality = candidates[span['choice']]; tonic = first['key']['tonic_pc']
        root = (relative_root+tonic) % 12; bass = (bass_for([rows[i] for i in indices], candidates[span['choice']])+tonic) % 12
        references = [h['id'] for h in shared['harmony'] if h['start_tick'] < last['end_tick'] and h['end_tick'] > first['start_tick']]
        result.append({'id': f"arranged_{phrase['id']}_{len(result)+1:02}",
            'root_pc': root, 'quality': quality, 'bass_pc': bass,
            'pitch_classes': [(root+x) % 12 for x in CHORD_TYPES[quality]],
            'name': chord_name(root, quality, bass, first['key']), 'key': deepcopy(first['key']),
            'start_tick': first['start_tick'], 'end_tick': last['end_tick'],
            'source_harmony_ids': references, 'phrase_id': phrase['id'], 'phrase_family_id': family,
            'requires_review': any(h.get('requires_review') for h in shared['harmony'] if h['id'] in references),
            'bass_is_inversion': bass != root, 'kind': 'joint_phrase_arrangement_not_raw_detection',
            'identity': [root, quality, bass], 'functional_root': relative_root,
            'prototype_choices': [candidates[prototype[i]] for i in indices]})
    return result


# 相似乐句和弦框架复用：新增共享规划；成员明显不兼容时独立变体，不为复用指标强制错误和声。
def build_phrase_harmony(shared, vocal):
    original = shared_fingerprint(shared)
    if not shared.get('harmony_windows') or not any(s['kind'] == 'vocal' for s in shared.get('sections', [])):
        return {'version': POLICY['version'], 'policy': deepcopy(POLICY), 'source_shared_sha256': original,
                # 相似乐句和弦框架复用：修改，旧单音符摘要保留；缺证据分支也绑定完整音乐状态。
                # 'source_vocal_sha256': fingerprint(vocal.get('quantized_notes', [])), 'phrases': [], 'families': [],
                'source_vocal_sha256': vocal_fingerprint(vocal), 'phrases': [], 'families': [],
                'status': 'preserve_original_missing_harmonic_evidence', 'arranged_harmony': deepcopy(shared['harmony'])}
    bar = shared['statistics']['bar_ticks']; denominator = shared['timing']['meter'][1]
    unit = int(PPQ*4/denominator); phrases = phrase_ranges(shared, vocal)
    # 跨曲低音与强拍复用通用修复：新增明确局部策略标记，不改变历史全局POLICY或已保存计划。
    source_aware = shared.get('method', {}).get('harmonic_source_quality', {}).get('version') == 2
    families = phrase_families(shared, vocal, phrases)
    candidates = [(root, quality) for root in range(12) for quality in CHORD_TYPES]
    evidence = {p['id']: phrase_evidence(shared, vocal, p, unit) for p in phrases}
    scores = {p['id']: candidate_scores(evidence[p['id']], candidates) for p in phrases}
    # 跨曲低音与强拍复用通用修复：新增性质音有据时参与共同规划，旧版本评分及历史计划保持。
    if shared.get('method', {}).get('harmonic_source_quality', {}).get('version') == 2:
        from phrase_harmony_source import source_scores
        scores = {p['id']: source_scores(evidence[p['id']], candidates, scores[p['id']]) for p in phrases}
    all_segments = []; audits = []; family_records = []
    # 相似乐句和弦框架复用：新增低质量/缺窗乐句保留实音，零谱能不能被候选顺序猜成C和弦。
    supported = {p['id'] for p in phrases if
                 sum(r['chroma'].sum() > .1 for r in evidence[p['id']]) >= max(2, math.ceil(len(evidence[p['id']])*.25))
                 and any(r['voice'].sum() > .1 for r in evidence[p['id']])}
    for family in families:
        for phrase in family['members']:
            if phrase['id'] in supported: continue
            spans = []
            for chord in shared['harmony']:
                a, b = max(chord['start_tick'], phrase['start_tick']), min(chord['end_tick'], phrase['end_tick'])
                if a >= b: continue
                item = deepcopy(chord)
                item.update(id=f"arranged_{phrase['id']}_preserve_{len(spans)+1:02}", start_tick=a, end_tick=b,
                            phrase_id=phrase['id'], phrase_family_id=family['id'],
                            functional_root=(chord['root_pc']-chord['key']['tonic_pc']) % 12,
                            source_harmony_ids=[chord['id']], kind='preserved_insufficient_harmonic_evidence')
                spans.append(item)
            all_segments.extend(spans)
            audits.append({**phrase, 'family_id': family['id'], 'action': 'preserve_source_insufficient_evidence',
                           'variants': [], 'variant_bar_positions': [], 'progression': []})
    for family in families:
        # 相似乐句和弦框架复用：修改，旧全成员投票保留；缺证据的成员不能拖动共同原型。
        # members = family['members']; base = members[0]; rows = evidence[base['id']]
        members = [p for p in family['members'] if p['id'] in supported]
        if not members: continue
        base = members[0]; rows = evidence[base['id']]
        joint = np.mean([scores[p['id']] for p in members], axis=0)
        # 跨曲低音与强拍复用通用修复：修改，旧统一稳定代价保留；新来源策略在所有候选路径一致启用。
        # prototype = decode_phrase(joint, candidates, [r['start_tick'] for r in rows], bar, unit)
        prototype = decode_phrase(joint, candidates, [r['start_tick'] for r in rows], bar, unit, source_aware=source_aware)
        # 相似乐句和弦框架复用：新增共同长主音证据，仅清晰旋律差异/重要低音允许局部改编。
        joint_stable = np.mean([[r['stable_voice'] for r in evidence[p['id']]] for p in members], axis=0)
        member_records = []
        for phrase in members:
            own = evidence[phrase['id']]; adjusted = scores[phrase['id']].copy()
            witnesses = [variant_witnesses(own, joint_stable, prototype, candidates, i) for i in range(len(own))]
            # 相似乐句和弦框架复用：新增有据变体按完整结构位置持有，长音结束后的休止不强制换回。
            witnessed_bars = defaultdict(list)
            for i, witness in enumerate(witnesses):
                if witness['supported']:
                    witnessed_bars[own[i]['start_tick']//bar].append((i, witness))
            for i, witness in enumerate(witnesses):
                origins = witnessed_bars.get(own[i]['start_tick']//bar, [])
                if not witness['supported'] and origins:
                    witnesses[i] = {'supported': True, 'sustained_structural_position': True,
                                    'source_offset_ticks': [j*unit for j, _ in origins],
                                    'witnesses': [deepcopy(w) for _, w in origins]}
            for i, common in enumerate(prototype):
                root, quality = candidates[common]
                for j, (other, q) in enumerate(candidates):
                    if other != root or basic_kind(q) != basic_kind(quality):
                        adjusted[i, j] -= POLICY['reuse_root_cost']
                    elif q != quality:
                        adjusted[i, j] -= POLICY['reuse_quality_cost']
                    # 相似乐句和弦框架复用：新增直接声学见证优先于简化成本，不再把清晰属七降成大三和弦。
                    witness_pcs = witnesses[i].get('sustained_accompaniment_third_pitch_classes', [])+witnesses[i].get(
                        'sustained_accompaniment_seventh_pitch_classes', [])
                    offered = {(other+x) % 12 for x in CHORD_TYPES[q]}
                    adjusted[i, j] -= POLICY['supported_character_omission_cost']*sum(pc not in offered for pc in witness_pcs)
                    # 相似乐句和弦框架复用：新增相似句默认实际共用，弱/短局部音不能独自推翻共同框架。
                    if len(members) > 1 and j != common and not witnesses[i]['supported']:
                        adjusted[i, j] = -math.inf
            # 跨曲低音与强拍复用通用修复：修改，原路径调用保留；实际成员与共同原型采用相同源约束。
            # path = decode_phrase(adjusted, candidates, [r['start_tick'] for r in own], bar, unit)
            path = decode_phrase(adjusted, candidates, [r['start_tick'] for r in own], bar, unit, source_aware=source_aware)
            differences = [i for i, (a, b) in enumerate(zip(path, prototype)) if candidates[a] != candidates[b]]
            positions = sorted({(i*unit)//bar for i in differences})
            maximum = max(1, math.ceil((phrase['end_tick']-phrase['start_tick'])/(4*bar))*POLICY['maximum_variant_positions_per_four_bars'])
            action = 'shared_progression' if not differences else 'supported_local_variant'
            if len(positions) > maximum:
                # 跨曲低音与强拍复用通用修复：修改，旧独立变体入口保留；真实来源差异不能被旧代价再次抹去。
                # path = decode_phrase(scores[phrase['id']], candidates, [r['start_tick'] for r in own], bar, unit)
                path = decode_phrase(scores[phrase['id']], candidates, [r['start_tick'] for r in own], bar, unit, source_aware=source_aware)
                action = 'independent_harmony_variant'
            segments = path_segments(shared, phrase, own, candidates, path, family['id'], prototype)
            all_segments.extend(segments)
            differences = [i for i, (a, b) in enumerate(zip(path, prototype)) if candidates[a] != candidates[b]]
            variants = [{'offset_tick': i*unit, 'prototype': list(candidates[prototype[i]]), 'chosen': list(candidates[path[i]]),
                         'local_score_gain': float(scores[phrase['id']][i, path[i]]-scores[phrase['id']][i, prototype[i]]),
                         # 相似乐句和弦框架复用：修改，原单一理由保留；输出独立长旋律/持续低音见证。
                         # 'reason': 'member_melody_and_accompaniment_support'} for i in differences]
                         'reason': 'member_melody_and_accompaniment_support', 'witness': witnesses[i]} for i in differences]
            record = {**phrase, 'family_id': family['id'], 'action': action, 'variants': variants,
                      'variant_bar_positions': sorted({(i*unit)//bar for i in differences}),
                      'progression': [{'offset_tick': h['start_tick']-phrase['start_tick'], 'duration_ticks': h['end_tick']-h['start_tick'],
                                       'root_degree_pc': h['functional_root'], 'quality': h['quality'], 'bass_pc': h['bass_pc'], 'name': h['name']} for h in segments]}
            audits.append(record); member_records.append({'phrase_id': phrase['id'], 'action': action})
        family_records.append({'id': family['id'], 'members': member_records, 'matches': family['matches'],
            'prototype': [{'offset_tick': i*unit, 'root_degree_pc': candidates[c][0], 'quality': candidates[c][1]} for i, c in enumerate(prototype)]})
    # 相似乐句和弦框架复用：新增器乐原分析片段保护，边界仅裁剪派生范围，不改原harmony字典。
    # 跨歌曲和弦复用与器乐准备：修改，旧整段发声范围保留；只替换完整拍乐句，边界不足一拍的原和声不丢失。
    # vocal_ranges = [(s['start_tick'], s['end_tick']) for s in shared['sections'] if s['kind'] == 'vocal']
    vocal_ranges = [(p['start_tick'], p['end_tick']) for p in phrases]
    outside = []
    for chord in shared['harmony']:
        pieces = [(chord['start_tick'], chord['end_tick'])]
        for a, b in vocal_ranges:
            remaining = []
            for x, y in pieces:
                if y <= a or x >= b:
                    remaining.append((x, y))
                else:
                    if x < a: remaining.append((x, a))
                    if b < y: remaining.append((b, y))
            pieces = remaining
        for i, (a, b) in enumerate(pieces):
            item = deepcopy(chord); item.update(start_tick=a, end_tick=b)
            if i: item['id'] += '_outside_'+str(i)
            outside.append(item)
    clock = SongClock(vocal)
    for chord in all_segments+outside:
        chord.update(start_seconds=clock.seconds(chord['start_tick']), end_seconds=clock.seconds(chord['end_tick']))
    # 原声覆盖与选音归属通用修复：新增共同框架的局部强低音守卫，源变化的实际拍界优先于复用偏好。
    from source_accompaniment_quality import enabled, guard_harmony
    bass_guard = []
    if enabled(shared):
        all_segments, bass_guard = guard_harmony(shared, vocal, sorted(all_segments, key=lambda h: h['start_tick']))
        # 原声覆盖与选音归属通用修复：新增真实守卫后进程审计；局部原低音修正不能仍宣称全部共用原型。
        for audit in audits:
            spans = [h for h in all_segments if h.get('phrase_id') == audit['id']]
            audit['progression'] = [{'offset_tick': h['start_tick'] - audit['start_tick'],
                'duration_ticks': h['end_tick'] - h['start_tick'], 'root_degree_pc':
                (h['root_pc'] - h['key']['tonic_pc']) % 12, 'quality': h['quality'],
                'bass_pc': h['bass_pc'], 'name': h['name']} for h in spans]
            guards = [g for g in bass_guard if audit['start_tick'] <= g['start_tick'] < audit['end_tick']]
            if guards:
                audit.update(action='source_bass_local_variant', source_bass_guard=guards)
                for family in family_records:
                    for member in family['members']:
                        if member['phrase_id'] == audit['id']:
                            member['action'] = audit['action']
    return {'version': POLICY['version'], 'policy': deepcopy(POLICY), 'source_shared_sha256': original,
            # 相似乐句和弦框架复用：修改，旧单音符摘要保留；联合音乐状态用于幂等/过期校验。
            # 'source_vocal_sha256': fingerprint(vocal['quantized_notes']), 'status': 'joint_phrase_arrangement_requires_listening',
            'source_vocal_sha256': vocal_fingerprint(vocal), 'status': 'joint_phrase_arrangement_requires_listening',
            'phrases': sorted(audits, key=lambda p: p['start_tick']), 'families': family_records,
            'arranged_harmony': sorted(all_segments+outside, key=lambda h: h['start_tick']),
            'unit_ticks': unit, 'source_harmony_count': len(shared['harmony']),
            'performed_harmony_count': len(all_segments+outside), 'lyrics_text_used': False,
            # 跨歌曲和弦复用与器乐准备：新增明确边界策略标记，历史无标记计划仍按原范围校验保护清单。
            # 'fixed_four_bar_phrasing': False}
            # 原声覆盖与选音归属通用修复：修改，旧计划无新增字段；新策略完整登记局部守卫以便确定重放。
            # 'fixed_four_bar_phrasing': False, 'beat_boundary_version': 1}
            'fixed_four_bar_phrasing': False, 'beat_boundary_version': 1,
            **({'source_bass_guard': bass_guard, 'source_coverage_quality_version': 1} if enabled(shared) else {})}
