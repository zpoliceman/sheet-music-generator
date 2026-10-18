"""人声连续音值与长休止漏音通用修复：复核原声局部平台及连续字尾，不改变拍轴。"""
from collections import defaultdict
from copy import deepcopy
import hashlib
import math

import numpy as np
from score_export import PPQ, TempoMap, attach_lyrics, read_json, sha256
from phrase_rhythm import duration_penalty, notation_events
from continuous_vocal_rhythm import review_locks
from rhythm_notation import validate_grouping

# 人声连续音值与长休止漏音通用修复：新增独立版本门限，音域／拍速适配；不读曲名或字词文本。
POLICY = {'version': 1, 'minimum_rest_seconds': .30, 'minimum_core_seconds': .18,
          'minimum_core_quarters': .25, 'minimum_pitch_support': .85,
          'minimum_yin_agreement': .80, 'minimum_vocal_dbfs': -50.,
          'minimum_foreground_ratio_db': -9., 'maximum_tail_bridge_quarters': .20,
          'maximum_lyric_tail_seconds': .18, 'minimum_nucleus_overlap_seconds': .12,
          'minimum_notated_gap_quarters': .25, 'minimum_tail_error_quarters': .18,
          'maximum_source_gap_quarters': .08, 'source_boundary_sigma_quarters': .125,
          # 人声连续音值与长休止漏音通用修复：修改，旧末项保留；真实短音用原细网格，同音休止尾段不新增重发。
          # 'ordinary_grid_ticks': 120, 'clock_preserved': True, 'reference_answers_used': False}
          'ordinary_grid_ticks': 120, 'fine_grid_for_preexisting_short_notes': True,
          'same_pitch_rest_tail_action': 'retain_for_duration_review',
          'clock_preserved': True, 'reference_answers_used': False}


# 人声连续音值与长休止漏音通用修复：新增实际人声／完整伴奏独立声学核验，不能只凭歌词窗口或RMVPE补音。
class SourceVerifier:
    def __init__(self, binding, analysis):
        import soundfile as sf
        self.audio = {}
        self.rates = {}
        self.offsets = {}
        for name in ('vocals', 'accompaniment'):
            source = binding['sources'][name]
            if sha256(source['path']) != source['sha256']:
                raise ValueError('漏音复核的原音轨指纹已改变。')
            data, rate = sf.read(source['path'], dtype='float32', always_2d=True)
            self.audio[name] = data.mean(axis=1)
            self.rates[name] = rate
            self.offsets[name] = source.get('offset_seconds', 0.)
        if (analysis['source']['sha256'] != binding['sources']['vocals']['sha256']
                or analysis['source'].get('offset_seconds', 0.) != self.offsets['vocals']):
            raise ValueError('连续音高与独立复核人声不是同一来源／时轴。')

    # 人声连续音值与长休止漏音通用修复：新增短窗提取，按实际源秒／原轨偏移，男声低音不受旧90Hz下限限制。
    def waveform(self, name, start, end):
        rate = self.rates[name]
        a = max(0, round((start - self.offsets[name]) * rate))
        b = min(len(self.audio[name]), round((end - self.offsets[name]) * rate))
        return self.audio[name][a:b], rate

    # 人声连续音值与长休止漏音通用修复：新增同频谐波前景比；弱串音即使YIN稳定也不自动进入主谱。
    @staticmethod
    def harmonic_power(wave, rate, pitch):
        from scipy.signal import welch
        if len(wave) < 32:
            return 0.
        frequencies, power = welch(wave.astype(float), rate, nperseg=min(len(wave), 4096))
        frequency = 440 * 2 ** ((pitch - 69) / 12)
        selected = np.zeros(len(frequencies), dtype=bool)
        for harmonic in range(1, 7):
            center = frequency * harmonic
            if center >= rate / 2:
                break
            selected |= abs(frequencies - center) <= max(8., center * .035)
        return float(power[selected].sum())

    def __call__(self, core):
        import librosa
        from scipy.signal import resample_poly
        start, end = core['start_seconds'], core['end_seconds']
        wave, rate = self.waveform('vocals', start - .12, end + .12)
        divisor = math.gcd(rate, 16000)
        wave = resample_poly(wave, 16000 // divisor, rate // divisor)
        pitch = core['pitch_midi']; frequency = 440 * 2 ** ((pitch - 69) / 12)
        f0 = librosa.yin(wave, fmin=max(45., frequency / 2.2), fmax=min(1800., frequency * 2.2),
                         sr=16000, frame_length=2048, hop_length=64)
        times = max(0., start - .12) + np.arange(len(f0)) * .004
        selected = (times >= start + .025) & (times < end - .025)
        values = 69 + 12 * np.log2(np.maximum(f0[selected], 1) / 440)
        agreement = float(np.mean(abs(values - pitch) <= .55)) if len(values) else 0.
        voice, sr = self.waveform('vocals', start, end)
        accompaniment, ar = self.waveform('accompaniment', start, end)
        rms = float(np.sqrt(np.mean(voice.astype(float) ** 2))) if len(voice) else 0.
        foreground = self.harmonic_power(voice, sr, pitch)
        background = self.harmonic_power(accompaniment, ar, pitch)
        return {'yin_agreement': agreement, 'yin_median_midi': float(np.median(values)) if len(values) else None,
                'vocal_dbfs': 20 * math.log10(max(rms, 1e-12)),
                'foreground_ratio_db': 10 * math.log10(max(foreground, 1e-20) / max(background, 1e-20)),
                'independent_source_audio_checked': True}


# 人声连续音值与长休止漏音通用修复：新增休止内部的局部稳定平台挑战；整段平均有声率低不能吞掉局部元音。
def recover_rest_tails(analysis, characters, existing, nominal, verifier, locked_ids=()):
    from musical_decode import AcousticEvidence
    evidence = AcousticEvidence(analysis, verify_audio=False)
    groups = defaultdict(list)
    for note in existing:
        if note.get('lyric_index') is not None and not note.get('grace'):
            groups[note['lyric_index']].append(note)
    locked_words = {n.get('lyric_index') for n in existing if n['id'] in locked_ids}
    candidates = []; audits = []
    for raw in analysis.get('notes', []):
        if not raw.get('is_rest') or raw['end_seconds'] - raw['start_seconds'] < POLICY['minimum_rest_seconds']:
            continue
        for char in characters:
            group = sorted(groups.get(char['index'], []), key=lambda n: n['start_seconds'])
            nucleus = next((p for p in char.get('phonemes', []) if p.get('role') == 'nucleus'
                            and not p.get('skipped') and p.get('start_seconds') is not None), None)
            if not group or nucleus is None:
                continue
            a = max(raw['start_seconds'], nucleus['start_seconds'])
            b = min(raw['end_seconds'], nucleus['end_seconds'] + POLICY['maximum_lyric_tail_seconds'])
            if b - a < POLICY['minimum_core_seconds']:
                continue
            previous = group[-1]
            for core in evidence.cores(a, b):
                span = core['end_seconds'] - core['start_seconds']
                overlap = min(nucleus['end_seconds'], core['end_seconds']) - max(nucleus['start_seconds'], core['start_seconds'])
                if (span < max(POLICY['minimum_core_seconds'], nominal * POLICY['minimum_core_quarters'])
                        or core['support'] < POLICY['minimum_pitch_support']
                        or overlap < POLICY['minimum_nucleus_overlap_seconds']
                        or not -.01 <= core['start_seconds'] - previous['end_seconds'] <= nominal * POLICY['maximum_tail_bridge_quarters']
                        or any(n['start_seconds'] < core['end_seconds'] - .015 and n['end_seconds'] > core['start_seconds'] + .015
                               for n in existing + candidates)):
                    continue
                check = verifier(core)
                accepted = (check.get('independent_source_audio_checked') is True
                            and check['yin_agreement'] >= POLICY['minimum_yin_agreement']
                            and check['vocal_dbfs'] >= POLICY['minimum_vocal_dbfs']
                            and check['foreground_ratio_db'] >= POLICY['minimum_foreground_ratio_db'])
                held = char['index'] in locked_words
                row = {'source_rest_id': raw['id'], 'character_index': char['index'], 'stable_core': deepcopy(core),
                       'independent_audio': check, 'action': 'preserve_review' if held else
                       'recover_voiced_rest_tail' if accepted else 'reject_weak_or_bleed_evidence'}
                audits.append(row)
                if not accepted or held:
                    continue
                # 人声连续音值与长休止漏音通用修复：新增同音续段安全边界，不能以两个独立MIDI音制造原唱没有的重发。
                if core['pitch_midi'] in (previous['pitch_midi'], previous.get('source_pitch_midi', previous['pitch_midi'])):
                    row['action'] = 'same_pitch_tail_requires_duration_review'
                    continue
                identity = f"{raw['id']}:{core['start_seconds']:.9f}:{core['end_seconds']:.9f}:{core['pitch_midi']}"
                note_id = raw['id'] + '.recovered_' + hashlib.sha256(identity.encode()).hexdigest()[:12]
                note = {'id': note_id, 'source_note_id': raw['id'], 'start_seconds': core['start_seconds'],
                        'end_seconds': core['end_seconds'], 'pitch_midi': core['pitch_midi'],
                        'confidence': core['support'], 'stable_duration_seconds': span,
                        'independent_pitch_support': check['yin_agreement'], 'stable_core': deepcopy(core),
                        'lyric_index': char['index'], 'line_index': char.get('line_index'),
                        'role': 'main', 'anchor': True, 'grace': False, 'review_flags': [],
                        'boundary_source': 'source_rest_local_f0_and_independent_audio',
                        'recovery_provenance': deepcopy(row)}
                candidates.append(note)
                previous = note
    return candidates, audits


# 人声连续音值与长休止漏音通用修复：新增词内绝对声学边界联合分配，避免仅按压缩总时值比例提前稳定主音。
def allocate_boundaries(notes, begin, end, mapping, origin):
    grid = POLICY['ordinary_grid_ticks']
    # 人声连续音值与长休止漏音通用修复：新增已有真实短转音／细网格保护；不能因普通十六分偏好使合法音段无法分配。
    if any('recovery_provenance' not in n and
           (mapping.seconds_to_quarters(n['end_seconds']) - mapping.seconds_to_quarters(n['start_seconds']) < .24
            or n.get('start_tick', 0) % grid or n.get('end_tick', 0) % grid) for n in notes):
        grid = 60
    # 人声连续音值与长休止漏音通用修复：修改，原无单位意义的转换保留；原秒必须严格正长度且有限。
    # if any((n['end_seconds'] - n['start_seconds']) * PPQ / 60 < 0 for n in notes):
    if any(not math.isfinite(n['start_seconds']) or not math.isfinite(n['end_seconds'])
           or n['end_seconds'] <= n['start_seconds'] for n in notes):
        raise ValueError('音段原秒无效。')
    states = {begin: (0., ())}
    for index, note in enumerate(notes):
        next_states = {}
        last = index == len(notes) - 1
        target = mapping.seconds_to_quarters(notes[index + 1]['start_seconds']) - origin if not last else end / PPQ
        for at, (cost, lengths) in states.items():
            stops = [end] if last else range(math.ceil((at + grid) / grid) * grid,
                                             end - (len(notes) - index - 1) * grid + 1, grid)
            for stop in stops:
                if stop <= at:
                    continue
                observed = mapping.seconds_to_quarters(note['end_seconds']) - mapping.seconds_to_quarters(note['start_seconds'])
                value = cost + .15 * duration_penalty(stop - at, observed)
                if not last:
                    value += ((stop / PPQ - target) / POLICY['source_boundary_sigma_quarters']) ** 2
                choice = (value, lengths + (stop - at,))
                if stop not in next_states or choice < next_states[stop]:
                    next_states[stop] = choice
        states = next_states
    if end not in states:
        raise ValueError('连续音值候选没有足够格位，拒绝挤压或删音。')
    return states[end][1]


# 人声连续音值与长休止漏音通用修复：新增仅对独立发现的问题整字重分配，原音高／身份／源秒及其它字保持。
def repair_continuity(base, binding, review=None, analysis=None, verifier=None):
    analysis = analysis if analysis is not None else read_json(base['inputs']['notes_path'])
    output = deepcopy(base); timing = base['timing']; mapping = TempoMap(timing['knots'])
    origin = timing['score_start_quarter']; nominal = 60 / timing['steady_tempo_bpm']
    locks = review_locks(base, binding, review)
    verifier = verifier if verifier is not None else SourceVerifier(binding, analysis)
    candidates, recovery_audit = recover_rest_tails(analysis, base['lyrics']['characters'],
                                                   base['quantized_notes'], nominal, verifier, locks)
    groups = defaultdict(list)
    for note in output['quantized_notes'] + candidates:
        if note.get('lyric_index') is not None:
            groups[note['lyric_index']].append(note)
    words = sorted(groups.items(), key=lambda row: min(n['start_seconds'] for n in row[1]))
    candidate_words = {n['lyric_index'] for n in candidates}; changes = []
    # 人声连续音值与长休止漏音通用修复：修改，原动态导入保留；使用明确的声学证据类型。
    # frame_evidence = __import__('musical_decode').AcousticEvidence(analysis, verify_audio=False)
    from musical_decode import AcousticEvidence
    frame_evidence = AcousticEvidence(analysis, verify_audio=False)
    for serial, (index, group) in enumerate(words):
        normal = sorted((n for n in group if not n.get('grace')), key=lambda n: n['start_seconds'])
        if not normal or any(n['id'] in locks for n in group):
            continue
        old = [n for n in normal if 'recovery_provenance' not in n]
        begin = min(n['start_tick'] for n in old); old_end = max(n['end_tick'] for n in old)
        following = [n for n in words[serial + 1][1] if not n.get('grace')] if serial + 1 < len(words) else []
        # 人声连续音值与长休止漏音通用修复：修改，原包含尚未量化补段的起拍读取保留；下一字入口只取既有源音。
        # next_begin = min(n['start_tick'] for n in following) if following else timing.get('total_ticks', base['statistics']['total_ticks'])
        following_ticks = [n['start_tick'] for n in following if 'start_tick' in n]
        next_begin = min(following_ticks) if following_ticks else base['statistics']['total_ticks']
        final = normal[-1]; source_end = mapping.seconds_to_quarters(final['end_seconds']) - origin
        connected = bool(following and abs(min(n['start_seconds'] for n in following) - final['end_seconds'])
                         <= nominal * POLICY['maximum_source_gap_quarters'])
        false_rest = (connected and next_begin - old_end >= PPQ * POLICY['minimum_notated_gap_quarters']
                      and source_end - old_end / PPQ >= POLICY['minimum_tail_error_quarters'])
        if index not in candidate_words and not false_rest:
            continue
        if false_rest:
            cores = frame_evidence.cores(final['start_seconds'], final['end_seconds'])
            support = sum(c['end_seconds'] - c['start_seconds'] for c in cores
                          if c['pitch_midi'] == final.get('source_pitch_midi', final['pitch_midi']))
            if support < nominal * .15:
                changes.append({'character_index': index, 'action': 'preserve_insufficient_continuous_voice'})
                continue
            end = next_begin
        else:
            end = min(next_begin, round(source_end * PPQ / POLICY['ordinary_grid_ticks']) * POLICY['ordinary_grid_ticks'])
        lengths = allocate_boundaries(normal, begin, end, mapping, origin)
        if index in candidate_words:
            main = max(normal, key=lambda n: n.get('stable_duration_seconds', 0.) * max(.05, n.get('confidence') or 0.))
            for note in normal:
                note['anchor'] = note is main
                note['role'] = 'main' if note is main else 'turn'
        before = [{k: n.get(k) for k in ('id', 'start_tick', 'end_tick', 'playback_start_tick', 'playback_end_tick')}
                  for n in normal]
        at = begin
        for note, length in zip(normal, lengths):
            note['start_tick'], note['end_tick'] = at, at + length
            note['playback_start_tick'], note['playback_end_tick'] = at, at + length
            note['quantized_start_seconds'] = mapping.quarters_to_seconds(origin + at / PPQ)
            note['quantized_end_seconds'] = mapping.quarters_to_seconds(origin + (at + length) / PPQ)
            note['start_error_seconds'] = note['quantized_start_seconds'] - note['start_seconds']
            note['end_error_seconds'] = note['quantized_end_seconds'] - note['end_seconds']
            note['rhythm_decision'] = {'version': 1, 'strategy': 'local_voiced_continuity', 'source_boundary_unchanged': True}
            at += length
        # 人声连续音值与长休止漏音通用修复：新增有倚音字的保护，不能把既有偷时预算在尾值修复时抹掉。
        if any(n.get('grace') for n in group):
            for note in normal:
                if any(g.get('anchor_id') == note['id'] for g in group if g.get('grace')):
                    original = next(n for n in base['quantized_notes'] if n['id'] == note['id'])
                    note['playback_start_tick'] = original['playback_start_tick']
        changes.append({'character_index': index, 'action': 'recover_tail_and_allocate_internal_boundaries'
                        if index in candidate_words else 'remove_false_rest_and_reallocate_internal_boundaries',
                        'before': before, 'begin_tick': begin, 'end_tick': end, 'durations': list(lengths)})
    output['quantized_notes'].extend(candidates)
    output['quantized_notes'].sort(key=lambda n: (n['start_seconds'], n['id']))
    if any(a['end_tick'] > b['start_tick'] for a, b in zip(
            sorted((n for n in output['quantized_notes'] if not n.get('grace')), key=lambda n: n['start_tick']),
            sorted((n for n in output['quantized_notes'] if not n.get('grace')), key=lambda n: n['start_tick'])[1:])):
        raise ValueError('连续人声修复产生语义重叠。')
    actual_changes = [r for r in changes if r['action'] != 'preserve_insufficient_continuous_voice']
    if actual_changes:
        output['events'] = notation_events(output['quantized_notes'], base['statistics']['total_ticks'], timing)
        # 人声连续音值与长休止漏音通用修复：新增同字同音补段跨片延音，不能把恢复的持续音误作重发。
        events = defaultdict(list)
        for event in output['events']:
            if event.get('piece_id') is not None and not event.get('grace'):
                events[event['piece_id']].append(event)
        ordered = sorted((n for n in output['quantized_notes'] if not n.get('grace')), key=lambda n: n['start_tick'])
        for left, right in zip(ordered, ordered[1:]):
            if (left.get('lyric_index') == right.get('lyric_index') and left['pitch_midi'] == right['pitch_midi']
                    and left['end_tick'] == right['start_tick'] and right.get('recovery_provenance')):
                events[left['id']][-1]['ties'].append('start'); events[right['id']][0]['ties'].append('stop')
        # 人声连续音值与长休止漏音通用修复：修改，错误调用注释保留；挂词使用项目既有的事件／字表接口。
        # attach_lyrics(output['events'], output['quantized_notes'], output['lyrics']['characters'], output['lyrics']['language'])
        output['lyric_mapping'] = attach_lyrics(output['events'], output['lyrics']['characters'])
        grouping = validate_grouping(output['events'], timing['meter'], timing.get('beat_groups'))
        if not grouping['valid']:
            raise ValueError('人声连续音值与音值组合校验失败。')
        # 人声连续音值与长休止漏音通用修复：新增新谱实际分组验收，不沿用旧音符数量的通过记录。
        output['statistics']['rhythm_grouping'] = grouping
        output['statistics']['lyric_split_pieces'] = len(output['quantized_notes'])
        for field, role in [('main_notes', 'main'), ('turn_notes', 'turn')]:
            output['statistics'][field] = sum(n.get('role') == role for n in output['quantized_notes'])
    # 人声连续音值与长休止漏音通用修复：新增保留语义逐字段验收及原音段恒等台账，新增平台另列，不伪装成旧音。
    by_id = {n['id']: n for n in output['quantized_notes']}
    if any(by_id[n['id']] != n for n in base['quantized_notes'] if n['id'] in locks):
        raise ValueError('修复改变了来源绑定的保留音符。')
    fields = ('id', 'source_note_id', 'pitch_midi', 'start_seconds', 'end_seconds', 'lyric_index', 'line_index')
    if any(tuple(by_id[n['id']].get(k) for k in fields) != tuple(n.get(k) for k in fields) for n in base['quantized_notes']):
        raise ValueError('连续修复改变了既有源音段身份、音高、原秒或挂词。')
    return output, {'version': 1, 'policy': deepcopy(POLICY), 'recovery': recovery_audit, 'changes': changes,
                    'recovered_note_ids': [n['id'] for n in candidates], 'preserved_note_ids': sorted(locks),
                    'existing_source_notes_preserved': True, 'source_clock_preserved': output['timing'] == base['timing']}
