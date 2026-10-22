"""保音持续按弦与整句八度衔接：初次吉他先建立原音高请求，再统一规划整句及完整声部。"""
from copy import deepcopy


# 保音持续按弦与整句八度衔接：新增通用初始配音入口，避免高音在旧逐音0／±12初始化处提前失败。
# 歌词自动加载与伴随声部音区保护：修改允许明确来源的既有伴随音区，仍执行原整句旋律／全部持续按弦规划。
# def arrange_phrase_guitar(shared, vocal, capo=None):
def _arrange_phrase_guitar(shared, vocal, capo=None, companion_reference=None, provisional_vocal=False, fixed_capo=False, reconcile=False):
    from accompaniment_arrange import TUNING, arrange_guitar, harmony_at
    from guitar_capo import apply_capo, capo_at
    from guitar_instrumental_register import prepare_instrumental_register, fingerprint
    scaffold = deepcopy(shared)
    scaffold['instrumental_melody'] = []
    guitar = arrange_guitar(scaffold, vocal, capo)
    if fixed_capo:
        initial=guitar['configuration']['capo_fret']
        guitar['configuration'].update(capo_segments=[{'start_tick':0,'end_tick':vocal['statistics']['total_ticks'],
            'start_measure':1,'capo_fret':initial,'key':vocal['notation']['key']['label'],
            'reason':'complete_instrumental_requests_require_fixed_capo'}],fixed_capo_entire_song=True,
            capo_policy={'version':1,'candidates':[],'complete_source_register_fallback':True})
    else:
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
    if provisional_vocal:
        # 新生成的唱段只是原型，随后由共同和声和稳定右手重新编配；
        # 此处先规划器乐原音请求，不把尚未采用的唱段指型当成认可边界。
        from guitar_instrumental_register import editable_notes
        identities = editable_notes(shared, guitar)
        subset = deepcopy(guitar)
        subset['notes'] = [n for n in subset['notes'] if n['id'] in identities]
        if reconcile:
            from guitar_initial_feasibility import reconcile_unisons
            subset,reconciliation=reconcile_unisons(shared,subset)
            after={n['id']:n for n in subset['notes']}
            guitar['notes']=[deepcopy(after.get(n['id'],n)) for n in guitar['notes'] if n['id'] not in identities or n['id'] in after]
            attacks={n['start_tick'] for n in guitar['notes']}
            guitar['attack_events']=[event for event in guitar.get('attack_events',[]) if event['start_tick'] in attacks]
            guitar['initial_prototype_reconciliation']=reconciliation
            raw_fingerprint=fingerprint(guitar['notes'])
        try:
            subset = prepare_instrumental_register(shared, vocal, subset)
        except ValueError as error:
            error.initial_capo=guitar['configuration']['capo_fret']
            error.initial_capo_has_changes=len(guitar['configuration'].get('capo_segments',[]))>1
            raise
        planned = {n['id']: n for n in subset['notes']}
        guitar['notes'] = [deepcopy(planned.get(n['id'], n)) for n in guitar['notes']]
        guitar['instrumental_register_preparations'] = deepcopy(subset.get('instrumental_register_preparations', []))
        guitar['prototype_preparation_scope'] = 'instrumentals_only_vocal_prototype_not_frozen'
    else:
        guitar = prepare_instrumental_register(shared, vocal, guitar)
    by_id={n['id']:n for n in guitar['notes']}
    if any(request['id'] not in by_id or any(by_id[request['id']].get(key)!=request.get(key)
           for key in ('start_tick','end_tick','source_request_pitch_midi')) for request in requests):
        raise ValueError('初次编配丢失或改变了原声器乐请求，拒绝继续。')
    guitar['configuration']['maximum_fret'] = 12
    guitar['initial_phrase_register_preparation'] = {
        'version': 2, 'source_notes_sha256': raw_fingerprint,
        'result_notes_sha256': fingerprint(guitar['notes']),
        'all_source_melody_requests_retained': True, 'individual_note_octave_folding': False}
    return guitar


def arrange_phrase_guitar(shared, vocal, capo=None, companion_reference=None, provisional_vocal=False):
    """Keep a feasible original plan; otherwise revisit upstream automatic choices."""
    if not provisional_vocal:
        return _arrange_phrase_guitar(shared,vocal,capo,companion_reference,False)
    from guitar_initial_feasibility import register_conflict
    try:
        return _arrange_phrase_guitar(shared,vocal,capo,companion_reference,True)
    except ValueError as error:
        if not register_conflict(error):raise
        initial=getattr(error,'initial_capo',capo)
        if initial is None:raise
        first_error=error
        choices=[]
        if getattr(error,'initial_capo_has_changes',False):choices.append((initial,True,False))
        choices.append((initial,False,True))
        if capo is None:
            # Retain the same automatic initial range as choose_shapes (0--4).
            for candidate in sorted((c for c in range(5) if c!=initial),key=lambda c:(abs(c-initial),c)):
                choices.extend(((candidate,True,False),(candidate,True,True)))
        attempts=[{'initial_capo':initial,'automatic_changes':True,'reconciled':False,'reason':str(error)[:600]}]
    for candidate,fixed,reconcile in choices:
        try:
            result=_arrange_phrase_guitar(shared,vocal,candidate,companion_reference,True,fixed,reconcile)
        except ValueError as error:
            if not register_conflict(error):raise
            attempts.append({'initial_capo':candidate,'automatic_changes':not fixed,'reconciled':reconcile,'reason':str(error)[:600]})
            continue
        result['initial_joint_feasibility']={'version':1,'original_initial_capo':initial,
            'selected_initial_capo':result['configuration']['capo_fret'],
            'fixed_capo_after_source_check':fixed,'prototype_reconciliation_requested':reconcile,
            'failed_attempts':attempts,'all_source_requests_retained':True,
            'maximum_fret':12,'musical_accuracy_verified':False}
        return result
    raise ValueError('自动夹位和器乐配音在完整源音符约束下仍未找到可行路径；已保留全部原声请求，未放宽十二品上限。'+str(attempts)) from first_error
