"""保音持续按弦与整句八度衔接：初次吉他先建立原音高请求，再统一规划整句及完整声部。"""
from copy import deepcopy


# 保音持续按弦与整句八度衔接：新增通用初始配音入口，避免高音在旧逐音0／±12初始化处提前失败。
# 歌词自动加载与伴随声部音区保护：修改允许明确来源的既有伴随音区，仍执行原整句旋律／全部持续按弦规划。
# def arrange_phrase_guitar(shared, vocal, capo=None):
def arrange_phrase_guitar(shared, vocal, capo=None, companion_reference=None):
    from accompaniment_arrange import TUNING, arrange_guitar, harmony_at
    from guitar_capo import apply_capo, capo_at
    from guitar_instrumental_register import prepare_instrumental_register, fingerprint
    scaffold = deepcopy(shared)
    scaffold['instrumental_melody'] = []
    guitar = arrange_guitar(scaffold, vocal, capo)
    apply_capo(shared, vocal, guitar)
    guitar['configuration'].update(source_register_input_version=2,
                                    instrumental_register_strategy_version=2,
                                    instrumental_register_voicing_version=2)
    # 尾段原声局部补证：新增首次v2同步转调后，实际变调夹接管原按弦时正确释放手指；旧来源重放不启用。
    if vocal.get('first_source_meter_correction',{}).get('version')==2:
        guitar['configuration']['capo_covered_hold_transition_version']=1
    requests = []
    for index, source in enumerate(shared.get('instrumental_melody', [])):
        begin = source['start_tick']
        # 保音持续按弦与整句八度衔接：修改避免默认参数提前读取缺少的duration；显式结束与时长均可作为来源。
        # end = source.get('end_tick', begin + source['duration_ticks'])
        end = source['end_tick'] if 'end_tick' in source else begin + source['duration_ticks']
        pitch = source['pitch_midi']
        capo_fret = capo_at(guitar, begin)
        chord = harmony_at(shared, begin)
        requests.append({'id': f'guitar_source_request_{index + 1:05d}',
                         'source_melody_id': source['id'], 'pitch_midi': pitch,
                         'source_request_pitch_midi': pitch,
                         # 两曲来源补证与首次生成：新增保留来源音区与段身份；此前转请求时丢失，导致自然音区交接未进入通用分句。
                         'source_backbone_pitch_midi':source.get('source_backbone_pitch_midi',pitch),
                         'source_backbone_section_id':source.get('section_id'),
                         'start_tick': begin, 'end_tick': end,
                         'string': 1, 'fret': pitch - TUNING[1] - capo_fret,
                         'finger': 1, 'hand_position': 1, 'velocity': 92,
                         'role': 'instrumental_melody', 'section': source['section'],
                         'source': source.get('source', 'source_instrumental_melody'),
                         'source_attack_seconds': source.get('source_start_seconds', source.get('start_seconds')),
                         'chord_id': chord['id']})
    guitar['notes'] = sorted(guitar['notes'] + requests, key=lambda note: (note['start_tick'], note['id']))
    # 歌词自动加载与伴随声部音区保护：新增只在显式的同源分析清单里有认可参考时保护伴随音区，不读取歌名或固定位置。
    if companion_reference is not None:
        from guitar_companion_register import make_protection
        guitar['initial_companion_register_protection'] = make_protection(companion_reference, shared, vocal, guitar)
    raw_fingerprint = fingerprint(guitar['notes'])
    guitar = prepare_instrumental_register(shared, vocal, guitar)
    guitar['configuration']['maximum_fret'] = 12
    guitar['initial_phrase_register_preparation'] = {
        'version': 2, 'source_notes_sha256': raw_fingerprint,
        'result_notes_sha256': fingerprint(guitar['notes']),
        'all_source_melody_requests_retained': True, 'individual_note_octave_folding': False}
    return guitar
