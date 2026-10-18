"""尾段原声局部补证：冻结已验拍轴，用原音衰减与只读起音缓存关闭纯尾响覆盖。"""
# 尾段原声局部补证：新增独立版本；不修改原选择器、局部分组和四秒未观察边界门槛。
from copy import deepcopy
from functools import lru_cache
import json
# 工作目录改名兼容：证据记录保留传入绝对路径的拼写，不将目录联接解析成另一个名字；文件摘要及完整重放保持。
from pathlib import Path
import numpy as np
import soundfile as sf
from score_export import read_json, save_json, sha256
from source_meter_selection import fingerprint

POLICY = {'version': 1, 'scope': 'terminal_decay_only_frozen_parent_clock',
          'maximum_relative_peak_flux': .25, 'maximum_relative_median_rms': .08,
          'envelope_bin_seconds': .25, 'maximum_audible_growth_db': .5,
          'audible_floor_dbfs': -60., 'minimum_decay_db': 20.,
          'minimum_full_envelope_bins': 4, 'minimum_cached_roles': 3,
          'required_cached_roles': ['accompaniment', 'bass'],
          'normal_publication_allowed': False, 'new_beats_inserted': False}


def cache_dependencies(binding, folders):
    # 尾段原声局部补证：新增严格只读缓存选择，缺失不启动全曲音高分析，不将分轨当多张独立票。
    rows = []
    for role in ('accompaniment', 'bass', 'six_guitar', 'six_piano'):
        source = binding['sources'].get(role)
        if source is None:
            continue
        paths = sorted({p.resolve() for folder in folders for p in Path(folder).glob('v1_'+source['sha256'][:16]+'_22050_512_24_96.npz')})
        if not paths:
            continue
        if len({sha256(p) for p in paths}) != 1:
            raise ValueError('同源尾部缓存不一致，不能任意挑选')
        path = paths[0]; meta = path.with_suffix('.json')
        value = read_json(meta)
        if value.get('version') != 1 or value['source_sha256'] != source['sha256']:
            raise ValueError('尾部缓存来源或版本不符')
        rows.append({'role': role, 'path': str(path), 'sha256': sha256(path),
                     'metadata_path': str(meta), 'metadata_sha256': sha256(meta), 'source_sha256': source['sha256']})
    return rows


def _verify_dependencies(binding, dependencies):
    # 尾段原声局部补证：新增每次读取均核验文件，不让重放缓存掩盖后续改动。
    for row in dependencies:
        source = binding['sources'].get(row['role'])
        if (source is None or source['sha256'] != row['source_sha256']
                or sha256(row['path']) != row['sha256'] or sha256(row['metadata_path']) != row['metadata_sha256']):
            raise ValueError('局部尾段补证缓存已改变')


def inspect_decay(binding, start, end, dependencies):
    # 尾段原声局部补证：新增原混音局部包络与全尾段缓存检查，不能只检查最后一秒而漏过前段新演奏。
    _verify_dependencies(binding, dependencies)
    source = binding['sources']['mix']
    if sha256(source['path']) != source['sha256'] or abs(end-binding['duration_seconds']) > 1e-6:
        raise ValueError('尾段必须绑定原曲完整结尾')
    with sf.SoundFile(source['path']) as stream:
        if abs(stream.frames/stream.samplerate - end) > 1e-6:
            raise ValueError('原曲实际结尾与补证范围不符')
        rate = stream.samplerate
        first = round(start*rate)
        stream.seek(first)
        audio = stream.read(dtype='float64', always_2d=True)
    hop = round(POLICY['envelope_bin_seconds']*rate)
    full = len(audio)//hop
    rms = np.array([np.sqrt(np.mean(audio[i*hop:(i+1)*hop]**2)) for i in range(full)])
    db = 20*np.log10(np.maximum(1e-9, rms))
    audible = (db[:-1] >= POLICY['audible_floor_dbfs']) | (db[1:] >= POLICY['audible_floor_dbfs'])
    growth = float(np.max(np.diff(db)[audible])) if np.any(audible) else 0.
    drop = float(db[0]-db[-1]) if len(db) else 0.
    issues = []
    if full < POLICY['minimum_full_envelope_bins']:
        issues.append('insufficient_decay_envelope')
    if growth > POLICY['maximum_audible_growth_db']:
        issues.append('original_mix_grows_again')
    if len(db) == 0 or db[-1] > POLICY['audible_floor_dbfs'] or drop < POLICY['minimum_decay_db']:
        issues.append('terminal_fade_not_established')
    roles = {row['role'] for row in dependencies}
    if len(roles) < POLICY['minimum_cached_roles'] or not set(POLICY['required_cached_roles']) <= roles:
        issues.append('insufficient_independent_tail_description')
    details = []
    for row in dependencies:
        meta = read_json(row['metadata_path'])
        if meta.get('version') != 1 or meta['source_sha256'] != row['source_sha256']:
            raise ValueError('尾段缓存元数据来源不符')
        with np.load(row['path'], allow_pickle=False) as data:
            times, flux, energy = [data[key] for key in ('times', 'flux', 'rms')]
            mask = (times >= start) & (times <= end)
            if (not np.any(mask) or times[-1] < end-.05 or not np.isfinite(flux).all()
                    or not np.isfinite(energy).all()):
                raise ValueError('尾部缓存缺帧或数值无效')
            relative_flux = float(np.max(flux[mask])/max(1e-8,np.percentile(flux,90)))
            relative_rms = float(np.median(energy[mask])/max(1e-8,np.percentile(energy,90)))
        attacks = [a for a in meta['attacks'] if start <= a['seconds'] <= end]
        prior = [a for a in meta['attacks'] if a['seconds'] < start]
        details.append({'role':row['role'],'relative_peak_flux':relative_flux,'relative_median_rms':relative_rms,
                        'new_cached_attack_seconds':[a['seconds'] for a in attacks],
                        'last_prior_attack_seconds':prior[-1]['seconds'] if prior else None})
        if attacks or relative_flux > POLICY['maximum_relative_peak_flux'] or relative_rms > POLICY['maximum_relative_median_rms']:
            issues.append('active_or_ambiguous_tail:'+row['role'])
    return {'status':'supported' if not issues else 'needs_review', 'issues':issues,
            'kind':'decay_of_preexisting_sound' if not issues else 'unresolved',
            'start_seconds':start,'end_seconds':end,'original_mix_envelope':{
                'bin_seconds':POLICY['envelope_bin_seconds'],'full_bin_count':full,
                'levels_dbfs':db.tolist(),'maximum_audible_growth_db':growth,'decay_db':drop},
            'cached_tracks':details, 'sustain_and_room_reverb_not_separated':True,
            'new_attack_or_new_beat_claimed':False, 'audio_tail_must_be_retained':True}


def apply_tail_evidence(parent_result, observation):
    # 尾段原声局部补证：新增仅消除实际已补证的尾部覆盖项；其它单位／分组／窗口未决均保留。
    result = deepcopy(parent_result)
    expected = {'kind':'tail_not_observed','start_seconds':observation['start_seconds'],'end_seconds':observation['end_seconds']}
    if expected not in result['coverage']['issues'] or expected not in result['issues']:
        raise ValueError('局部证据范围没有精确对应原决定尾部缺口')
    if observation['status'] == 'supported':
        result['issues'].remove(expected); result['coverage']['issues'].remove(expected)
        result['coverage']['status'] = 'supported' if not result['coverage']['issues'] else 'needs_review'
        for edge in result['coverage']['edge_ranges']:
            if edge['kind']=='tail':
                edge.update(status='source_verified_terminal_decay',unmetered_music_claimed=False,
                            new_beats_inserted=False,terminal_evidence=deepcopy(observation))
        # 尾段原声局部补证：新增候选分析账本原样保留，补证覆盖单列，不改任何候选拍点或首拍。
        result['status']='passed' if not result['issues'] else 'needs_review'
        result['downstream_timing_revision_allowed']=not result['issues']
    result['terminal_tail_supplement']={'policy':deepcopy(POLICY),'observation':deepcopy(observation),
                                       'parent_candidates_unchanged':True,'normal_publication_allowed':False}
    return result


def _parent(path, binding):
    # 尾段原声局部补证：新增重放原决定，允许其保留尾部未决，不接受裸passed或二次补证套娃。
    from first_generation_source import _replay_decision
    from first_generation_meter import POLICY as PARENT_POLICY
    path=Path(path).resolve()
    if read_json(path).get('version') != 1:
        raise ValueError('尾部补证只接受原始首次拍轴决定')
    return deepcopy(_replay_decision(str(path),sha256(path),json.dumps(binding,sort_keys=True,ensure_ascii=False),fingerprint(PARENT_POLICY)))


def build_tail_decision(parent_path, binding, dependencies):
    # 尾段原声局部补证：新增确定性补证；范围来自父决定，不接受歌名、歌词、固定秒数或人工答案。
    parent = _parent(parent_path,binding)
    gaps = [row for row in parent['result']['coverage']['issues'] if row['kind']=='tail_not_observed']
    if len(gaps)!=1:
        raise ValueError('没有唯一可补证的末端覆盖缺口')
    gap=gaps[0]
    observation=inspect_decay(binding,gap['start_seconds'],gap['end_seconds'],dependencies)
    result=deepcopy(parent)
    result.update(version=2, result=apply_tail_evidence(parent['result'],observation),
        tail_provenance={'parent_decision_path':str(Path(parent_path).absolute()),
                         'parent_decision_sha256':sha256(parent_path),'policy':deepcopy(POLICY),
                         'dependencies':deepcopy(dependencies),'parent_result_sha256':fingerprint(parent['result'])})
    return result


@lru_cache(maxsize=8)
def _replay(path, expected, binding_json, policy_sha):
    # 尾段原声局部补证：新增完整局部重放，策略及原文件指纹均进入缓存身份。
    bound=read_json(path); provenance=bound['tail_provenance'];binding=json.loads(binding_json)
    actual=build_tail_decision(provenance['parent_decision_path'],binding,provenance['dependencies'])
    if bound != actual or sha256(path)!=expected:
        raise ValueError('尾部补证不能从原曲和原决定确定性重放')
    return actual


def replay_tail_decision(path,binding):
    # 尾段原声局部补证：新增缓存外依赖核验；父文件、来源或缓存变化立即失效。
    from first_generation_source import read_bound_evidence
    path=Path(path).resolve();bound=read_json(path);provenance=bound['tail_provenance']
    if (bound.get('version')!=2 or provenance['policy']!=POLICY
            or sha256(provenance['parent_decision_path'])!=provenance['parent_decision_sha256']):
        raise ValueError('局部补证父决定或策略已变')
    read_bound_evidence(bound['evidence_path'],binding)
    _verify_dependencies(binding,provenance['dependencies'])
    return deepcopy(_replay(str(path),sha256(path),json.dumps(binding,sort_keys=True,ensure_ascii=False),fingerprint(POLICY)))


def supplement_tail(parent_path,binding,feature_folders,output):
    # 尾段原声局部补证：新增只另存的公共调用，失败也保留真实未决报告，不篡改父决定。
    from source_timing_acceptance import require_isolated_output
    output=require_isolated_output(Path(output),Path(__file__).resolve().parents[1])
    if output.exists():
        raise ValueError('局部尾部补证不能覆盖已有版本')
    value=build_tail_decision(parent_path,binding,cache_dependencies(binding,feature_folders))
    save_json(output,value)
    return value


def verified_tail_observation(vocal,binding):
    # 尾段原声局部补证：新增伴奏使用同一来源结论，不能复制一个尾响标记就删除实际新音。
    correction=vocal.get('first_source_meter_correction')
    if not correction:
        return None
    if sha256(correction['decision_path'])!=correction['decision_sha256']:
        raise ValueError('尾响编配约束对应的拍轴决定已变')
    from first_generation_source import load_first_decision
    decision=load_first_decision(correction['decision_path'],binding)
    observation=decision['result'].get('terminal_tail_supplement',{}).get('observation')
    # 两曲来源补证与首次生成：新增严格重放的新来源决定可携带末次实际攻击后的衰减，不覆盖旧尾响证书。
    if observation is None and decision.get('version')==3:
        observation=decision['result'].get('source_resolution',{}).get('terminal_observation')
    # 首拍与首尾局部补证：新增第四版继承严格衰减证据；实际活动部分不作为尾响删除。
    if observation is None and decision.get('version')==4:
        # 首拍与首尾局部补证：修改无尾部缺证的新决定可没有补充尾响，不能把空值当字典。
        # observation=decision['result'].get('source_content_supplement',{}).get('tail',{}).get('terminal_decay')
        observation=(decision['result'].get('source_content_supplement',{}).get('tail') or {}).get('terminal_decay')
    return deepcopy(observation) if observation and observation['status']=='supported' else None


def constrain_terminal_events(events,observation):
    # 尾段原声局部补证：新增只阻止已证实尾响内的假新起音；先前音符及完整结束不裁短，原候选另存供审查。
    if observation is None:
        return deepcopy(events),None
    # 两曲来源补证与首次生成：修改明确区分非单调持续声和已验衰减；两者均须通过来源重放，不允许裸标记冒充新来源。
    # if observation['status']!='supported' or observation['kind']!='decay_of_preexisting_sound':
    if observation['status']!='supported' or observation['kind'] not in ('decay_of_preexisting_sound','unarticulated_terminal_sustain'):
        raise ValueError('未经通过的尾部证据不能约束器乐')
    result=[];excluded=[]
    for event in events:
        start=event.get('source_start_seconds',event.get('start_seconds'))
        if start is None:
            raise ValueError('器乐候选缺少实际源起音秒数')
        if observation['start_seconds']<=start<observation['end_seconds']:
            excluded.append(deepcopy(event))
        else:
            result.append(deepcopy(event))
    return result,{'observation':deepcopy(observation),'unarticulated_decay_candidates':excluded,
                   'prior_event_releases_preserved':True,'tail_audio_preserved':True}


def constrain_shared_tail(shared,observation):
    # 尾段原声局部补证：新增起音恢复与和声织体共同遵守尾响证据；原缓存、和弦窗口及既有持续音不改。
    result=deepcopy(shared)
    if observation is None:return result
    melody,audit=constrain_terminal_events(result.get('instrumental_melody',[]),observation)
    result['instrumental_melody']=melody
    changes=[]
    for texture in result['measure_textures']:
        removed=[row for row in texture['attacks'] if row['seconds']>=observation['start_seconds']]
        if removed:
            texture['attacks']=[row for row in texture['attacks'] if row not in removed]
            texture['attack_grid_ticks']=[row['tick']-texture['start_tick'] for row in texture['attacks']]
            changes.extend(deepcopy(removed))
        held=texture.get('sustained_observation')
        if held and held['seconds']>=observation['start_seconds']:
            texture.pop('sustained_observation')
        if texture['start_seconds']>=observation['start_seconds']:
            texture['kind']='sustain'
            texture['terminal_no_new_reattack']=True
    audit['rejected_local_flux_reattacks']=changes
    result['terminal_decay_constraint']=audit
    return result


def require_terminal_arrangements(shared,vocal,arrangements):
    # 尾段原声局部补证：新增首次交付、时间导出和冻结阅读共用实际攻击守卫，未决旧源不借此升级通过。
    observation=verified_tail_observation(vocal,shared['input_binding'])
    if observation is None:return {'status':'not_applicable','valid':True}
    from accompaniment_analysis import SongClock
    clock=SongClock(vocal)
    attacks={name:[{'id':note['id'],'seconds':clock.seconds(note['start_tick'])} for note in value['notes']
                   if clock.seconds(note['start_tick'])>=observation['start_seconds']-1e-6]
             for name,value in arrangements.items()}
    if any(attacks.values()):
        raise ValueError('已证实尾响内仍有新编配攻击：'+str(attacks))
    return {'status':'source_terminal_decay_preserved','valid':True,'start_seconds':observation['start_seconds'],
            'end_seconds':observation['end_seconds'],'new_attacks':attacks,'prior_sustains_not_truncated':True}


def pattern_attack_allowed(shared,tick):
    # 首拍与首尾局部补证：新增模板起音共同边界；只阻止尚未生成的尾响拨弦，不删除既有音符或缩短之前延音。
    observation=shared.get('terminal_decay_constraint',{}).get('observation')
    if observation is None:return True
    if observation.get('status')!='supported' or observation.get('kind') not in ('decay_of_preexisting_sound','unarticulated_terminal_sustain'):
        raise ValueError('模板不能使用未通过的尾响约束')
    from score_export import TempoMap,PPQ
    timing=shared['timing'];second=TempoMap(timing['knots']).quarters_to_seconds(timing['score_start_quarter']+tick/PPQ)
    return second<observation['start_seconds']-1e-6
