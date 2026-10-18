"""原声覆盖与选音归属通用修复：局部弱起音、持续伴奏和强低音边界的独立证据。"""
# 原声覆盖与选音归属通用修复：新增显式源质量版本，历史缓存只读，新判据不覆盖旧攻击列表。
from copy import deepcopy
import numpy as np
from scipy.ndimage import gaussian_filter1d
from scipy.signal import find_peaks

POLICY = {'version': 1, 'local_onset_window_seconds': 8., 'minimum_attack_spacing_seconds': .12,
          'minimum_relative_rms': .007, 'local_flux_percentile': 62,
          'strong_bass_fraction': .82, 'song_specific_rules': False}


def enabled(shared):
    return shared.get('method', {}).get('source_coverage_quality', {}).get('version') == POLICY['version']


# 原声覆盖与选音归属通用修复：新增局部起音门限，避免整曲强鼓点把安静吉他小节的拨弦全部掩盖。
def refine_attacks(feature):
    from accompaniment_analysis import LOW_MIDI
    smooth = gaussian_filter1d(feature.activations, .7, axis=1)
    difference = np.maximum(0., np.diff(smooth, prepend=smooth[:, :1], axis=1))
    flux = difference.sum(axis=0)
    delta = float(np.median(np.diff(feature.times)))
    size = max(4, round(POLICY['local_onset_window_seconds'] / delta))
    added = []
    for a in range(0, len(flux), size // 2):
        b = min(len(flux), a + size); part = flux[a:b]
        floor = max(float(np.percentile(part, POLICY['local_flux_percentile'])), float(part.max()) * .008, 1e-8)
        peaks, _ = find_peaks(part, distance=max(1, round(.12 / delta)), height=floor, prominence=floor * .6)
        for i in peaks + a:
            seconds = float(feature.times[i])
            if (feature.rms[i] < max(float(feature.rms.max()) * .007, 1e-6)
                    or any(abs(r['seconds'] - seconds) < .09 for r in feature.attacks + added)):
                continue
            sustain = smooth[:, i:min(len(flux), i + 5)].mean(axis=1)
            weights = difference[:, max(0, i - 1):min(len(flux), i + 2)].max(axis=1) * .7 + sustain * .08
            order = np.argsort(weights)[::-1][:6]
            pitches = [{'pitch_midi': int(j + LOW_MIDI), 'weight': float(weights[j]),
                        'relative_weight': float(weights[j] / max(1e-9, weights.max())),
                        'attack_frame': int(i), 'sustain_weight': float(sustain[j])}
                       for j in order if weights[j] >= weights.max() * .22]
            if pitches:
                added.append({'seconds': seconds, 'strength': float(flux[i]), 'pitches': pitches,
                              'origin': 'source_local_flux_recovery'})
    feature.attacks = sorted(deepcopy(feature.attacks) + added, key=lambda a: a['seconds'])
    return {'source_sha256': feature.source['sha256'], 'recovered_attack_count': len(added)}


# 原声覆盖与选音归属通用修复：新增真实持续音表示，不把缺少重发攻击等同于整小节静音。
def sustained_attack(texture, features, clock):
    name = texture['source']; feature = features[name]
    start, end = texture['start_tick'], texture['end_tick']
    weights = feature.pitch_weights(clock.seconds(start), clock.seconds(end))
    order = np.argsort(weights)[::-1][:6]
    from accompaniment_analysis import LOW_MIDI
    pitches = [{'pitch_midi': int(i + LOW_MIDI), 'relative_weight': float(weights[i] / max(1e-9, weights.max())),
                'weight': float(weights[i])} for i in order if weights[i] >= weights.max() * .25 and weights[i] > 1e-8]
    return {'tick': start, 'seconds': clock.seconds(start), 'strength': float(weights.max()),
            'pitches': pitches, 'source': name, 'origin': 'observed_sustain_without_reattack'} if pitches else None


# 原声覆盖与选音归属通用修复：新增局部强低音保护，即使低音是新和弦的三音也不能提前换成另一个根音。
def guard_harmony(shared, vocal, chords):
    from accompaniment_analysis import SongClock
    clock = SongClock(vocal); result = []; audit = []
    for chord in chords:
        cuts = {chord['start_tick'], chord['end_tick']}
        for source in shared['harmony']:
            if chord['start_tick'] < source['start_tick'] < chord['end_tick']:
                cuts.add(source['start_tick'])
        for window in shared['harmony_windows']:
            if chord['start_tick'] < window['start_tick'] < chord['end_tick']:
                cuts.add(window['start_tick'])
        bounds = sorted(cuts)
        for serial, (a, b) in enumerate(zip(bounds[:-1], bounds[1:])):
            source = next((h for h in shared['harmony'] if h['start_tick'] <= a < h['end_tick']), None)
            window = next((w for w in shared['harmony_windows'] if w['start_tick'] <= a < w['end_tick']), None)
            vector = np.asarray((window or {}).get('bass_chroma', []))
            low = (window or {}).get('harmonic_source_quality', {}).get('low_register', {})
            strong = (source is not None and len(vector) == 12 and vector.max() >= POLICY['strong_bass_fraction']
                      and low.get('independent_bass_active') is True and int(vector.argmax()) == source['bass_pc'])
            selected = source if strong and chord['bass_pc'] != source['bass_pc'] else chord
            item = deepcopy(chord); item.update(start_tick=a, end_tick=b,
                                               start_seconds=clock.seconds(a), end_seconds=clock.seconds(b))
            if selected is source:
                for key in ('root_pc', 'quality', 'bass_pc', 'name', 'pitch_classes', 'key'):
                    item[key] = deepcopy(source[key])
                # 原声覆盖与选音归属通用修复：新增实际功能根音同步，不能只改名称留下旧审计答案。
                item['functional_root'] = (source['root_pc'] - source['key']['tonic_pc']) % 12
                item['source_bass_guard'] = {'source_harmony_id': source['id'], 'bass_fraction': float(vector.max())}
                audit.append({'start_tick': a, 'end_tick': b, 'proposed': chord['name'],
                              'retained': source['name'], 'source_bass_pc': source['bass_pc']})
            if (result and result[-1]['end_tick'] == a and all(result[-1][k] == item[k] for k in
                    ('root_pc', 'quality', 'bass_pc', 'name', 'phrase_id') if k in item and k in result[-1])):
                result[-1].update(end_tick=b, end_seconds=clock.seconds(b))
            else:
                item['id'] = chord['id'] + '.source_' + str(serial)
                result.append(item)
    return result, audit


# 原声覆盖与选音归属通用修复：新增交付源覆盖门槛，文件自洽仍不能放行有真实伴奏却整小节无音的唱段。
def validate_source_coverage(shared, vocal, arrangements):
    if not enabled(shared):
        return {'valid': True, 'status': 'historical_policy_preserved', 'errors': []}
    errors = []; checked = []
    for texture in shared['measure_textures']:
        supported = (texture['section'] == 'vocal' and texture['kind'] != 'silence'
                     and max(texture['source_rms'].values()) >= .004
                     and bool(texture['attacks'] or texture.get('sustained_observation')))
        if not supported:
            continue
        row = {'measure': texture['measure'], 'instruments': {}}
        for name, arrangement in arrangements.items():
            count = sum(n['start_tick'] < texture['end_tick'] and n['end_tick'] > texture['start_tick']
                        for n in arrangement['notes'])
            row['instruments'][name] = count
            if not count:
                errors.append('source_active_but_arrangement_empty:' + name + ':' + str(texture['measure']))
        checked.append(row)
    # 原声覆盖与选音归属通用修复：新增恢复音的实际存在／音高核验；另由源派生重放核查其秒与音素归属。
    expected = vocal.get('source_vocal_quality', {}).get('coverage_checks', [])
    for check in expected:
        # 原声覆盖与选音归属通用修复：修改，独立新增唱音与同音连续续长都必须实际覆盖。
        # if check['action'] != 'recover_uncovered_voiced_core':
        if check['action'] not in ('recover_uncovered_voiced_core','extend_same_pitch_continuation'):
            continue
        core = check['core']; owner = check['character_index']
        covered = sum(max(0., min(n['end_seconds'], core['end_seconds']) - max(n['start_seconds'], core['start_seconds']))
                      for n in vocal['quantized_notes'] if n.get('lyric_index') == owner
                      and n.get('source_pitch_midi', n['pitch_midi']) == core['pitch_midi'])
        if covered < core['end_seconds'] - core['start_seconds'] - .015:
            errors.append('independently_supported_vocal_still_unnotated:' + str(owner))
    return {'valid': not errors, 'errors': errors, 'checked_measures': checked,
            'source_vocal_recoveries': sum(c['action'] == 'recover_uncovered_voiced_core' for c in expected),
            'policy': deepcopy(POLICY)}
