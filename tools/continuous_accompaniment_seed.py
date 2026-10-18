"""连续源拍序与人声联合重解通用修复：区分旧自动循环、真实器乐和新编配的边界续音。"""
from copy import deepcopy


# 连续源拍序与人声联合重解通用修复：新增旧普通循环来源识别，不能把移轴后的自动模板当成器乐录音。
def synthetic_vocal_seed(note):
    return (note.get('section') == 'vocal' and note.get('role') in ('bass', 'harmony')
            and not note.get('source_melody_id') and (
                note.get('onset_origin') in ('arranged_common_pattern', 'arranged_meter_arpeggio')
                or note.get('phrase_harmony_generated')))


# 连续源拍序与人声联合重解通用修复：新增只关闭过期的自动循环；真实旋律/低音身份和源秒迁移保持。
def prepare_continuous_seeds(old_arrangements, fresh):
    for name, arrangement in fresh.items():
        old_by_id = {n['id']: n for n in old_arrangements[name]['notes']}
        notes = []; removed = []; retired_markers = []
        for note in arrangement['notes']:
            original_id = note['id']
            while original_id not in old_by_id and original_id.startswith('preserved_'):
                original_id = original_id[len('preserved_'):]
            old = old_by_id.get(original_id)
            if old and synthetic_vocal_seed(old) and note.get('section') != 'vocal':
                removed.append({'note_id': note['id'], 'source_note_id': old['id'],
                                'start_tick': note['start_tick'], 'end_tick': note['end_tick'],
                                'reason': 'obsolete_vocal_pattern_outside_new_vocal_range'})
                continue
            # 连续源拍序与人声联合重解通用修复：新增本轮/历史编配标志分离，历史保留音不能冒充本轮新和弦实音。
            if note.pop('phrase_harmony_generated', False):
                note['prior_phrase_harmony_generated'] = True
                retired_markers.append(note['id'])
            notes.append(note)
        removed_ticks = {n['start_tick'] for n in removed}
        present_ticks = {n['start_tick'] for n in notes}
        arrangement['notes'] = notes
        arrangement['attack_events'] = [e for e in arrangement.get('attack_events', [])
            if e['start_tick'] not in removed_ticks or e['start_tick'] in present_ticks]
        arrangement['continuous_seed_provenance'] = {'version': 1,
            'obsolete_synthetic_notes': removed, 'retired_generation_markers': retired_markers,
            'real_instrumental_notes_removed': False}
        if 'beat_phase_seed' in arrangement:
            arrangement['beat_phase_seed']['source_notes'] = deepcopy(notes)
    return fresh


# 连续源拍序与人声联合重解通用修复：新增普通伴奏向新完整拍交接时释放旧续音，保留前面的真实攻击及器乐旋律。
# 尾段原声局部补证：修改首次已验来源的未定稿普通伴奏也正确交接完整拍；旧工程默认仍按旧条件。
# def release_ordinary_boundary_tails(shared, originals):
#     if not shared.get('continuous_source_meter'):
def release_ordinary_boundary_tails(shared, originals, first_source=False):
    if not shared.get('continuous_source_meter') and not first_source:
        return originals
    from phrase_harmony_arrange import ordinary
    from score_export import PPQ
    pulse = int(PPQ * 4 / shared['timing']['meter'][1])
    entries = sorted({p['start_tick'] for p in shared.get('phrase_harmony_plan', {}).get('phrases', [])
                      if not p['action'].startswith('preserve_source') and not p['start_tick'] % pulse})
    for arrangement in originals.values():
        releases = []
        for note in arrangement['notes']:
            if (ordinary(shared, note) or note.get('section') != 'vocal'
                    or note.get('role') not in ('bass', 'harmony') or note.get('source_melody_id')):
                continue
            entry = next((t for t in entries if note['start_tick'] < t < note['end_tick']), None)
            if entry is None:
                continue
            releases.append({'note_id': note['id'], 'old_end_tick': note['end_tick'], 'new_end_tick': entry,
                             'reason': 'ordinary_sustain_released_for_complete_beat_rearticulation'})
            note['end_tick'] = entry
        arrangement['continuous_boundary_releases'] = releases
    return originals
