"""默认入口原曲节拍强制复核：未经来源校正的旧谱不能直接进入编配或排版复制。"""
from copy import deepcopy
from pathlib import Path
import math
# 默认入口原曲节拍强制复核：修改，旧仅指纹导入保留；人工复核须直接核对真实映射点，用户覆盖字段不能让检查短路。
# from score_export import sha256
from score_export import sha256,TempoMap
from accompaniment_rebar import validate_vocal_snapshot


# 默认入口原曲节拍强制复核：新增来源派生名单，不以小节数、结点数、曲名或自报通过字段判断拍轴可靠。
CLOCK_LAYERS=('source_meter_rebuild_correction','continuous_meter_correction','source_meter_correction',
    'performance_clock_correction','structural_clock_correction','local_clock_correction','beat_phase_correction')


# 默认入口原曲节拍强制复核：新增实际来源和整份人声重放核验；所有分支在输出／复制前执行。
def inspect_source_meter(vocal,binding):
    original=Path(binding['vocal_project'])
    if not original.is_file() or sha256(original)!=binding['vocal_project_sha256']:
        raise ValueError('节拍前置检查：原人声来源已改变。')
    checked={}
    for name,source in binding['sources'].items():
        path=Path(source['path']);key=(str(path.resolve()),source['sha256'])
        if key not in checked:
            checked[key]=path.is_file() and sha256(path)==source['sha256']
        if not checked[key]:raise ValueError('节拍前置检查：原音轨来源已改变：'+name)
    if not validate_vocal_snapshot(vocal,binding):
        raise ValueError('节拍前置检查：人声／拍轴不能由原来源重建，拒绝覆盖或继续编配。')
    # 首次生成自动拍轴交接：新增来源决定已完整重放的专用状态，不伪装成旧人工或相对单位投影。
    if vocal.get('first_source_meter_correction'):
        return {'version': 3, 'status': 'source_verified_first_generation_clock_retained', 'needs_rebuild': False,
                'scope': 'verified_automatic_pulses_groups_coverage_not_whole_music_acceptance',
                'decision_sha256': vocal['first_source_meter_correction']['decision_sha256']}
    # 慢拍单位与两曲最小修订：新增已验证单位决定的真实入口状态，不能落回旧快拍派生分支。
    if vocal.get('meter_unit_correction'):
        return {'version': 2, 'status': 'source_verified_meter_unit_projection_retained', 'needs_rebuild': False,
                'scope': 'verified_unit_and_groups_existing_performance_preserved_not_full_music_acceptance',
                'decision_sha256': vocal['meter_unit_correction']['decision_sha256']}
    layers=[name for name in CLOCK_LAYERS if vocal.get(name)]
    if layers:
        return {'version':1,'status':'source_bound_correction_retained','needs_rebuild':False,
            'verified_layers':layers,'vocal_project_sha256':binding['vocal_project_sha256'],
            'scope':'existing_source_correction_replayed_not_new_music_certification'}
    # 默认入口原曲节拍强制复核：新增人工首拍必须匹配真实混音及登记记录，并核对实际轴；孤立review_id不足以跳过。
    from beat_phase_alignment import phase_review,apply_phase_timing
    analysis=vocal.get('audio_analysis',{});timing=vocal['timing']
    review=phase_review(analysis,timing)
    if (review and analysis.get('source_sha256')==binding['sources']['mix']['sha256']
            # 默认入口原曲节拍强制复核：新增直接验原轨复核锚点，不能因user_override令apply_phase_timing原样返回就冒充匹配。
            and math.isclose(TempoMap(timing['knots']).quarters_to_seconds(review['anchor_quarter']),review['anchor_seconds'],abs_tol=1e-6,rel_tol=0.)
            and apply_phase_timing(analysis,timing,review)==timing):
        return {'version':1,'status':'source_bound_human_review_retained','needs_rebuild':False,
            'review_id':review.get('review_id'),'vocal_project_sha256':binding['vocal_project_sha256']}
    return {'version':1,'status':'unverified_clock_requires_source_rebuild','needs_rebuild':True,
        'vocal_project_sha256':binding['vocal_project_sha256'],
        'reason':'没有可重放的原轨拍轴校正或匹配实际轴的人工复核；旧谱存在和文件一致不等于节拍已校准。'}


# 默认入口原曲节拍强制复核：新增旧工程默认自动升级请求，保留用户参数对象，不提供忽略检查的开关。
def prepare_edited_request(args):
    if not getattr(args,'edited_project',None) or getattr(args,'rebuild_source_meter',False):
        return args,None
    from score_export import read_json
    project=read_json(args.edited_project)
    check=inspect_source_meter(project['accepted_vocal_project'],project['shared_analysis']['input_binding'])
    if not check['needs_rebuild']:return args,check
    legacy=any(getattr(args,name,False) for name in ('correct_beat_phase','phrase_rhythm','local_beat_clock',
        'structural_rhythm','performance_beat_clock','continuous_meter'))
    if legacy:
        raise ValueError('旧谱尚未校准：请先通过默认入口完成原曲节拍重建，再另存执行历史校正选项；不能继续沿未经核对的旧拍轴编配。')
    updated=deepcopy(args);updated.rebuild_source_meter=True
    check={**check,'automatic_rebuild_requested':True}
    return updated,check


# 默认入口原曲节拍强制复核：新增最后进入编配／纯排版前的门槛，失败不能静默降级到原旧谱。
def require_calibrated_source(vocal,binding):
    check=inspect_source_meter(vocal,binding)
    if check['needs_rebuild']:
        raise ValueError('原曲节拍尚未通过来源复核，停止生成；请使用完整默认入口重建拍轴，不能仅复制旧谱排版。')
    return check
