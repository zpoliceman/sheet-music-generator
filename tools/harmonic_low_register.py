"""跨曲低音与强拍复用通用修复：低音按实际音区取证，不按分轨名称排除吉他或键盘。"""
from copy import deepcopy
import numpy as np
from harmonic_source_quality import band_evidence, quality_window as legacy_window

# 跨曲低音与强拍复用通用修复：新增独立版本；历史质量版本1的所有输出保持。
POLICY = {'version': 2, 'low_midi': 24, 'high_bass_midi': 55,
          'harmony_low_midi': 36, 'minimum_low_mass_fraction': .025,
          'minimum_low_mass_of_backing': .015, 'minimum_peak_fraction': .24,
          'minimum_bass_rms_fraction': .015, 'correlated_stems_are_independent_votes': False}


# 跨曲低音与强拍复用通用修复：新增归一化前门限与集中度；宽带噪声和几乎静音的分轨不能产生根音。
def low_vector(feature, start, end, reference_mass):
    row = band_evidence(feature, start + .04, end, 24, 55)
    pitch = np.asarray(feature.pitch_weights(start + .04, end))[:32]
    peak = float(pitch.max()) if len(pitch) else 0.
    good = (row['pitch_mass'] > max(1e-9, reference_mass * POLICY['minimum_low_mass_of_backing'])
            and row['band_fraction'] >= POLICY['minimum_low_mass_fraction']
            and peak / max(1e-12, row['pitch_mass']) >= POLICY['minimum_peak_fraction'])
    vector = np.zeros(12)
    if good:
        # 跨曲低音与强拍复用通用修复：新增按音高能量集中支持根音，弱半音泄漏与八度伪影不等权投票。
        for midi, value in zip(range(24, 56), pitch):
            vector[midi % 12] += value ** 2
        vector /= max(1e-12, vector.sum())
    return vector, {**{k: v for k, v in row.items() if k != 'chroma'},
                    'peak_fraction': peak / max(1e-12, row['pitch_mass']), 'active': bool(good)}


# 跨曲低音与强拍复用通用修复：新增低音主源与同源辅助核查，相关混音/分轨不会增加独立票数。
def quality_window(features, start, end, weights):
    chromas, energies, active, mixture, mid, bass, audit = legacy_window(features, start, end, weights)
    backing = features.get('accompaniment', features.get('other'))
    reference = float(backing.pitch_weights(start + .04, end).sum()) if backing is not None else 0.
    low = {name: low_vector(f, start, end, reference) for name, f in features.items() if name != 'mix'}
    independent = ('bass' in low and low['bass'][1]['active'] and
                   energies['bass'] >= max(1e-7, energies.get('accompaniment', 0.) * POLICY['minimum_bass_rms_fraction']))
    if independent:
        selected = 'bass'
    else:
        # 跨曲低音与强拍复用通用修复：新增完整伴奏优先回退；分离吉他/钢琴仅作为有效音区辅助。
        selected = next((n for n in ('accompaniment', 'other', 'six_guitar', 'six_piano', 'six_other')
                         if n in low and low[n][1]['active']), None)
    bass = low[selected][0] if selected else np.zeros(12)
    audit['low_register'] = {'version': 2, 'selected_source': selected,
        'independent_bass_active': bool(independent), 'sources': {n: r for n, (_, r) in low.items()},
        'correlated_support_not_added_as_votes': True}
    if active:
        # 跨曲低音与强拍复用通用修复：新增保留低把位的三音/七音，原48下限会删除开放Em的G音等性质证据。
        amount = sum(active.values())
        broad = sum(active[n] * band_evidence(features[n], start + .03, end, 36, 84)['chroma']
                    for n in active) / amount
        mid = sum(active[n] * band_evidence(features[n], start + .03, end, 36, 72)['chroma']
                  for n in active) / amount
        mixture = .65 * mid + .35 * broad
    return chromas, energies, active, mixture, mid, bass, audit
