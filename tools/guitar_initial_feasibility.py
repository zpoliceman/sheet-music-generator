"""Coordinate freshly generated harmony prototypes with actual instrumental requests."""
from copy import deepcopy

def register_conflict(error):
    return isinstance(error,ValueError) and str(error).startswith((
        '器乐十二品内未找到可行路径',
        '保留全部器乐声部和持续音的低把位规划未找到可行路径'))

def reconcile_unisons(shared, arrangement):
    """Only resolve impossible events, keeping all source requests and bass notes.

    A generated harmony which doubles an already sounding source melody is
    optional prototype material, not an accepted or independently observed note.
    The acoustic requests, source times, bass and hand limits remain unchanged.
    """
    from guitar_instrumental_register import editable_notes, fingerprint
    from guitar_register_search import source_octave_candidates
    from guitar_capo import capo_at
    from instrumental_phrase_register import event_possible
    result=deepcopy(arrangement);notes=result['notes'];original={n['id']:deepcopy(n) for n in notes}
    editable=editable_notes(shared,result);shifts=source_octave_candidates(result)
    voicing=result['configuration'].get('instrumental_register_voicing_version',1)
    source={n['id'] for n in notes if n.get('source_request_pitch_midi') is not None}
    locked=set(result.get('initial_companion_register_protection',{}).get('pitch_locks',{})) & set(original)
    changes=[];affected_onsets=set()
    def possible(active,tick):
        return any(event_possible(active,original,editable,capo_at(result,tick),shift,12,voicing) for shift in shifts)
    ticks=sorted({t for n in notes for t in (n['start_tick'],n['end_tick'])})
    for tick in ticks:
        active=[n for n in notes if n['start_tick']<=tick<n['end_tick']]
        leads=[n for n in active if n['id'] in source]
        if not leads or possible(active,tick):continue
        redundant=[n for n in active if n['role']=='harmony' and n['id'] in editable and n['id'] not in source and n['id'] not in locked
                   and any(n['pitch_midi']==lead['pitch_midi'] for lead in leads)]
        for note in sorted(redundant,key=lambda n:(-n['start_tick'],n['id'])):
            before=deepcopy(note);covered=[lead['id'] for lead in leads if lead['pitch_midi']==note['pitch_midi']]
            if tick-note['start_tick']>=120:
                note['end_tick']=tick;action='release_generated_unison_at_source_takeover'
            else:
                notes.remove(note);action='omit_redundant_generated_unison'
            affected_onsets.add(before['start_tick'])
            changes.append({'prototype_note':before,'action':action,'tick':tick,'source_melody_note_ids':covered,
                            'reason':'simultaneous_source_and_generated_unison_has_no_legal_fingering'})
            active=[n for n in notes if n['start_tick']<=tick<n['end_tick']]
            if possible(active,tick):break
    attacks={n['start_tick'] for n in notes}
    result['attack_events']=[event for event in result.get('attack_events',[]) if event['start_tick'] not in affected_onsets or event['start_tick'] in attacks]
    for identity in source | locked:
        new=next(n for n in notes if n['id']==identity)
        if any(new.get(k)!=original[identity].get(k) for k in ('id','pitch_midi','start_tick','end_tick','source_request_pitch_midi')):
            raise ValueError('原型协调意外改变原声旋律请求，拒绝继续。')
    report={'version':1,'scope':'new_prototype_harmony_only_after_infeasible_event',
            'changes':changes,'source_notes_sha256':fingerprint(list(original.values())),
            'result_notes_sha256':fingerprint(notes),'all_source_requests_and_bass_preserved':True,'protected_companion_notes_preserved':True,
            'minimum_generated_duration_ticks':120,'musical_accuracy_verified':False}
    return result,report
