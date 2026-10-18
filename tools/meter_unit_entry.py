"""慢拍单位与两曲最小修订：选择结果与保音重记谱之间的可重放交接。"""
# 慢拍单位与两曲最小修订：新增真正生成入口使用的证据验证；不能复制passed或回到旧快拍提示重新识别。
from copy import deepcopy
# 工作目录改名兼容：证据记录保留传入绝对路径的拼写，不将目录联接解析成另一个名字；文件摘要及完整重放保持。
from pathlib import Path
import numpy as np
from score_export import read_json, save_json, sha256, TempoMap
from source_meter_selection import select_meter, fingerprint
from source_meter_bar_groups import group_fixed_pulses
from source_timing_acceptance import require_isolated_output


# 慢拍单位与两曲最小修订：修改分组版本显式进入交接，匿名层级判断始终保持已封存版本。
# def inspect_unit_decision(project, evidence_path, selection_path, quarter_scale):
def inspect_unit_decision(project, evidence_path, selection_path, quarter_scale, grouping_version=1):
    # 慢拍单位与两曲最小修订：新增从匿名包实际重算选择，验证原音和所有候选内容，伪造结果立即失败。
    if quarter_scale not in (.5, 1., 2.):
        raise ValueError('无效记谱单位比例')
    meta = read_json(evidence_path)
    archive = Path(evidence_path).with_suffix('.npz')
    binding = project['shared_analysis']['input_binding']
    if meta['version'] != 2 or meta['mix_sha256'] != binding['sources']['mix']['sha256'] or sha256(archive) != meta['array_sha256']:
        raise ValueError('新单位原声证据来源或版本不符')
    for role, source in binding['sources'].items():
        if sha256(source['path']) != source['sha256']:
            raise ValueError('原声文件已改变：' + role)
    with np.load(archive, allow_pickle=False) as stored:
        arrays = {key: stored[key].copy() for key in stored.files}
    actual = select_meter(meta, arrays)
    sealed = read_json(selection_path)
    if fingerprint(actual) != fingerprint(sealed):
        raise ValueError('选拍结果不能由匿名原声及当前冻结规则重现')
    vocal = project['accepted_vocal_project']
    mapping = TempoMap(vocal['timing']['knots'])
    q = np.arange(0., np.ceil(mapping.seconds_to_quarters(meta['duration_seconds'])), 1. / quarter_scale)
    seconds = np.array([mapping.quarters_to_seconds(float(x)) for x in q])
    tracks = {r['role']: {key: arrays[r['prefix'] + '_' + key] for key in ('times', 'novelty')} for r in meta['tracks']}
    # 慢拍单位与两曲最小修订：修改只切换明确请求的固定拍序分组器，旧封存决定按原版重放。
    # grouping = group_fixed_pulses(seconds, arrays, tracks)
    grouping = group_fixed_pulses(seconds, arrays, tracks, version=grouping_version)
    grouping['old_quarters'] = q.tolist()
    target = 60 / float(np.median(np.diff(seconds)))
    unit = actual['notation_level']
    issues = []
    if unit['status'] != 'selected' or abs(float(unit.get('bpm') or 0.) / target - 1.) > .06:
        issues.append({'kind': 'proposed_projection_not_supported_by_selected_unit'})
    issues.extend(grouping['issues'])
    status = 'passed' if not issues else 'needs_review'
    return {'version': 1, 'status': status, 'issues': issues,
        'scope': 'source_verified_relative_meter_projection_preserves_existing_seconds_not_whole_music_certificate',
        'evidence_path': str(Path(evidence_path).absolute()), 'evidence_sha256': sha256(evidence_path),
        'selection_path': str(Path(selection_path).absolute()), 'selection_sha256': sha256(selection_path),
        'mix_sha256': meta['mix_sha256'], 'quarter_scale': quarter_scale,
        'notation_level': deepcopy(unit), 'fixed_pulse_grouping': grouping,
        'first_downbeat_old_quarter': next(float(x) for x, b in zip(q, grouping['beats']) if b['beat'] == 1),
        'projection_allowed': not issues, 'normal_publication_allowed': False,
        'raw_model_unobserved_ranges_preserved_for_review': actual['unresolved_windows']}


def load_verified_decision(project, path):
    # 慢拍单位与两曲最小修订：新增调用方不能自行盖章，候选／算法／原音改变都使旧验收失效。
    value = read_json(path)
    # 慢拍单位与两曲最小修订：修改重放按实际绑定的分组版本，不能用新参数静默重解释旧决定。
    # replay = inspect_unit_decision(project, value['evidence_path'], value['selection_path'], value['quarter_scale'])
    replay = inspect_unit_decision(project, value['evidence_path'], value['selection_path'], value['quarter_scale'],
                                   value.get('fixed_pulse_grouping', {}).get('version', 1))
    if fingerprint(value) != fingerprint(replay):
        raise ValueError('记谱单位决定已过期或被改写')
    if not value['projection_allowed']:
        raise ValueError('拍单位或固定拍序首拍仍未通过，停止生成：' + str(value['issues']))
    return replay


def replay_unit_voice(correction, binding):
    # 慢拍单位与两曲最小修订：新增原工程绑定的确定性重放，不接受拿修订稿自己作基线。
    from accompaniment_rebar import validate_vocal_snapshot
    from meter_unit_projection import project_voice_units
    if correction.get('version') != 1:
        raise ValueError('未知纯单位投影版本')
    path = Path(correction['source_project'])
    if sha256(path) != correction['source_project_sha256'] or sha256(correction['decision']) != correction['decision_sha256']:
        raise ValueError('纯单位投影的原工程／证据被改动')
    base = read_json(path)
    if base['accepted_vocal_project'].get('meter_unit_correction'):
        raise ValueError('纯单位修订不允许重复套用，请绑定最初的受保护工程')
    if base['shared_analysis']['input_binding'] != binding or not validate_vocal_snapshot(base['accepted_vocal_project'], binding):
        raise ValueError('纯单位投影的原来源不能重放')
    decision = load_verified_decision(base, correction['decision'])
    voice = project_voice_units(base['accepted_vocal_project'], decision['quarter_scale'],
        decision['first_downbeat_old_quarter'], decision['fixed_pulse_grouping'])
    voice['meter_unit_correction'] = deepcopy(correction)
    return voice


def verify_projected_shared(project):
    # 慢拍单位与两曲最小修订：新增共享分析来源重放；自行刷新乐句计划摘要也不能改词音、音高或和弦。
    from meter_unit_projection import project_existing_music
    correction = project['accepted_vocal_project'].get('meter_unit_correction')
    if not correction:
        raise ValueError('纯单位工程缺少人声来源绑定')
    original = read_json(correction['source_project'])
    if sha256(correction['source_project']) != correction['source_project_sha256']:
        raise ValueError('纯单位原工程已改变')
    decision = load_verified_decision(original, correction['decision'])
    expected, _ = project_existing_music(original, decision['quarter_scale'],
        decision['first_downbeat_old_quarter'], decision['fixed_pulse_grouping'])
    if project['shared_analysis'] != expected['shared_analysis']:
        raise ValueError('投影后的共享和声或源证据不能从受保护原工程重放')
    # 慢拍单位与两曲最小修订：新增真实入口基线重放，不能拿修改后的候选自己充当纯投影祖先。
    source = project.get('readability_source', {})
    if source.get('baseline_is_verified_unit_projection_of_source'):
        path = Path(source['baseline_project'])
        if sha256(path) != source['baseline_project_sha256']:
            raise ValueError('纯投影基线文件已改变')
        baseline = read_json(path)
        voice = deepcopy(baseline['accepted_vocal_project'])
        voice.pop('meter_unit_correction', None)
        if (voice != expected['accepted_vocal_project'] or baseline['shared_analysis'] != expected['shared_analysis']
                or baseline['arrangements'] != expected['arrangements']):
            raise ValueError('基线不是原工程可重放的纯单位投影，不得以修订稿自证')
    # 慢拍单位与两曲最小修订：新增逐身份检查器乐全音值与局部范围，不只验共享和弦或几个音高出现过。
    before = {n['id']: n for n in expected['arrangements']['guitar']['notes']
              if n.get('section') != 'vocal' or n.get('role') == 'instrumental_melody'}
    after = {n['id']: n for n in project['arrangements']['guitar']['notes']}
    for identity, old in before.items():
        note = after.get(identity)
        if (note is None or any(note.get(k) != old.get(k) for k in ('pitch_midi', 'role', 'velocity', 'melody_accent'))
                or note['end_tick'] - note['start_tick'] < old['end_tick'] - old['start_tick']
                or note['end_tick'] < old['end_tick'] or abs(note['start_tick'] - old['start_tick']) > 120):
            raise ValueError('受保护器乐身份／音高／完整延音或局部时移范围改变：' + identity)
    return {'valid': True, 'scope': 'exact_source_shared_analysis_meter_unit_projection',
            # 慢拍单位与两曲最小修订：新增明确记录实际核对范围，既有同音换弦仍须共同12品与持续按弦验收。
            'source_project_sha256': correction['source_project_sha256'], 'harmony_reselected': False,
            'instrumental_ids_pitch_expression_and_complete_duration_checked': len(before),
            'maximum_allowed_local_attack_shift_ticks': 120,
            'unit_baseline_replayed': bool(source.get('baseline_is_verified_unit_projection_of_source'))}


def main(argv=None):
    # 慢拍单位与两曲最小修订：新增通用命令行交接，不依赖报告里的曲目清单才能生成来源绑定决定。
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, required=True)
    parser.add_argument('--evidence', type=Path, required=True)
    parser.add_argument('--selection', type=Path, required=True)
    parser.add_argument('--quarter-scale', type=float, choices=(.5, 1., 2.), required=True)
    parser.add_argument('--grouping-version', type=int, choices=(1, 2, 3), default=3)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    if args.output.exists():
        raise ValueError('选拍决定必须另存，不能覆盖旧证据')
    decision = inspect_unit_decision(read_json(args.project), args.evidence, args.selection,
                                     args.quarter_scale, args.grouping_version)
    save_json(args.output, decision)
    print({'status': decision['status'], 'projection_allowed': decision['projection_allowed'],
           'normal_publication_allowed': False, 'output': str(args.output.resolve())})
    return 0 if decision['projection_allowed'] else 2


if __name__ == '__main__':
    # 慢拍单位与两曲最小修订：新增未决以非零码返回，不会继续调用编配器。
    raise SystemExit(main())
