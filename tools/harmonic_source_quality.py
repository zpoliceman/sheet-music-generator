"""局部时序与弱证据通用修复：有效音区质量筛选，禁止近零音高归一化成强和声证据。"""
import math
import numpy as np

VERSION = 1
POLICY = {'version': VERSION, 'minimum_band_fraction_of_reference': .008,
          'minimum_band_fraction_of_source': .001, 'minimum_bass_rms_fraction': .015,
          'minimum_absolute_pitch_energy': 1e-10,
          'unpitched_broadband_rms_is_not_harmonic_confidence': True}


# 局部时序与弱证据通用修复：新增归一化前的真实音区总量与谐波浓度，不只看宽带RMS。
def band_evidence(feature, start, end, low, high):
    pitch = np.asarray(feature.pitch_weights(start, end), dtype=float)
    selected = pitch[low - 24:high - 24 + 1]
    mass = float(selected.sum())
    all_mass = float(pitch.sum())
    chroma = np.zeros(12)
    for midi, energy in zip(range(low, high + 1), selected):
        chroma[midi % 12] += energy
    normalized = chroma / mass if mass > POLICY['minimum_absolute_pitch_energy'] else np.zeros(12)
    nonzero = normalized[normalized > 0]
    entropy = -float(np.dot(nonzero, np.log(nonzero))) / math.log(12) if len(nonzero) else 1.
    return {'pitch_mass': mass, 'all_pitch_mass': all_mass, 'band_fraction': mass / max(1e-12, all_mass),
            'tonality': max(0., 1 - entropy), 'chroma': normalized}


# 局部时序与弱证据通用修复：新增实际分析音区相对能量限权，并把低音根音可信度单独处理。
def quality_window(features, start, end, weights):
    evidence = {name: band_evidence(f, start + .03, end, 48, 84) for name, f in features.items() if name != 'bass'}
    reference = max((evidence[name]['pitch_mass'] for name in ('accompaniment', 'other') if name in evidence), default=0.)
    if reference <= POLICY['minimum_absolute_pitch_energy']:
        reference = max((r['pitch_mass'] for r in evidence.values()), default=0.)
    energies = {name: float(f.rms[f.window(start, end)].mean()) for name, f in features.items()}
    active, audit = {}, {}
    for name, r in evidence.items():
        good = (r['pitch_mass'] > POLICY['minimum_absolute_pitch_energy']
                and r['pitch_mass'] >= reference * POLICY['minimum_band_fraction_of_reference']
                and r['band_fraction'] >= POLICY['minimum_band_fraction_of_source'])
        audit[name] = {k: v for k, v in r.items() if k != 'chroma'}
        audit[name].update(active=bool(good), rms=energies[name], reference_pitch_mass=reference,
                           reason='effective_pitch_band_supported' if good else 'insufficient_effective_pitch_band')
        if good:
            active[name] = weights[name]
    chromas = {name: r['chroma'] for name, r in evidence.items()}
    if active:
        amount = sum(active.values())
        mixture = sum(active[name] * chromas[name] for name in active) / amount
        mid = sum(active[name] * band_evidence(features[name], start + .03, end, 48, 72)['chroma'] for name in active) / amount
    else:
        # 局部时序与弱证据通用修复：新增无有效音高时使用零证据，不能凭一个固定other回退伪造投票。
        mixture, mid = np.zeros(12), np.zeros(12)
    mixture = .65 * mid + .35 * mixture
    bass = np.zeros(12)
    if 'bass' in features:
        b = band_evidence(features['bass'], start, end, 24, 59)
        rms_floor = max(1e-7, energies.get('accompaniment', 0.) * POLICY['minimum_bass_rms_fraction'])
        good = b['pitch_mass'] > POLICY['minimum_absolute_pitch_energy'] and energies['bass'] >= rms_floor
        if good:
            bass = b['chroma']
        audit['bass'] = {k: v for k, v in b.items() if k != 'chroma'}
        audit['bass'].update(active=bool(good), rms=energies['bass'], rms_floor=rms_floor,
                            reason='effective_bass_supported' if good else 'weak_bass_not_normalized_as_truth')
    return chromas, energies, active, mixture, mid, bass, audit
