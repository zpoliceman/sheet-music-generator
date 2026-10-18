"""首次生成自动拍轴交接：来源绑定、未决返回、纯时间投影与严格重放。"""
# 首次生成自动拍轴交接：新增新源专用层；不调用旧拍轴推断、词音质量重建或和弦识别。
from copy import deepcopy
from functools import lru_cache
# 工作目录改名兼容：证据记录保留传入绝对路径的拼写，不将目录联接解析成另一个名字；文件摘要及完整重放保持。
from pathlib import Path
import math
import numpy as np
from score_export import PPQ, TempoMap, read_json, save_json, sha256
from source_meter_selection import fingerprint
from first_generation_meter import POLICY, decide_first_generation
from source_timing_acceptance import require_isolated_output


class UnresolvedFirstSource(ValueError):
    # 首次生成自动拍轴交接：新增带决定路径的显式未决，不清空歧义也不触发歌曲提问。
    def __init__(self, path, decision):
        self.decision_path = str(path)
        self.decision = decision
        super().__init__('首次生成拍轴尚有未决，已保存自动选拍／分组／覆盖证据：' + str(path))


def read_bound_evidence(path, binding):
    # 首次生成自动拍轴交接：新增原音、匿名包及轨道绑定检查；旧谱和人工判断不能进入选择器。
    path = Path(path).resolve()
    meta = read_json(path)
    archive = path.with_suffix('.npz')
    if meta.get('version') != 2 or meta['mix_sha256'] != binding['sources']['mix']['sha256']:
        raise ValueError('首次生成原音或匿名证据版本不匹配')
    # 首次生成自动拍轴交接：新增全长绑定，不能缩短证据时长以绕过首尾覆盖验收。
    import soundfile as sf
    actual_duration = sf.info(binding['sources']['mix']['path']).duration
    if (not math.isclose(float(meta['duration_seconds']), float(binding['duration_seconds']), abs_tol=1e-6)
            or not math.isclose(actual_duration, float(binding['duration_seconds']), abs_tol=1e-6)):
        raise ValueError('首次生成证据／原音实际时长不符，不能裁掉缺证首尾')
    if sha256(archive) != meta['array_sha256']:
        raise ValueError('首次生成匿名数组已改变')
    for row in meta['tracks']:
        source = binding['sources'].get(row['role'])
        if source is None or source['sha256'] != row['source_sha256']:
            raise ValueError('首次生成声学分轨绑定不符')
    for source in binding['sources'].values():
        if sha256(source['path']) != source['sha256']:
            raise ValueError('首次生成音源已改变')
    if sha256(binding['vocal_project']) != binding['vocal_project_sha256']:
        raise ValueError('首次生成人声原工程已改变')
    with np.load(archive, allow_pickle=False) as stored:
        arrays = {key: stored[key].copy() for key in stored.files}
    return meta, arrays


def make_source_clock(decision):
    # 首次生成自动拍轴交接：新增直接消费经过验收的拍秒；尾端只封口延音，不补造声学起音。
    from source_timing_reviewed_clock import make_timeline
    if decision['status'] != 'passed' or decision['issues'] or not decision['downstream_timing_revision_allowed']:
        raise ValueError('拍单位、局部分组或覆盖尚未通过，禁止投影人声')
    chosen = next(row for row in decision['candidates'] if row['candidate_index'] == decision['selected_candidate_index'])
    # 首拍与首尾局部补证：修改新第四版可消费已严格重放的有效拍轴；旧候选和旧三种决定仍原样使用。
    # beats = deepcopy(chosen['clock']['beats'])
    beats = deepcopy(decision.get('effective_source_clock',chosen['clock'])['beats'])
    period = float(np.median(np.diff([beat['seconds'] for beat in beats[-9:]])))
    duration = decision['coverage']['full_audio_duration_seconds']
    while beats[-1]['seconds'] < duration or beats[-1]['beat'] != 1:
        beats.append({'seconds': beats[-1]['seconds'] + period, 'beat': beats[-1]['beat'] % 4 + 1,
                      'model_observed': False, 'purpose': 'held_note_measure_closure_only'})
    mapping = TempoMap([{'quarter': float(index), 'seconds': beat['seconds']} for index, beat in enumerate(beats)])
    return {'knots': mapping.knots, 'meter': [4, 4], 'beats': beats,
            'measure_timeline': make_timeline(beats, mapping), 'source_duration_seconds': duration,
            'source_mix_sha256': decision['mix_sha256'], 'audio_origin_seconds': 0.,
            'source_clock_kind': 'automatic_first_generation_verified_pulses_and_local_groups',
            'coverage': deepcopy(decision['coverage'])}


# 尾段原声局部补证：修改投影版本，新首次投影同步转调坐标；历史v1重放保持。
# def project_first_voice(original, decision):
def project_first_voice(original, decision, version=1):
    # 首次生成自动拍轴交接：新增仅换算现有词音真实秒；源身份、音高、词归属和完整秒区间必须保持。
    from source_timing_revision import project_voice
    clock = make_source_clock(decision)
    if any(note['start_seconds'] < clock['beats'][0]['seconds'] - .04 for note in original['quantized_notes']):
        raise ValueError('已有人声音符早于受支持拍轴，不能靠裁头完成首次投影')
    updated = project_voice(original, clock, original['quantized_notes'])
    # 尾段原声局部补证：新增转调沿原秒数换算新拍位，不重新识别调性／音高；首调仍覆盖引子。
    if version not in (1,2):
        raise ValueError('未知首次来源时间投影版本')
    if version==2:
        mapping=TempoMap(clock['knots'])
        timeline=clock['measure_timeline']
        for index,segment in enumerate(updated['notation'].get('key_segments',[])):
            # 尾段原声局部补证：修改转换的是既有记谱位置，分析中的变调候选字头秒数不能冒充原谱的调号落点；原小节线调号仍落在新实际小节线上。
            # second=segment.get('start_seconds')
            # if second is None:
            #     previous=TempoMap(original['timing']['knots'])
            #     second=previous.quarters_to_seconds(original['timing']['score_start_quarter']+segment.get('start_tick',0)/PPQ)
            # tick=0 if index==0 and segment.get('start_tick',0)==0 else max(0,round(mapping.seconds_to_quarters(second)*PPQ/120)*120)
            previous=TempoMap(original['timing']['knots'])
            old_tick=segment.get('start_tick',0)
            second=previous.quarters_to_seconds(original['timing']['score_start_quarter']+old_tick/PPQ)
            old_timeline=original['timing'].get('measure_timeline',[])
            bar_boundary=(any(row['start_tick']==old_tick for row in old_timeline) if old_timeline
                          else old_tick%original['statistics']['bar_ticks']==0)
            tick=(0 if index==0 and old_tick==0 else min(timeline,key=lambda row:abs(row['start_seconds']-second))['start_tick']
                  if bar_boundary else max(0,round(mapping.seconds_to_quarters(second)*PPQ/120)*120))
            if tick>=updated['statistics']['total_ticks']:
                raise ValueError('来源转调位置超出新曲长，不能截掉或忽略')
            segment['start_tick']=tick
            segment['start_measure']=next(row['number'] for row in timeline if row['start_tick']<=tick<row['end_tick'])
        from source_timing_revision import rebuild_events
        rebuild_events(updated,timeline)
    # 首次生成自动拍轴交接：新增本次派生使用自身来源层，避免投影工具的临时标记误入旧人工时间修订路线。
    if 'time_only_revision' not in original:
        updated.pop('time_only_revision', None)
    before = {note['id']: note for note in original['quantized_notes']}
    for note in updated['quantized_notes']:
        old = before.get(note['id'])
        if old is None or any(note.get(key) != old.get(key) for key in ('pitch_midi', 'start_seconds', 'end_seconds', 'lyric_index', 'grace')):
            raise ValueError('首次时间投影改变已有音符、词归属或完整源时值')
    if len(updated['quantized_notes']) != len(before):
        raise ValueError('首次时间投影丢失音符身份')
    old_unmapped = original['lyric_mapping']['unmapped_character_indices']
    if updated['lyric_mapping']['unmapped_character_indices'] != old_unmapped:
        raise ValueError('首次时间投影改变挂词覆盖，需局部复核')
    mapping = TempoMap(clock['knots'])
    # 首次生成自动拍轴交接：新增试听细坐标，正文节奏仍沿用原投影策略，不将完整源延音裁成网格长度。
    for note in updated['quantized_notes']:
        note['playback_start_tick'] = max(0, round(mapping.seconds_to_quarters(note['start_seconds']) * PPQ))
        note['playback_end_tick'] = max(note['playback_start_tick'] + 1, round(mapping.seconds_to_quarters(note['end_seconds']) * PPQ))
    updated['timing'].update(tempo_source='verified_automatic_first_source_clock', requires_confirmation=False)
    return updated


def _bound_decision(value, evidence_path, binding):
    # 首次生成自动拍轴交接：新增验收绑定，不接受自填passed、歌名分支或裸BPM参数。
    return {'version': 1, 'scope': 'first_generation_clock_only_not_whole_music_certificate',
            'evidence_path': str(Path(evidence_path).absolute()), 'evidence_sha256': sha256(evidence_path),
            'evidence_array_sha256': sha256(Path(evidence_path).with_suffix('.npz')),
            'source_vocal_project_sha256': binding['vocal_project_sha256'],
            'source_fingerprints': {role: source['sha256'] for role, source in binding['sources'].items()},
            'result': value, 'normal_publication_allowed': False}


@lru_cache(maxsize=8)
# 首次生成自动拍轴交接：修改缓存身份纳入实际策略，避免同进程策略变化沿用旧复算。
# def _replay_decision(path, expected, binding_fingerprint):
def _replay_decision(path, expected, binding_fingerprint, policy_fingerprint):
    # 首次生成自动拍轴交接：新增同一进程复算缓存；调用前仍逐文件验SHA，不能缓存绕过篡改检查。
    bound = read_json(path)
    binding = __import__('json').loads(binding_fingerprint)
    meta, arrays = read_bound_evidence(bound['evidence_path'], binding)
    actual = _bound_decision(decide_first_generation(meta, arrays), bound['evidence_path'], binding)
    if bound != actual or sha256(path) != expected:
        raise ValueError('首次拍轴决定无法由原声和冻结策略重放')
    return actual


def load_first_decision(path, binding):
    # 首次生成自动拍轴交接：新增所有普通重导都能核验的新来源层，不借用旧人工或相对单位证书。
    import json
    path = Path(path).resolve()
    bound = read_json(path)
    if (sha256(bound['evidence_path']) != bound['evidence_sha256']
            or sha256(Path(bound['evidence_path']).with_suffix('.npz')) != bound['evidence_array_sha256']
            or bound['source_vocal_project_sha256'] != binding['vocal_project_sha256']):
        raise ValueError('首次拍轴决定来源或匿名包已变')
    # 首次生成自动拍轴交接：新增实际源SHA验证在缓存之前，旧凭证不能复用新音频。
    read_bound_evidence(bound['evidence_path'], binding)
    # 首次生成自动拍轴交接：修改调用绑定新层策略；旧决定不因策略变更继续通过。
    # value = deepcopy(_replay_decision(str(path), sha256(path), json.dumps(binding, sort_keys=True, ensure_ascii=False)))
    # 尾段原声局部补证：修改新补证版本使用其独立来源重放，原v1决定仍按原策略精确验证。
    # value = deepcopy(_replay_decision(str(path), sha256(path), json.dumps(binding, sort_keys=True, ensure_ascii=False), fingerprint(POLICY)))
    # 两曲来源补证与首次生成：修改版本分派；新角色／尾部补证从原曲重放，旧v1／多远v2保持。
    # if bound.get('version') == 2:
    # 首拍与首尾局部补证：修改显式第四版分派，旧v1／v2／v3完全保留。
    # if bound.get('version') == 3:
    if bound.get('version') == 4:
        from first_generation_content import replay_content
        value = replay_content(path,binding)
    elif bound.get('version') == 3:
        from first_generation_resolution import replay_resolution
        value = replay_resolution(path,binding)
    elif bound.get('version') == 2:
        from first_generation_tail import replay_tail_decision
        value = replay_tail_decision(path, binding)
    else:
        value = deepcopy(_replay_decision(str(path), sha256(path), json.dumps(binding, sort_keys=True, ensure_ascii=False), fingerprint(POLICY)))
    if value['result']['status'] != 'passed' or value['result']['issues']:
        raise UnresolvedFirstSource(path, value['result'])
    return value


def replay_first_voice(original, binding, correction):
    # 首次生成自动拍轴交接：新增从不可变原人声及原声决定确定性投影，不整曲重识别。
    # 尾段原声局部补证：修改版本分派，旧v1投影绝不被新坐标策略覆盖。
    # if (correction.get('version') != 1 or sha256(correction['decision_path']) != correction['decision_sha256']
    if (correction.get('version') not in (1,2) or sha256(correction['decision_path']) != correction['decision_sha256']
            or correction['source_vocal_project_sha256'] != binding['vocal_project_sha256']):
        raise ValueError('首次拍轴人声派生来源已变')
    decision = load_first_decision(correction['decision_path'], binding)
    # 尾段原声局部补证：修改按实际来源层版本重放，音高／字位仍完整保持。
    # updated = project_first_voice(original, decision['result'])
    updated = project_first_voice(original, decision['result'],version=correction['version'])
    updated['first_source_meter_correction'] = deepcopy(correction)
    return updated


# 尾段原声局部补证：修改签名增加来源决定输入；原入口仍可直接由匿名原声独立计算。
# def prepare_first_source(vocal, binding, cache, evidence=None, feature_caches=(), model_cache=None):
def prepare_first_source(vocal, binding, cache, evidence=None, feature_caches=(), model_cache=None, decision_path=None):
    # 首次生成自动拍轴交接：新增首次入口实际调度；未决也另存完整决定，绝不自动询问或重试放宽。
    from select_source_meter import ROLES, prepare_evidence
    work = require_isolated_output(Path(cache).parent / 'first_source_meter', Path(__file__).resolve().parents[1])
    if work.exists():
        raise ValueError('首次拍轴诊断目录已存在，请使用新的分析目录，不覆盖旧决定')
    # 尾段原声局部补证：新增补证成功后的真实首次入口，严格重放，冻结原拍轴，不再重选候选。
    if decision_path is not None:
        if evidence is not None or model_cache is not None:
            raise ValueError('已验拍轴决定不能同时要求重选原声证据')
        bound = load_first_decision(decision_path, binding)
        work.mkdir(parents=True, exist_ok=True)
        path = work / 'decision.json'
        save_json(path, bound)
        # 尾段原声局部补证：修改新投影显式v2，历史已有v1标记不改。
        # correction = {'version':1, 'decision_path':str(path.resolve()), 'decision_sha256':sha256(path),
        correction = {'version':2, 'decision_path':str(path.resolve()), 'decision_sha256':sha256(path),
                      'source_vocal_project_sha256':binding['vocal_project_sha256']}
        result = replay_first_voice(read_json(binding['vocal_project']),binding,correction)
        save_json(work/'accepted_vocal_project.json',result)
        return result, {'status':'verified_first_source_decision_retained','decision_path':str(path.resolve()),
                        'decision_sha256':sha256(path),'pitch_chord_or_lyric_recognition_changed':False,
                        'scope':'clock_grouping_and_local_coverage_only_not_full_music_acceptance'}
    if evidence is None:
        caches = list(feature_caches) or [Path(cache)]
        if not feature_caches:
            # 首次生成自动拍轴交接：新增无缓存的真正新输入只做首次声学准备；已给只读缓存则缺失即停止。
            from accompaniment_analysis import extract_features
            for role in ROLES:
                if role in binding['sources'] and role not in ('drums', 'vocals'):
                    extract_features(binding['sources'][role], cache, role)
        evidence = prepare_evidence(binding, work / 'evidence', model_cache, caches)
    meta, arrays = read_bound_evidence(evidence, binding)
    decision = decide_first_generation(meta, arrays)
    work.mkdir(parents=True, exist_ok=True)
    path = work / 'decision.json'
    save_json(path, _bound_decision(decision, evidence, binding))
    # 两曲来源补证与首次生成：新增首次未决后自动补证；原父决定另存保留，不清标记放行或请用户选择歌曲答案。
    if decision['status']!='passed' and 'drums' in binding['sources']:
        from first_generation_resolution import resolve_sources
        resolved_path=work/'source_resolution/decision.json'
        resolved=resolve_sources(path,binding,list(feature_caches) or [Path(cache)],resolved_path)
        path=resolved_path
        decision=resolved['result']
    # 首拍与首尾局部补证：新增模型角色层仍未决时独立补验实际内容及首尾；不能在离线报告中通过、首次入口却继续用旧选择。
    if decision['status']!='passed' and read_json(path).get('version')==3:
        from first_generation_content import resolve_content
        content_path=work/'source_content/decision.json'
        content=resolve_content(path,binding,content_path)
        path=content_path
        decision=content['result']
    if decision['status'] != 'passed':
        raise UnresolvedFirstSource(path, decision)
    # 尾段原声局部补证：修改新首次投影启用转调坐标同步，原版本仅用于历史重放。
    # correction = {'version': 1, 'decision_path': str(path.resolve()), 'decision_sha256': sha256(path),
    correction = {'version': 2, 'decision_path': str(path.resolve()), 'decision_sha256': sha256(path),
                  'source_vocal_project_sha256': binding['vocal_project_sha256']}
    result = replay_first_voice(read_json(binding['vocal_project']), binding, correction)
    save_json(work / 'accepted_vocal_project.json', result)
    return result, {'status': 'automatic_first_source_clock_retained', 'decision_path': str(path.resolve()),
                    'decision_sha256': sha256(path), 'pitch_chord_or_lyric_recognition_changed': False,
                    'scope': 'clock_grouping_and_coverage_only_not_full_music_acceptance'}
