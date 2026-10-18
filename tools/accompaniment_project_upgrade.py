"""旧工程功能自动升级与三曲器乐表现统一：通用能力注册、实际数据检查及最小来源绑定升级。"""
from copy import deepcopy
from pathlib import Path
from guitar_instrumental_expression import (POLICY as EXPRESSION_POLICY, instrumental, apply_expression,
    validate_expression, expression_parent, derive_expression)
from guitar_instrumental_register import fingerprint
from score_export import read_json, save_json, sha256

SCHEMA_VERSION = 1
FOCUS_FIELDS = ('melody_accent', 'expression_original_velocity', 'velocity')
DERIVED_FIELDS = ('tab_display', 'rhythm_display', 'time_alignment_display')


# 旧工程功能自动升级与三曲器乐表现统一：新增候选来自已认可音符角色及原器乐区段，不读取曲名／歌词答案。
def candidates(shared, guitar):
    eligible = [n for n in guitar['notes'] if instrumental(shared, n)]
    return ([n for n in eligible if n['role'] == EXPRESSION_POLICY['melody_role']],
            [n for n in eligible if n.get('instrumental_flow_fill') and n['role'] != EXPRESSION_POLICY['melody_role']])


# 旧工程功能自动升级与三曲器乐表现统一：新增只检查事实的能力状态；自报版本清单不能代替音符／来源。
def inspect_focus(shared, vocal, guitar, verify_sources=True):
    melody, fill = candidates(shared, guitar); info = guitar.get('instrumental_expression')
    if info:
        # 旧工程功能自动升级与三曲器乐表现统一：新增沿用严格旧验证器，篡改已有音乐或来源不会被自动覆盖。
        check = validate_expression(shared, vocal, guitar, replay=True) if verify_sources else None
        if check is not None and not check['valid']:
            raise ValueError('已有器乐表现来源／数据不完整：' + str(check['errors'][:6]))
        absent = [n['id'] for n in melody if n.get('melody_accent') is not True or 'expression_original_velocity' not in n]
        absent += [n['id'] for n in fill if 'expression_original_velocity' not in n]
        if absent: raise ValueError('已有表现层缺少可验证的重音／力度数据：' + str(absent[:6]))
        return {'version': info['version'], 'status': 'complete', 'melody_notes': len(melody),
                'fill_notes': len(fill), 'source_verified': verify_sources, 'needed': False}
    # 旧工程功能自动升级与三曲器乐表现统一：新增未绑定的半成品拒绝，不猜测是否已增强而重复叠加音量。
    if any(n.get('melody_accent') or 'expression_original_velocity' in n for n in melody + fill):
        raise ValueError('已有器乐重音／力度但缺少来源绑定，不能直接再叠加；需恢复原表现来源。')
    return {'version': 0, 'status': 'missing' if melody or fill else 'not_applicable',
            'melody_notes': len(melody), 'fill_notes': len(fill), 'source_verified': False,
            'needed': bool(melody or fill)}


# 旧工程功能自动升级与三曲器乐表现统一：新增能力升级操作，仅填空表现层，不启用背景筛选或节奏重编。
def migrate_focus(shared, vocal, arrangements, parent_path):
    guitar, report = apply_expression(shared, vocal, arrangements['guitar'], parent_path,
                                      review_path=None, clarity_dir=None)
    result = deepcopy(arrangements); result['guitar'] = guitar
    return result, {'accent_notes': len(report['melody_accent_ids']),
                    'softened_fills': len(report['softened_fill_ids']),
                    'rest_changes': len(report['removed_note_ids']) + len(report['shortened_notes']),
                    'upstream_project': str(Path(parent_path).resolve()), 'upstream_sha256': sha256(parent_path)}


# 旧工程功能自动升级与三曲器乐表现统一：新增可扩展注册表，音乐数据能力与按需重建的谱面能力分开。
DATA_CAPABILITIES = {
    'guitar_instrumental_expression': {'version': EXPRESSION_POLICY['version'], 'inspect': inspect_focus,
                                     'migrate': migrate_focus, 'allowed_note_fields': FOCUS_FIELDS},
}
# 吉他长段反复与流畅阅读：修改显示能力版本，原1版注释保留；显示升级不改变音乐数据能力。
# DISPLAY_CAPABILITIES = {'guitar_repeat_layout': {'version': 1, 'stage': 'after_verified_music_export',
#                                                'music_changes': False}}
DISPLAY_CAPABILITIES = {'guitar_repeat_layout': {'version': 2, 'stage': 'after_verified_music_export',
                                               'music_changes': False}}


# 旧工程功能自动升级与三曲器乐表现统一：新增所有重导出入口共享的实际能力清单，完整旧层严格重放后保留。
def inspect_project_features(shared, vocal, arrangements, verify_sources=True):
    entries = {}
    for name, definition in DATA_CAPABILITIES.items():
        if 'guitar' not in arrangements:
            entries[name] = {'status': 'not_applicable', 'version': 0, 'needed': False}
        else:
            entries[name] = definition['inspect'](shared, vocal, arrangements['guitar'], verify_sources)
        entries[name]['required_version'] = definition['version']
    return {'schema_version': SCHEMA_VERSION, 'data_capabilities': entries,
            'complete': all(not item['needed'] for item in entries.values())}


# 旧工程功能自动升级与三曲器乐表现统一：新增可修复的缺失派生字段；只有严格上游可重建且值缺失才补。
def repair_missing_expression_fields(shared, vocal, guitar):
    if not guitar.get('instrumental_expression'): return deepcopy(guitar), []
    base = expression_parent(guitar)['arrangements']['guitar']
    rebuilt, _ = derive_expression(shared, vocal, base, guitar['instrumental_expression']['settings'])
    expected = {n['id']: n for n in rebuilt['notes']}; result = deepcopy(guitar); repairs = []
    for note in result['notes']:
        origin = expected.get(note['id'], {})
        for field in FOCUS_FIELDS:
            if field not in note and field in origin:
                note[field] = deepcopy(origin[field]); repairs.append({'note_id': note['id'], 'field': field})
    if repairs:
        check = validate_expression(shared, vocal, result, replay=True)
        if not check['valid']: raise ValueError('缺失派生字段无法由原来源恢复：' + str(check['errors'][:6]))
    return result, repairs


# 旧工程功能自动升级与三曲器乐表现统一：新增明确许可字段外的逐音保护，所有正文／钢琴／事件保持。
def validate_upgrade_scope(shared, vocal, before, after):
    errors = []
    if set(before) != set(after): errors.append('instruments_changed')
    for name in set(before) | set(after):
        if name != 'guitar':
            if before.get(name) != after.get(name): errors.append(name + '_changed')
            continue
        old, new = before.get(name, {}), after.get(name, {})
        old_notes = {n['id']: n for n in old.get('notes', [])}; new_notes = {n['id']: n for n in new.get('notes', [])}
        if old_notes.keys() != new_notes.keys(): errors.append('guitar_note_ids_changed')
        for identity, original in old_notes.items():
            current = new_notes.get(identity, {}); eligible = instrumental(shared, original) and (
                original['role'] == EXPRESSION_POLICY['melody_role'] or original.get('instrumental_flow_fill'))
            fields = set(FOCUS_FIELDS) if eligible else set()
            if ({k: v for k, v in original.items() if k not in fields} !=
                    {k: v for k, v in current.items() if k not in fields}): errors.append('protected_note_changed:' + identity)
        # 旧工程功能自动升级与三曲器乐表现统一：新增账本／手型／踏板／音序／换夹也保持，不只比较音高。
        ignored = {'notes', 'instrumental_expression', *DERIVED_FIELDS}
        for field in old.keys() | new.keys():
            if field not in ignored and old.get(field) != new.get(field): errors.append('guitar_field_changed:' + field)
    return {'valid': not errors, 'errors': errors, 'note_ids_unchanged': not errors,
            'allowed_note_fields': list(FOCUS_FIELDS), 'vocal_harmony_rhythm_piano_preserved': not errors}


# 旧工程功能自动升级与三曲器乐表现统一：新增当前实际状态的不可覆盖快照，升级来源可重放。
def bind_parent(shared, vocal, arrangements, source_path, workspace):
    seed = {'shared_analysis': deepcopy(shared), 'accepted_vocal_project': deepcopy(vocal),
            'arrangements': deepcopy(arrangements)}
    if source_path:
        source = read_json(source_path)
        if all(source.get(k) == value for k, value in seed.items()): return Path(source_path).resolve()
    workspace = Path(workspace).resolve(); path = workspace / ('project_feature_source_' + fingerprint(seed)[:20] + '.json')
    if path.exists():
        if read_json(path) != seed: raise ValueError('不能覆盖旧工程功能升级的真实输入。')
    else:
        workspace.mkdir(parents=True, exist_ok=True); save_json(path, seed)
    return path


# 旧工程功能自动升级与三曲器乐表现统一：新增统一升级编排器，完整能力零改动，缺失能力逐项最小迁移。
def ensure_project_features(shared, vocal, arrangements, source_path=None, workspace=None):
    before = inspect_project_features(shared, vocal, arrangements); result = deepcopy(arrangements); migrations = []
    for name, definition in DATA_CAPABILITIES.items():
        if not before['data_capabilities'][name]['needed']: continue
        if workspace is None and source_path is None: raise ValueError('自动旧工程升级需要实际来源或专用缓存目录。')
        parent = bind_parent(shared, vocal, result, source_path, workspace or Path(source_path).parent)
        result, change = definition['migrate'](shared, vocal, result, parent)
        migrations.append({'capability': name, 'from_version': before['data_capabilities'][name]['version'],
                           'to_version': definition['version'], 'changes': change})
    scope = validate_upgrade_scope(shared, vocal, arrangements, result)
    if not scope['valid']: raise ValueError('自动升级改变了已认可音乐：' + str(scope['errors'][:6]))
    after = inspect_project_features(shared, vocal, result)
    if not after['complete']: raise ValueError('自动升级后仍缺少要求的功能数据。')
    return result, {'schema_version': SCHEMA_VERSION, 'before': before, 'after': after,
                    'changed': bool(migrations), 'migrations': migrations, 'scope': scope,
                    'background_and_density_rhythm_reanalysis': False}


# 旧工程功能自动升级与三曲器乐表现统一：新增交付能力清单，派生排版只有实际验收通过才记完整。
def delivery_capabilities(feature_report, repeat_result=None):
    result = deepcopy(feature_report['after']); result['display_capabilities'] = {}
    if repeat_result is not None:
        if not repeat_result['valid']: raise ValueError('反复排版能力未通过实际验收。')
        result['display_capabilities']['guitar_repeat_layout'] = {'version': DISPLAY_CAPABILITIES['guitar_repeat_layout']['version'],
                                                               'status': 'complete', 'validated': True}
    return result
