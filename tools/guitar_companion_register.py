"""歌词自动加载与伴随声部音区保护：认可伴随声部的初次配音约束。"""
# 歌词自动加载与伴随声部音区保护：新增来源完全匹配时复用既有音区，不按曲名、固定时间或音符编号设例外。
from copy import deepcopy
from score_export import read_json, sha256
from source_meter_selection import fingerprint

POLICY = {'version': 1, 'scope': 'initial_joint_voicing_companion_register_only',
          'match_id_role_full_ticks_and_pitch_class': True, 'preserve_all_attacks_and_releases': True,
          'no_constraint_relaxation_on_failure': True}


def _voice_music(voice):
    # 歌词自动加载与伴随声部音区保护：新增剥离已单独严格重放的两层凭证；其余全部词音和拍轴字段完整比较。
    value = deepcopy(voice)
    value.pop('first_source_meter_correction', None)
    value.pop('first_source_word_correction', None)
    return fingerprint(value)


def reference_project(reference, shared, voice):
    # 歌词自动加载与伴随声部音区保护：新增认可工程及其实际编配来源双重SHA检查，不能拿不相关音乐或自填音区当保护依据。
    from source_meter_entry import require_calibrated_source
    if sha256(reference['path']) != reference['sha256']:
        raise ValueError('既有伴随声部来源工程已经改变')
    approved = read_json(reference['path'])
    binding = shared['input_binding']
    require_calibrated_source(approved['accepted_vocal_project'], binding)
    require_calibrated_source(voice, binding)
    old_shared = approved['shared_analysis']
    if (old_shared['input_binding'] != binding or _voice_music(approved['accepted_vocal_project']) != _voice_music(voice)
            or any(old_shared[k] != shared[k] for k in ('harmony', 'harmony_windows'))):
        raise ValueError('既有伴随声部的原声、完整词音、拍轴或和弦不一致')
    origin = approved.get('vocal_pattern_source')
    if origin is None or sha256(origin['project']) != origin['project_sha256']:
        raise ValueError('既有伴随声部没有可核验的实际初次编配来源')
    stage = read_json(origin['project'])
    if (_voice_music(stage['accepted_vocal_project']) != _voice_music(voice)
            or any(stage['shared_analysis'][k] != shared[k] for k in ('harmony', 'harmony_windows'))):
        raise ValueError('既有初次编配阶段与实际音乐不同')
    # 歌词自动加载与伴随声部音区保护：修改读取真正同阶段的器乐重提取之前快照；重提取后的编号可能复用，不能把另一阶段配音硬锁到初次临时旋律上。
    # return stage
    backbone = stage['arrangements']['guitar'].get('instrumental_source_backbone')
    if backbone is not None:
        if sha256(backbone['upstream_project']) != backbone['upstream_sha256']:
            raise ValueError('既有初次伴随声部的上游快照已经改变')
        upstream = read_json(backbone['upstream_project'])
        if (_voice_music(upstream['accepted_vocal_project']) != _voice_music(voice)
                or upstream['shared_analysis']['input_binding'] != binding
                or any(upstream['shared_analysis'][k] != shared[k] for k in ('harmony', 'harmony_windows'))):
            raise ValueError('既有初次伴随声部上游与实际音乐不同')
        return upstream
    return stage


def make_protection(reference, shared, voice, guitar):
    # 歌词自动加载与伴随声部音区保护：新增只锁定同身份、同完整时间、同音级的伴随音；弦位仍由完整持续音求解器规划。
    stage = reference_project(reference, shared, voice)
    prior = {n['id']: n for n in stage['arrangements']['guitar']['notes']}
    locks = {}
    for note in guitar['notes']:
        old = prior.get(note['id'])
        if (note.get('section') not in ('intro', 'interlude', 'outro') or note.get('role') not in ('bass', 'harmony')
                or old is None or any(note.get(k) != old.get(k) for k in ('start_tick', 'end_tick', 'role', 'section'))
                or note['pitch_midi'] % 12 != old['pitch_midi'] % 12):
            continue
        locks[note['id']] = old['pitch_midi']
    return {'policy': deepcopy(POLICY), 'reference': deepcopy(reference),
            'input_notes_sha256': fingerprint(guitar['notes']), 'pitch_locks': locks,
            'all_other_voices_and_phrase_octaves_still_planned': True}


def active_constraints(shared, voice, guitar):
    # 歌词自动加载与伴随声部音区保护：新增约束只作用于原始初次快照；后续真实重提取有独立来源，不把旧编号误贴到新音上。
    protection = guitar.get('initial_companion_register_protection')
    if protection is None:
        return {}
    if protection.get('policy') != POLICY:
        raise ValueError('伴随声部音区保护策略不同')
    if fingerprint(guitar['notes']) != protection['input_notes_sha256']:
        return {}
    expected = make_protection(protection['reference'], shared, voice, guitar)
    if expected != protection:
        raise ValueError('伴随声部音区约束不能由原工程复核')
    return protection['pitch_locks']
