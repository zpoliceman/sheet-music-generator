"""两曲来源补证与首次生成：独立鼓角色与连续尾部原声补证，保留旧决定重放。"""
# 两曲来源补证与首次生成：新增第三种来源决定；不修改父选择器、门槛、拍点或旧人工音乐。
from copy import deepcopy
from functools import lru_cache
import json
# 工作目录改名兼容：证据记录保留传入绝对路径的拼写，不将目录联接解析成另一个名字；文件摘要及完整重放保持。
from pathlib import Path
import numpy as np
import soundfile as sf
from score_export import read_json,save_json,sha256
from source_meter_selection import fingerprint
from source_drum_roles import POLICY as DRUM_POLICY,extract_drum_bands,compare_drum_roles
from first_generation_tail import POLICY as DECAY_POLICY,cache_dependencies,_verify_dependencies,_parent
from source_edge_pulses import POLICY as EDGE_POLICY,inspect_terminal_continuation

# 两曲来源补证与首次生成：修改补证版本，增加实际仍有规律声响的结尾验证；原试算v1留在隔离报告。
# POLICY={'version':1,'scope':'source_role_and_unarticulated_terminal_observation',
POLICY={'version':2,'scope':'source_roles_and_observed_terminal_pulses_or_sustain',
        'drum_role_policy':deepcopy(DRUM_POLICY),'cached_activity_policy':deepcopy(DECAY_POLICY),
        'terminal_pulse_policy':deepcopy(EDGE_POLICY),
        'terminal_envelope_seconds':.03,'terminal_hop_seconds':.01,
        'terminal_prior_context_seconds':.08,'maximum_terminal_transient_growth_db':6.,
        'terminal_audio_floor_dbfs':-60.,'minimum_terminal_fade_db':20.,
        'new_pulses_inserted':False,'pitch_chord_or_lyric_recognition_performed':False,
        'original_selection_thresholds_changed':False,'normal_publication_allowed':False}


def inspect_unarticulated_tail(binding,start,dependencies):
    # 两曲来源补证与首次生成：新增连续持续声尾部；缓存活动门限沿用原值，原混音另验实际瞬态，不能将持续效果音谎称静音或单调衰减。
    _verify_dependencies(binding,dependencies)
    end=float(binding['duration_seconds']);source=binding['sources']['mix']
    if sha256(source['path'])!=source['sha256']:
        raise ValueError('末段原混音已改变')
    with sf.SoundFile(source['path']) as stream:
        rate=stream.samplerate
        if abs(stream.frames/rate-end)>1e-6:
            raise ValueError('原混音末端时长不符')
        stream.seek(max(0,round((start-.1)*rate)))
        context_start=stream.tell()/rate
        audio=stream.read(dtype='float64',always_2d=True)
    hop=round(POLICY['terminal_hop_seconds']*rate);size=round(POLICY['terminal_envelope_seconds']*rate)
    positions=np.arange(0,max(0,len(audio)-size+1),hop)
    energy=np.asarray([np.sqrt(np.mean(audio[i:i+size]**2)) for i in positions])
    times=context_start+(positions+size/2)/rate
    db=20*np.log10(np.maximum(1e-9,energy))
    lag=max(1,round(POLICY['terminal_prior_context_seconds']/POLICY['terminal_hop_seconds']))
    growth=np.asarray([db[i]-20*np.log10(max(1e-9,float(np.mean(energy[max(0,i-lag):i]))))
                       if i else 0. for i in range(len(energy))])
    take=(times>=start)&(db>=POLICY['terminal_audio_floor_dbfs'])
    burst=float(np.max(growth[take])) if np.any(take) else 0.
    issue=[];details=[]
    fade=float(np.percentile(db[times>=start],90)-np.median(db[-max(1,round(.5/POLICY['terminal_hop_seconds'])):] )) if len(db) else 0.
    if len(db)<100 or db[-1]>POLICY['terminal_audio_floor_dbfs'] or fade<POLICY['minimum_terminal_fade_db']:
        issue.append('terminal_fade_not_established')
    if burst>POLICY['maximum_terminal_transient_growth_db']:
        issue.append('original_mix_has_new_transient')
    roles={row['role'] for row in dependencies}
    if len(roles)<DECAY_POLICY['minimum_cached_roles'] or not set(DECAY_POLICY['required_cached_roles'])<=roles:
        issue.append('insufficient_tail_source_caches')
    for row in dependencies:
        meta=read_json(row['metadata_path'])
        with np.load(row['path'],allow_pickle=False) as stored:
            at,flux,rms=[stored[key] for key in ('times','flux','rms')]
            local=(at>=start)&(at<=end)
            if not local.any() or at[-1]<end-.05:
                raise ValueError('尾部缓存没有覆盖完整原曲')
            peak=float(np.max(flux[local])/max(1e-8,np.percentile(flux,90)))
            level=float(np.median(rms[local])/max(1e-8,np.percentile(rms,90)))
        attacks=[a['seconds'] for a in meta['attacks'] if start<=a['seconds']<=end]
        details.append({'role':row['role'],'relative_peak_flux':peak,'relative_median_rms':level,'new_cached_attack_seconds':attacks})
        if attacks or peak>DECAY_POLICY['maximum_relative_peak_flux'] or level>DECAY_POLICY['maximum_relative_median_rms']:
            issue.append('active_or_ambiguous_tail:'+row['role'])
    return {'status':'supported' if not issue else 'needs_review','issues':issue,
            'kind':'unarticulated_terminal_sustain' if not issue else 'unresolved',
            'start_seconds':float(start),'end_seconds':end,
            'original_mix_transient':{'maximum_growth_db':burst,'envelope_seconds':POLICY['terminal_envelope_seconds'],
                'prior_context_seconds':POLICY['terminal_prior_context_seconds'],'fade_db':fade},
            'cached_tracks':details,'new_attack_or_new_beat_claimed':False,'audio_tail_must_be_retained':True,
            'monotonic_decay_or_silence_not_claimed':True}


# 两曲来源补证与首次生成：修改签名加入原曲尾部攻击验证，原签名保留。
# def apply_resolution(parent_result,drum,terminal=None):
def apply_resolution(parent_result,drum,terminal=None,continuation=None):
    # 两曲来源补证与首次生成：新增单位、首拍和覆盖分别结算；只有独立正证据能替换单位，不清除其它音乐疑问。
    result=deepcopy(parent_result)
    chosen_index=(drum['selected_candidate_index'] if drum['status']=='selected' else parent_result['selected_candidate_index'])
    chosen=next(c for c in result['candidates'] if c['candidate_index']==chosen_index)
    level=deepcopy(parent_result['notation_level'])
    if drum['status']=='selected':
        level={'status':'selected','bpm':chosen['bpm'],'margin':drum['margin'],'issues':[],
               'scope':'positive_distributed_original_drum_roles_not_global_harmonic_template',
               'evidence_policy_version':DRUM_POLICY['version'],'parent_notation_level':deepcopy(parent_result['notation_level'])}
    phase=deepcopy(chosen['grouping']['issues'])+deepcopy(chosen['counterfactual_issues'])
    if level['status']!='selected':
        phase.append({'kind':'grouping_conditional_on_unresolved_level'})
    coverage=deepcopy(chosen['coverage'])
    if terminal and terminal['status']=='supported':
        # 两曲来源补证与首次生成：新增仅覆盖完全落在原声持续尾部内的缺证项；重叠实际演奏的窗口不能直接放过。
        unresolved=[]
        for issue in coverage['issues']:
            if issue.get('start_seconds',-1)>=terminal['start_seconds'] and issue.get('end_seconds',float('inf'))<=terminal['end_seconds']:
                continue
            unresolved.append(issue)
        coverage['issues']=unresolved
        coverage['terminal_source_observation']=deepcopy(terminal)
        coverage['status']='supported' if not unresolved else 'needs_review'
    if continuation and continuation['status']=='supported':
        # 两曲来源补证与首次生成：新增仅替换完整覆盖的末窗口模型缺证；首部、主体、快慢或首拍未决不因此消失。
        coverage['issues']=[issue for issue in coverage['issues'] if not (
            issue['kind'] in ('source_window_unresolved','tail_not_observed')
            and issue.get('start_seconds',-1)>=continuation['start_seconds']
            and issue.get('end_seconds',float('inf'))<=continuation['end_seconds'])]
        coverage['terminal_pulse_continuation']=deepcopy(continuation)
        coverage['status']='supported' if not coverage['issues'] else 'needs_review'
    issues=([{'kind':'notation_level_unresolved','reasons':level['issues']}] if level['status']!='selected' else [])+phase+deepcopy(coverage['issues'])
    result.update(notation_level=level,selected_candidate_index=chosen_index,
                  bar_first_beat={'status':'selected' if not phase else 'needs_review','issues':phase,
                                  'local_short_bars':deepcopy(chosen['grouping']['short_bars'])},
                  coverage=coverage,issues=issues,status='passed' if not issues else 'needs_review',
                  downstream_timing_revision_allowed=not issues,
                  source_resolution={'policy':deepcopy(POLICY),'drum_roles':deepcopy(drum),
                                     'terminal_observation':deepcopy(terminal),'parent_candidates_unchanged':True})
    result['source_resolution']['terminal_continuation']=deepcopy(continuation)
    return result


def build_resolution(parent_path,binding,dependencies):
    # 两曲来源补证与首次生成：新增每次从真实原鼓计算，元数据不能伪造一张通过证书；已有缓存与父决定只读。
    parent=_parent(parent_path,binding)
    if 'drums' not in binding['sources']:
        raise ValueError('来源补证缺少原鼓分轨')
    drum=compare_drum_roles(parent['result']['candidates'],extract_drum_bands(binding['sources']['drums']),float(binding['duration_seconds']))
    chosen_index=drum['selected_candidate_index'] if drum['status']=='selected' else parent['result']['selected_candidate_index']
    chosen=next(c for c in parent['result']['candidates'] if c['candidate_index']==chosen_index)
    terminal_ranges=[r for r in chosen['coverage']['issues'] if abs(r.get('end_seconds',0)-binding['duration_seconds'])<1e-6]
    # 两曲来源补证与首次生成：修改不能把仍有瞬态的末段叫作尾响；原试算保留，并实际验证四分／八分声响后再单独验最后衰减。
    # terminal=(inspect_unarticulated_tail(binding,min(r['start_seconds'] for r in terminal_ranges),dependencies)
    #           if terminal_ranges else None)
    terminal=None;continuation=None;diagnostic=None
    if terminal_ranges:
        start=min(r['start_seconds'] for r in terminal_ranges)
        diagnostic=inspect_unarticulated_tail(binding,start,dependencies)
        if diagnostic['status']=='supported':
            terminal=diagnostic
        elif chosen['grouping']['status']=='supported':
            continuation=inspect_terminal_continuation(binding,chosen,start,dependencies)
            if continuation['status']=='supported':
                terminal=deepcopy(continuation['terminal_decay'])
    bound=deepcopy(parent)
    # 两曲来源补证与首次生成：修改结算使用实际原声覆盖，失败诊断也保存，不隐藏证据冲突。
    # bound.update(version=3,result=apply_resolution(parent['result'],drum,terminal),
    bound.update(version=3,result=apply_resolution(parent['result'],drum,terminal,continuation),
                 resolution_provenance={'parent_decision_path':str(Path(parent_path).absolute()),
                    'parent_decision_sha256':sha256(parent_path),'parent_result_sha256':fingerprint(parent['result']),
                    'policy':deepcopy(POLICY),'dependencies':deepcopy(dependencies)})
    bound['result']['source_resolution']['unarticulated_tail_diagnostic']=diagnostic
    return bound


@lru_cache(maxsize=8)
def _replay(path,expected,binding_json,policy_sha):
    # 两曲来源补证与首次生成：新增完整确定性重放；缓存外仍检查原文件和依赖SHA。
    bound=read_json(path);p=bound['resolution_provenance'];binding=json.loads(binding_json)
    actual=build_resolution(p['parent_decision_path'],binding,p['dependencies'])
    if actual!=bound or sha256(path)!=expected:
        raise ValueError('来源角色补证无法从原曲及冻结父决定重放')
    return actual


def replay_resolution(path,binding):
    # 两曲来源补证与首次生成：新增来源版本分派，不覆盖多远尾响v2及原v1重放含义。
    from first_generation_source import read_bound_evidence
    path=Path(path).resolve();bound=read_json(path);p=bound['resolution_provenance']
    if bound.get('version')!=3 or p['policy']!=POLICY or sha256(p['parent_decision_path'])!=p['parent_decision_sha256']:
        raise ValueError('来源补证父决定或策略已经变化')
    read_bound_evidence(bound['evidence_path'],binding);_verify_dependencies(binding,p['dependencies'])
    return deepcopy(_replay(str(path),sha256(path),json.dumps(binding,sort_keys=True,ensure_ascii=False),fingerprint(POLICY)))


def resolve_sources(parent_path,binding,feature_folders,output):
    # 两曲来源补证与首次生成：新增只另存的通用调用；失败也保存证据，不启动音高、词音和和弦重算。
    from source_timing_acceptance import require_isolated_output
    output=require_isolated_output(Path(output),Path(__file__).resolve().parents[1])
    if output.exists():
        raise ValueError('来源补证不能覆盖旧版本')
    bound=build_resolution(parent_path,binding,cache_dependencies(binding,feature_folders))
    save_json(output,bound)
    return bound
