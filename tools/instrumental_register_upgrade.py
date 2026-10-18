"""器乐合理分句与十二品硬限制：明确旧版低品升级，从真实来源恢复未折八度的器乐输入。"""
# 器乐合理分句与十二品硬限制：新增通用来源链恢复，避免拿已降位／加重音／填充结果再降一次。
from copy import deepcopy
from pathlib import Path

from score_export import read_json, sha256
from guitar_instrumental_register import (editable_notes, fingerprint,
    register_shared_view, validate_instrumental_register)


def prepare_register_upgrade(shared, vocal, guitar):
    info = guitar.get('instrumental_register')
    if not info or info.get('version') == 2:
        return deepcopy(guitar), None
    # 器乐合理分句与十二品硬限制：新增旧来源完整核验；不能用手工改写的原音快照来绕过保护。
    checked = validate_instrumental_register(shared, vocal, guitar, replay=True)
    if not checked or not checked['valid']:
        raise ValueError('旧器乐音区来源不可靠，拒绝升级：' + str((checked or {}).get('errors', [])[:6]))
    source_path = Path(info['source_path'])
    if sha256(source_path) != info['source_sha256']:
        raise ValueError('旧器乐音区的真实来源已改变。')
    seed = read_json(source_path)
    if (fingerprint(seed['accepted_vocal_project']) != fingerprint(vocal) or
            fingerprint(register_shared_view(seed['shared_analysis'], vocal)) !=
            fingerprint(register_shared_view(shared, vocal))):
        raise ValueError('低品升级不能改变已认可人声或共同和声／拍轴。')
    restored = deepcopy(seed['arrangements']['guitar'])
    if restored['notes'] != info['source_notes']:
        raise ValueError('真实器乐来源与原音快照不一致。')
    editable = editable_notes(shared, restored)
    actual = {n['id']: n for n in guitar['notes']}
    for note in restored['notes']:
        if note['id'] not in editable and actual.get(note['id']) != note:
            raise ValueError('低品升级的来源会改变正常唱段，拒绝：' + note['id'])
    # 器乐合理分句与十二品硬限制：新增明确新版配置，旋律只能统一降八度，伴奏按已验证候选协调声部。
    restored['configuration']['instrumental_register_strategy_version'] = 2
    restored['configuration']['instrumental_register_voicing_version'] = 2
    restored['configuration']['instrumental_flow_motion_version'] = 2
    review = guitar.get('instrumental_expression', {}).get('review_path')
    report = {'source_path': str(source_path.resolve()), 'source_sha256': info['source_sha256'],
        'old_version': info['version'], 'new_version': 2, 'restored_note_count': len(restored['notes']),
        'protected_normal_note_count': len(restored['notes']) - len(editable),
        'inherited_rest_review': review, 'restore_before_register_flow_expression': True}
    restored['instrumental_register_upgrade_source'] = deepcopy(report)
    return restored, report
