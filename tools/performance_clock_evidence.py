"""跨歌曲和弦复用与器乐准备：版本3，解析相关分轨近攻击与弱轨／多字联合拟合。"""
from collections import defaultdict
from copy import deepcopy
from pathlib import Path
import sys
import performance_beat_clock as legacy
import performance_clock_refinement as previous

# 跨歌曲和弦复用与器乐准备：新增独立版本，旧1／2全部阈值与严格重建不变。
VERSION = 3
POLICY = dict(deepcopy(previous.POLICY), version=VERSION,
              source_event_resolution_version=1, correlated_attack_tolerance_quarters=.08,
              weak_pulse_local_weight_fraction=.15,
              strong_pulse_weights_preserved=True, original_attack_seconds_preserved=True)


# 跨歌曲和弦复用与器乐准备：新增仅解决相关轨间近距离倒置；同轨两次攻击、独立低音及宽距离冲突仍拒绝。
def resolve_source_pulses(rows, nominal):
    _, original = legacy.deduplicate_source_pulses(rows, nominal)
    old_tolerance = nominal * legacy.POLICY['same_source_event_tolerance_quarters']
    tolerance = nominal * POLICY['correlated_attack_tolerance_quarters']
    by_family = defaultdict(list)
    for row in rows:
        by_family[row['family']].append(row)
    groups = []
    for family, values in by_family.items():
        local = []
        for row in sorted(values, key=lambda r: r['seconds']):
            if not local or row['seconds'] - local[-1][0]['seconds'] > old_tolerance:
                local.append([row])
            else:
                local[-1].append(row)
        groups.extend(local)
    resolved, removed = [], set()
    for conflict in original['unresolved_phase_conflicts']:
        if conflict['family'] != legacy.POLICY['related_sources_family']:
            continue
        pair = [next((i for i, group in enumerate(groups)
                      if group[0]['family'] == conflict['family']
                      and any(r['seconds'] == t for r in group)), None)
                for t in conflict['source_seconds']]
        if None in pair or pair[0] == pair[1] or any(i in removed for i in pair):
            continue
        a, b = (groups[i] for i in pair)
        combined = a + b
        seconds = [r['seconds'] for r in combined]
        # 跨歌曲和弦复用与器乐准备：新增完整跨度而非连锁距离；同源两次不同攻击不冒认为串音副本。
        if (max(seconds) - min(seconds) > tolerance
                or {r['source'] for r in a} & {r['source'] for r in b}):
            continue
        winner = max(combined, key=lambda r: r['selection_rank'])
        removed.update(pair)
        resolved.append({'family': conflict['family'], 'source_seconds': sorted(set(seconds)),
                         'sources': sorted({r['source'] for r in combined}),
                         'candidate_quarters': sorted({r['quarter'] for r in combined}),
                         'chosen_quarter': winner['quarter'], 'chosen_seconds': winner['seconds'],
                         'maximum_span_seconds': tolerance, 'seconds_averaged': False,
                         'status': 'correlated_track_near_attack_resolved_by_existing_window_rank'})
        groups.append([winner])
    candidates = [r for i, group in enumerate(groups) if i not in removed for r in group]
    observations, audit = legacy.deduplicate_source_pulses(candidates, nominal)
    audit['correlated_track_near_attack_resolution'] = resolved
    audit['resolution_version'] = POLICY['source_event_resolution_version']
    return observations, audit


# 跨歌曲和弦复用与器乐准备：新增只有可靠多字触发的局部窗才下调弱脉冲，不删攻击，不改原秒与强脉冲。
def local_observation_weights(region, pulse, heads, interiors):
    weighted, changes = [], []
    threshold = legacy.POLICY['minimum_reliable_pulse_weight']
    for row in pulse:
        copy = deepcopy(row)
        if (len(heads) >= previous.POLICY['minimum_heads']
                and region['first_quarter'] < row['quarter'] < region['last_quarter']
                and row['weight'] < threshold):
            copy['weight'] *= POLICY['weak_pulse_local_weight_fraction']
            changes.append({'quarter': row['quarter'], 'source': row.get('source'),
                            'original_weight': row['weight'], 'fit_weight': copy['weight']})
        weighted.append(copy)
    return weighted + heads + interiors, {'weak_pulses': changes, 'strong_pulse_weights_changed': False,
                                         'source_seconds_changed': False, 'heads_preserved': len(heads)}


# 跨歌曲和弦复用与器乐准备：新增使用既有窗口、边界及独立验收，只显式替换证据解析和局部弱轨权重。
def infer_evidence_clock(base, binding, cache):
    return previous.infer_refined_clock(base, binding, cache, source_pulse_resolver=resolve_source_pulses,
                                       local_observation_weights=local_observation_weights, evidence_policy=POLICY)


# 跨歌曲和弦复用与器乐准备：新增应用新版拍秒，不改变谱面tick、人声源秒、音高与歌词。
def apply_evidence_clock(base, knots, audit, correction=None):
    return previous.apply_refined_clock(base, knots, audit, correction)


# 跨歌曲和弦复用与器乐准备：新增严格策略／源指纹／完整证据重放，拒绝篡改校准或手工平移原唱。
def derive_evidence_vocal(original, binding, correction):
    if (correction.get('version') != VERSION or correction.get('policy') != POLICY
            or correction.get('source_vocal_project_sha256') != binding['vocal_project_sha256']
            or correction.get('source_fingerprints') != {k: s['sha256'] for k, s in binding['sources'].items()}):
        raise ValueError('跨歌曲源证据拍轴策略或源指纹不一致。')
    base = legacy.reconstruct_base(original, binding, correction)
    knots, audit = infer_evidence_clock(base, binding, Path(correction['feature_cache']))
    if audit != correction.get('clock_evidence'):
        raise ValueError('跨歌曲源证据拍轴无法从绑定原轨严格重建。')
    return apply_evidence_clock(base, knots, audit, correction)


# 跨歌曲和弦复用与器乐准备：新增显式升级入口，重用同源分析与两套编配；历史普通重导不升级。
def correct_evidence_project(shared, vocal, arrangements, cache_dir):
    return previous.correct_refined_project(shared, vocal, arrangements, cache_dir, strategy=sys.modules[__name__])
