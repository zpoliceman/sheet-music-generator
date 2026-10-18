"""小节划分与拍速层级纠错：区分检测脉冲、四分拍与人工确认的记谱层级。"""
# 小节划分与拍速层级纠错：新增与源音频SHA绑定的复核策略，不按歌名或BPM阈值强行减半。
from copy import deepcopy
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REVIEW_PATH = ROOT / 'data' / 'metrical_reviews.json'


# 小节划分与拍速层级纠错：新增半速/原速/倍速候选；规则不能从和弦变化次数唯一推断拍号。
def beat_level_candidates(bpm, meter):
    quarters = meter[0] * 4 / meter[1]
    return [{'quarter_scale': scale, 'quarter_bpm': bpm * scale,
             'bar_seconds': 60 * quarters / (bpm * scale),
             'detected_pulses_per_bar': quarters / scale}
            for scale in (.5, 1., 2.) if 20 <= bpm * scale <= 300]


# 小节划分与拍速层级纠错：新增身份、拍号和速度范围核验；未知曲保留歧义，不擅自全局减半。
def reviewed_beat_level(analysis, bpm, meter, explicit_tempo=False, review_path=REVIEW_PATH):
    from score_export import read_json
    decision = {'version': 1, 'quarter_scale': 1., 'source_audio_sha256': analysis.get('source_sha256'),
                'detected_pulse_bpm': bpm, 'candidates': beat_level_candidates(bpm, meter),
                'status': 'explicit_quarter_tempo' if explicit_tempo else 'unresolved',
                'basis': 'explicit_tempo' if explicit_tempo else 'pulse_regularity_does_not_prove_quarter_beat'}
    if explicit_tempo or not Path(review_path).exists():
        return decision
    review = read_json(review_path).get('reviews', {}).get(analysis.get('source_sha256'))
    if review and review['meter'] == list(meter):
        expected = review['detected_pulse_bpm']
        # 小节划分与拍速层级纠错：新增层级保护；已是58.5或234时不能再次机械套用117的复核。
        if math.isclose(bpm, expected, rel_tol=.04):
            decision.update(quarter_scale=float(review['quarter_scale']), status='reviewed',
                            basis=review['basis'], review_id=review['review_id'])
    return decision


# 小节划分与拍速层级纠错：新增绕谱面零点缩放拍坐标；秒坐标不变，局部速度图也逐段保留。
def rebase_timing(timing, scale, decision=None):
    if scale not in (.5, 1., 2.):
        raise ValueError('四分拍层级只支持半速、原速和倍速。')
    result = deepcopy(timing)
    origin = float(timing['score_start_quarter'])
    result['knots'] = [{'seconds': p['seconds'], 'quarter': (p['quarter'] - origin) * scale}
                       for p in timing['knots']]
    result['score_start_quarter'] = 0.
    result['beat_origin_seconds'] = timing['score_start_seconds']
    result['beat_origin_source'] = 'preserved_score_zero_during_beat_level_review'
    for key in ('steady_tempo_bpm', 'unrounded_tempo_bpm'):
        if key in result:
            result[key] *= scale
    if decision is not None:
        result['beat_level'] = deepcopy(decision)
    result['tempo_source'] = 'reviewed_metrical_beat_level'
    return result


# 小节划分与拍速层级纠错：新增时序入口共用策略；显式四分拍覆盖优先于按源SHA复核。
def resolve_timing(analysis, timing, explicit_tempo=False):
    from score_export import TempoMap
    # 强拍相位与伴奏同步纠错：新增保存显式首拍，拍层级换算不能抹掉用户覆盖。
    explicit_origin=timing.get('beat_origin_seconds') if timing.get('beat_origin_source')=='user_override' else None
    bpm = timing.get('steady_tempo_bpm') or TempoMap(timing['knots']).tempo_at(timing['score_start_quarter'])
    decision = reviewed_beat_level(analysis, bpm, timing['meter'], explicit_tempo)
    if decision['quarter_scale'] != 1:
        timing = rebase_timing(timing, decision['quarter_scale'], decision)
    else:
        timing = deepcopy(timing)
        timing['beat_level'] = decision
    if explicit_origin is not None and decision['quarter_scale']!=1:
        # 强拍相位与伴奏同步纠错：新增按正确四分拍重新确定用户小节零点，不将原两拍零点冒充四拍首拍。
        period=60/timing['steady_tempo_bpm'];bar=timing['meter'][0]*4/timing['meter'][1]
        mapping=TempoMap([{'seconds':explicit_origin,'quarter':0},{'seconds':explicit_origin+period,'quarter':1}])
        start=math.floor(mapping.seconds_to_quarters(0)/bar)*bar
        timing.update(knots=mapping.knots,score_start_quarter=start,score_start_seconds=mapping.quarters_to_seconds(start),
                      beat_origin_seconds=explicit_origin,beat_origin_source='user_override')
    # 强拍相位与伴奏同步纠错：修改，原仅校准拍单位的返回保留；正确小节长度不能证明强拍相位正确。
    # return TempoMap(timing['knots']), timing
    from beat_phase_alignment import apply_phase_timing
    timing = apply_phase_timing(analysis, timing)
    return TempoMap(timing['knots']), timing


# 小节划分与拍速层级纠错：新增谱头与复核页共用速度，检测脉冲速度不再冒充记谱四分拍速度。
def selected_quarter_tempo(project):
    from score_export import TempoMap
    timing=project['timing']
    if timing.get('knots'):
        return TempoMap(timing['knots']).tempo_at(timing['score_start_quarter'])
    return timing.get('steady_tempo_bpm') or project.get('overrides',{}).get('tempo') or project['audio_analysis']['tempo']['bpm']
