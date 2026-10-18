"""连续唱段拍轴与原唱同步修复：保留记谱骨架，联合原轨规则脉冲和实际演唱重估物理拍秒。"""
from copy import deepcopy
from pathlib import Path
from collections import defaultdict
import math
import numpy as np
from scipy.optimize import minimize
from score_export import TempoMap, PPQ, tempo_events, sha256, read_json

VERSION = 1
POLICY = {'version': VERSION, 'window_quarters': 8., 'window_step_quarters': 2.,
          'period_ratios': [.80, 1.35], 'phase_search_quarters': .36,
          'minimum_pulse_attacks': 7, 'minimum_pulse_span_quarters': 3.,
          'minimum_pulse_fraction': .70, 'pulse_tolerance_quarters': .055,
          # 连续唱段拍轴与原唱同步修复：新增连续覆盖、细分门限与共享攻击相位一致性，禁止跨长空档伪拟合。
          'fine_pulse_fraction': .85, 'maximum_pulse_gap_quarters': 2.,
          'minimum_center_coverage_quarters': 1., 'minimum_reliable_pulse_weight': 5.,
          # 连续唱段拍轴与原唱同步修复：新增等价脉冲相位的发声证据权重和可审计重叠窗代价。
          'phase_voice_weight': .6, 'overlap_phase_weight': .12,
          # 连续唱段拍轴与原唱同步修复：新增按真实攻击秒去重，避免同一声音在相位竞争窗被计成两个拍点。
          'same_source_event_tolerance_quarters': .04,
          'minimum_attack_strength': .30, 'minimum_active_rms_fraction': .06,
          # 连续唱段拍轴与原唱同步修复：修改，旧仅和声音轨配置保留；低音参加候选、鼓仅交叉支持。
          # 'pulse_sources': {'six_piano': 1., 'six_guitar': .8, 'accompaniment': .8, 'other': .6, 'six_other': .4},
          'pulse_sources': {'six_piano': 1., 'six_guitar': .8, 'accompaniment': .8, 'other': .6, 'six_other': .4, 'bass': .8, 'drums': .35},
          'related_sources_family': 'harmonic_mix', 'quarter_subdivisions': [.5, .25],
          'pulse_change_quarters': .12, 'vocal_change_quarters': .20,
          'minimum_vocal_witnesses': 3, 'minimum_vocal_fraction': .5,
          'maximum_consonant_compensation_quarters': .12, 'vowel_latency_quarters': .08,
          'region_padding_quarters': 2., 'tempo_period_ratios': [.55, 1.75],
          'pulse_observation_weight': 8., 'vocal_observation_weight': 1.5,
          'clock_prior_weight': .025, 'tempo_smooth_weight': .025,
          'residual_review_quarters': .20, 'retain_notation_ticks': True,
          'retain_source_seconds': True, 'confidence_kind': 'local_evidence_not_calibrated_accuracy'}


# 连续唱段拍轴与原唱同步修复：新增严格版本/源指纹缓存复制，既有特征和原录音只读。
def copy_features(binding, cache, preferred=()):
    from shutil import copy2
    root = Path(__file__).resolve().parents[1]
    cache = Path(cache).resolve()
    if not cache.is_relative_to(root / 'test_outputs/accompaniment_runs'):
        raise ValueError('演奏拍轴缓存必须在本项目独立分析目录中')
    cache.mkdir(parents=True, exist_ok=True)
    for source in binding['sources'].values():
        token = 'v1_' + source['sha256'][:16] + '_22050_512_24_96'
        candidates = [Path(p) / (token + '.json') for p in preferred if p]
        candidates += sorted((root / 'test_outputs/accompaniment_runs').glob('*/features/' + token + '.json'))
        found = next((p for p in candidates if p.is_file() and p.with_suffix('.npz').is_file()), None)
        if found:
            for suffix in ('.json', '.npz'):
                src, dst = found.with_suffix(suffix), cache / (token + suffix)
                if not dst.exists() and src.resolve() != dst.resolve():
                    copy2(src, dst)


# 连续唱段拍轴与原唱同步修复：新增完整频段起音与逐点实际能量门限，尾音不能仅凭低音音高权重升级成强拍。
def fullband_tracks(binding, cache):
    from accompaniment_analysis import extract_features
    tracks = {}
    for name, priority in POLICY['pulse_sources'].items():
        source = binding['sources'].get(name)
        if not source:
            continue
        feature = extract_features(source, cache, name)
        scale = max(1e-9, float(np.percentile([a['strength'] for a in feature.attacks], 85))) if feature.attacks else 1.
        energy = max(1e-6, float(np.percentile(feature.rms, 90)) * POLICY['minimum_active_rms_fraction'])
        attacks = []
        for a in feature.attacks:
            index = min(len(feature.rms) - 1, int(np.searchsorted(feature.times, a['seconds'])))
            strength = min(2., float(a['strength']) / scale)
            if strength >= POLICY['minimum_attack_strength'] and feature.rms[index] >= energy:
                attacks.append({'seconds': float(a['seconds']) + float(source.get('offset_seconds', 0)),
                                'strength': strength, 'track': name})
        tracks[name] = {'attacks': attacks, 'priority': priority, 'source_sha256': source['sha256'],
                        'rms_floor': energy, 'full_attack_count': len(feature.attacks)}
    return tracks


# 连续唱段拍轴与原唱同步修复：新增半拍/十六分脉冲拟合，攻击允许在弱拍或切分位置，不逐音吸附整拍。
# 连续唱段拍轴与原唱同步修复：修改，旧入口保留；加入演唱时序只用于脉冲相位的等价解竞争。
# def fit_pulse(attacks, center_q, center_seconds, period, reference=None):
def fit_pulse(attacks, center_q, center_seconds, period, reference=None, voice=()):
    if len(attacks) < POLICY['minimum_pulse_attacks']:
        return None
    ts = np.array([a['seconds'] for a in attacks], dtype=float)
    weights = np.array([a['strength'] for a in attacks], dtype=float)
    if (ts[-1] - ts[0]) / period < POLICY['minimum_pulse_span_quarters']:
        return None
    # 连续唱段拍轴与原唱同步修复：修改，旧无界累计相位预测保留；已有记谱相位限制半拍别名累计漂移。
    # expected = center_seconds if reference is None else reference['center_seconds'] + (center_q - reference['center_quarter']) * reference['period_seconds']
    expected = center_seconds
    previous_seconds = center_seconds if reference is None else reference['center_seconds'] + (center_q - reference['center_quarter']) * reference['period_seconds']
    vq = np.array([r['quarter'] for r in voice], dtype=float)
    vt = np.array([r['seconds'] for r in voice], dtype=float)
    vw = np.array([r['weight'] for r in voice], dtype=float)
    choices = []
    for subdivision in POLICY['quarter_subdivisions']:
        for ratio in np.linspace(*POLICY['period_ratios'], 57):
            p = period * float(ratio)
            for shift in np.linspace(-POLICY['phase_search_quarters'], POLICY['phase_search_quarters'], 41):
                origin = expected + float(shift) * period
                labels = center_q + np.round((ts - origin) / p / subdivision) * subdivision
                residual = ts - (origin + (labels - center_q) * p)
                tolerance = POLICY['pulse_tolerance_quarters'] * period
                use = np.abs(residual) <= tolerance
                fraction = float(weights[use].sum() / weights.sum())
                # 连续唱段拍轴与原唱同步修复：修改，旧细网格支持门限保留；十六分网格须有更强证据，避免噪声碰巧对齐。
                # if (int(use.sum()) < POLICY['minimum_pulse_attacks'] or fraction < POLICY['minimum_pulse_fraction']
                # 连续唱段拍轴与原唱同步修复：修改，旧常数保留；版本化全部细分支持门限。
                # minimum_fraction = POLICY['minimum_pulse_fraction'] if subdivision == .5 else .85
                minimum_fraction = POLICY['minimum_pulse_fraction'] if subdivision == .5 else POLICY['fine_pulse_fraction']
                if (int(use.sum()) < POLICY['minimum_pulse_attacks'] or fraction < minimum_fraction
                        or (ts[use].max() - ts[use].min()) / p < POLICY['minimum_pulse_span_quarters']):
                    continue
                # 连续唱段拍轴与原唱同步修复：新增粗相位搜索后的实际最小二乘微调，避免采样网格成为拍点精度上限。
                design = np.column_stack((np.ones(int(use.sum())), labels[use] - center_q))
                sw = np.sqrt(weights[use])
                fitted, _, _, _ = np.linalg.lstsq(design * sw[:, None], ts[use] * sw, rcond=None)
                origin, p = map(float, fitted)
                if not POLICY['period_ratios'][0] * period <= p <= POLICY['period_ratios'][1] * period:
                    continue
                if abs(origin - expected) > POLICY['phase_search_quarters'] * period:
                    continue
                residual = ts - (origin + (labels - center_q) * p)
                use = np.abs(residual) <= tolerance
                fraction = float(weights[use].sum() / weights.sum())
                # 连续唱段拍轴与原唱同步修复：修改，旧统一门限保留；精拟合也须满足当前细分证据门限。
                # if int(use.sum()) < POLICY['minimum_pulse_attacks'] or fraction < POLICY['minimum_pulse_fraction']:
                if int(use.sum()) < POLICY['minimum_pulse_attacks'] or fraction < minimum_fraction:
                    continue
                # 连续唱段拍轴与原唱同步修复：新增真实连续覆盖，不从窗末少数攻击外推到无伴奏的窗首。
                matched = ts[use]
                coverage = POLICY['minimum_center_coverage_quarters'] * p
                if (np.max(np.diff(matched)) > POLICY['maximum_pulse_gap_quarters'] * p
                        or not matched[0] + coverage <= origin <= matched[-1] - coverage):
                    continue
                # 连续唱段拍轴与原唱同步修复：新增重叠窗的同一个源攻击必须保留同一拍坐标，杜绝十六分别名跳变。
                overlap_penalty = 0.
                if reference:
                    previous_labels = {round(o['seconds'], 7): o['quarter'] for o in reference['observations']}
                    common = [(float(q), previous_labels[round(float(t), 7)]) for q, t in zip(labels[use], ts[use])
                              if round(float(t), 7) in previous_labels]
                    # 连续唱段拍轴与原唱同步修复：修改，旧硬锁早期相位保留；新证据可纠正初次别名，但须付连续性代价。
                    # if len(common) >= 2 and any(abs(q - old_q) > 1e-6 for q, old_q in common):
                    #     continue
                    if len(common) >= 2:
                        overlap_penalty = POLICY['overlap_phase_weight'] * float(np.mean(
                            [min(4., ((q - old_q) / subdivision) ** 2) for q, old_q in common]))
                # 连续唱段拍轴与原唱同步修复：新增累计拍相位连续性；上一可靠窗口约束半拍/四分之一拍的等价解。
                loss = float(np.average(np.minimum((residual / tolerance) ** 2, 1.), weights=weights))
                loss += overlap_penalty
                loss += .10 * (math.log(p / period) / .15) ** 2
                # 连续唱段拍轴与原唱同步修复：修改，旧单一连续性项保留；基准相位与前窗连续性共同限制累计别名漂移。
                # loss += (.20 if reference is not None else .04) * ((origin - expected) / period / .25) ** 2
                loss += .04 * ((origin - expected) / period / .25) ** 2
                if reference is not None:
                    loss += .025 * ((origin - previous_seconds) / period / .25) ** 2
                if len(vq) >= 3:
                    voice_error = vt - (origin + (vq - center_q) * p)
                    # 连续唱段拍轴与原唱同步修复：修改，旧小权重保留；相同脉冲的等价相位由多个真实发声共同判别。
                    # loss += .15 * float(np.average(np.minimum((voice_error / period / .15) ** 2, 4.), weights=vw))
                    loss += POLICY['phase_voice_weight'] * float(np.average(np.minimum((voice_error / period / .15) ** 2, 4.), weights=vw))
                loss += .035 if subdivision == .25 else 0.
                choices.append((loss, {'center_quarter': float(center_q), 'center_seconds': origin,
                                      'fit_loss': float(loss),
                                      'period_seconds': p, 'subdivision_quarters': subdivision,
                                      'support_fraction': fraction, 'support_count': int(use.sum()),
                                      'first_quarter': float(labels[use].min()), 'last_quarter': float(labels[use].max()),
                                      'maximum_residual_seconds': float(np.abs(residual[use]).max()),
                                      'observations': [{'quarter': float(q), 'seconds': float(t), 'strength': float(w)}
                                                       for q, t, w in zip(labels[use], ts[use], weights[use])]}))
    return min(choices, key=lambda row: row[0])[1] if choices else None


# 连续唱段拍轴与原唱同步修复：新增真实唱段范围，长过门和已确认累计拍数不被连续脉冲外推重新覆盖。
def singing_spans(vocal):
    period = 60 / vocal['timing']['steady_tempo_bpm']
    notes = [n for n in vocal['quantized_notes'] if n.get('lyric_index') is not None and not n.get('grace')]
    by_word = defaultdict(list)
    for n in notes:
        by_word[n['lyric_index']].append(n)
    units = sorted((min(n['start_seconds'] for n in ns), max(n['end_seconds'] for n in ns),
                    min(n['start_tick'] for n in ns) / PPQ, max(n['end_tick'] for n in ns) / PPQ)
                   for ns in by_word.values())
    spans = []
    bar = vocal['statistics']['bar_ticks'] / PPQ
    for a, b, q, end in units:
        if not spans or a - spans[-1]['end_seconds'] >= bar * period:
            spans.append({'first_quarter': q, 'last_quarter': end, 'start_seconds': a, 'end_seconds': b})
        else:
            spans[-1]['last_quarter'] = max(spans[-1]['last_quarter'], end)
            spans[-1]['end_seconds'] = max(spans[-1]['end_seconds'], b)
    return spans


# 连续唱段拍轴与原唱同步修复：新增逐窗脉冲支持，相关分轨只选同族最可靠序列，不叠加为独立真值。
# 跨歌曲和弦复用与器乐准备：修改，保留旧入口；新版可显式提供源攻击身份解析，历史调用仍走原策略。
# def pulse_observations(vocal, tracks):
def pulse_observations(vocal, tracks, pulse_resolver=None):
    mapping = TempoMap(vocal['timing']['knots'])
    origin = vocal['timing']['score_start_quarter']
    nominal = 60 / vocal['timing']['steady_tempo_bpm']
    # 连续唱段拍轴与原唱同步修复：新增音素/发声相位辅助与同族观察去重，不能复制滑窗外推成为多个独立攻击。
    fits, observations, triggers = [], [], []
    vocal_anchors = vocal_observations(vocal)
    # 连续唱段拍轴与原唱同步修复：修改，旧仅拍坐标去重保留；先收集竞争相位，再按源攻击身份去重。
    # unique = {}
    candidates = []
    half = POLICY['window_quarters'] / 2
    for span in singing_spans(vocal):
        previous = {}
        start = math.ceil(span['first_quarter'] / POLICY['window_step_quarters']) * POLICY['window_step_quarters']
        for center in np.arange(start, span['last_quarter'], POLICY['window_step_quarters']):
            left, right = max(span['first_quarter'], center - half), min(span['last_quarter'], center + half)
            a, b = mapping.quarters_to_seconds(left + origin), mapping.quarters_to_seconds(right + origin)
            alternatives = []
            for name, track in tracks.items():
                if name == 'drums':
                    continue
                atts = [r for r in track['attacks'] if a - nominal * .15 <= r['seconds'] <= b + nominal * .15]
                ref = previous.get(name)
                if ref and center - ref['center_quarter'] > POLICY['window_quarters']:
                    ref = None
                # 连续唱段拍轴与原唱同步修复：修改，旧纯音轨拟合保留；人声约束半拍等价相位而不强迫辅音贴拍。
                # fit = fit_pulse(atts, center, mapping.quarters_to_seconds(center + origin), nominal, ref)
                anchors = [r for r in vocal_anchors if left <= r['quarter'] <= right and r['weight'] >= 1.]
                fit = fit_pulse(atts, center, mapping.quarters_to_seconds(center + origin), nominal, ref, anchors)
                if fit:
                    previous[name] = fit
                    quality = track['priority'] * fit['support_fraction'] * min(1., fit['support_count'] / 12.)
                    alternatives.append((quality, name, fit))
            if not alternatives:
                fits.append({'center_quarter': float(center), 'status': 'insufficient_periodic_support'})
                continue
            _, name, best = max(alternatives, key=lambda row: row[0])
            # 连续唱段拍轴与原唱同步修复：修改，旧统一族名保留；独立低音与相关和声分轨分别记录。
            # best = dict(best, source=name, family='harmonic_mix', status='periodic_source_supported')
            best = dict(best, source=name, family='bass' if name == 'bass' else 'harmonic_mix', status='periodic_source_supported')
            # 连续唱段拍轴与原唱同步修复：新增鼓的独立交叉支持，只做证据，不把无音高鼓CQT当拍点真值。
            drum_times = [r['seconds'] for r in tracks.get('drums', {}).get('attacks', []) if a <= r['seconds'] <= b]
            best['independent_drum_support_count'] = sum(any(abs(t - o['seconds']) <= .08 * nominal for t in drum_times)
                                                        for o in best['observations'])
            fits.append(best)
            first = max(left, best['first_quarter'])
            last = min(right, best['last_quarter'])
            deltas = []
            # 连续唱段拍轴与原唱同步修复：修改，旧半拍整窗外推保留；只使用真实匹配攻击，相关窗口/分轨同族最多一份权重。
            # for q in np.arange(math.ceil(first * 2) / 2, last + .01, .5):
            #     target = best['center_seconds'] + (q - center) * best['period_seconds']
            #     base = mapping.quarters_to_seconds(q + origin)
            #     deltas.append(abs(target - base) / nominal)
            #     observations.append({'quarter': float(q), 'seconds': float(target),
            #                          'weight': POLICY['pulse_observation_weight'] * best['support_fraction'],
            #                          'kind': 'fullband_periodic_pulse', 'source': name})
            for observed in best['observations']:
                q, target = observed['quarter'], observed['seconds']
                if not first <= q <= last:
                    continue
                base = mapping.quarters_to_seconds(q + origin)
                deltas.append(abs(target - base) / nominal)
                quality = tracks[name]['priority'] * best['support_fraction']
                key = (round(q * PPQ), 'bass' if name == 'bass' else 'harmonic_mix')
                row = {'quarter': float(q), 'seconds': float(target),
                       'weight': POLICY['pulse_observation_weight'] * quality,
                       'kind': 'fullband_periodic_pulse', 'source': name,
                       'family': key[1], 'support_fraction': best['support_fraction']}
                # 连续唱段拍轴与原唱同步修复：修改，旧同拍去重保留；同一个源攻击必须只有一个相位，中央窗和低残差优先。
                # if key not in unique or quality > unique[key][0]:
                #     unique[key] = (quality, row)
                row['selection_rank'] = quality * math.exp(-((q - center) / half) ** 2) / (1. + best['fit_loss'])
                candidates.append(row)
            if deltas and max(deltas) >= POLICY['pulse_change_quarters']:
                triggers.append({'first_quarter': float(first), 'last_quarter': float(last), 'reason': 'source_pulse_disagreement'})
    # 连续唱段拍轴与原唱同步修复：修改，旧滑窗叠加观察返回保留；返回同族去重后的真实攻击。
    # return observations, fits, triggers
    # 连续唱段拍轴与原唱同步修复：修改，旧按拍位置去重返回保留；源事件身份去重并显式审计矛盾相位。
    # return [row for _, row in unique.values()], fits, triggers
    # 跨歌曲和弦复用与器乐准备：修改，旧去重保留为默认；独立版本才使用新的相关分轨解析。
    # observations, resolution = deduplicate_source_pulses(candidates, nominal)
    observations, resolution = (pulse_resolver or deduplicate_source_pulses)(candidates, nominal)
    return observations, fits, triggers, resolution


# 连续唱段拍轴与原唱同步修复：新增同族真实起音去重及单调证据门限，不把一个攻击的两个相位折中成假拍点。
def deduplicate_source_pulses(rows, nominal):
    by_family = defaultdict(list)
    for row in rows:
        by_family[row['family']].append(row)
    selected, aliases = [], []
    tolerance = nominal * POLICY['same_source_event_tolerance_quarters']
    for family, values in by_family.items():
        groups = []
        for row in sorted(values, key=lambda r: r['seconds']):
            if not groups or row['seconds'] - groups[-1][0]['seconds'] > tolerance:
                groups.append([row])
            else:
                groups[-1].append(row)
        for group in groups:
            winner = max(group, key=lambda r: r['selection_rank'])
            selected.append(winner)
            choices = sorted({r['quarter'] for r in group})
            if len(choices) > 1:
                aliases.append({'source_seconds': winner['seconds'], 'family': family,
                                'candidate_quarters': choices, 'chosen_quarter': winner['quarter'],
                                'status': 'same_source_attack_phase_resolved_once'})
    unique = {}
    for row in selected:
        key = (round(row['quarter'] * PPQ), row['family'])
        if key not in unique or row['selection_rank'] > unique[key]['selection_rank']:
            unique[key] = row
    observations = list(unique.values())
    rejected, conflicts = set(), []
    for family in by_family:
        ordered = sorted([r for r in observations if r['family'] == family], key=lambda r: r['quarter'])
        for a, b in zip(ordered, ordered[1:]):
            if b['seconds'] <= a['seconds']:
                rejected.update([id(a), id(b)])
                conflicts.append({'family': family, 'quarters': [a['quarter'], b['quarter']],
                                  'source_seconds': [a['seconds'], b['seconds']],
                                  'status': 'nonmonotonic_phase_evidence_rejected_for_review'})
    return [r for r in observations if id(r) not in rejected], {'resolved_aliases': aliases,
                                                             'unresolved_phase_conflicts': conflicts,
                                                             'source_attack_counted_once': True}


# 连续唱段拍轴与原唱同步修复：新增音素/稳定发声共同起音，不把所有辅音提前和倚音一概当物理拍点。
def vocal_observations(vocal):
    nominal = 60 / vocal['timing']['steady_tempo_bpm']
    notes = defaultdict(list)
    for n in vocal['quantized_notes']:
        if n.get('lyric_index') is not None and not n.get('grace'):
            notes[n['lyric_index']].append(n)
    rows = []
    for c in vocal.get('lyrics', {}).get('characters', []):
        ns = notes.get(c['index'], [])
        if not ns or c.get('start_seconds') is None:
            continue
        raw = min(n['start_seconds'] for n in ns)
        phone = float(c['start_seconds'])
        first = max(raw, phone) if raw < phone - .15 * nominal else raw
        nucleus = next((p.get('start_seconds') for p in c.get('phonemes', [])
                        if p.get('role') == 'nucleus' and p.get('start_seconds') is not None and not p.get('skipped')), None)
        correction = 0. if nucleus is None else min(POLICY['maximum_consonant_compensation_quarters'] * nominal,
                max(0., float(nucleus) - first - POLICY['vowel_latency_quarters'] * nominal))
        confidence = .4 if abs(raw - phone) > .25 * nominal else 1.
        rows.append({'quarter': min(n['start_tick'] for n in ns) / PPQ, 'seconds': float(first + correction),
                     'raw_seconds': raw, 'phone_seconds': phone, 'nucleus_seconds': nucleus,
                     'character_index': c['index'], 'line_index': c['line_index'],
                     'weight': POLICY['vocal_observation_weight'] * confidence, 'kind': 'vocal_performance_onset'})
    return rows


# 连续唱段拍轴与原唱同步修复：新增多字持续误差门限，单字离群或可靠伴奏上的普通拖唱不重置时钟。
def vocal_disagreements(vocal, mapping, voice, pulse):
    origin = vocal['timing']['score_start_quarter']
    nominal = 60 / vocal['timing']['steady_tempo_bpm']
    groups = vocal['statistics'].get('phrase_rhythm', {}).get('phrases', [])
    if not groups:
        by_line = defaultdict(list)
        for r in voice:
            by_line[r['line_index']].append(r)
        groups = [{'first_character_index': min(r['character_index'] for r in values),
                   'last_character_index': max(r['character_index'] for r in values)} for values in by_line.values()]
    evidence, triggers = [], []
    for group in groups:
        first, last = group.get('first_character_index'), group.get('last_character_index')
        if first is None or last is None:
            continue
        selected = [r for r in voice if first <= r['character_index'] <= last and r['weight'] >= 1.]
        if len(selected) < POLICY['minimum_vocal_witnesses']:
            continue
        residual = np.array([(r['seconds'] - mapping.quarters_to_seconds(r['quarter'] + origin)) / nominal for r in selected])
        positive = int(np.sum(residual >= POLICY['vocal_change_quarters']))
        negative = int(np.sum(residual <= -POLICY['vocal_change_quarters']))
        supported = max(positive, negative) >= max(POLICY['minimum_vocal_witnesses'], math.ceil(len(selected) * POLICY['minimum_vocal_fraction']))
        # 连续唱段拍轴与原唱同步修复：修改，旧任意弱分轨计数保留；只有局部强支持脉冲可否决持续人声分歧。
        # pulse_count = sum(any(abs(p['quarter'] - r['quarter']) < .30 for p in pulse) for r in selected)
        pulse_count = sum(any(abs(p['quarter'] - r['quarter']) < .30
                              and p['weight'] >= POLICY['minimum_reliable_pulse_weight'] for p in pulse) for r in selected)
        entry = {'first_character_index': first, 'last_character_index': last,
                 'first_quarter': selected[0]['quarter'], 'last_quarter': selected[-1]['quarter'],
                 'median_residual_quarters': float(np.median(residual)), 'witness_count': max(positive, negative),
                 'word_count': len(selected), 'periodic_pulse_word_count': pulse_count,
                 'status': 'within_performance_tolerance'}
        if supported:
            if pulse_count >= len(selected) * .5:
                entry['status'] = 'vocal_expression_or_notation_conflict_periodic_pulse_kept'
            elif group.get('needs_review'):
                entry['status'] = 'uncertain_notation_keep_clock_for_review'
            else:
                entry['status'] = 'coherent_vocal_time_disagreement'
                triggers.append({'first_quarter': selected[0]['quarter'], 'last_quarter': selected[-1]['quarter'],
                                 'reason': entry['status']})
        evidence.append(entry)
    return triggers, evidence


# 连续唱段拍轴与原唱同步修复：新增变化窗合并与固定边界，已经确认的过门/首拍不会由外推隐式改号。
def changed_regions(vocal, triggers):
    regions = []
    max_q = vocal['statistics']['total_ticks'] / PPQ
    spans = singing_spans(vocal)
    for trigger in sorted(triggers, key=lambda r: r['first_quarter']):
        span = next((s for s in spans if s['first_quarter'] <= trigger['first_quarter'] <= s['last_quarter']), None)
        if not span:
            continue
        lo = max(0., math.floor(span['first_quarter']), math.floor(trigger['first_quarter'] - POLICY['region_padding_quarters']))
        hi = min(max_q, math.ceil(span['last_quarter']), math.ceil(trigger['last_quarter'] + POLICY['region_padding_quarters']))
        if hi <= lo:
            continue
        if regions and lo <= regions[-1]['last_quarter'] and regions[-1]['span_first_quarter'] == span['first_quarter']:
            regions[-1]['last_quarter'] = max(hi, regions[-1]['last_quarter'])
            regions[-1]['reasons'].append(trigger['reason'])
        else:
            regions.append({'first_quarter': float(lo), 'last_quarter': float(hi),
                            'span_first_quarter': span['first_quarter'], 'reasons': [trigger['reason']]})
    return regions


# 连续唱段拍轴与原唱同步修复：新增固定两端、正速度约束与速度平滑的共同时间拟合，原唱不变速。
def fit_region(mapping, origin, region, observations, nominal):
    lo, hi = region['first_quarter'], region['last_quarter']
    local = [r for r in observations if lo < r['quarter'] < hi]
    x = np.array(sorted({lo, hi} | {k['quarter'] - origin for k in mapping.knots if lo < k['quarter'] - origin < hi}
                        | {r['quarter'] for r in local}), dtype=float)
    old = np.array([mapping.quarters_to_seconds(q + origin) for q in x], dtype=float)
    dx = np.diff(x)
    period = float(np.median(np.diff(old) / dx))
    lower = POLICY['tempo_period_ratios'][0] * period * dx
    upper = POLICY['tempo_period_ratios'][1] * period * dx
    # 连续唱段拍轴与原唱同步修复：新增源时长可行性保护，真实极慢尾句不用普通窗范围强压。
    if old[-1] - old[0] < lower.sum() or old[-1] - old[0] > upper.sum():
        return [], dict(region, status='duration_bounds_infeasible_keep_original')
    matrix, targets, weights = [], [], []
    for r in local:
        index = int(np.searchsorted(x, r['quarter']))
        row = np.zeros(len(dx))
        row[:index] = 1.
        matrix.append(row)
        targets.append(r['seconds'] - old[0])
        weights.append(r['weight'])
    for i in range(1, len(x) - 1):
        row = np.zeros(len(dx)); row[:i] = 1.
        matrix.append(row); targets.append(old[i] - old[0]); weights.append(POLICY['clock_prior_weight'])
    A, b, w = np.array(matrix), np.array(targets), np.array(weights)
    smooth = np.zeros((max(0, len(dx) - 1), len(dx)))
    for i in range(len(dx) - 1):
        smooth[i, i] = -1 / dx[i]
        smooth[i, i + 1] = 1 / dx[i + 1]
    smooth_weight = POLICY['tempo_smooth_weight']
    def objective(d):
        residual = A @ d - b
        return float(np.dot(w, residual ** 2) / nominal ** 2 + smooth_weight * np.sum((smooth @ d / period) ** 2))
    def gradient(d):
        return 2 * A.T @ (w * (A @ d - b)) / nominal ** 2 + 2 * smooth_weight * smooth.T @ (smooth @ d) / period ** 2
    result = minimize(objective, np.clip(np.diff(old), lower, upper), jac=gradient, method='SLSQP',
                      bounds=list(zip(lower, upper)), constraints=[{'type': 'eq',
                      'fun': lambda d: float(d.sum() - (old[-1] - old[0])), 'jac': lambda d: np.ones(len(d))}],
                      options={'ftol': 1e-10, 'maxiter': 300})
    if not result.success or abs(result.x.sum() - (old[-1] - old[0])) > 1e-7:
        return [], dict(region, status='solver_unresolved_keep_original', solver_message=str(result.message))
    fitted = np.concatenate(([old[0]], old[0] + np.cumsum(result.x)))
    fitted[-1] = old[-1]
    points = [{'quarter': float(q + origin), 'seconds': float(t)} for q, t in zip(x, fitted)]
    evidence = dict(region, status='source_performance_time_refitted', observation_count=len(local),
                    maximum_change_seconds=float(np.max(np.abs(fitted - old))),
                    period_range_seconds=[float(np.min(result.x / dx)), float(np.max(result.x / dx))],
                    boundary_seconds=[float(old[0]), float(old[-1])], solver_iterations=int(result.nit))
    return points, evidence


# 连续唱段拍轴与原唱同步修复：新增可重放推断，只修改有跨音证据的局部映射，全部源身份/记谱音值保留。
# 跨歌曲和弦复用与器乐准备：修改，旧调用语义保留；仅显式新策略可替换攻击身份解析。
# def infer_performance_clock(vocal, binding, cache):
def infer_performance_clock(vocal, binding, cache, pulse_resolver=None):
    timing = vocal['timing']; mapping = TempoMap(timing['knots']); origin = timing['score_start_quarter']
    nominal = 60 / timing['steady_tempo_bpm']
    tracks = fullband_tracks(binding, cache)
    # 连续唱段拍轴与原唱同步修复：修改，旧三值入口保留；明确接收真实源攻击的相位去重审计。
    # pulse, windows, source_triggers = pulse_observations(vocal, tracks)
    # 跨歌曲和弦复用与器乐准备：修改，旧三参数调用保留，避免改变版本1／2的严格源重放。
    # pulse, windows, source_triggers, phase_resolution = pulse_observations(vocal, tracks)
    if pulse_resolver is None:
        pulse, windows, source_triggers, phase_resolution = pulse_observations(vocal, tracks)
    else:
        pulse, windows, source_triggers, phase_resolution = pulse_observations(vocal, tracks, pulse_resolver)
    voice = vocal_observations(vocal)
    initial_regions = changed_regions(vocal, source_triggers)
    initial_knots = {p['quarter']: deepcopy(p) for p in mapping.knots}
    for region in initial_regions:
        points, _ = fit_region(mapping, origin, region, pulse, nominal)
        for p in points:
            initial_knots[p['quarter']] = p
    initial_mapping = TempoMap([initial_knots[q] for q in sorted(initial_knots)])
    vocal_triggers, before = vocal_disagreements(vocal, initial_mapping, voice, pulse)
    regions = changed_regions(vocal, source_triggers + vocal_triggers)
    knots = {p['quarter']: deepcopy(p) for p in mapping.knots}
    regional = []
    for region in regions:
        # 连续唱段拍轴与原唱同步修复：新增只向真实人声持续分歧窗引入演唱观测，可靠脉冲区不追逐每个辅音。
        local_voice = [r for r in voice if any(t['first_quarter'] <= r['quarter'] <= t['last_quarter'] for t in vocal_triggers)]
        points, evidence = fit_region(mapping, origin, region, pulse + local_voice, nominal)
        regional.append(evidence)
        for p in points:
            knots[p['quarter']] = p
    updated = [knots[q] for q in sorted(knots)]
    revised = TempoMap(updated)
    _, after = vocal_disagreements(vocal, revised, voice, pulse)
    residuals = [{'quarter': r['quarter'], 'character_index': r['character_index'], 'source_onset_seconds': r['seconds'],
                  'before_seconds': mapping.quarters_to_seconds(r['quarter'] + origin),
                  'after_seconds': revised.quarters_to_seconds(r['quarter'] + origin),
                  'after_residual_seconds': r['seconds'] - revised.quarters_to_seconds(r['quarter'] + origin)} for r in voice]
    # 连续唱段拍轴与原唱同步修复：新增绝对源时序检查，不能只凭候选差距或播放器同启宣称音乐同步。
    pulse_residuals = [dict(r, residual_seconds=r['seconds'] - revised.quarters_to_seconds(r['quarter'] + origin)) for r in pulse]
    unresolved_pulses = [r for r in pulse_residuals if r['weight'] >= POLICY['minimum_reliable_pulse_weight']
                         and abs(r['residual_seconds']) > POLICY['residual_review_quarters'] * nominal]
    unresolved_voice = [r for r in after if r['status'] == 'coherent_vocal_time_disagreement']
    review_voice = [r for r in after if r['status'] in ('vocal_expression_or_notation_conflict_periodic_pulse_kept',
                                                     'uncertain_notation_keep_clock_for_review')]
    # 连续唱段拍轴与原唱同步修复：修改，旧单一秒残差门限保留；不允许矛盾源相位靠平均秒数掩盖。
    # absolute_check = {'valid': not unresolved_pulses and not unresolved_voice,
    absolute_check = {'valid': not unresolved_pulses and not unresolved_voice and not phase_resolution['unresolved_phase_conflicts'],
                      'unresolved_source_phase_conflicts': phase_resolution['unresolved_phase_conflicts'],
                      'pulse_count': len(pulse_residuals), 'unresolved_pulses': unresolved_pulses,
                      'unresolved_vocal_regions': unresolved_voice, 'vocal_expression_or_notation_review': review_voice,
                      'source_evidence_accuracy_claimed': False,
                      'maximum_pulse_residual_seconds': max((abs(r['residual_seconds']) for r in pulse_residuals), default=0.)}
    audit = {'version': VERSION, 'policy': deepcopy(POLICY),
             'status': 'performance_time_reconciled' if any(r['status'] == 'source_performance_time_refitted' for r in regional) else 'retained_clock',
             'sources': {name: {k: v for k, v in track.items() if k != 'attacks'} for name, track in tracks.items()},
             'periodic_windows': windows, 'regions': regional, 'vocal_before': before, 'vocal_after': after,
             'source_pulse_residuals': pulse_residuals, 'music_residual_check': absolute_check,
             'source_event_phase_resolution': phase_resolution,
             'vocal_residuals': residuals, 'notation_ticks_unchanged': True, 'original_source_seconds_unchanged': True,
             'human_answers_used': False, 'related_tracks_counted_once': True}
    return updated, audit


# 连续唱段拍轴与原唱同步修复：新增只更新物理秒映射和派生误差，音符/歌词/装饰分类/小节tick完全保留。
def apply_performance_clock(base, knots, audit, correction=None):
    vocal = deepcopy(base)
    # 连续唱段拍轴与原唱同步修复：修改，旧提前构造映射保留；先给出明确单调校验错误。
    # timing = vocal['timing']; mapping = TempoMap(knots); origin = timing['score_start_quarter']
    timing = vocal['timing']; origin = timing['score_start_quarter']
    if any(a['quarter'] >= b['quarter'] or a['seconds'] >= b['seconds'] for a, b in zip(knots, knots[1:])):
        raise ValueError('演奏拍轴必须严格单调，不能挪动或变速原歌手录音补偿。')
    mapping = TempoMap(knots)
    timing.update(knots=deepcopy(knots), score_start_seconds=mapping.quarters_to_seconds(origin),
                  tempo_source='source_bound_continuous_performance_clock',
                  performance_beat_clock={'version': VERSION, 'status': audit['status'],
                                          'notation_ticks_preserved': True, 'original_audio_seconds_preserved': True})
    errors = []
    for note in vocal['quantized_notes']:
        for side in ('start', 'end'):
            actual = mapping.quarters_to_seconds(note[side + '_tick'] / PPQ + origin)
            note['quantized_' + side + '_seconds'] = actual
            note[side + '_error_seconds'] = actual - note[side + '_seconds']
            errors.append(abs(note[side + '_error_seconds']))
    errors.sort()
    vocal['statistics']['quantization_error_seconds'] = {
        'median_abs': float(np.median(errors)) if errors else 0.,
        'p95_abs': errors[min(len(errors) - 1, int(.95 * len(errors)))] if errors else 0.,
        'max_abs': max(errors, default=0.)}
    vocal['statistics']['performance_beat_clock'] = deepcopy(audit['music_residual_check'])
    vocal['tempo_events'] = tempo_events(mapping, timing, vocal['statistics']['total_ticks'])
    vocal.setdefault('decoder', {})['performance_beat_clock'] = {
        'version': VERSION, 'notation_source_unchanged': True, 'source_seconds_preserved': True,
        'review_required': bool(audit['music_residual_check']['vocal_expression_or_notation_review'])}
    if correction is not None:
        vocal['performance_clock_correction'] = deepcopy(correction)
    return vocal


# 连续唱段拍轴与原唱同步修复：新增历史策略重放，各版的源绑定严格重建仍独立有效。
def reconstruct_base(original, binding, correction):
    if correction.get('base_structural_correction'):
        from structure_beat_clock import derive_structural_vocal
        return derive_structural_vocal(original, binding, correction['base_structural_correction'])
    if correction.get('base_local_correction'):
        from local_beat_clock import derive_local_vocal
        return derive_local_vocal(original, binding, correction['base_local_correction'])
    if correction.get('base_phase_correction'):
        from beat_phase_alignment import derive_phase_vocal
        return derive_phase_vocal(original, correction['base_phase_correction'])
    if correction.get('base_grid_correction'):
        from accompaniment_rebar import derive_vocal
        return derive_vocal(original, correction['base_grid_correction'])
    return deepcopy(original)


# 连续唱段拍轴与原唱同步修复：新增版本/来源/完整证据确定重放，拒绝人工平移或静默改写已认可谱面。
def derive_performance_vocal(original, binding, correction):
    # 局部时序与弱证据通用修复：新增版本2派生分发；版本1策略及以下旧重建代码完整保留。
    if correction.get('version') == 2:
        from performance_clock_refinement import derive_refined_vocal
        return derive_refined_vocal(original, binding, correction)
    # 跨歌曲和弦复用与器乐准备：新增版本3分发，旧版本及旧策略字典保持。
    if correction.get('version') == 3:
        from performance_clock_evidence import derive_evidence_vocal
        return derive_evidence_vocal(original, binding, correction)
    if (correction.get('version') != VERSION or correction.get('policy') != POLICY
            or correction.get('source_vocal_project_sha256') != binding['vocal_project_sha256']
            or correction.get('source_fingerprints') != {k: s['sha256'] for k, s in binding['sources'].items()}):
        raise ValueError('演奏拍轴派生策略或源指纹不一致。')
    base = reconstruct_base(original, binding, correction)
    knots, audit = infer_performance_clock(base, binding, Path(correction['feature_cache']))
    if audit != correction.get('clock_evidence'):
        raise ValueError('连续演奏拍轴证据不能由绑定原轨确定重建。')
    return apply_performance_clock(base, knots, audit, correction)


# 连续唱段拍轴与原唱同步修复：新增种子语义区分；原器乐保留录音秒，合成演唱伴奏保留拍位供重编。
def restore_synthetic_seed_ticks(old_shared, old_vocal, old_arrangements, shared, vocal, fresh):
    from accompaniment_analysis import SongClock, section_at
    from accompaniment_arrange import harmony_at
    old_clock, clock = SongClock(old_vocal), SongClock(vocal)
    old_notes = {n['id']: n for n in old_arrangements['guitar']['notes']}
    changes = []
    for note in fresh['guitar']['notes']:
        old = old_notes[note['id']]
        # 连续唱段拍轴与原唱同步修复：新增只作用合成普通伴奏，带源旋律ID/器乐角色的音乐仍按源秒迁移。
        synthetic = (old['role'] in ('bass', 'harmony') and not old.get('source_melody_id')
                     and section_at(old_shared['sections'], old_clock.seconds(old['start_tick']))['kind'] == 'vocal')
        if not synthetic:
            continue
        before = [note['start_tick'], note['end_tick']]
        note.update(start_tick=old['start_tick'], end_tick=old['end_tick'])
        note['chord_id'] = harmony_at(shared, note['start_tick'])['id']
        note['texture_measure'] = note['start_tick'] // shared['statistics']['bar_ticks'] + 1
        note['section'] = section_at(shared['sections'], clock.seconds(note['start_tick']))['kind']
        if before != [note['start_tick'], note['end_tick']]:
            changes.append({'note_id': note['id'], 'from_ticks': before, 'to_ticks': [note['start_tick'], note['end_tick']]})
    for event, old in zip(fresh['guitar']['attack_events'], old_arrangements['guitar']['attack_events']):
        if section_at(old_shared['sections'], old_clock.seconds(old['start_tick']))['kind'] == 'vocal':
            event['start_tick'] = old['start_tick']
            chord = harmony_at(shared, event['start_tick'])
            event.update(chord_id=chord['id'], sounding_name=chord['name'])
    fresh['guitar']['beat_phase_seed']['source_notes'] = deepcopy(fresh['guitar']['notes'])
    fresh['guitar']['performance_seed_timing'] = {'synthetic_accompaniment_tick_restorations': changes,
                                                'instrumental_source_seconds_preserved': True,
                                                'reason': 'synthetic_notes_are_score_time_not_original_source_audio'}
    return fresh


# 连续唱段拍轴与原唱同步修复：新增一体升级，所有和声取窗、编配、正式MIDI与合播复用同一修正拍轴。
def correct_performance_project(shared, vocal, arrangements, cache_dir):
    if vocal.get('performance_clock_correction'):
        return shared, vocal, arrangements
    from accompaniment_analysis import analyze
    # 渴首次吉他编配：修改，重建阶段继承绑定的乐器范围；原代码注释保留。
    # from accompaniment_arrange import arrange_guitar, arrange_piano
    # 渴首次吉他编配：新增按所选乐器执行，保留各乐器原验证。
    from accompaniment_arrange import arrange_requested
    from accompaniment_texture_policy import add_block_support
    from beat_phase_alignment import seed_existing_music, align_piano_bass
    from local_beat_clock import reusable_guitar_configuration
    binding = shared['input_binding']; cache = Path(cache_dir).resolve()
    copy_features(binding, cache, [vocal.get('structural_clock_correction', {}).get('feature_cache'),
                                  vocal.get('local_clock_correction', {}).get('feature_cache')])
    knots, audit = infer_performance_clock(vocal, binding, cache)
    # 连续唱段拍轴与原唱同步修复：新增不确定输出的可审阅诊断，即使安全门限停止发布也留下实际原因。
    from score_export import save_json
    save_json(cache.parent / 'performance_clock_evidence.json', audit)
    correction = {'version': VERSION, 'policy': deepcopy(POLICY),
                  'source_vocal_project_sha256': binding['vocal_project_sha256'],
                  'source_fingerprints': {k: s['sha256'] for k, s in binding['sources'].items()},
                  'base_structural_correction': deepcopy(vocal.get('structural_clock_correction')),
                  'base_local_correction': deepcopy(vocal.get('local_clock_correction')),
                  'base_phase_correction': deepcopy(vocal.get('beat_phase_correction')),
                  'base_grid_correction': deepcopy(vocal.get('grid_correction')),
                  'feature_cache': str(cache), 'clock_evidence': audit}
    updated = apply_performance_clock(vocal, knots, audit, correction)
    if audit['status'] == 'retained_clock':
        retained = deepcopy(shared)
        retained['performance_beat_clock'] = deepcopy(audit)
        return retained, updated, arrangements
    fresh_shared = add_block_support(analyze(binding, updated, cache), updated, cache)
    for field in ('arrangement_policy', 'musical_structure', 'melodic_motif_matches'):
        if field in shared:
            fresh_shared[field] = deepcopy(shared[field])
    fresh_shared['performance_beat_clock'] = deepcopy(audit)
    # 渴首次吉他编配：修改，避免未请求乐器阻塞所选乐器；原代码注释保留。
    # fresh = {'guitar': arrange_guitar(fresh_shared, updated, arrangements['guitar']['configuration']['capo_fret']),
    #          'piano': arrange_piano(fresh_shared, updated)}
    # 渴首次吉他编配：新增按所选乐器执行，保留各乐器原验证。
    fresh = arrange_requested(fresh_shared, updated, arrangements['guitar']['configuration']['capo_fret'])
    fresh = seed_existing_music(shared, vocal, arrangements, fresh_shared, updated, fresh, source_time_sections=True)
    # 连续唱段拍轴与原唱同步修复：新增恢复合成种子拍位；沿旧秒反量化会在换夹处制造虚假的密集错位。
    fresh = restore_synthetic_seed_ticks(shared, vocal, arrangements, fresh_shared, updated, fresh)
    fresh['guitar']['configuration'].update(reusable_guitar_configuration(arrangements['guitar']['configuration']))
    fresh['guitar']['configuration']['beat_synchronous_patterns'] = True
    # 渴首次吉他编配：修改，仅对已选择钢琴校准钢琴低音；原代码注释保留。
    # align_piano_bass(fresh_shared, updated, fresh['piano'])
    # 渴首次吉他编配：新增按所选乐器执行，保留各乐器原验证。
    if 'piano' in fresh:
        align_piano_bass(fresh_shared, updated, fresh['piano'])
    return fresh_shared, updated, fresh
