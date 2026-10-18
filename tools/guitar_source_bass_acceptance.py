"""吉他编配规则闭环修复：独立核对新增实际低音与原低音的冲突证据。"""
# 吉他编配规则闭环修复：新增全曲差分验收；不解码新音高、不重选和弦、不按歌曲名分支。
from collections import Counter, defaultdict
from copy import deepcopy
import hashlib
import json
import numpy as np
from accompaniment_analysis import SongClock
from guitar_capo import capo_at

# 吉他编配规则闭环修复：修改低声部身份策略，旧仅看role的门槛失效，必须重验真实弦品音区。
# POLICY = {'version': 1, 'minimum_interval_seconds': .15,
# 慢拍单位与两曲最小修订：修改差分版本，逐身份检查新增前沿／尾音；保留旧阈值，旧验收需重放。
# POLICY = {'version': 2, 'minimum_interval_seconds': .15,
POLICY = {'version': 3, 'minimum_interval_seconds': .15,
          'old_relative_support_at_least': .65, 'new_relative_support_below': .25,
          'bass_low_midi': 24, 'bass_high_midi': 59,
          'attack_skip_seconds': .02, 'attack_window_seconds': .25,
          'upper_voice_maximum_string': 3, 'upper_voice_minimum_gap_semitones': 7,
          'bass_identity_uses_physical_grip_and_original_low_voice': True}
# 慢拍单位与两曲最小修订：新增历史原样重导的封存规则；只接收完整音乐摘要未变的旧v2，不用于新单位修订。
LEGACY_POLICY = {**POLICY, 'version': 2}


def _fingerprint(value):
    # 吉他编配规则闭环修复：新增与共同验收一致的规范摘要，结果不包含自身，避免循环绑定。
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(',', ':'), allow_nan=True).encode('utf-8')).hexdigest()


def _harmony(project):
    # 吉他编配规则闭环修复：新增独立读取实际吉他和声；不复用编配选择器及其评分。
    guitar = project['arrangements']['guitar']
    if 'readable_harmony' in guitar:
        return guitar['readable_harmony']
    from phrase_harmony_plan import arrangement_view
    return arrangement_view(project['shared_analysis'], project['accepted_vocal_project'])['harmony']


def source_bass_music_fingerprint(project):
    # 吉他编配规则闭环修复：新增公共接口，完全绑定真实人声拍轴、吉他音符及实际和声。
    return _fingerprint({'vocal': project['accepted_vocal_project'],
                         'guitar': project['arrangements']['guitar'], 'harmony': _harmony(project)})


def _source(project):
    # 吉他编配规则闭环修复：新增只读原低音绑定，缺轨不能伪装成零冲突。
    return project.get('shared_analysis', {}).get('input_binding', {}).get('sources', {}).get('bass')


# 吉他编配规则闭环修复：修改旧role独断式，保留以说明被反例证明的缺口。
# def _bass_notes(project):
#     return sorted((n for n in project['arrangements']['guitar']['notes'] if n.get('role') == 'bass'),
#                   key=lambda n: (n['start_tick'], n['pitch_midi'], n['end_tick']))
def _bass_notes(project, reference_notes=None, identity_audit=None):
    # 吉他编配规则闭环修复：新增物理身份联合原低音语境；真上声部须有实际指型与至少五度的音区证据。
    tuning = {6: 40, 5: 45, 4: 50, 3: 55, 2: 59, 1: 64}
    guitar = project['arrangements']['guitar']
    notes = guitar['notes']
    prior = reference_notes if reference_notes is not None else [n for n in notes if n.get('role') == 'bass']
    output = []
    for note in notes:
        tick, pitch, string = note['start_tick'], int(note['pitch_midi']), note.get('string')
        capo = capo_at(guitar, tick)
        minima = []
        for chart in guitar.get('fingering_diagrams', []):
            if not chart['start_tick'] <= tick < chart['end_tick']:
                continue
            frets = {int(s): int(f) for s, f in chart.get('frets', {}).items() if int(f) >= 0 and int(s) in tuning}
            if (string in frets and frets[string] == note.get('fret')
                    and tuning[string] + capo + frets[string] == pitch):
                minima.append(min(tuning[s] + capo + fret for s, fret in frets.items()))
        grip_lowest = bool(minima and pitch <= max(minima))
        verified_upper = bool(minima and string <= POLICY['upper_voice_maximum_string']
                              and all(pitch - value >= POLICY['upper_voice_minimum_gap_semitones'] for value in minima))
        # 吉他编配规则闭环修复：新增把真实换到高三弦的音排除；同一个低音改role不会改变其弦品或指型最低音。
        if verified_upper and not grip_lowest:
            if identity_audit is not None:
                identity_audit['verified_upper_voice_ids'].append(note.get('id'))
            continue
        # 吉他编配规则闭环修复：新增普通分解的中声部识别；持握内非最低音不因独立拨响就变成低音。
        # 高三弦/五度是新共用型的明确上声部证据；普通四弦和声音同样不能按原bass时点误判根音。
        if minima and not grip_lowest:
            if identity_audit is not None:
                identity_audit['higher_grip_voice_ids'].append(note.get('id'))
            continue
        old_active = [n for n in prior if n['start_tick'] <= tick < n['end_tick']]
        # 吉他编配规则闭环修复：新增无持握图的器乐高声部证据；实际高弦在原活动低声部上方五度，不因微调时刻变成根低音。
        upper_over_original = bool(not minima and string in tuning and string <= POLICY['upper_voice_maximum_string']
                                   and tuning[string] + capo + note.get('fret', -100) == pitch
                                   and any(n.get('string', 0) > string and pitch - n['pitch_midi'] >=
                                           POLICY['upper_voice_minimum_gap_semitones'] for n in old_active))
        if upper_over_original:
            if identity_audit is not None:
                identity_audit['verified_upper_voice_ids'].append(note.get('id'))
            continue
        bass_context = bool(old_active and pitch <= max(n['pitch_midi'] for n in old_active)
                            + POLICY['upper_voice_minimum_gap_semitones'])
        if note.get('role') == 'bass' or grip_lowest or bass_context:
            output.append(note)
            if identity_audit is not None and note.get('role') != 'bass':
                identity_audit['physically_inferred_bass_ids'].append(note.get('id'))
    return sorted(output, key=lambda n: (n['start_tick'], n['pitch_midi'], n['end_tick']))


def _current(rows, tick):
    # 吉他编配规则闭环修复：新增独立实际区间查找，不能把后续和弦提前当作当前证据。
    return next((h for h in rows if h['start_tick'] <= tick < h['end_tick']), None)


def _added_sound_intervals(new_notes, original_notes):
    # 慢拍单位与两曲最小修订：新增一对一原音身份匹配，只剔除真实保留的同音发声交集；新增尾音同样必须受检。
    # 不能只比较起音而漏掉延长，也不能把旧和声音改判为低音后误报其完整旧时值为新增。
    available = set(range(len(original_notes)))
    by_id, by_attack = defaultdict(list), defaultdict(list)
    for index, note in enumerate(original_notes):
        if note.get('id') is not None:
            by_id[note['id']].append(index)
        by_attack[(note['start_tick'], note['pitch_midi'])].append(index)
    output = []
    for note in new_notes:
        matching = [i for i in by_id.get(note.get('id'), []) if i in available
                    and original_notes[i]['pitch_midi'] == note['pitch_midi']]
        if not matching:
            matching = [i for i in by_attack[(note['start_tick'], note['pitch_midi'])] if i in available]
        prior = None
        if matching:
            index = min(matching, key=lambda i: abs(original_notes[i]['end_tick'] - note['end_tick']))
            available.remove(index)
            prior = original_notes[index]
        a, b = note['start_tick'], note['end_tick']
        overlap = (max(a, prior['start_tick']), min(b, prior['end_tick'])) if prior else (b, a)
        pieces = [(a, b)] if overlap[0] >= overlap[1] else [(a, overlap[0]), (overlap[1], b)]
        for start, end in pieces:
            if end > start:
                output.append({**note, 'start_tick': start, 'end_tick': end,
                               'actual_attack_tick': a, 'full_candidate_end_tick': b,
                               'retained_original_id': prior.get('id') if prior else None,
                               'interval_kind': 'added_sound' if prior else 'new_note'})
    return output


def assess_changed_bass_source(project, baseline_project, bass_features=None):
    """比较全曲实际低音变化；相对声学支持仅用于拦截明显冲突，不代表正确率。"""
    # 吉他编配规则闭环修复：新增先绑定真实材料，再独立判断原音；通过标记不能来自编配器自评。
    old_harmony, new_harmony = _harmony(baseline_project), _harmony(project)
    # 吉他编配规则闭环修复：修改新低音同时参照原低声部，不能通过重命名角色绕过独立源证据。
    # old_notes, new_notes = _bass_notes(baseline_project), _bass_notes(project)
    identity_audit = {'physically_inferred_bass_ids': [], 'verified_upper_voice_ids': [], 'higher_grip_voice_ids': []}
    old_notes = _bass_notes(baseline_project)
    new_notes = _bass_notes(project, old_notes, identity_audit)
    old_source, source = _source(baseline_project), _source(project)
    clock = SongClock(project['accepted_vocal_project'])
    old_clock = SongClock(baseline_project['accepted_vocal_project'])
    total = project['accepted_vocal_project']['statistics']['total_ticks']
    boundaries = sorted({0, total} | {max(0, min(total, h[k])) for rows in (old_harmony, new_harmony)
                                      for h in rows for k in ('start_tick', 'end_tick')})
    # 慢拍单位与两曲最小修订：修改旧只比起音的差分，完整旧实现注释保留。
    # signature = lambda note: (note['start_tick'], note['pitch_midi'])
    # 吉他编配规则闭环修复：新增全体原实音的差分保护；新身份推断不能把未变器乐旋律当新增低音。
    # existing = Counter(signature(n) for n in old_notes)
    # existing = Counter(signature(n) for n in baseline_project['arrangements']['guitar']['notes'])
    # old_by_id = {n.get('id'): n for n in old_notes if n.get('id') is not None}
    # changed = []
    # for note in new_notes:
    #     identity = signature(note)
    #     if existing[identity]: existing[identity] -= 1
    #     else: changed.append(note)
    changed = _added_sound_intervals(new_notes, baseline_project['arrangements']['guitar']['notes'])
    errors, unresolved, rows = [], [], []
    source_sha = source.get('sha256') if source else None
    # 吉他编配规则闭环修复：修改验收版本跟随实际身份策略，旧通过不能覆盖新物理低声部判定。
    # result = {'version': 1, 'policy': deepcopy(POLICY), 'valid': False, 'status': 'needs_review',
    result = {'version': POLICY['version'], 'policy': deepcopy(POLICY), 'valid': False, 'status': 'needs_review',
              'input_music_sha256': source_bass_music_fingerprint(project),
              'baseline_input_music_sha256': source_bass_music_fingerprint(baseline_project),
              'source_sha256': source_sha, 'baseline_source_sha256': old_source.get('sha256') if old_source else None,
              'source_binding_sha256': _fingerprint(source),
              'source': deepcopy(source), 'scope': 'changed_actual_bass_source_conflict_diagnostic_not_music_accuracy',
              'full_song_evaluated': True, 'total_ticks': total, 'changed_bass_attacks': len(changed),
              'changed_intervals': rows, 'errors': errors, 'unresolved': unresolved,
              'applicable': False, 'source_features_used': False, 'bass_identity': identity_audit}
    # 吉他编配规则闭环修复：新增联合所有旧/新和声边界，始终检查同一原曲秒窗。
    for left, right in zip(boundaries, boundaries[1:]):
        old, new = _current(old_harmony, left), _current(new_harmony, left)
        # 慢拍单位与两曲最小修订：修改必须审计新增延音跨过的每个和声区间，不能只看攻击所在和弦。
        # attacks = [n for n in changed if left <= n['start_tick'] < right]
        attacks = [{**n, 'start_tick': max(left, n['start_tick']), 'end_tick': min(right, n['end_tick'])}
                   for n in changed if n['start_tick'] < right and n['end_tick'] > left]
        if old is None or new is None:
            if attacks:
                unresolved.append({'reason': 'changed_bass_has_no_complete_harmony_reference', 'ticks': [left, right]})
            continue
        old_pc = int(old.get('bass_pc', old['root_pc'])) % 12
        new_pc = int(new.get('bass_pc', new['root_pc'])) % 12
        groups = defaultdict(list)
        for note in attacks:
            actual_pc = int(note['pitch_midi']) % 12
            if actual_pc != old_pc:
                # 吉他编配规则闭环修复：新增原身份同音的微小时移只审新增前沿，不能把30ms规整当整拍换根音。
                end = min(right, note['end_tick'])
                # 慢拍单位与两曲最小修订：删除仅适用于旧bass身份的截前沿式，已在完整原音一对一差分中处理。
                # prior = old_by_id.get(note.get('id'))
                # if prior and prior['pitch_midi'] == note['pitch_midi'] and note['start_tick'] < prior['start_tick']:
                #     end = min(end, prior['start_tick'])
                groups[(actual_pc, end)].append(note)
        # 吉他编配规则闭环修复：新增保留无新攻击的和声变化信息，但不会凭和弦文字变化认定实际冲突。
        if old_pc != new_pc and not groups:
            rows.append({'ticks': [left, right], 'source_seconds': [clock.seconds(left), clock.seconds(right)],
                         'old_chord': old.get('name'), 'new_chord': new.get('name'),
                         'old_bass_pc': old_pc, 'new_harmony_bass_pc': new_pc,
                         'actual_new_bass_attacks': [], 'substantial_new_source_conflict_clue': False,
                         'observation': 'no_changed_actual_bass_attack'})
        for (actual_pc, end), actual in groups.items():
            start = max(left, min(n['start_tick'] for n in actual))
            sa, sb = clock.seconds(start), clock.seconds(end)
            row = {'ticks': [start, end], 'source_seconds': [sa, sb], 'duration_seconds': sb - sa,
                   'old_chord': old.get('name'), 'new_chord': new.get('name'),
                   'old_bass_pc': old_pc, 'new_harmony_bass_pc': new_pc, 'actual_new_bass_pc': actual_pc,
                   'actual_new_bass_attacks': [{'id': n.get('id'), 'start_tick': n['start_tick'],
                                               'pitch_midi': n['pitch_midi'], 'source_seconds': clock.seconds(n['start_tick'])}
                                              for n in actual], 'substantial_new_source_conflict_clue': False}
            row['reference_kind'] = 'old_harmony_bass'
            rows.append(row)
    # 吉他编配规则闭环修复：新增与旧实际低音活动区间取并集，标签没变也能发现转位被错误改写。
    for note in changed:
        start, end = note['start_tick'], note['end_tick']
        # 慢拍单位与两曲最小修订：修改按所有旧实音起止分窗，新增尾音后来碰上的原低音也不能漏审。
        # old_active = [n for n in old_notes if n['start_tick'] <= start < n['end_tick']]
        # for old_pc in sorted({int(n['pitch_midi']) % 12 for n in old_active} - {int(note['pitch_midi']) % 12}):
        overlapping = [n for n in old_notes if n['start_tick'] < end and n['end_tick'] > start
                       and int(n['pitch_midi']) % 12 != int(note['pitch_midi']) % 12]
        for prior in overlapping:
            start, end = max(note['start_tick'], prior['start_tick']), min(note['end_tick'], prior['end_tick'])
            old_pc = int(prior['pitch_midi']) % 12
            old_active = [prior]
            old = _current(old_harmony, start)
            new = _current(new_harmony, start)
            # 慢拍单位与两曲最小修订：修改原实音比较限于真实重叠，旧音停止后不能继续冒充持续的原低音。
            # rows.append({'ticks': [start, end], 'source_seconds': [clock.seconds(start), clock.seconds(end)],
            #              'duration_seconds': clock.seconds(end) - clock.seconds(start),
            overlap_end = min(end, max(n['end_tick'] for n in old_active if int(n['pitch_midi']) % 12 == old_pc))
            rows.append({'ticks': [start, overlap_end], 'source_seconds': [clock.seconds(start), clock.seconds(overlap_end)],
                         'duration_seconds': clock.seconds(overlap_end) - clock.seconds(start),
                         'old_chord': old.get('name') if old else None, 'new_chord': new.get('name') if new else None,
                         'old_bass_pc': old_pc,
                         'new_harmony_bass_pc': int(new.get('bass_pc', new['root_pc'])) % 12 if new else None,
                         'actual_new_bass_pc': int(note['pitch_midi']) % 12,
                         'reference_kind': 'old_actual_sounding_bass',
                         'old_actual_bass_ids': [n.get('id') for n in old_active if int(n['pitch_midi']) % 12 == old_pc],
                         'actual_new_bass_attacks': [{'id': note.get('id'), 'start_tick': start,
                                                     'pitch_midi': note['pitch_midi'], 'source_seconds': clock.seconds(start)}],
                         'substantial_new_source_conflict_clue': False})
    # 吉他编配规则闭环修复：新增首端和完整发声双窗；后半拍转根不能掩盖起音时的提前根音。
    onset_rows = []
    for row in rows:
        if not row['actual_new_bass_attacks']:
            continue
        row['observation_window_kind'] = 'whole_actual_overlap'
        sa, sb = row['source_seconds']
        attack_left, attack_right = sa + POLICY['attack_skip_seconds'], min(sb, sa + POLICY['attack_window_seconds'])
        if attack_right - attack_left >= POLICY['minimum_interval_seconds'] - 1e-9:
            onset = deepcopy(row)
            onset.update(observation_window_kind='actual_attack_onset', actual_interval_source_seconds=[sa, sb],
                         source_seconds=[attack_left, attack_right], duration_seconds=attack_right - attack_left)
            onset_rows.append(onset)
    rows.extend(onset_rows)
    # 吉他编配规则闭环修复：新增统一评估两类独立参照，窗口是实际新低音的发声部分而非标签总长度。
    for row in rows:
        if not row['actual_new_bass_attacks']:
            continue
        start, end = row['ticks']
        sa, sb = row['source_seconds']
        old_pc, actual_pc = row['old_bass_pc'], row['actual_new_bass_pc']
        if sb - sa < POLICY['minimum_interval_seconds'] - 1e-9:
            row['observation'] = 'change_shorter_than_diagnostic_interval'
            continue
        result['applicable'] = True
        if abs(old_clock.seconds(start) - clock.seconds(start)) > 1e-7 or abs(old_clock.seconds(end) - clock.seconds(end)) > 1e-7:
            unresolved.append({'reason': 'baseline_and_candidate_source_clock_differ', 'ticks': [start, end]})
            continue
        if (not source_sha or not old_source or old_source.get('sha256') != source_sha
                or float(old_source.get('offset_seconds', 0.)) != float(source.get('offset_seconds', 0.))):
            unresolved.append({'reason': 'bass_source_missing_or_changed', 'ticks': [start, end]})
            continue
        if bass_features is None:
            unresolved.append({'reason': 'bound_bass_features_required_for_changed_bass', 'ticks': [start, end]})
            continue
        if (bass_features.source.get('sha256') != source_sha
                or float(bass_features.source.get('offset_seconds', 0.)) != float(source.get('offset_seconds', 0.))):
            unresolved.append({'reason': 'bass_feature_source_sha_mismatch', 'ticks': [start, end]})
            continue
        times = np.asarray(bass_features.times)
        tolerance = float(np.median(np.diff(times))) if len(times) > 1 else 0.
        if not len(times) or sa < float(times[0]) - tolerance or sb > float(times[-1]) + tolerance:
            unresolved.append({'reason': 'changed_bass_outside_observed_source', 'ticks': [start, end]})
            continue
        chroma = np.asarray(bass_features.chroma(sa, sb, POLICY['bass_low_midi'], POLICY['bass_high_midi']), dtype=float)
        if chroma.shape != (12,) or not np.isfinite(chroma).all() or float(chroma.max()) <= 1e-9:
            unresolved.append({'reason': 'changed_bass_source_has_no_usable_pitch_evidence', 'ticks': [start, end]})
            continue
        result['source_features_used'] = True
        peak = float(chroma.max())
        old_support, new_support = float(chroma[old_pc] / peak), float(chroma[actual_pc] / peak)
        conflict = old_support >= POLICY['old_relative_support_at_least'] and new_support < POLICY['new_relative_support_below']
        row.update(source_bass_chroma=list(map(float, chroma)),
                   old_bass_source_relative_support=old_support, new_bass_source_relative_support=new_support,
                   strongest_source_bass_pc=int(np.argmax(chroma)),
                   substantial_new_source_conflict_clue=conflict,
                   observation='strong_old_weak_new_source_conflict' if conflict else 'no_threshold_conflict_observed')
        if conflict:
            errors.append('new_actual_bass_conflicts_with_strong_original_bass')
    result['errors'] = sorted(set(errors))
    result['valid'] = not result['errors'] and not unresolved
    result['status'] = 'passed' if result['valid'] else 'needs_review'
    result['conclusion'] = ('not_applicable_no_substantial_changed_bass' if not result['applicable'] and result['valid']
                            else 'no_threshold_conflict_observed' if result['valid'] else 'source_bass_review_required')
    result['conflict_interval_count'] = sum(bool(r['substantial_new_source_conflict_clue']) for r in rows)
    result['conflict_attack_ids'] = sorted({str(n.get('id')) for r in rows if r['substantial_new_source_conflict_clue']
                                           for n in r['actual_new_bass_attacks']})
    result['conflict_attack_count'] = len(result['conflict_attack_ids'])
    return result


def require_changed_bass_source(project, assessment):
    # 吉他编配规则闭环修复：新增交付硬门槛，不能复用旧音符摘要、旧来源或不同阈值的通过状态。
    if not assessment or assessment.get('valid') is not True or assessment.get('status') != 'passed':
        raise ValueError('原低音独立验收未通过，新增低音须复核，不能交付替换。')
    # 吉他编配规则闭环修复：修改旧固定验收版本，物理身份策略升级后的旧flag必须失效。
    # if assessment.get('version') != 1 or assessment.get('policy') != POLICY or not assessment.get('full_song_evaluated'):
    # 慢拍单位与两曲最小修订：修改兼容旧音乐原样重放；新单位修订必须v3，后面的实际音乐与来源摘要仍逐一校验。
    # if assessment.get('version') != POLICY['version'] or assessment.get('policy') != POLICY or not assessment.get('full_song_evaluated'):
    current = assessment.get('version') == POLICY['version'] and assessment.get('policy') == POLICY
    legacy = (assessment.get('version') == LEGACY_POLICY['version'] and assessment.get('policy') == LEGACY_POLICY
              and not project.get('meter_unit_revision')
              and not project.get('accepted_vocal_project', {}).get('meter_unit_correction'))
    if not (current or legacy) or not assessment.get('full_song_evaluated'):
        raise ValueError('原低音独立验收规则或全曲范围不完整。')
    if assessment.get('input_music_sha256') != source_bass_music_fingerprint(project):
        raise ValueError('原低音独立验收已失效：实际拍轴、吉他或和声已改变。')
    source = _source(project)
    if assessment.get('source_sha256') != (source.get('sha256') if source else None):
        raise ValueError('原低音独立验收已失效：来源SHA已经改变。')
    if assessment.get('source_binding_sha256') != _fingerprint(source):
        raise ValueError('原低音独立验收已失效：原声来源绑定或秒偏移已经改变。')
    return assessment
