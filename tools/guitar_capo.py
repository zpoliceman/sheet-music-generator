"""结构稳定伴奏与人声合播：持续转调的夹位计划及实际音高保护。"""
# 结构稳定伴奏与人声合播：新增统一夹位查询，兼容只有固定夹位的旧工程。
from copy import deepcopy
from itertools import product
import math
from accompaniment_analysis import SongClock, MAJOR_SCALE


def capo_at(arrangement, tick):
    config = arrangement.get('configuration', arrangement)
    value = int(config.get('capo_fret', 0))
    for segment in config.get('capo_segments', []):
        if segment['start_tick'] <= tick: value = int(segment['capo_fret'])
        else: break
    return value


# 结构稳定伴奏与人声合播：新增持续按音的相对品数换算，不改变实际发声。
def fret_at(note, arrangement, tick):
    return note['fret'] + capo_at(arrangement, note['start_tick']) - capo_at(arrangement, tick)


# 结构稳定伴奏与人声合播：新增旋律/和声共同支持核查，时长只用于选择是否换夹。
def modulation_support(shared, vocal, segment, end):
    begin = segment.get('start_tick', 0); key = segment['key']
    scale = {(key['tonic_pc'] + p) % 12 for p in MAJOR_SCALE}
    voice = [n for n in vocal.get('quantized_notes', []) if begin <= n.get('start_tick', -1) < end
             and n.get('role') == 'main' and not n.get('grace')]
    duration = sum(max(1, n['end_tick'] - n['start_tick']) for n in voice)
    voice_fit = sum(max(1, n['end_tick'] - n['start_tick']) for n in voice
                    if n['pitch_midi'] % 12 in scale) / max(1, duration)
    chords = [h for h in shared['harmony'] if h['start_tick'] < end and h['end_tick'] > begin and h['name'] != 'N.C.']
    harmony_duration = sum(min(end, h['end_tick']) - max(begin, h['start_tick']) for h in chords)
    harmony_fit = sum((min(end, h['end_tick']) - max(begin, h['start_tick'])) *
                      (float(h['root_pc'] in scale) + float(h['bass_pc'] in scale)) / 2 for h in chords) / max(1, harmony_duration)
    accepted = bool(segment.get('evidence', {}).get('accepted_change'))
    repeated = bool(segment.get('evidence', {}).get('melody_repeat_evidence', {}).get('accepted'))
    return {'supported': bool(voice and voice_fit >= .80 and harmony_fit >= .72 and (accepted or repeated)),
            'vocal_main_notes': len(voice), 'vocal_scale_fit': voice_fit,
            'harmony_root_and_bass_fit': harmony_fit, 'accepted_source_change': accepted,
            'repeat_melody_supported': repeated, 'confidence_is_accuracy': False}


# 结构稳定伴奏与人声合播：新增至少8小节的计划；滑动夹的操作耗时不作为门槛。
def plan_capo(shared, vocal, initial, minimum_measures=8):
    bar = shared['statistics']['bar_ticks']; total = shared['statistics']['total_ticks']; clock = SongClock(vocal)
    keys = vocal['notation'].get('key_segments', []) or [{'start_tick': 0, 'key': vocal['notation']['key']}]
    base = keys[0]['key']['tonic_pc']; shape_tonic = (base - initial) % 12
    plan = [{'start_tick': 0, 'end_tick': total, 'start_measure': 1, 'capo_fret': initial,
             'key': keys[0]['key']['label'], 'reason': 'initial_capo'}]; candidates = []
    for index, segment in enumerate(keys[1:], 1):
        begin = segment['start_tick']; end = keys[index+1]['start_tick'] if index+1 < len(keys) else total
        evidence = modulation_support(shared, vocal, segment, end)
        duration_measures = (end - begin) / bar
        target = (segment['key']['tonic_pc'] - shape_tonic) % 12
        reason = 'sustained_supported_modulation' if duration_measures >= minimum_measures and evidence['supported'] else 'short_or_unconfirmed_keep_capo'
        if target > 7: reason = 'same_shape_capo_out_of_supported_range'
        row = {'start_tick': begin, 'end_tick': end, 'duration_measures': duration_measures,
               'duration_seconds': clock.seconds(end) - clock.seconds(begin),
               'proposed_capo_fret': target, 'evidence': evidence, 'decision': reason}
        candidates.append(row)
        if reason != 'sustained_supported_modulation' or target == plan[-1]['capo_fret']: continue
        plan[-1]['end_tick'] = begin
        plan.append({'start_tick': begin, 'end_tick': total, 'start_measure': begin//bar + 1,
                     'capo_fret': target, 'key': segment['key']['label'], 'reason': reason})
    return plan, {'minimum_duration_measures': minimum_measures,
                  'sliding_capo_operation_time_gate': False, 'candidates': candidates}


# 结构稳定伴奏与人声合播：新增同音弦品重算，器乐主线不移八度、不添起音、不截持续。
def apply_capo(shared, vocal, guitar):
    if guitar['configuration'].get('capo_policy', {}).get('version') == 1: return guitar
    from accompaniment_arrange import TUNING, grip_info
    old = deepcopy(guitar); initial = old['configuration']['capo_fret']
    plan, evidence = plan_capo(shared, vocal, initial)
    guitar['configuration']['capo_segments'] = plan
    guitar['configuration']['fixed_capo_entire_song'] = len(plan) == 1
    guitar['configuration']['capo_policy'] = {'version': 1, **evidence}
    changes = []
    for tick in sorted({n['start_tick'] for n in guitar['notes']}):
        group = [n for n in guitar['notes'] if n['start_tick'] == tick]; capo = capo_at(guitar, tick)
        choices = []
        for note in group:
            locations = [(s, note['pitch_midi'] - TUNING[s] - capo) for s in range(6, 0, -1)
                         if 0 <= note['pitch_midi'] - TUNING[s] - capo <= 20]
            locations.sort(key=lambda sf: (sf[0] != note['string'], abs(sf[1] - max(0, note['fret']+initial-capo))))
            if not locations: raise ValueError('新夹位无法保留实际音高：' + note['id'])
            choices.append(locations)
        held = [n for n in guitar['notes'] if n['start_tick'] < tick < n['end_tick']]
        best = None
        for values in product(*choices):
            strings = {s for s, f in values}
            if len(strings) != len(values) or strings & {n['string'] for n in held}: continue
            effective = {n['string']: fret_at(n, guitar, tick) for n in held}
            effective.update(values)
            if any(f < 0 for f in effective.values()) or grip_info(effective) is None: continue
            cost = sum(6 * (s != n['string']) + abs(f-max(0,n['fret']+initial-capo)) for n,(s,f) in zip(group,values))
            if best is None or cost < best[0]: best = (cost, values)
        if best is None: raise ValueError('新夹位下同音持续覆盖不可行：' + str(tick))
        for note, (string, fret) in zip(group, best[1]):
            before = [note['string'], note['fret']]
            note['string'], note['fret'] = string, fret
            if before != [string, fret]: changes.append({'note_id': note['id'], 'from_string_fret': before,
                                                        'to_string_fret': [string, fret], 'capo_fret': capo})
    for segment in plan[1:]:
        for note in guitar['notes']:
            if note['start_tick'] < segment['start_tick'] < note['end_tick'] and fret_at(note,guitar,segment['start_tick']) < 0:
                raise ValueError('换夹会改变正在发声的空弦，需另行编配：'+note['id'])
    for key in ('fingering_diagrams', 'notation_regions', 'grip_hand_positions', 'grip_fingerings'):
        guitar.pop(key, None)
    guitar['fingering_diagrams'] = []
    guitar['capo_refingering'] = {'source_notes': old['notes'], 'changes': changes,
                                'pitches_onsets_releases_velocities_preserved': True}
    return guitar


# 结构稳定伴奏与人声合播：新增独立弦品/计划核查，不能只信任capo元数据。
def validate_capo(guitar, vocal, xml_root=None):
    config = guitar['configuration']; segments = config.get('capo_segments')
    if not segments: return None
    from accompaniment_arrange import TUNING
    errors = []; total = vocal['statistics']['total_ticks']; bar = vocal['statistics']['bar_ticks']
    if segments[0]['start_tick'] != 0 or segments[-1]['end_tick'] != total: errors.append('capo_plan_incomplete')
    for a,b in zip(segments,segments[1:]):
        if a['end_tick'] != b['start_tick'] or a['start_tick'] >= b['start_tick']: errors.append('capo_plan_gap_or_overlap')
    for segment in segments:
        if not 0 <= segment['capo_fret'] <= 7 or segment['start_tick'] % bar: errors.append('capo_range_or_boundary_invalid')
    for n in guitar['notes']:
        if TUNING[n['string']] + capo_at(guitar,n['start_tick']) + n['fret'] != n['pitch_midi']:
            errors.append('capo_tab_sound_mismatch:'+n['id'])
        for s in segments[1:]:
            if n['start_tick'] < s['start_tick'] < n['end_tick'] and fret_at(n,guitar,s['start_tick']) < 0:
                errors.append('held_open_note_changed_by_capo:'+n['id'])
    if xml_root is not None:
        observed = []
        for measure in xml_root.findall('./part/measure'):
            node = measure.find('./attributes/staff-details/capo')
            if node is not None: observed.append(((int(measure.get('number'))-1)*bar,int(node.text)))
        if observed != [(s['start_tick'],s['capo_fret']) for s in segments]: errors.append('musicxml_capo_plan_mismatch')
        # 结构稳定伴奏与人声合播：新增逐碎片回读技术弦品，续音也须与当时夹位的实音一致。
        from score_export import PITCH_CLASS
        xml_capo = config.get('capo_fret',0)
        checked_fragments = 0
        for measure in xml_root.findall('./part/measure'):
            node = measure.find('./attributes/staff-details/capo')
            if node is not None: xml_capo = int(node.text)
            for note in measure.findall('note'):
                if note.find('pitch') is None: continue
                string = note.findtext('notations/technical/string')
                fret = note.findtext('notations/technical/fret')
                if string is None or fret is None:
                    errors.append('musicxml_missing_technical_position:'+str(note.get('id'))); continue
                midi = PITCH_CLASS[note.findtext('pitch/step')] + int(note.findtext('pitch/alter','0')) + 12*(int(note.findtext('pitch/octave'))+1)
                if int(string) not in TUNING or int(fret)<0 or TUNING[int(string)]+xml_capo+int(fret)!=midi:
                    errors.append('musicxml_capo_actual_sound_mismatch:'+str(note.get('id')))
                checked_fragments += 1
    return {'valid':not errors,'errors':errors,'segments':segments,
            'actual_pitch_checked_notes':len(guitar['notes'])}
