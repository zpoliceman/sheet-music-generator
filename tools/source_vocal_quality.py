"""原声覆盖与选音归属通用修复：在量化前检查漏音和相邻字的真实音段归属。"""
# 原声覆盖与选音归属通用修复：新增独立质量版本，不修改原f0、音素和历史音段文件。
from copy import deepcopy
import hashlib
import numpy as np
from musical_decode import AcousticEvidence
from score_export import read_json
from vocal_continuity import SourceVerifier

POLICY = {'version': 1, 'minimum_core_seconds': .12, 'minimum_core_quarters': .25,
          'minimum_support': .85, 'minimum_yin_agreement': .80,
          'minimum_vocal_dbfs': -50., 'minimum_foreground_ratio_db': -9.,
          'minimum_nucleus_overlap_seconds': .08, 'owner_overlap': .72,
          'wrong_owner_overlap': .20, 'minimum_word_quarters': .20,
          'minimum_split_quarters': .06, 'song_specific_rules': False}

# 字音唯一挂词音保护通用修复：新增质量v2，音素重叠不能删除某字唯一的计量挂词音；旧v1严格重放。
COVERAGE_POLICY = {**deepcopy(POLICY), 'version': 2,
                   'last_metered_word_owner_preserved_without_replacement': True,
                   'ambiguous_ownership_recorded_not_silently_certified': True}


# 原声覆盖与选音归属通用修复：新增不可信音素窗保护，不能用缺失行或极短字窗覆盖真实唱音。
def reliable_character(char, period):
    flags = set(char.get('review_flags', []))
    return (char['end_seconds'] - char['start_seconds'] >= period * POLICY['minimum_word_quarters']
            and 'asr_missing_line' not in flags
            and any(p.get('role') == 'nucleus' and not p.get('skipped') for p in char.get('phonemes', [])))


def overlap(note, char):
    return max(0., min(note['end_seconds'], char['end_seconds']) - max(note['start_seconds'], char['start_seconds']))


# 原声覆盖与选音归属通用修复：新增强重叠归属纠正，保留原挂词身份，短滑音不再抢走下一字。
# 字音唯一挂词音保护通用修复：修改签名，原入口保留；新质量版本才启用挂词完整性保护。
# def repair_owners(notes, characters, period, evidence):
def repair_owners(notes, characters, period, evidence, protect_coverage=False):
    chars = {c['index']: c for c in characters}
    output = deepcopy(notes); audit = []
    # 字音唯一挂词音保护通用修复：修改逐个计数方式，原代码保留；整组候选先判覆盖，避免先搬前音再留后音造成逆序。
    # counts = {index: sum(n.get('lyric_index') == index and not n.get('grace') for n in output) for index in chars}
    transfers = set(); owned = {}
    if protect_coverage:
        for n in output:
            index = n.get('lyric_index'); current = chars.get(index)
            if n.get('grace') or current is None: continue
            owned.setdefault(index, []).append(n['id'])
            if not reliable_character(current, period): continue
            candidates = [c for c in characters if c.get('line_index') == current.get('line_index')
                          and abs(c['index'] - index) <= 1 and reliable_character(c, period)]
            winner = max(candidates, key=lambda c: overlap(n, c)); duration = n['end_seconds'] - n['start_seconds']
            if (winner['index'] != index and overlap(n, winner) >= duration * POLICY['owner_overlap']
                    and overlap(n, current) <= duration * POLICY['wrong_owner_overlap']):
                transfers.add(n['id'])
    protected_words = {index for index, ids in owned.items() if all(identity in transfers for identity in ids)}
    for n in output:
        index = n.get('lyric_index'); current = chars.get(index)
        if current is None or not reliable_character(current, period):
            continue
        duration = n['end_seconds'] - n['start_seconds']
        candidates = [c for c in characters if c.get('line_index') == current.get('line_index')
                      and abs(c['index'] - index) <= 1 and reliable_character(c, period)]
        winner = max(candidates, key=lambda c: overlap(n, c))
        if (winner['index'] != index and overlap(n, winner) >= duration * POLICY['owner_overlap']
                and overlap(n, current) <= duration * POLICY['wrong_owner_overlap']):
            # 字音唯一挂词音保护通用修复：新增最后一个挂词音的保护，保留已绑定来源的旧归属并明确记为音素冲突。
            # 字音唯一挂词音保护通用修复：修改逐个迁移门槛，原式保留；没有替代计量音时整组保留源归属。
            # if protect_coverage and not n.get('grace') and counts[index] <= 1:
            if protect_coverage and not n.get('grace') and index in protected_words:
                audit.append({'id': n['id'], 'old_owner': index, 'proposed_owner': winner['index'],
                              'action': 'retain_only_metered_owner_phoneme_conflict',
                              'evidence': 'phoneme_overlap_without_replacement_for_original_word',
                              'requires_ownership_review': True})
                continue
            n.setdefault('source_lyric_index', index)
            n.update(lyric_index=winner['index'], line_index=winner['line_index'])
            # 字音唯一挂词音保护通用修复：修改删除逐次计数，原代码保留；迁移前已检查整组覆盖。
            # if not n.get('grace'):
            #     counts[index] -= 1; counts[winner['index']] += 1
            audit.append({'id': n['id'], 'old_owner': index, 'new_owner': winner['index'],
                          'evidence': 'dominant_adjacent_phoneme_overlap'})
    # 原声覆盖与选音归属通用修复：新增有声短前缀分音；只修后字抢走的前字尾音，拒绝向不可信下一字强切。
    result = []
    for n in output:
        index = n.get('lyric_index'); char = chars.get(index)
        previous = chars.get(index - 1) if index is not None else None
        split = bool(char and previous and reliable_character(char, period) and reliable_character(previous, period)
                     and char['line_index'] == previous['line_index']
                     and abs(previous['end_seconds'] - char['start_seconds']) <= .10 * period
                     and char['start_seconds'] - n['start_seconds'] >= period * POLICY['minimum_split_quarters']
                     and n['end_seconds'] - char['start_seconds'] >= period * .12
                     and n['start_seconds'] >= previous['start_seconds'] - .02)
        if split:
            a, b = np.searchsorted(evidence.times, [n['start_seconds'], char['start_seconds']])
            split = b > a and np.mean(np.isfinite(evidence.midi[a:b])) >= .75
        if split:
            boundary = char['start_seconds']; tail = deepcopy(n)
            tail.update(id=n['id'] + '.quality_word_' + str(index), start_seconds=boundary)
            n.setdefault('source_lyric_index', index)
            n.update(end_seconds=boundary, lyric_index=index - 1, line_index=previous['line_index'])
            audit.append({'id': n['id'], 'tail_id': tail['id'], 'old_owner': index,
                          'new_owner': index - 1, 'boundary_seconds': boundary,
                          'evidence': 'adjacent_phonemes_with_short_voiced_prefix'})
            result.extend([n, tail])
        else:
            result.append(n)
    return result, audit


# 原声覆盖与选音归属通用修复：新增全窗口漏音检查，首音和尾音同等检查，不要求已经存在同字前音。
def uncovered_cores(evidence, characters, existing, period):
    covered = sorted((n['start_seconds'], n['end_seconds']) for n in existing)
    for char in characters:
        if not reliable_character(char, period):
            continue
        nucleus = next(p for p in char['phonemes'] if p.get('role') == 'nucleus' and not p.get('skipped'))
        # 原声覆盖与选音归属通用修复：修改，颤音延伸遇到另一稳定半音平台必须停止，避免混成一个恢复音。
        # for core in evidence.cores(char['start_seconds'], char['end_seconds']):
        cores = evidence.cores(char['start_seconds'], char['end_seconds'])
        for core in cores:
            # 原声覆盖与选音归属通用修复：新增稳定平台的连续滑入／颤音边界，不能只补后半段平直元音。
            core = deepcopy(core)
            left, right = np.searchsorted(evidence.times, [core['start_seconds'], core['end_seconds']])
            # 原声覆盖与选音归属通用修复：新增独立稳定音的屏障，弱短滑入与真实相邻半音分别处理。
            others = [c for c in cores if c['pitch_midi'] != core['pitch_midi'] and c['support'] >= .85
                      and c['end_seconds'] - c['start_seconds'] >= .12]
            lower = max([char['start_seconds']] + [c['end_seconds'] for c in others if c['end_seconds'] <= core['start_seconds']])
            upper = min([char['end_seconds']] + [c['start_seconds'] for c in others if c['start_seconds'] >= core['end_seconds']])
            while (left > 0 and evidence.times[left - 1] >= lower
                   and np.isfinite(evidence.midi[left - 1])
                   and abs(evidence.midi[left - 1] - core['pitch_midi']) <= 1.1):
                left -= 1
            # 原声覆盖与选音归属通用修复：修改，原整个字窗延伸保留；限定到下一独立稳定唱音前。
            # while (right < len(evidence.times) and evidence.times[right] < char['end_seconds']
            while (right < len(evidence.times) and evidence.times[right] < upper
                   and np.isfinite(evidence.midi[right])
                   and abs(evidence.midi[right] - core['pitch_midi']) <= 1.1):
                right += 1
            core.update(start_seconds=float(evidence.times[left]),
                        end_seconds=float(evidence.times[right - 1] + evidence.step))
            core['support'] = float(np.mean(abs(evidence.midi[left:right] - core['pitch_midi']) <= 1.1))
            intervals = [(core['start_seconds'], core['end_seconds'])]
            for a, b in covered:
                intervals = [(x, y) for left, right in intervals for x, y in
                             ((left, min(right, a)), (max(left, b), right)) if y > x] if any(
                                 left < b and right > a for left, right in intervals) else intervals
            for a, b in intervals:
                if (b - a < max(POLICY['minimum_core_seconds'], period * POLICY['minimum_core_quarters'])
                        or core['support'] < POLICY['minimum_support']
                        or min(b, nucleus['end_seconds']) - max(a, nucleus['start_seconds'])
                           < POLICY['minimum_nucleus_overlap_seconds']):
                    continue
                yield char, {**core, 'start_seconds': a, 'end_seconds': b}


# 原声覆盖与选音归属通用修复：新增来源可重放的准备层；每个补音均通过原人声和完整伴奏的独立核验。
# 字音唯一挂词音保护通用修复：修改准备签名，原入口保留；历史v1不启用新归属保护。
# def prepare_quality_vocal(base, binding, timing, verifier=None):
def prepare_quality_vocal(base, binding, timing, verifier=None, protect_coverage=False):
    analysis = read_json(base['inputs']['notes_path'])
    evidence = AcousticEvidence(analysis, verify_audio=False)
    period = 60 / timing['steady_tempo_bpm']
    # 字音唯一挂词音保护通用修复：修改归属准备，原调用保留；无新开关的旧策略音乐和证据保持。
    # notes, owners = repair_owners(base['quantized_notes'], base['lyrics']['characters'], period, evidence)
    notes, owners = repair_owners(base['quantized_notes'], base['lyrics']['characters'], period, evidence, protect_coverage=True) if protect_coverage else repair_owners(base['quantized_notes'], base['lyrics']['characters'], period, evidence)
    verifier = verifier if verifier is not None else SourceVerifier(binding, analysis)
    recovered = []; checks = []
    for char, core in uncovered_cores(evidence, base['lyrics']['characters'], notes, period):
        # 原声覆盖与选音归属通用修复：新增平台扩展后的重叠去重，颤音两侧稳定点属于同一个恢复音。
        if any(n['start_seconds'] < core['end_seconds'] and n['end_seconds'] > core['start_seconds'] for n in recovered):
            continue
        check = verifier(core)
        accepted = (check.get('independent_source_audio_checked') is True
                    and check['yin_agreement'] >= POLICY['minimum_yin_agreement']
                    and check['vocal_dbfs'] >= POLICY['minimum_vocal_dbfs']
                    and check['foreground_ratio_db'] >= POLICY['minimum_foreground_ratio_db'])
        row = {'character_index': char['index'], 'core': core, 'independent_audio': check,
               'action': 'recover_uncovered_voiced_core' if accepted else 'reject_weak_or_bleed'}
        checks.append(row)
        if accepted:
            # 原声覆盖与选音归属通用修复：新增同字同音连续尾段合并，不能补成原唱没有的第二次MIDI重发。
            previous = next((n for n in reversed(notes) if n.get('lyric_index') == char['index']
                and n.get('source_pitch_midi', n['pitch_midi']) == core['pitch_midi']
                and abs(n['end_seconds'] - core['start_seconds']) <= evidence.step * 1.5), None)
            if previous is not None:
                row.update(action='extend_same_pitch_continuation', previous_note_id=previous['id'],
                           previous_end_seconds=previous['end_seconds'])
                previous['end_seconds'] = core['end_seconds']
                previous['source_quality_continuation'] = deepcopy(row)
                continue
            identity = repr((char['index'], core['start_seconds'], core['end_seconds'], core['pitch_midi']))
            # 原声覆盖与选音归属通用修复：修改，新增源身份供量化账本完整核验。
            # recovered.append({'id': 'source_quality_' + hashlib.sha256(identity.encode()).hexdigest()[:16],
            note_id = 'source_quality_' + hashlib.sha256(identity.encode()).hexdigest()[:16]
            recovered.append({'id': note_id, 'source_note_id': note_id,
                'start_seconds': core['start_seconds'], 'end_seconds': core['end_seconds'],
                'pitch_midi': core['pitch_midi'], 'source_pitch_midi': core['pitch_midi'],
                'lyric_index': char['index'], 'line_index': char['line_index'], 'role': 'main',
                'anchor': True, 'grace': False, 'confidence': core['support'], 'review_flags': [],
                'recovery_provenance': deepcopy(row)})
    output = deepcopy(base)
    output['quantized_notes'] = sorted(notes + recovered, key=lambda n: (n['start_seconds'], n['id']))
    # 字音唯一挂词音保护通用修复：修改新策略账本，原政策保留；归属不确定性随完整来源证据交付。
    # audit = {'policy': deepcopy(POLICY), 'owner_changes': owners, 'coverage_checks': checks,
    audit = {'policy': deepcopy(COVERAGE_POLICY if protect_coverage else POLICY), 'owner_changes': owners, 'coverage_checks': checks,
             'recovered_note_count': len(recovered), 'original_source_files_unchanged': True}
    output['source_vocal_quality'] = deepcopy(audit)
    return output, audit
