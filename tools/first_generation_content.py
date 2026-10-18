"""首拍与首尾局部补证：独立原声内容补证和第四版严格来源重放。"""
# 首拍与首尾局部补证：新增版本，不改变原v1、尾响v2、鼓角色v3决定的重放含义。
from copy import deepcopy
from functools import lru_cache
import json
# 工作目录改名兼容：证据记录保留传入绝对路径的拼写，不将目录联接解析成另一个名字；文件摘要及完整重放保持。
from pathlib import Path
import numpy as np
from score_export import read_json,save_json,sha256
from source_meter_selection import fingerprint
from first_generation_meter import evidence_tracks
from first_generation_resolution import replay_resolution
from first_generation_tail import _verify_dependencies
from source_clock_content import POLICY,content_grouping,residual_calibration,inspect_prefix,inspect_tail


def apply_content(parent,grouping,prefix,tail):
    # 首拍与首尾局部补证：新增单位／首拍／首尾独立结算；只移除范围完整且已有正证据的问题。
    result=deepcopy(parent);phase=deepcopy(parent['bar_first_beat'])
    if grouping['status']=='supported':
        phase['issues']=[i for i in phase['issues'] if i['kind']!='insufficient_independent_grouping_support']
        phase['status']='selected' if not phase['issues'] else 'needs_review'
        phase['independent_steady_content']=deepcopy(grouping)
    coverage=deepcopy(parent['coverage']);unresolved=[]
    for issue in coverage['issues']:
        head=(prefix['status']=='supported' and issue['kind']=='head_not_observed'
              and issue.get('end_seconds',1e99)<=prefix['end_seconds'])
        last=(tail and tail['status']=='supported' and issue['kind'] in ('source_window_unresolved','tail_not_observed')
              and issue.get('start_seconds',-1)>=tail['start_seconds'] and issue.get('end_seconds',1e99)<=tail['end_seconds'])
        if not (head or last):unresolved.append(issue)
    coverage['issues']=unresolved;coverage['status']='supported' if not unresolved else 'needs_review'
    if prefix['status']=='supported':coverage['unmetered_source_prefix']=deepcopy(prefix)
    if tail and tail['status']=='supported':coverage['terminal_source_continuation']=deepcopy(tail)
    chosen=next(c for c in result['candidates'] if c['candidate_index']==result['selected_candidate_index'])
    if prefix['status']=='supported':
        # 首拍与首尾局部补证：新增有效拍轴只去除无实际演奏支撑的前导模型拍；父候选全部保留，任何内部拍点／分组不改。
        count=prefix['details']['trimmed_model_prefix_beats']
        result['effective_source_clock']={'beats':deepcopy(chosen['clock']['beats'][count:]),
            'removed_model_prefix_beats':deepcopy(chosen['clock']['beats'][:count]),
            'body_pulse_seconds_and_groups_preserved':True,'unmetered_prefix':deepcopy(prefix)}
    issues=([{'kind':'notation_level_unresolved','reasons':result['notation_level']['issues']}]
            if result['notation_level']['status']!='selected' else [])+deepcopy(phase['issues'])+deepcopy(unresolved)
    result.update(bar_first_beat=phase,coverage=coverage,issues=issues,status='passed' if not issues else 'needs_review',
                  downstream_timing_revision_allowed=not issues,
                  source_content_supplement={'policy':deepcopy(POLICY),'grouping':deepcopy(grouping),
                    'prefix':deepcopy(prefix),'tail':deepcopy(tail),'parent_candidates_unchanged':True})
    return result


def build_content(parent_path,binding):
    # 首拍与首尾局部补证：新增从原混音、冻结CQT及父角色决定重算；不得自填结论或使用歌词／旧谱拍号。
    parent=replay_resolution(parent_path,binding)
    dependencies=parent['resolution_provenance']['dependencies'];_verify_dependencies(binding,dependencies)
    meta=read_json(parent['evidence_path'])
    with np.load(Path(parent['evidence_path']).with_suffix('.npz'),allow_pickle=False) as data:
        arrays={k:data[k].copy() for k in data.files}
    tracks=evidence_tracks(meta,arrays);r=parent['result'];duration=float(binding['duration_seconds'])
    candidate=next(c for c in r['candidates'] if c['candidate_index']==r['selected_candidate_index'])
    grouping=content_grouping(candidate,tracks,duration);calibration=residual_calibration(binding)
    prefix=inspect_prefix(binding,candidate,dependencies,calibration)
    terminal=[i for i in r['coverage']['issues'] if abs(i.get('end_seconds',0)-duration)<1e-6]
    tail=inspect_tail(binding,candidate,min(i['start_seconds'] for i in terminal),dependencies,calibration) if terminal else None
    bound=deepcopy(parent)
    bound.update(version=4,result=apply_content(r,grouping,prefix,tail),content_provenance={
        'parent_decision_path':str(Path(parent_path).absolute()),'parent_decision_sha256':sha256(parent_path),
        'parent_result_sha256':fingerprint(r),'policy':deepcopy(POLICY),'dependencies':deepcopy(dependencies),
        'residual_calibration':calibration})
    return bound


@lru_cache(maxsize=8)
def _replay(path,expected,binding_json,policy_sha):
    # 首拍与首尾局部补证：新增确定性完整重算，证据字段、有效拍轴或结论被改均失效。
    bound=read_json(path);binding=json.loads(binding_json)
    actual=build_content(bound['content_provenance']['parent_decision_path'],binding)
    if actual!=bound or sha256(path)!=expected:raise ValueError('原声内容补证无法由原音及冻结父决定重放')
    return actual


def replay_content(path,binding):
    # 首拍与首尾局部补证：新增缓存外校验所有来源；旧结论不能套用更换后的原曲或缓存。
    from first_generation_source import read_bound_evidence
    path=Path(path).resolve();bound=read_json(path);p=bound['content_provenance']
    if bound.get('version')!=4 or p['policy']!=POLICY or sha256(p['parent_decision_path'])!=p['parent_decision_sha256']:
        raise ValueError('原声内容补证的策略或父决定已变化')
    read_bound_evidence(bound['evidence_path'],binding);_verify_dependencies(binding,p['dependencies'])
    return deepcopy(_replay(str(path),sha256(path),json.dumps(binding,sort_keys=True,ensure_ascii=False),fingerprint(POLICY)))


def resolve_content(parent_path,binding,output):
    # 首拍与首尾局部补证：新增只另存的真实首次入口，失败也保存完整证据，绝不覆盖正常曲谱。
    from source_timing_acceptance import require_isolated_output
    output=require_isolated_output(Path(output),Path(__file__).resolve().parents[1])
    if output.exists():raise ValueError('内容补证不覆盖旧版本')
    bound=build_content(parent_path,binding);save_json(output,bound)
    return bound
