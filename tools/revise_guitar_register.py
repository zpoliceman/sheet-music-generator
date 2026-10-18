"""保音持续按弦与整句八度衔接：固定原音乐分析，仅重规划吉他音区／用弦并隔离导出。"""
from __future__ import annotations

# 保音持续按弦与整句八度衔接：新增公共CLI，输入真实工程／已绑定骨干，不调用音高或和弦识别。
import argparse
from copy import deepcopy
from pathlib import Path

from guitar_instrumental_register import (
    arrange_instrumental_register, bind_register_source, fingerprint, require_instrumental_fret_limit,
)
from instrumental_source_melody import revised_guitar, validate_source_backbone
from score_export import read_json, save_json, sha256
from source_timing_acceptance import require_isolated_output

ROOT = Path(__file__).resolve().parents[1]


# 保音持续按弦与整句八度衔接：新增完整音符／时值守卫，禁止后续阅读整理暗中删音或截延音。
def require_retained_notes(before, after):
    old = {note['id']: note for note in before}
    new = {note['id']: note for note in after}
    errors = []
    if old.keys() != new.keys():
        errors.append('note_id_set_changed')
    for identity, note in old.items():
        current = new.get(identity)
        if current is None:
            continue
        if any(note.get(field) != current.get(field) for field in ('start_tick', 'end_tick', 'role')):
            errors.append('note_attack_release_or_role_changed:' + identity)
        if note['pitch_midi'] % 12 != current['pitch_midi'] % 12:
            errors.append('note_pitch_class_changed:' + identity)
    if errors:
        raise ValueError('保音／完整延音保护未通过：' + str(errors[:8]))
    return {'valid': True, 'note_count': len(old), 'all_note_ids_attacks_releases_roles_pitch_classes_retained': True}


# 保音持续按弦与整句八度衔接：新增从已核验原音高计划构建未配音请求，所有音乐位置均来自绑定数据。
def canonical_source(project, source_path):
    shared, vocal, guitar = (project[key] for key in ('shared_analysis', 'accepted_vocal_project', 'arrangements'))
    guitar = guitar['guitar']
    if not guitar.get('instrumental_source_backbone'):
        raise ValueError('保音音区修订需要绑定的原器乐骨干；不在此入口重新识别旋律。')
    check = validate_source_backbone(shared, vocal, guitar, replay=False)
    if not check['valid']:
        raise ValueError('原器乐骨干来源未通过：' + str(check['errors'][:8]))
    info = deepcopy(guitar['instrumental_source_backbone'])
    plan = read_json(info['source_plan_path'])
    raw, superseded = revised_guitar(shared, vocal, guitar, plan, register_input_version=2)
    require_retained_notes(guitar['notes'], raw['notes'])
    info.update(upstream_project=str(Path(source_path).resolve()), upstream_sha256=sha256(source_path),
                source_notes_sha256=fingerprint(guitar['notes']),
                seed_notes=deepcopy(raw['notes']), seed_notes_sha256=fingerprint(raw['notes']),
                superseded_note_ids=superseded, register_input_version=2,
                seed_is_unvoiced_source_request=True)
    raw['instrumental_source_backbone'] = info
    raw['configuration'].update(instrumental_register_strategy_version=2,
                                instrumental_register_voicing_version=2,
                                source_register_input_version=2)
    result = deepcopy(project)
    result['arrangements']['guitar'] = raw
    return result


# 保音持续按弦与整句八度衔接：新增各阶段都检查受保护层，吉他派生不允许修改拍轴／人声／原和声／钢琴。
def require_protected(before, after):
    fields = {'accepted_vocal_project': before['accepted_vocal_project'] == after['accepted_vocal_project'],
              'shared_analysis': before['shared_analysis'] == after['shared_analysis'],
              'piano': before['arrangements'].get('piano') == after['arrangements'].get('piano')}
    if not all(fields.values()):
        raise ValueError('保音吉他修订改变受保护音乐层：' + str(fields))
    return {'valid': True, **fields}


# 保音持续按弦与整句八度衔接：新增来源绑定的完整公共流程，任何失败只留隔离候选，不更新正常入口。
# 保音持续按弦与整句八度衔接：新增纯显示预算，逐小节测宽后贪心安排1–4小节，不改任何声音或来源音乐。
# 保音持续按弦与整句八度衔接：修改原生宽度预算，网页最小缩放为0.64；2000原生像素仍能在常用视窗内保持可读字形。
# def prepare_reading_layout(project, width_limit=1300):
def prepare_reading_layout(project, width_limit=2000):
    from export_timing_revision import render_row, measure_timeline
    from guitar_repeat_readability import reading_line_end
    import xml.etree.ElementTree as ET
    timeline = measure_timeline(project)
    widths = {str(measure['number']): float(ET.fromstring(render_row(project, [measure], True)).get('width'))
              for measure in timeline}
    config = project['arrangements']['guitar']['configuration']
    config.update(maximum_bars_per_reading_line=4, reading_maximum_native_width=width_limit,
                  reading_measure_widths=widths)
    groups, cursor = [], 0
    while cursor < len(timeline):
        first = timeline[cursor]['number']
        last = first if timeline[cursor].get('pickup') else reading_line_end(project['arrangements']['guitar'], first, timeline[-1]['number'])
        groups.append([first, last])
        cursor += last - first + 1
    layout = {'maximum_bars_per_line': 4, 'target_native_width': width_limit,
              'single_measure_maximum_native_width': max(widths.values(), default=0),
              'unfolded_reading_rows': groups, 'musical_repeat_minimum_measures_unchanged': 8,
              'music_notes_unchanged': True, 'method': 'per_line_actual_measure_width_budget'}
    project.setdefault('guitar_register_revision', {})['reading_layout'] = layout
    return layout


def revise(project_path, output, protected_project=None, feature_cache=None):
    project_path = Path(project_path).resolve()
    output = require_isolated_output(output, ROOT)
    if output.exists() and any(output.iterdir()):
        raise ValueError('输出已有内容，请使用新的隔离目录，不能覆盖旧谱。')
    original_sha = sha256(project_path)
    original = read_json(project_path)
    if protected_project:
        protected_path = Path(protected_project).resolve()
        protected = read_json(protected_path)
        if any(original[key] != protected[key] for key in ('accepted_vocal_project', 'shared_analysis')):
            raise ValueError('受保护钢琴工程与吉他来源的拍轴／人声／和弦分析不同，拒绝拼接。')
        original['arrangements']['piano'] = deepcopy(protected['arrangements']['piano'])
    output.mkdir(parents=True)
    bound_input = output / 'protected_input.json'
    save_json(bound_input, original)
    seed = canonical_source(original, bound_input)
    seed_path = output / 'unvoiced_register_source.json'
    save_json(seed_path, seed)
    print('在原音高上统一规划吉他整句八度及持续用弦', flush=True)
    guitar, register = arrange_instrumental_register(seed['shared_analysis'], seed['accepted_vocal_project'], seed['arrangements']['guitar'])
    bind_register_source(guitar, seed_path, seed['shared_analysis'], seed['accepted_vocal_project'])
    registered = deepcopy(seed)
    registered['arrangements']['guitar'] = guitar
    guitar['configuration']['maximum_fret'] = 12
    require_protected(original, registered)
    retention = require_retained_notes(original['arrangements']['guitar']['notes'], guitar['notes'])
    fret = require_instrumental_fret_limit(registered['shared_analysis'], guitar)
    # 保音持续按弦与整句八度衔接：新增实际常用指型及x显示派生；严格核对完整持握，不改变任何音符或延音。
    from guitar_chord_diagrams import prepare_diagrams
    from guitar_grip_policy import validate_grip_policy
    from guitar_instrumental_register import register_shared_view
    diagram_shared = register_shared_view(registered['shared_analysis'], registered['accepted_vocal_project'])
    prepare_diagrams(diagram_shared, guitar, registered['accepted_vocal_project'])
    diagrams = validate_grip_policy(diagram_shared, guitar, registered['accepted_vocal_project'])
    if not diagrams['valid']:
        raise ValueError('吉他实际指型／持握未通过：' + str(diagrams['errors'][:8]))
    require_retained_notes(original['arrangements']['guitar']['notes'], guitar['notes'])
    # 保音持续按弦与整句八度衔接：新增仅补器乐突出力度，不启用删背景或截尾；实际变动仍受完整时值守卫。
    from accompaniment_project_upgrade import ensure_project_features
    registered['arrangements'], features = ensure_project_features(
        registered['shared_analysis'], registered['accepted_vocal_project'], registered['arrangements'],
        workspace=output / 'feature_sources')
    require_retained_notes(original['arrangements']['guitar']['notes'], registered['arrangements']['guitar']['notes'])
    require_protected(original, registered)
    registered['guitar_register_revision'] = {
        'version': 2, 'source_project': str(project_path), 'source_sha256': original_sha,
        'source_notes_sha256': fingerprint(original['arrangements']['guitar']['notes']),
        'all_notes_and_complete_releases_retained': True, 'normal_entry_replacement_allowed': False}
    # 保音持续按弦与整句八度衔接：新增按真实渲染宽度决定1–4小节显示行，不缩小音符或强迫横向滚动，也不改变反复范围。
    # 保音持续按弦与整句八度衔接：修改全曲统一行长为逐行预算；原实现完整注释保留。
    #     from export_timing_revision import render_row, measure_timeline
    #     import xml.etree.ElementTree as ET
    #     timeline = measure_timeline(registered)
    #     # 保音持续按弦与整句八度衔接：修改目标留出页面边距，原阈值保留，避免1640像素视窗仍须横向滚动。
    #     # width_limit = 1400
    #     width_limit = 1300
    #     layout = None
    #     for line_bars in (4, 3, 2, 1):
    #         widths = [float(ET.fromstring(render_row(registered, timeline[index:index + line_bars], True)).get('width'))
    #                   for index in range(0, len(timeline), line_bars)]
    #         layout = {'maximum_bars_per_line': line_bars, 'maximum_native_width': max(widths, default=0),
    #                   'target_native_width': width_limit, 'musical_repeat_minimum_measures_unchanged': 8}
    #         if layout['maximum_native_width'] <= width_limit:
    #             break
    #     registered['arrangements']['guitar']['configuration']['maximum_bars_per_reading_line'] = layout['maximum_bars_per_line']
    #     registered['guitar_register_revision']['reading_layout'] = layout
    layout = prepare_reading_layout(registered)
    registered_path = output / 'registered_project.json'
    save_json(registered_path, registered)
    save_json(output / 'register_report.json', register)
    save_json(output / 'feature_report.json', features)
    save_json(output / 'fingering_diagram_check.json', diagrams)
    save_json(output / 'reading_layout.json', layout)
    print('检查稳定和弦、十六分和长段复用，随后导出隔离吉他谱', flush=True)
    # 保音持续按弦与整句八度衔接：新增阅读变换先在内存作完整音符守卫，再调用既有同一公开导出／验收路线。
    from accompaniment_analysis import extract_features
    from guitar_readable_arrangement import revise_guitar_arrangement
    sources = registered['shared_analysis']['input_binding']['sources']
    cache = Path(feature_cache) if feature_cache else output / 'features'
    source_features = {name: extract_features(sources[name], cache, name)
                       for name in ('mix', 'accompaniment', 'bass', 'six_guitar') if name in sources}
    readable, _ = revise_guitar_arrangement(registered, source_features=source_features)
    require_retained_notes(registered['arrangements']['guitar']['notes'], readable['arrangements']['guitar']['notes'])
    require_protected(original, readable)
    from revise_guitar_readability import revise as revise_readability
    result = revise_readability(registered_path, output / 'guitar_candidate', cache)
    final = read_json(output / 'guitar_candidate/project.json')
    require_retained_notes(original['arrangements']['guitar']['notes'], final['arrangements']['guitar']['notes'])
    protection = require_protected(original, final)
    if sha256(project_path) != original_sha:
        raise ValueError('处理期间原工程改变，本候选不得采用。')
    summary = {'output': str(output), 'guitar_output': result['output'],
               'retention': retention, 'protected_music': protection, 'instrumental_frets': fret,
               'normal_entry_changed': False, 'music_acceptance': 'needs_review'}
    save_json(output / 'revision_report.json', summary)
    return summary


def main():
    # 保音持续按弦与整句八度衔接：新增通用命令参数，曲名和实际位置均由输入工程决定。
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, required=True)
    parser.add_argument('--protected-project', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--feature-cache', type=Path)
    args = parser.parse_args()
    print(revise(args.project, args.output, args.protected_project, args.feature_cache), flush=True)


if __name__ == '__main__':
    # 保音持续按弦与整句八度衔接：新增直接执行入口。
    main()
