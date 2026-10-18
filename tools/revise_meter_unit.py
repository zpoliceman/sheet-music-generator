"""慢拍单位与两曲最小修订：来源验收后纯投影，必要局部整理，再隔离导出。"""
# 慢拍单位与两曲最小修订：新增实际生成路线，不调用整曲词音、音高或和弦重识别，旧版和正常入口保持。
from copy import deepcopy
from pathlib import Path
import argparse
from score_export import read_json, save_json, sha256
from source_timing_acceptance import require_isolated_output
from meter_unit_entry import load_verified_decision
from meter_unit_projection import project_existing_music

ROOT = Path(__file__).resolve().parents[1]


def read_existing_features(binding, caches):
    # 慢拍单位与两曲最小修订：新增只允许存在且来源绑定的缓存，缺失停止，禁止extract_features隐式重识别。
    from accompaniment_analysis import extract_features
    result = {}
    for role in ('accompaniment', 'bass', 'six_guitar', 'six_piano'):
        if role not in binding['sources']:
            continue
        source = binding['sources'][role]
        token = 'v1_' + source['sha256'][:16] + '_22050_512_24_96'
        directory = next((Path(p) for p in caches if (Path(p) / (token + '.npz')).is_file()
                          and (Path(p) / (token + '.json')).is_file()), None)
        if directory is None:
            raise ValueError('纯单位修订缺少原声缓存，停止而不重识别：' + role)
        metadata = read_json(directory / (token + '.json'))
        if metadata.get('source_sha256') != source['sha256']:
            raise ValueError('原声缓存来源改变：' + role)
        before = sha256(directory / (token + '.npz'))
        result[role] = extract_features(source, directory, role)
        if before != sha256(directory / (token + '.npz')):
            raise ValueError('只读原声缓存被改动')
    return result


def revise(project_path, decision_path, output, feature_caches=()):
    # 慢拍单位与两曲最小修订：新增在输出前实际重放选拍与分组验收，不会回到旧速度提示或改词头。
    source_path = Path(project_path).resolve()
    output = require_isolated_output(output, ROOT)
    if output.exists() and any(output.iterdir()):
        raise ValueError('请使用新的记谱单位修订目录，不能覆盖旧版')
    original = read_json(source_path)
    decision = load_verified_decision(original, decision_path)
    if original['accepted_vocal_project'].get('meter_unit_correction'):
        raise ValueError('不要重复缩放已修订工程；原样重导请直接使用既有工程')
    from accompaniment_rebar import validate_vocal_snapshot
    binding = original['shared_analysis']['input_binding']
    if not validate_vocal_snapshot(original['accepted_vocal_project'], binding):
        raise ValueError('受保护原人声不能来源重放，停止')
    features = read_existing_features(binding, feature_caches)
    projected, preservation = project_existing_music(original, decision['quarter_scale'],
        decision['first_downbeat_old_quarter'], decision['fixed_pulse_grouping'])
    correction = {'version': 1, 'source_project': str(source_path), 'source_project_sha256': sha256(source_path),
                  'decision': str(Path(decision_path).resolve()), 'decision_sha256': sha256(decision_path)}
    projected['accepted_vocal_project']['meter_unit_correction'] = correction
    projected['meter_unit_revision']['source'] = correction
    projected['meter_unit_revision']['clock_assessment'] = deepcopy(decision)
    output.mkdir(parents=True, exist_ok=True)
    baseline_path = output / 'pure_projection/project.json'
    save_json(baseline_path, projected)
    save_json(output / 'seconds_preservation.json', preservation)
    # 慢拍单位与两曲最小修订：新增按新拍单位整理违规邻域，保留所有器乐音及完整持续时长，必要同音低品换弦另记。
    from meter_unit_guitar import regularize_complete_sustain
    prepared = deepcopy(projected)
    prepared['arrangements']['guitar'], local = regularize_complete_sustain(projected['arrangements']['guitar'],
        # 慢拍单位与两曲最小修订：修改传入真实原秒，使局部网格整理兼顾完整延音后的换把准备。
        projected['accepted_vocal_project']['statistics']['total_ticks'], vocal=projected['accepted_vocal_project'])
    save_json(output / 'local_sixteenth_changes.json', local)
    from guitar_readable_arrangement import revise_guitar_arrangement
    # 慢拍单位与两曲最小修订：修改只整理既有实际和弦，旧基础和弦选择式保留。
    # readable, harmony = revise_guitar_arrangement(prepared, source_features=features)
    readable, harmony = revise_guitar_arrangement(prepared, source_features=features, preserve_performed_harmony=True)
    # 慢拍单位与两曲最小修订：新增完整器乐保护守卫，后续旧量化器不可再次截尾或覆盖已核对的同音低品处理。
    protected = {n['id']: n for n in prepared['arrangements']['guitar']['notes']
                 if n.get('section') != 'vocal' or n.get('role') == 'instrumental_melody'}
    current = {n['id']: n for n in readable['arrangements']['guitar']['notes']}
    if any(current.get(identity) != note for identity, note in protected.items()):
        raise ValueError('局部和声整理改变了受保护的完整器乐音符')
    save_json(output / 'local_harmony_readability.json', harmony)
    # 慢拍单位与两曲最小修订：新增原工程缺钢琴时仅用已保存的共同分析配音，绝不重新猜和弦／音高。
    if 'piano' not in readable['arrangements']:
        from accompaniment_arrange import arrange_piano
        readable['arrangements']['piano'] = arrange_piano(readable['shared_analysis'], readable['accepted_vocal_project'])
        readable['meter_unit_revision']['new_piano_from_existing_shared_analysis'] = True
    # 慢拍单位与两曲最小修订：修改调用遵守原局部整理接口，验收单独读取真实结果而非假定返回二元组。
    # from piano_harmony_readability import revise_piano_labels
    # readable, piano_audit = revise_piano_labels(readable, bass_features=features.get('bass'))
    from piano_harmony_readability import revise_piano_labels, assess_piano_labels
    readable = revise_piano_labels(readable, bass_features=features.get('bass'))
    piano_audit = assess_piano_labels(readable)
    if not piano_audit['valid']:
        raise ValueError('钢琴局部和声未通过：' + str(piano_audit['errors']))
    save_json(output / 'piano_local_readability.json', piano_audit)
    # 慢拍单位与两曲最小修订：新增复核旧器乐完整图式，延音规整后不强迫同时按住未演奏的整副和弦。
    from meter_unit_grip_display import reconcile_instrumental_charts
    readable['arrangements']['guitar'], display_audit = reconcile_instrumental_charts(
        readable['arrangements']['guitar'], readable['accepted_vocal_project'])
    save_json(output / 'instrumental_grip_display.json', display_audit)
    # 慢拍单位与两曲最小修订：新增在最终单位上执行已验证的简单右手；旧八音型合并后超密时必须重验，不能沿用旧标记。
    pattern_path = output / 'pattern_baseline/project.json'
    save_json(pattern_path, readable)
    from guitar_section_patterns import arrange_section_patterns
    revised, patterns = arrange_section_patterns(readable, features)
    save_json(output / 'stable_right_hand.json', patterns)
    revised['vocal_pattern_source'] = {'project': str(pattern_path.resolve()), 'project_sha256': sha256(pattern_path)}
    revised['readability_source'] = {'project': str(baseline_path.resolve()), 'project_sha256': sha256(baseline_path),
        'baseline_project': str(baseline_path.resolve()), 'baseline_project_sha256': sha256(baseline_path),
        'no_pitch_or_harmony_reanalysis': True, 'baseline_is_verified_unit_projection_of_source': correction}
    # 慢拍单位与两曲最小修订：新增显示配置先完成再绑定验收摘要；不能在通过后改配置再沿用旧结果。
    from revise_guitar_register import prepare_reading_layout
    prepare_reading_layout(revised)
    from guitar_source_bass_acceptance import assess_changed_bass_source, require_changed_bass_source
    bass_check = assess_changed_bass_source(revised, projected, features.get('bass'))
    revised['guitar_source_bass_acceptance'] = bass_check
    save_json(output / 'guitar_source_bass_acceptance.json', bass_check)
    require_changed_bass_source(revised, bass_check)
    # 慢拍单位与两曲最小修订：新增新单位下重新查自然长段；原12／10小节长度不直接继承为通过。
    from guitar_variable_repeat import build_repeat_plan
    from guitar_readability_acceptance import assess_guitar_readability, require_guitar_readability
    plan = build_repeat_plan(revised)
    preflight = assess_guitar_readability(revised, repeat_plan=plan)
    save_json(output / 'preflight.json', preflight)
    save_json(output / 'project.json', revised)
    from meter_unit_entry import verify_projected_shared
    save_json(output / 'shared_projection_replay.json', verify_projected_shared(revised))
    require_guitar_readability(revised, preflight, final=False)
    # 慢拍单位与两曲最小修订：删除通过后才改变显示配置的旧顺序，原调用已提前执行。
    # from revise_guitar_register import prepare_reading_layout
    # prepare_reading_layout(revised)
    save_json(output / 'project.json', revised)
    from export_timing_revision import export_revision
    result = export_revision(output / 'project.json', output)
    if sha256(source_path) != correction['source_project_sha256']:
        raise ValueError('原工程在隔离修订过程中改变')
    return result


def export_preserved(project_path, output):
    # 慢拍单位与两曲最小修订：新增新版原样重导，只验证来源与实际硬要求，不重新套右手、改八度或推拍轴。
    project = read_json(project_path)
    from meter_unit_entry import verify_projected_shared
    verify_projected_shared(project)
    from source_meter_entry import require_calibrated_source
    require_calibrated_source(project['accepted_vocal_project'], project['shared_analysis']['input_binding'])
    # 慢拍单位与两曲最小修订：新增原样重导也须独立工程和新目录，避免只有页面、再次编辑却落回旧工程。
    output = require_isolated_output(output, ROOT)
    if output.exists() and any(output.iterdir()):
        raise ValueError('原样重导也必须另存新的版本目录')
    output.mkdir(parents=True, exist_ok=True)
    save_json(output / 'project.json', project)
    from export_timing_revision import export_revision
    # 慢拍单位与两曲最小修订：修改使用已核验且原样保存的工程，真实音符与来源绑定不变。
    # return export_revision(project_path, output)
    return export_revision(output / 'project.json', output)


def main():
    # 慢拍单位与两曲最小修订：新增命令行参数，和主生成入口共用同一实现。
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, required=True)
    parser.add_argument('--decision', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--features-from', type=Path, action='append', default=[])
    args = parser.parse_args()
    revise(args.project, args.decision, args.output, args.features_from)


if __name__ == '__main__':
    main()
