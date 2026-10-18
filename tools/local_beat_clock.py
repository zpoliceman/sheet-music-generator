"""局部拍轴与原唱同步纠错：新增源绑定的多轨拍轴、确定性派生和伴奏共同时间。"""
from copy import deepcopy
from pathlib import Path
import math
import numpy as np

VERSION = 1
POLICY = {'version': VERSION, 'low_midi_max': 55, 'relative_pitch_floor': .30,
          'weak_attack_floor': .055, 'cluster_seconds': .075, 'normalization_percentile': 85,
          'track_weights': {'bass': 1.4, 'accompaniment': 1.1, 'other': .45,
                            'six_piano': .6, 'six_other': .4, 'mix': .25},
          'minimum_period_ratio': .80, 'maximum_period_ratio': 1.35,
          'maximum_missing_span': 4, 'beam_width': 18, 'period_bin_seconds': .035,
          'prediction_grid_per_beat': 8, 'smooth_weight': .65, 'smooth_sigma': .13,
          'tempo_prior_weight': .35, 'tempo_prior_sigma': .16,
          'attack_reward': 1.7, 'missing_penalty': .9, 'terminal_support_floor': 1.1}


# 局部拍轴与原唱同步纠错：新增按源指纹读取实测起音，整曲低频证据不依赖歌词或歌曲名称。
def collect_candidates(binding, cache_dir):
    from accompaniment_analysis import extract_features
    observations = []
    for name, weight in POLICY['track_weights'].items():
        source = binding['sources'].get(name)
        if source is None:
            continue
        features = extract_features(source, cache_dir, name)
        rows = []
        for attack in features.attacks:
            low = max((p['weight'] for p in attack['pitches']
                       if p['pitch_midi'] <= POLICY['low_midi_max'] and
                       p['relative_weight'] >= POLICY['relative_pitch_floor']), default=0.)
            if low:
                rows.append((attack['seconds'] + float(source.get('offset_seconds', 0)), low))
        if not rows:
            continue
        scale = max(1e-9, float(np.percentile([r[1] for r in rows], POLICY['normalization_percentile'])))
        observations.extend({'seconds': float(t), 'strength': weight * min(1.5, w/scale), 'track': name}
                            for t, w in rows if w/scale > POLICY['weak_attack_floor'])
    return fuse_candidates(observations)


# 局部拍轴与原唱同步纠错：新增同一次起音的多轨聚合，单轨最多贡献一次，不把串音视作多个独立真值。
def fuse_candidates(observations):
    clusters = []
    for row in sorted(observations, key=lambda x: x['seconds']):
        if not clusters or row['seconds'] - clusters[-1][0]['seconds'] > POLICY['cluster_seconds']:
            clusters.append([row])
        else:
            clusters[-1].append(row)
    result = []
    for cluster in clusters:
        tracks = {}
        for row in cluster:
            if row['track'] not in tracks or row['strength'] > tracks[row['track']]['strength']:
                tracks[row['track']] = row
        rows = sorted(tracks.values(), key=lambda x: x['seconds'])
        total = sum(r['strength'] for r in rows)
        cumulative = 0.
        for row in rows:
            cumulative += row['strength']
            if cumulative >= total/2:
                seconds = row['seconds']
                break
        result.append({'seconds': float(seconds), 'strength': min(2.6, total),
                       'tracks': sorted(tracks), 'observations': rows})
    return result


# 局部拍轴与原唱同步纠错：新增二阶拍点链，缺失拍可插值，倍频和瞬间变速受约束。
def track_direction(nodes, anchor, period, direction=1):
    rows = [{'seconds': 0., 'strength': 0., 'tracks': []}]
    rows += [dict(n, seconds=direction*(n['seconds']-anchor)) for n in nodes
             if direction*(n['seconds']-anchor) > .35*period]
    extent = max((n['seconds'] for n in rows), default=0.)
    grid = POLICY['prediction_grid_per_beat']
    rows += [{'seconds': i*period/grid, 'strength': 0., 'tracks': []}
             for i in range(math.ceil(.35*grid), math.ceil(extent/period*grid))]
    rows.sort(key=lambda x: x['seconds'])
    states = [{} for _ in rows]
    states[0][(0, round(period/POLICY['period_bin_seconds']))] = (0., period, 0, ())
    span = POLICY['maximum_missing_span']
    for index, node in enumerate(rows[1:], 1):
        current = {}
        for previous_index in range(index-1, -1, -1):
            delta = node['seconds'] - rows[previous_index]['seconds']
            if delta > span*period*POLICY['maximum_period_ratio']:
                break
            for score, previous_period, count, path in states[previous_index].values():
                for step in range(1, span+1):
                    local_period = delta/step
                    if not period*POLICY['minimum_period_ratio'] <= local_period <= period*POLICY['maximum_period_ratio']:
                        continue
                    smooth = POLICY['smooth_weight'] * (math.log(local_period/previous_period)/POLICY['smooth_sigma'])**2 / max(1., math.sqrt(step))
                    prior = step*POLICY['tempo_prior_weight'] * (math.log(local_period/period)/POLICY['tempo_prior_sigma'])**2
                    value = score + POLICY['attack_reward']*node['strength'] - smooth - prior - POLICY['missing_penalty']*(step-1)
                    key = (count+step, round(local_period/POLICY['period_bin_seconds']))
                    if key not in current or value > current[key][0]:
                        current[key] = (value, local_period, count+step, path+((index, step),))
        states[index] = dict(sorted(current.items(), key=lambda item: item[1][0], reverse=True)[:POLICY['beam_width']])
    valid = [i for i in range(1, len(rows)) if states[i] and rows[i]['strength'] > POLICY['terminal_support_floor']]
    beats = [{'seconds': anchor, 'step': 0, 'strength': 0., 'tracks': [], 'kind': 'anchor'}]
    if not valid:
        return beats
    final = max(valid, key=lambda i: max(r[0] for r in states[i].values()))
    best = max(states[final].values(), key=lambda x: x[0])
    count, previous_seconds = 0, 0.
    for index, step in best[3]:
        node = rows[index]
        for k in range(1, step+1):
            observed = k == step and bool(node['tracks'])
            beats.append({'seconds': anchor+direction*(previous_seconds+(node['seconds']-previous_seconds)*k/step),
                          'step': direction*(count+k), 'strength': node['strength'] if observed else 0.,
                          'tracks': node['tracks'] if observed else [],
                          'kind': 'observed_attack' if observed else 'predicted_missing_beat'})
        previous_seconds = node['seconds']
        count += step
    return beats


# 局部拍轴与原唱同步纠错：新增可独立测试的拍轴拟合；预测节点只在实测邻点之间插值，锚点始终固定。
def fit_clock(nodes, anchor_seconds, anchor_quarter, period, beat_quarters=1.):
    beats = track_direction(nodes, anchor_seconds, period)
    beats += track_direction(nodes, anchor_seconds, period, -1)[1:]
    beats = sorted((dict(b, quarter=anchor_quarter+b['step']*beat_quarters) for b in beats), key=lambda b: b['quarter'])
    supported = [i for i, b in enumerate(beats) if b['tracks'] or b['kind'] == 'anchor']
    for a, b in zip(supported, supported[1:]):
        for index in range(a+1, b):
            fraction = (beats[index]['quarter']-beats[a]['quarter'])/(beats[b]['quarter']-beats[a]['quarter'])
            beats[index]['seconds'] = beats[a]['seconds']+(beats[b]['seconds']-beats[a]['seconds'])*fraction
            beats[index]['kind'] = 'interpolated_missing_beat'
    return beats


# 局部拍轴与原唱同步纠错：新增实测证据决策与来源审计，未知/稀疏歌曲不套样曲拍点。
def infer_clock(binding, base, cache_dir):
    from score_export import TempoMap
    from rhythm_notation import MeterTree
    timing = base['timing']
    mapping = TempoMap(timing['knots'])
    tree = MeterTree.from_meter(timing['meter'], timing.get('beat_groups'))
    beat_quarters = tree.groups[0]*tree.unit_ticks/480
    review = timing.get('beat_phase', {})
    anchor_quarter = float(review.get('anchor_quarter', mapping.seconds_to_quarters(max(0., timing.get('beat_origin_seconds', 0.)))))
    anchor_seconds = float(review.get('anchor_seconds', mapping.quarters_to_seconds(anchor_quarter)))
    period = 60/timing['steady_tempo_bpm']*beat_quarters
    nodes = collect_candidates(binding, cache_dir)
    beats = fit_clock(nodes, anchor_seconds, anchor_quarter, period, beat_quarters)
    observed = [b for b in beats if b['kind'] == 'observed_attack']
    strong = [b for b in observed if b['strength'] >= POLICY['terminal_support_floor']]
    sufficient = len(strong) >= 4 and beats[-1]['seconds']-beats[0]['seconds'] >= 6*period
    audit = {'version': VERSION, 'policy': deepcopy(POLICY), 'status': 'tracked' if sufficient else 'insufficient_evidence',
             'anchor_seconds': anchor_seconds, 'anchor_quarter': anchor_quarter, 'beat_quarters': beat_quarters,
             'candidate_count': len(nodes), 'observed_beat_count': len(observed), 'strong_beat_count': len(strong),
             'predicted_beat_count': sum(b['kind'] not in ('anchor', 'observed_attack') for b in beats),
             'last_supported_song_seconds': beats[-1]['seconds'], 'tail_extrapolation': 'last_supported_interval',
             'beats': beats, 'human_lyric_answers_used': False, 'confidence_kind': 'evidence_not_calibrated_accuracy'}
    knots = [{'seconds': b['seconds'], 'quarter': b['quarter']} for b in beats] if sufficient else deepcopy(timing['knots'])
    return knots, audit


# 局部拍轴与原唱同步纠错：新增由源工程和源音轨确定性重建的新派生，不允许任意修改人声或拍点。
def derive_local_vocal(original, binding, correction):
    from score_export import TempoMap, attach_lyrics, tempo_events, sha256
    from beat_phase_alignment import derive_phase_vocal
    from accompaniment_rebar import derive_vocal
    from phrase_rhythm import quantize_phrase
    from phrase_rhythm_local import POLICY as RHYTHM_POLICY
    if (correction.get('version') != VERSION or correction.get('policy') != POLICY or
            correction.get('rhythm_policy') != RHYTHM_POLICY or
            correction.get('source_vocal_project_sha256') != binding['vocal_project_sha256'] or
            correction.get('source_audio_sha256') != binding['sources']['mix']['sha256']):
        raise ValueError('局部拍轴派生来源或策略不匹配。')
    if sha256(binding['vocal_project']) != binding['vocal_project_sha256']:
        raise ValueError('局部拍轴绑定原人声工程已改变。')
    base = deepcopy(original)
    if correction.get('base_phase_correction'):
        base = derive_phase_vocal(original, correction['base_phase_correction'])
    elif correction.get('base_grid_correction'):
        base = derive_vocal(original, correction['base_grid_correction'])
    knots, audit = infer_clock(binding, base, Path(correction['feature_cache']))
    if correction.get('clock_evidence') != audit:
        raise ValueError('局部拍轴证据与原音轨重建结果不一致。')
    vocal = deepcopy(base)
    mapping = TempoMap(knots)
    bar_quarters = base['statistics']['bar_ticks']/480
    start = math.floor(mapping.seconds_to_quarters(0)/bar_quarters)*bar_quarters
    vocal['timing'].update(knots=knots, score_start_quarter=start,
                           score_start_seconds=mapping.quarters_to_seconds(start),
                           beat_origin_seconds=mapping.quarters_to_seconds(0),
                           local_beat_clock=deepcopy(audit), tempo_source='source_bound_local_beat_clock' if audit['status']=='tracked' else base['timing']['tempo_source'])
    if base['timing'].get('beat_phase'):
        pickup = start < 0 < mapping.quarters_to_seconds(0)
        vocal['timing'].update(initial_pickup_measure=pickup, measure_number_offset=1 if pickup else 0)
    events, notes, stats = quantize_phrase(deepcopy(base['quantized_notes']), vocal['lyrics']['characters'], mapping,
                                          vocal['timing'], vocal['audio_analysis']['duration_seconds'])
    vocal.update(events=events, quantized_notes=notes, statistics=stats,
                 lyric_mapping=attach_lyrics(events, vocal['lyrics']['characters']),
                 local_clock_correction=deepcopy(correction))
    vocal['tempo_events'] = tempo_events(mapping, vocal['timing'], stats['total_ticks'])
    vocal['decoder']['local_beat_clock'] = {'version': VERSION, 'source_seconds_pitch_and_ownership_preserved': True}
    vocal['decoder']['phrase_rhythm'] = deepcopy(stats['phrase_rhythm'])
    for index, section in enumerate(vocal['notation'].get('key_segments', [])):
        first = next(n for n in notes if n.get('lyric_index') == section['first_character_index'])
        section['performance_start_tick'] = first['start_tick']
        section['start_tick'] = math.ceil(first['start_tick']/stats['bar_ticks'])*stats['bar_ticks'] if index else 0
        section['start_measure'] = section['start_tick']//stats['bar_ticks']+1
        section['pickup_before_signature'] = bool(index and first['start_tick'] < section['start_tick'])
    return vocal


# 局部拍轴与原唱同步纠错：新增旧伴奏的明确升级，重算和声/演奏型，同时保留器乐原时间种子。
def correct_local_project(shared, vocal, arrangements, cache_dir):
    from score_export import read_json
    from accompaniment_analysis import analyze
    # 渴首次吉他编配：修改，重建阶段继承绑定的乐器范围；原代码注释保留。
    # from accompaniment_arrange import arrange_guitar, arrange_piano
    # 渴首次吉他编配：新增按所选乐器执行，保留各乐器原验证。
    from accompaniment_arrange import arrange_requested
    from accompaniment_texture_policy import add_block_support
    from beat_phase_alignment import seed_existing_music, align_piano_bass
    from phrase_rhythm_local import POLICY as RHYTHM_POLICY
    binding = shared['input_binding']
    if vocal.get('local_clock_correction'):
        return shared, vocal, arrangements
    # 局部拍轴与原唱同步纠错：新增同源特征缓存复制，只写本轮缓存，不重跑模型或覆盖旧文件。
    from shutil import copy2
    root = Path(__file__).resolve().parents[1]
    cache_dir = Path(cache_dir).resolve()
    if not cache_dir.is_relative_to(root/'test_outputs/accompaniment_runs'):
        raise ValueError('局部拍轴缓存必须位于本项目分析工作区。')
    cache_dir.mkdir(parents=True, exist_ok=True)
    for source in binding['sources'].values():
        token = 'v1_'+source['sha256'][:16]+'_22050_512_24_96'
        cached = sorted((root/'test_outputs/accompaniment_runs').glob('*/features/'+token+'.json'))
        if cached:
            for suffix in ('.json', '.npz'):
                src, dst = cached[0].with_suffix(suffix), cache_dir/(token+suffix)
                if src.is_file() and src.resolve() != dst and not dst.exists():
                    copy2(src, dst)
    knots, audit = infer_clock(binding, vocal, cache_dir)
    # 局部拍轴与原唱同步纠错：新增低证据回退，不能在未知曲或静音中伪造局部速度。
    if audit['status'] != 'tracked':
        assessed = deepcopy(shared)
        assessed['local_beat_clock'] = audit
        return assessed, vocal, arrangements
    correction = {'version': VERSION, 'policy': deepcopy(POLICY), 'rhythm_policy': deepcopy(RHYTHM_POLICY),
                  'source_vocal_project_sha256': binding['vocal_project_sha256'],
                  'source_audio_sha256': binding['sources']['mix']['sha256'],
                  'base_phase_correction': deepcopy(vocal.get('beat_phase_correction')),
                  'base_grid_correction': deepcopy(vocal.get('grid_correction')),
                  'feature_cache': str(Path(cache_dir).resolve()), 'clock_evidence': audit}
    updated = derive_local_vocal(read_json(binding['vocal_project']), binding, correction)
    fresh_shared = analyze(binding, updated, cache_dir)
    fresh_shared = add_block_support(fresh_shared, updated, cache_dir)
    fresh_shared['arrangement_policy'] = deepcopy(shared.get('arrangement_policy', {}))
    fresh_shared['local_beat_clock'] = deepcopy(audit)
    capo = arrangements['guitar']['configuration']['capo_fret']
    # 渴首次吉他编配：修改，避免未请求乐器阻塞所选乐器；原代码注释保留。
    # fresh = {'guitar': arrange_guitar(fresh_shared, updated, capo), 'piano': arrange_piano(fresh_shared, updated)}
    # 渴首次吉他编配：新增按所选乐器执行，保留各乐器原验证。
    fresh = arrange_requested(fresh_shared, updated, capo)
    # 局部拍轴与原唱同步纠错：修改，原调用保留；明确采用器乐种子迁移后的完整编配结果。
    # seed_existing_music(shared, vocal, arrangements, fresh_shared, updated, fresh)
    # 局部拍轴与原唱同步纠错：修改，保留原调用；器乐种子和新演唱伴奏必须按同一个实际时间分区。
    # fresh = seed_existing_music(shared, vocal, arrangements, fresh_shared, updated, fresh)
    fresh = seed_existing_music(shared, vocal, arrangements, fresh_shared, updated, fresh, source_time_sections=True)
    # 局部拍轴与原唱同步纠错：修改，保留复制全部配置的原式；旧拍轴派生的换夹结果须重新计算。
    # fresh['guitar']['configuration'].update(deepcopy(arrangements['guitar']['configuration']))
    fresh['guitar']['configuration'].update(reusable_guitar_configuration(arrangements['guitar']['configuration']))
    # 局部拍轴与原唱同步纠错：新增真实低音入口与普通右手型同拍，休止/换和弦后重启。
    fresh['guitar']['configuration']['beat_synchronous_patterns'] = True
    # 渴首次吉他编配：修改，仅对已选择钢琴校准钢琴低音；原代码注释保留。
    # align_piano_bass(fresh_shared, updated, fresh['piano'])
    # 渴首次吉他编配：新增按所选乐器执行，保留各乐器原验证。
    if 'piano' in fresh:
        align_piano_bass(fresh_shared, updated, fresh['piano'])
    return fresh_shared, updated, fresh


# 局部拍轴与原唱同步纠错：新增保留演奏偏好，移除旧拍轴的结果缓存，否则换夹程序会误判已完成。
def reusable_guitar_configuration(configuration):
    result = deepcopy(configuration)
    for field in ('capo_policy', 'capo_segments', 'fixed_capo_entire_song'):
        result.pop(field, None)
    return result
