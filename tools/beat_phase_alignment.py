"""强拍相位与伴奏同步纠错：音源绑定的拍点复核、音素起音与确定性重新量化。"""
# 强拍相位与伴奏同步纠错：新增独立时间派生层，原音频、连续音高和认可源工程只读。
from copy import deepcopy
from collections import defaultdict
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REVIEW_PATH = ROOT / 'data/metrical_reviews.json'


# 强拍相位与伴奏同步纠错：新增严格按音源、拍号、四分拍速度匹配；未知歌曲不套首句答案。
def phase_review(analysis, timing, review_path=REVIEW_PATH):
    from score_export import read_json, TempoMap
    if not Path(review_path).is_file():
        return None
    record = read_json(review_path).get('reviews', {}).get(analysis.get('source_sha256'), {})
    review = record.get('beat_phase')
    bpm = TempoMap(timing['knots']).tempo_at(timing['score_start_quarter'])
    if (not review or review.get('meter') != timing['meter']
            or not math.isclose(bpm, review['quarter_bpm'], rel_tol=.0001)):
        return None
    return deepcopy(review)


# 强拍相位与伴奏同步纠错：新增拍点秒相位与小节首拍独立校准；显式起点覆盖优先。
def apply_phase_timing(analysis, timing, review=None):
    from score_export import TempoMap
    if timing.get('beat_origin_source') == 'user_override':
        return deepcopy(timing)
    review = review or phase_review(analysis, timing)
    if review is None:
        return deepcopy(timing)
    result = deepcopy(timing)
    period = 60 / review['quarter_bpm']
    zero = review['anchor_seconds'] - review['anchor_quarter'] * period
    mapping = TempoMap([{'seconds': zero, 'quarter': 0}, {'seconds': zero + period, 'quarter': 1}])
    bar = result['meter'][0] * 4 / result['meter'][1]
    start = math.floor(mapping.seconds_to_quarters(0) / bar) * bar
    result.update(knots=mapping.knots, score_start_quarter=start,
                  score_start_seconds=mapping.quarters_to_seconds(start), beat_origin_seconds=zero,
                  beat_origin_source='source_bound_reviewed_downbeat', steady_tempo_bpm=review['quarter_bpm'],
                  bar_phase_method='user_beat_locations_and_original_bass_onset', beat_phase=deepcopy(review),
                  requires_confirmation=False)
    # 强拍相位与伴奏同步纠错：新增负秒的预备弱起单独排版，不冒充一个完整前奏小节。
    result['initial_pickup_measure'] = start < 0 < zero
    result['measure_number_offset'] = 1 if result['initial_pickup_measure'] else 0
    return result


# 强拍相位与伴奏同步纠错：新增所有谱页共用分行，弱起独立，其余始终四个正式小节一行。
def score_row_ranges(vocal, size=4):
    total=vocal['statistics']['measure_count'];pickup=bool(vocal.get('timing',{}).get('initial_pickup_measure'))
    return ([(1,1)] if pickup else []) + [(i,min(i+size-1,total)) for i in range(2 if pickup else 1,total+1,size)]


# 强拍相位与伴奏同步纠错：新增显示编号与内部时间索引分开，弱起不计入正式小节号。
def display_measure(vocal, number):
    offset=vocal.get('timing',{}).get('measure_number_offset',0)
    return '弱起' if offset and number==1 else str(number-offset)


# 强拍相位与伴奏同步纠错：新增清理旧拍轴的先验；只调整字首，字内真实音高变化仍保留。
def nucleus_onsets(pieces, characters, mapping, timing):
    output = deepcopy(pieces); groups = defaultdict(list); audit = []
    for note in output:
        note.pop('notation_onset_prior', None)
        if note.get('lyric_index') is not None and not note.get('grace'):
            groups[note['lyric_index']].append(note)
    lookup = {c['index']: c for c in characters}
    period = 60 / timing['steady_tempo_bpm']; origin = timing['score_start_quarter']
    for index, group in groups.items():
        char = lookup.get(index, {})
        phonemes = [p for p in char.get('phonemes', []) if not p.get('skipped') and p.get('start_seconds') is not None]
        nuclei = [p for p in phonemes if p.get('role') == 'nucleus']
        # 强拍相位与伴奏同步纠错：新增有声声母保护；声学起音已可靠的字不因元音更晚而整体搬走。
        if not nuclei or not any(p.get('role') == 'initial' for p in phonemes):
            continue
        first = min(group, key=lambda n: n['start_seconds']); nucleus = min(p['start_seconds'] for p in nuclei)
        q = mapping.seconds_to_quarters(nucleus) - origin
        half, quarter = round(q * 2) / 2, round(q * 4) / 4
        target = half if abs(q-half) <= .16 else quarter if abs(q-quarter) <= .09 else round(q*8)/8
        seconds = mapping.quarters_to_seconds(target + origin)
        # 强拍相位与伴奏同步纠错：新增最大位移与独立前导平台门槛，保留真正弱起/切分和字内音序。
        stable_lead = first.get('stable_duration_seconds', 0) >= .10 and (first.get('independent_pitch_support') or 0) >= .70
        # 强拍相位与伴奏同步纠错：修改，原0.35拍门槛保留；避免把四分之一拍弱起吸到下一小节首拍。
        # if (abs(seconds-first['start_seconds']) > .35 * period
        if (abs(seconds-first['start_seconds']) > .25 * period
                or seconds < min(first['start_seconds'], char.get('start_seconds', first['start_seconds'])) - .04
                or seconds > nucleus + .17 * period
                or seconds > first['end_seconds'] + .04
                or (stable_lead and len(group) > 1 and first['pitch_midi'] != group[1]['pitch_midi'])):
            continue
        prior = {'quarter': target, 'kind': 'phoneme_nucleus_grid', 'source_start_seconds': first['start_seconds'],
                 'notation_start_seconds': seconds, 'nucleus_start_seconds': nucleus,
                 'timing_review_id': timing.get('beat_phase', {}).get('review_id'),
                 'method': 'unvoiced_initial_then_nucleus_near_subdivision', 'confidence_is_accuracy': False}
        first['notation_onset_prior'] = prior
        audit.append({'character_index': index, 'piece_id': first['id'], **prior})
    return output, audit


# 强拍相位与伴奏同步纠错：新增从认可原音段重新量化，而不是移动旧音符或重复缩放旧节奏。
def derive_phase_vocal(original, correction):
    from score_export import TempoMap, attach_lyrics, tempo_events
    from accompaniment_rebar import derive_vocal
    from musical_decode import musical_quantize
    base = derive_vocal(original, correction['base_grid_correction']) if correction.get('base_grid_correction') else deepcopy(original)
    review = phase_review(base['audio_analysis'], base['timing'])
    if not review or review != correction['review']:
        raise ValueError('强拍复核记录与音源不匹配。')
    vocal = deepcopy(base); vocal['timing'] = apply_phase_timing(base['audio_analysis'], base['timing'], review)
    mapping = TempoMap(vocal['timing']['knots'])
    # 强拍相位与伴奏同步纠错：新增用户首句文字复核只写派生谱，原TXT和音素所有者索引不变。
    for change in review.get('lyric_text_corrections', []):
        char = next(c for c in vocal['lyrics']['characters'] if c['index'] == change['index'])
        if char['text'] != change['old']:
            raise ValueError('歌词复核原字不匹配。')
        char['text'] = change['new']; char['text_correction'] = deepcopy(change)
    # 乐句节奏与音值分组：修改，原绝对元音先验调用注释保留；历史派生复现与新版策略严格区分。
    # pieces, audit = nucleus_onsets(base['quantized_notes'], vocal['lyrics']['characters'], mapping, vocal['timing'])
    # events, notes, stats = musical_quantize(pieces, mapping, vocal['timing'], vocal['audio_analysis']['duration_seconds'])
    if correction.get('phrase_rhythm'):
        from phrase_rhythm import VERSION, POLICY
        if correction['phrase_rhythm'] != {'version': VERSION, 'policy': POLICY}:
            raise ValueError('乐句节奏派生策略不匹配，拒绝任意改写认可人声。')
        pieces = deepcopy(base['quantized_notes']); audit = []
        events, notes, stats = musical_quantize(pieces, mapping, vocal['timing'],
                              vocal['audio_analysis']['duration_seconds'], vocal['lyrics']['characters'])
        vocal['decoder']['phrase_rhythm'] = deepcopy(stats['phrase_rhythm'])
    else:
        pieces, audit = nucleus_onsets(base['quantized_notes'], vocal['lyrics']['characters'], mapping, vocal['timing'])
        events, notes, stats = musical_quantize(pieces, mapping, vocal['timing'], vocal['audio_analysis']['duration_seconds'])
    vocal.update(events=events, quantized_notes=notes, statistics=stats,
                 lyric_mapping=attach_lyrics(events, vocal['lyrics']['characters']),
                 beat_phase_correction=deepcopy(correction))
    vocal['tempo_events'] = tempo_events(mapping, vocal['timing'], stats['total_ticks'])
    vocal['decoder']['beat_phase_quantization'] = {'version': 1, 'source_pitches_and_piece_ids_preserved': True,
                                                 'stale_onset_priors_discarded': True, 'nucleus_onsets': audit}
    # 强拍相位与伴奏同步纠错：新增新调弱起用临时升降号，完整调号及换夹从随后完整小节开始。
    bar = stats['bar_ticks']
    for index, section in enumerate(vocal['notation'].get('key_segments', [])):
        first = next(n for n in notes if n.get('lyric_index') == section['first_character_index'])
        section['performance_start_tick'] = first['start_tick']
        section['start_tick'] = math.ceil(first['start_tick'] / bar) * bar if index else 0
        section['start_measure'] = section['start_tick'] // bar + 1
        section['pickup_before_signature'] = bool(index and first['start_tick'] < section['start_tick'])
    return vocal


# 强拍相位与伴奏同步纠错：新增用户16拍的实音核验；延音与无新歌词的拍点不强行重起音。
def validate_reviewed_beats(vocal):
    from accompaniment_analysis import SongClock
    review = vocal.get('timing', {}).get('beat_phase')
    if not review:
        return None
    clock = SongClock(vocal); origin = vocal['timing']['score_start_quarter']; rows = []; errors = []
    notes = [n for n in vocal['quantized_notes'] if not n.get('grace')]
    for anchor in review.get('vocal_beats', []):
        tick = round((anchor['quarter'] - origin) * 480)
        active = [n for n in notes if n['start_tick'] <= tick < n['end_tick']]
        new_words = [e.get('lyric', {}).get('character_index') for e in vocal['events']
                     if e['start_tick'] == tick and e.get('lyric', {}).get('text')]
        kind = anchor['kind']; index = anchor.get('character_index')
        valid = (any(n.get('lyric_index') == index for n in active) if kind in ('word', 'sustain')
                 else not active if kind == 'rest' else not new_words)
        if kind == 'word':
            valid = valid and index in new_words
        # 强拍相位与伴奏同步纠错：新增延音必须始于该拍之前；包含同一个字但从此拍新起唱仍判错。
        if kind == 'sustain':
            first = min(n['start_tick'] for n in notes if n.get('lyric_index') == index)
            valid = valid and first < tick and index not in new_words
        if kind == 'before_first_word':
            first = min(n['start_tick'] for n in notes if n.get('lyric_index') == index)
            valid = tick < first
        row = {**anchor, 'tick': tick, 'seconds': clock.seconds(tick), 'active_characters': sorted({n.get('lyric_index') for n in active if n.get('lyric_index') is not None}),
               'new_word_characters': new_words, 'valid': valid}
        rows.append(row)
        if not valid: errors.append('reviewed_vocal_beat_mismatch:' + str(anchor['quarter']))
    return {'valid': not errors, 'errors': errors, 'review_id': review['review_id'], 'beats': rows,
            'scope': 'user_first_four_bars; rest_and_sustained_words_are_distinct'}


# 强拍相位与伴奏同步纠错：新增从实际弦品、音高和起点验证，防止Bass标签正确但真正拨弦仍错拍。
def validate_beat_synchrony(shared, vocal, guitar):
    if not guitar.get('configuration',{}).get('beat_synchronous_patterns'):
        return None
    from accompaniment_arrange import TUNING, harmony_at
    from guitar_capo import capo_at
    errors=[]; starts=[]; simple=[]; ordinary=[]
    for note in guitar['notes']:
        if note.get('section')!='vocal' or note['role'] not in ('bass','harmony') or note.get('source_melody_id'): continue
        ordinary.append(note)
        if note.get('right_hand_pattern_id'):
            origin=note.get('pattern_cycle_origin_tick')
            if origin is None or origin%480: errors.append('cycle_origin_not_on_quarter:'+note['id'])
            if note.get('right_hand_slot')==0:
                chord=harmony_at(shared,note['start_tick'])
                if note['start_tick']!=origin: errors.append('cycle_first_attack_not_at_origin:'+note['id'])
                if 'B' not in note['right_hand_token'].split('+'): errors.append('cycle_starts_with_inner_string:'+note['id'])
                if note['role']=='bass':
                    actual=TUNING[note['string']]+capo_at(guitar,note['start_tick'])+note['fret']
                    if actual!=note['pitch_midi'] or actual%12!=chord['bass_pc']:errors.append('cycle_actual_bass_wrong:'+note['id'])
                    starts.append({'note_id':note['id'],'tick':note['start_tick'],'string':note['string'],
                                   'pitch_midi':actual,'chord_id':chord['id']})
        else:
            entry=note.get('beat_phase_entry_correction');chord=harmony_at(shared,note['start_tick'])
            valid=bool(entry and entry['new_start_tick']==note['start_tick']==chord['start_tick']
                       and not note['start_tick']%480 and note['pitch_midi']%12==chord['bass_pc'])
            if not valid:errors.append('ordinary_note_keeps_old_phase:'+note['id'])
            simple.append({'note_id':note['id'],'tick':note['start_tick'],'valid':valid,'reason':'bass_with_protected_instrumental_pickup'})
    # 强拍相位与伴奏同步纠错：新增真正演奏的换和弦必须起于该拍；源休止不被无意义补齐。
    for chord in shared['harmony']:
        group=[n for n in ordinary if n['chord_id']==chord['id']]
        if not group:continue
        first=min(n['start_tick'] for n in group)
        first_group=[n for n in group if n['start_tick']==first]
        if first%480 or not any(n['role']=='bass' and n['pitch_midi']%12==chord['bass_pc'] for n in first_group):
            errors.append('chord_first_played_attack_not_beat_bass:'+chord['id'])
    return {'valid':not errors,'errors':errors,'ordinary_notes':len(ordinary),
            'actual_bass_cycle_starts':starts,'instrumental_pickup_bass_entries':simple,
            'same_clock_as_vocal':True,'source_rest_gaps_preserved':True}


# 强拍相位与伴奏同步纠错：新增钢琴演唱伴奏低音入口与循环正拍，原分解高音和器乐特征攻击保留。
def align_piano_bass(shared, vocal, piano):
    from accompaniment_arrange import resolve_piano_sustain,piano_hand_positions
    from accompaniment_analysis import SongClock
    moves=[];added=[];serial=0
    for chord in shared['harmony']:
        body=[n for n in piano['notes'] if n['chord_id']==chord['id'] and n['section']=='vocal'
              and n['role'] in ('bass','harmony') and not n.get('source_melody_id')]
        if not body:continue
        target=max(chord['start_tick'],min(n['start_tick'] for n in body)//480*480)
        basses=sorted((n for n in body if n['role']=='bass'),key=lambda n:n['start_tick'])
        if not basses:
            prototype=min((n for n in piano['notes'] if n['role']=='bass'),
                          key=lambda n:abs(n['start_tick']-target))
            active=[n['pitch_midi'] for n in piano['notes'] if n['hand']=='left' and n['start_tick']<=target<n['end_tick']]
            candidates=[p for p in range(24,65) if p%12==chord['bass_pc']
                        and (not active or max(active+[p])-min(active+[p])<=12)]
            if not candidates:raise ValueError('钢琴拍点低音与左手持续音不可覆盖：'+chord['id'])
            serial+=1;note=deepcopy(prototype)
            note.update(id='piano_beat_bass_'+str(serial),chord_id=chord['id'],start_tick=target,
                        end_tick=min(target+480,chord['end_tick']),section='vocal',role='bass',hand='left',
                        pitch_midi=min(candidates,key=lambda p:abs(p-prototype['pitch_midi'])),
                        arrangement_reason='beat_aligned_chord_entry_bass')
            piano['notes'].append(note);basses=[note];added.append(note['id'])
        for index,note in enumerate(basses):
            old=note['start_tick']
            begin=target if not index else max(target,min(chord['end_tick']-480,round(old/480)*480))
            # 强拍相位与伴奏同步纠错：新增同拍左手和音的八度覆盖；单独低音移到正拍后仍须单手能弹。
            attacks=[n['pitch_midi'] for n in piano['notes'] if n['id']!=note['id'] and n['hand']=='left' and n['start_tick']==begin]
            if attacks:
                options=[p for p in range(24,85) if p%12==note['pitch_midi']%12
                         and max(attacks+[p])-min(attacks+[p])<=12 and len(set(attacks+[p]))<=5]
                if not options:raise ValueError('钢琴正拍低音与同刻左手攻击不可覆盖：'+chord['id'])
                pitch=min(options,key=lambda p:abs(p-note['pitch_midi']))
                if pitch!=note['pitch_midi']:
                    piano['adjustments'].append({'type':'beat_bass_octave_for_single_hand','note_id':note['id'],
                                                  'old_pitch_midi':note['pitch_midi'],'new_pitch_midi':pitch})
                    note['pitch_midi']=pitch
            if begin!=old:
                moves.append({'note_id':note['id'],'old_start_tick':old,'new_start_tick':begin})
                note['start_tick']=begin;note['end_tick']=max(begin+120,note['end_tick'])
    # 强拍相位与伴奏同步纠错：新增同键同刻去重和自然重拨结束，避免两低音吸附到同拍后重叠。
    unique={}
    for note in sorted(piano['notes'],key=lambda n:n['start_tick']):
        key=(note['start_tick'],note['pitch_midi'],note['hand'])
        # 强拍相位与伴奏同步纠错：修改，原只合并时长保留；同键同拍的真实低音身份也要保留。
        # if key in unique:unique[key]['end_tick']=max(unique[key]['end_tick'],note['end_tick'])
        if key in unique:
            unique[key]['end_tick']=max(unique[key]['end_tick'],note['end_tick'])
            if note['role']=='bass':unique[key]['role']='bass'
        else:unique[key]=note
    piano['notes']=resolve_piano_sustain(list(unique.values()),piano['adjustments'])
    piano['hand_positions']=piano_hand_positions(piano['notes'],SongClock(vocal))
    piano['beat_bass_alignment']={'version':1,'moves':moves,'added_note_ids':added,
                                  'right_hand_source_attack_times_preserved':True}
    return piano


# 强拍相位与伴奏同步纠错：新增钢琴真正换和弦起音和柱式拍点检查，不能只检查吉他。
def validate_piano_beats(shared,piano):
    if not piano.get('beat_bass_alignment'):return None
    errors=[];checked=[]
    for chord in shared['harmony']:
        body=[n for n in piano['notes'] if n['chord_id']==chord['id'] and n['section']=='vocal'
              and n['role'] in ('bass','harmony') and not n.get('source_melody_id')]
        if not body:continue
        tick=min(n['start_tick'] for n in body)
        valid=not tick%480 and any(n['start_tick']==tick and n['role']=='bass' and n['pitch_midi']%12==chord['bass_pc'] for n in body)
        checked.append({'chord_id':chord['id'],'tick':tick,'valid':valid})
        if not valid:errors.append('piano_chord_entry_not_beat_bass:'+chord['id'])
    for event in piano['attack_events']:
        if event['kind'] in ('block','chord','strum') and event['start_tick']%480:
            errors.append('piano_block_chord_off_quarter:'+str(event['start_tick']))
    return {'valid':not errors,'errors':errors,'chord_entries':checked}


# 强拍相位与伴奏同步纠错：新增独立的人声简谱/XML/MIDI交付，旧认可工程保持只读。
def export_phase_vocal(output,vocal):
    import html
    import xml.etree.ElementTree as ET
    from score_export import build_musicxml,validate_score,write_midi,save_json
    from accompaniment_export import vocal_row,html_page
    folder=Path(output)/'vocal';folder.mkdir(parents=True,exist_ok=True)
    root=build_musicxml(vocal);check=validate_score(vocal,root)
    # 乐句节奏与音值分组：新增正式导出前的拍内音符/休止和倚音百分比检查。
    if vocal['statistics'].get('phrase_rhythm'):
        from rhythm_notation import validate_grouping
        from musical_decode import validate_grace_allocation
        check['rhythm_grouping']=validate_grouping(vocal['events'],vocal['timing']['meter'],vocal['timing'].get('beat_groups'))
        check['grace_allocation']=validate_grace_allocation(root,vocal)
        if not check['rhythm_grouping']['valid']:raise ValueError(str(check['rhythm_grouping']['errors']))
    if not check['valid']:raise ValueError('节拍校正人声XML不完整：'+str(check['errors']))
    for measure in root.findall('part/measure'):
        number=int(measure.get('number'));measure.set('text',display_measure(vocal,number))
        if vocal['timing'].get('initial_pickup_measure') and number==1:measure.set('implicit','yes')
    ET.indent(root,space='  ');ET.ElementTree(root).write(folder/'vocal.musicxml',encoding='utf-8',xml_declaration=True)
    write_midi(folder/'vocal.mid',vocal);save_json(folder/'project.json',vocal);save_json(folder/'validation.json',check)
    # 强拍相位与伴奏同步纠错：修改，原样曲固定谱头保留；将来复核其它音源时采用其实际拍号/速度。
    # body='<h1>'+html.escape(vocal['title'])+' · 人声节拍校正版</h1><p>4/4 · ♩=58.5。弱起预备不计正式小节；正文每行四小节。</p><nav><a href="../guitar/score.html">吉他谱与原歌手合播</a><a href="../piano/score.html">钢琴谱与合播</a><a href="vocal.musicxml" download>人声MusicXML</a><a href="vocal.mid" download>人声旋律MIDI</a></nav>'
    from metrical_timing import selected_quarter_tempo
    meter=vocal['timing']['meter'];bpm=selected_quarter_tempo(vocal)
    # 局部拍轴与原唱同步纠错：修改，保留旧谱头；独立人声和伴奏共同显示局部拍轴的起始速度。
    # body='<h1>'+html.escape(vocal['title'])+f' · 人声节拍校正版</h1><p>{meter[0]}/{meter[1]} · ♩={bpm:g}。弱起预备不计正式小节；正文每行四小节。</p><nav><a href="../guitar/score.html">吉他谱与原歌手合播</a><a href="../piano/score.html">钢琴谱与合播</a><a href="vocal.musicxml" download>人声MusicXML</a><a href="vocal.mid" download>人声旋律MIDI</a></nav>'
    if vocal['timing'].get('local_beat_clock',{}).get('status')=='tracked':
        from accompaniment_analysis import SongClock
        clock=SongClock(vocal);tempo_caption=f'起始 ♩={clock.mapping.tempo_at(clock.origin):.1f}（速度随原曲变化）'
    else:
        tempo_caption=f'♩={bpm:g}'
    # 渴首次吉他编配：修改，独立人声页不链接未生成的钢琴谱；原代码注释保留。
    # body='<h1>'+html.escape(vocal['title'])+f' · 人声节拍校正版</h1><p>{meter[0]}/{meter[1]} · {tempo_caption}。弱起预备不计正式小节；正文每行四小节。</p><nav><a href="../guitar/score.html">吉他谱与原歌手合播</a><a href="../piano/score.html">钢琴谱与合播</a><a href="vocal.musicxml" download>人声MusicXML</a><a href="vocal.mid" download>人声旋律MIDI</a></nav>'
    # 渴首次吉他编配：新增按所选乐器执行，保留各乐器原验证。
    piano_link='<a href="../piano/score.html">钢琴谱与合播</a>' if (Path(output)/'piano/score.html').is_file() else ''
    # 原曲拍轴与歌词拍位通用修复：修改，旧无条件弱起文案保留；首小节完整时按真实小节编号说明。
    # body='<h1>'+html.escape(vocal['title'])+f' · 人声节拍校正版</h1><p>{meter[0]}/{meter[1]} · {tempo_caption}。弱起预备不计正式小节；正文每行四小节。</p><nav><a href="../guitar/score.html">吉他谱与原歌手合播</a>'+piano_link+'<a href="vocal.musicxml" download>人声MusicXML</a><a href="vocal.mid" download>人声旋律MIDI</a></nav>'
    pickup_caption='弱起预备不计正式小节；' if vocal['timing'].get('initial_pickup_measure') else ''
    body='<h1>'+html.escape(vocal['title'])+f' · 人声节拍校正版</h1><p>{meter[0]}/{meter[1]} · {tempo_caption}。{pickup_caption}正文每行四小节。</p><nav><a href="../guitar/score.html">吉他谱与原歌手合播</a>'+piano_link+'<a href="vocal.musicxml" download>人声MusicXML</a><a href="vocal.mid" download>人声旋律MIDI</a></nav>'
    for first,last in score_row_ranges(vocal):
        svg=vocal_row(vocal,first,last).svg();name=f'measures_{first:03}_{last:03}.svg'
        (folder/name).write_text(svg,encoding='utf-8')
        # 原曲拍轴与歌词拍位通用修复：修改，旧单行首小节必作弱起保留；按实际弱起标记显示。
        # label='弱起预备' if first==last==1 else '第'+display_measure(vocal,first)+'–'+display_measure(vocal,last)+'小节'
        label='弱起预备' if first==last==1 and vocal['timing'].get('initial_pickup_measure') else '第'+display_measure(vocal,first)+'–'+display_measure(vocal,last)+'小节'
        body+='<section class="score-row"><header>'+label+'</header>'+svg+'</section>'
    (folder/'score.html').write_text(html_page(vocal['title']+' · 人声节拍校正',body),encoding='utf-8')
    # 强拍相位与伴奏同步纠错：新增交付入口的校正状态与独立谱链接，避免沿用旧版人声的误导文案。
    index=Path(output)/'index.html';text=index.read_text(encoding='utf-8')
    text=text.replace('人声简谱沿用已认可成果。','人声简谱按原音段和已复核拍点重新量化。')
    # 原曲拍轴与歌词拍位通用修复：修改，旧重复插入入口保留；再次导出独立谱时入口保持幂等。
    # text=text.replace('</h1>','</h1><p><a href="vocal/score.html">人声节拍校正版（独立简谱 / MusicXML / MIDI）</a></p>',1)
    if 'href="vocal/score.html"' not in text:
        text=text.replace('</h1>','</h1><p><a href="vocal/score.html">人声节拍校正版（独立简谱 / MusicXML / MIDI）</a></p>',1)
    internal=vocal['statistics']['measure_count'];formal=internal-vocal['timing'].get('measure_number_offset',0)
    # 原曲拍轴与歌词拍位通用修复：修改，旧无条件入口标弱起保留；没有弱起时保持真实全曲小节说明。
    # text=text.replace('<b>'+str(internal)+'</b>全曲小节','<b>'+str(formal)+'</b>正式小节 + 弱起预备')
    if vocal['timing'].get('initial_pickup_measure'):
        text=text.replace('<b>'+str(internal)+'</b>全曲小节','<b>'+str(formal)+'</b>正式小节 + 弱起预备')
    else:
        # 原曲拍轴与歌词拍位通用修复：新增旧导出误标弱起的幂等恢复，音乐及实际小节数不改写。
        text=text.replace('<b>'+str(formal)+'</b>正式小节 + 弱起预备','<b>'+str(internal)+'</b>全曲小节')
    index.write_text(text,encoding='utf-8')
    return check


# 强拍相位与伴奏同步纠错：新增已有器乐音秒时间迁移；正确段落边界上的普通吉他音只作为可弹种子。
# 局部拍轴与原唱同步纠错：修改，保留原签名；新版用共同时间分类旧种子与新伴奏，旧派生行为保持。
# def seed_existing_music(old_shared, old_vocal, old_arrangements, shared, vocal, fresh):
def seed_existing_music(old_shared, old_vocal, old_arrangements, shared, vocal, fresh, source_time_sections=False):
    from accompaniment_analysis import SongClock, section_at
    from accompaniment_arrange import harmony_at, TUNING, piano_hand_positions, resolve_piano_sustain
    from guitar_capo import capo_at
    old_clock, clock = SongClock(old_vocal), SongClock(vocal)
    def tick(value):
        # 强拍相位与伴奏同步纠错：新增原细网格迁移，不产生导出不支持的任意一tick碎片。
        return max(0, round(clock.tick(old_clock.seconds(value))/30)*30)
    def remap_note(note, instrument):
        result = deepcopy(note)
        for field in ('start_tick', 'end_tick'): result[field] = tick(note[field])
        result['chord_id'] = harmony_at(shared, result['start_tick'])['id']
        result['texture_measure'] = result['start_tick']//shared['statistics']['bar_ticks']+1
        section = section_at(shared['sections'], clock.seconds(result['start_tick']))['kind']
        result['section'] = section
        # 强拍相位与伴奏同步纠错：新增移除旧右手循环相位，源音段ID及攻击秒证据保留。
        for field in list(result):
            if field.startswith('right_hand_') or field.startswith('pattern_'): result.pop(field)
        # 局部拍轴与原唱同步纠错：修改，保留旧边界重分类；器乐填句落入演唱小节仍保留原旋律来源。
        # if section == 'vocal' and note.get('section') != 'vocal':
        protected_fill = source_time_sections and bool(note.get('source_melody_id'))
        if protected_fill and section == 'vocal' and note.get('section') != 'vocal':
            result['section_reclassification'] = 'instrumental_fill_within_vocal_bar'
        if section == 'vocal' and note.get('section') != 'vocal' and not protected_fill:
            result.pop('source_melody_id', None)
            # 强拍相位与伴奏同步纠错：修改，原角色名保留；项目实际使用instrumental_melody。
            # if result['role'] == 'melody': result['role'] = 'harmony'
            if result['role'] in ('melody','instrumental_melody'): result['role'] = 'harmony'
            result['section_reclassification'] = 'weak_pickup_bar_is_vocal_accompaniment'
        if instrument == 'guitar':
            initial = fresh['guitar']['configuration']['capo_fret']
            result['fret'] = result['pitch_midi'] - TUNING[result['string']] - initial
        return result
    guitar = fresh['guitar']
    guitar['notes'] = [remap_note(n,'guitar') for n in old_arrangements['guitar']['notes']]
    # 强拍相位与伴奏同步纠错：新增段落首拍重拨会自然终止同弦旧低音；逐项记录，不误称持续时间未改。
    entry_releases=[]
    for section in shared['sections']:
        if section['kind'] != 'vocal': continue
        entry=section['start_tick']
        for note in guitar['notes']:
            if note['start_tick'] < entry < note['end_tick'] and note['role'] == 'bass':
                entry_releases.append({'note_id':note['id'],'old_end_tick':note['end_tick'],'new_end_tick':entry,
                                       'reason':'bass_replucked_on_correct_vocal_entry_downbeat'})
                note['end_tick']=entry
    # 强拍相位与伴奏同步纠错：新增器乐弱起共存拍的旧合成低音校准；实际器乐旋律攻击不移动。
    feature_entry_moves=[]
    for note in guitar['notes']:
        if note['section']!='vocal' or note['role']!='bass' or note.get('onset_origin')!='arranged_common_pattern': continue
        chord=harmony_at(shared,note['start_tick']);target=chord['start_tick']
        same_beat=target//480==note['start_tick']//480
        feature=any(n.get('source_melody_id') and target<=n['start_tick']<target+480 for n in guitar['notes'])
        prior=any(n['string']==note['string'] and n['start_tick']<target<n['end_tick'] for n in guitar['notes'])
        if (same_beat and feature and target<note['start_tick'] and not prior
                and note['pitch_midi']%12==chord['bass_pc']):
            feature_entry_moves.append({'note_id':note['id'],'old_start_tick':note['start_tick'],'new_start_tick':target,
                                        'reason':'old_synthetic_bass_entry_in_instrumental_pickup_beat'})
            note['beat_phase_entry_correction']=deepcopy(feature_entry_moves[-1]);note['start_tick']=target
    guitar['attack_events'] = []
    for event in old_arrangements['guitar']['attack_events']:
        new = deepcopy(event); new['start_tick'] = tick(event['start_tick'])
        chord = harmony_at(shared,new['start_tick']);new['chord_id'] = chord['id'];new['chart_id'] = None
        new['sounding_name'] = chord['name']
        for field in list(new):
            if field.startswith('right_hand_') or field.startswith('pattern_'): new.pop(field)
        guitar['attack_events'].append(new)
    guitar['chord_charts'] = []; guitar['fingering_diagrams'] = []
    # 强拍相位与伴奏同步纠错：新增钢琴只重编演唱伴奏，前奏/间奏/尾奏采用已导出器乐音。
    # 渴首次吉他编配：修改，器乐种子保留只处理实际存在的钢琴；原代码注释保留。
    # piano = fresh['piano']; kept = [remap_note(n,'piano') for n in old_arrangements['piano']['notes']]
    # kept = [n for n in kept if n['section'] != 'vocal']
    # # 局部拍轴与原唱同步纠错：修改，保留按整小节标签筛选的原式；局部拍轴使用同一个真实时间分区。
    # # ordinary = [n for n in piano['notes'] if n['section'] == 'vocal']
    # if source_time_sections:
    #     ordinary = piano_source_time_partition(piano['notes'], shared, clock, 'vocal')
    #     piano['local_clock_seed_partition'] = {'kind': 'one_song_time_partition',
    #         'preserved_instrumental_notes': len(kept), 'new_vocal_notes': len(ordinary),
    #         'reason': 'bar_texture_label_is_not_a_note_section_boundary'}
    # else:
    #     ordinary = [n for n in piano['notes'] if n['section'] == 'vocal']
    # for n in kept: n['id'] = 'preserved_' + n['id']
    # piano['notes'] = resolve_piano_sustain(sorted(kept+ordinary,key=lambda n:n['start_tick']),piano['adjustments'])
    # piano['hand_positions'] = piano_hand_positions(piano['notes'],clock)
    # piano['attack_events'] = [e for e in piano['attack_events']
    #                           if section_at(shared['sections'],clock.seconds(e['start_tick']))['kind']=='vocal']
    # for e in old_arrangements['piano']['attack_events']:
    #     t = tick(e['start_tick'])
    #     if section_at(shared['sections'],clock.seconds(t))['kind'] != 'vocal':
    #         new = deepcopy(e);new['start_tick'] = t;new['chord_id'] = harmony_at(shared,t)['id']
    #         piano['attack_events'].append(new)
    # piano['attack_events'].sort(key=lambda e:e['start_tick'])
    # 渴首次吉他编配：新增按所选乐器执行，保留各乐器原验证。
    if 'piano' in fresh:
        piano = fresh['piano']; kept = [remap_note(n,'piano') for n in old_arrangements['piano']['notes']]
        kept = [n for n in kept if n['section'] != 'vocal']
        # 局部拍轴与原唱同步纠错：修改，保留按整小节标签筛选的原式；局部拍轴使用同一个真实时间分区。
        # ordinary = [n for n in piano['notes'] if n['section'] == 'vocal']
        if source_time_sections:
            ordinary = piano_source_time_partition(piano['notes'], shared, clock, 'vocal')
            piano['local_clock_seed_partition'] = {'kind': 'one_song_time_partition',
                'preserved_instrumental_notes': len(kept), 'new_vocal_notes': len(ordinary),
                'reason': 'bar_texture_label_is_not_a_note_section_boundary'}
        else:
            ordinary = [n for n in piano['notes'] if n['section'] == 'vocal']
        for n in kept: n['id'] = 'preserved_' + n['id']
        piano['notes'] = resolve_piano_sustain(sorted(kept+ordinary,key=lambda n:n['start_tick']),piano['adjustments'])
        piano['hand_positions'] = piano_hand_positions(piano['notes'],clock)
        piano['attack_events'] = [e for e in piano['attack_events']
                                  if section_at(shared['sections'],clock.seconds(e['start_tick']))['kind']=='vocal']
        for e in old_arrangements['piano']['attack_events']:
            t = tick(e['start_tick'])
            if section_at(shared['sections'],clock.seconds(t))['kind'] != 'vocal':
                new = deepcopy(e);new['start_tick'] = t;new['chord_id'] = harmony_at(shared,t)['id']
                piano['attack_events'].append(new)
        piano['attack_events'].sort(key=lambda e:e['start_tick'])
    guitar['beat_phase_seed'] = {'version':1,'old_timing_not_used_for_rhythm_selection':True,
                                 # 强拍相位与伴奏同步纠错：修改，原只记录入口释放保留；补充器乐弱起拍合成低音的校准证据。
                                 # 'source_notes':deepcopy(guitar['notes']), 'entry_releases':entry_releases}
                                 'source_notes':deepcopy(guitar['notes']), 'entry_releases':entry_releases,
                                 'feature_entry_moves':feature_entry_moves}
    return fresh


# 局部拍轴与原唱同步纠错：新增按实际起音秒时间筛选，整小节织体标签不能造成两份同源音叠加。
def piano_source_time_partition(notes, shared, clock, wanted):
    from accompaniment_analysis import section_at
    result = []
    for note in notes:
        kind = section_at(shared['sections'], clock.seconds(note['start_tick']))['kind']
        if kind == wanted:
            item = deepcopy(note)
            if item.get('section') != kind:
                item['section_reclassification'] = 'local_clock_note_section_boundary'
            item['section'] = kind
            result.append(item)
    return result


# 强拍相位与伴奏同步纠错：新增正确时钟先于和声和伴奏选择；复用声学缓存，不使用旧编配作节奏证据。
# 乐句节奏与音值分组：修改，原声明注释保留；旧工程可显式升级乐句节奏，已升级工程重导幂等。
# def correct_phase_project(shared, vocal, arrangements, cache_dir):
def correct_phase_project(shared, vocal, arrangements, cache_dir, phrase_rhythm=False):
    from score_export import read_json
    from accompaniment_analysis import analyze
    # 渴首次吉他编配：修改，重建阶段继承绑定的乐器范围；原代码注释保留。
    # from accompaniment_arrange import arrange_guitar, arrange_piano
    # 渴首次吉他编配：新增按所选乐器执行，保留各乐器原验证。
    from accompaniment_arrange import arrange_requested
    from accompaniment_texture_policy import add_block_support
    from shutil import copy2
    # 乐句节奏与音值分组：修改，原提前返回保留；新版只跳过已采用同一策略的工程。
    # if vocal.get('beat_phase_correction'):
    #     return shared, vocal, arrangements
    if vocal.get('beat_phase_correction') and (not phrase_rhythm or vocal['beat_phase_correction'].get('phrase_rhythm')):
        return shared, vocal, arrangements
    binding = shared['input_binding']; review = phase_review(vocal['audio_analysis'], vocal['timing'])
    if review is None:
        raise ValueError('当前音源没有已复核的强拍基准；不能借用其它歌曲的拍点。')
    correction = {'version': 1, 'source_vocal_project_sha256': binding['vocal_project_sha256'],
                  'source_audio_sha256': binding['sources']['mix']['sha256'],
                  'base_grid_correction': deepcopy(vocal.get('grid_correction')), 'review': review}
    # 乐句节奏与音值分组：新增源工程重建条件及固定策略，不接受每字人工时间覆盖。
    if phrase_rhythm:
        from phrase_rhythm import VERSION, POLICY
        correction['phrase_rhythm'] = {'version': VERSION, 'policy': deepcopy(POLICY)}
    fresh_vocal = derive_phase_vocal(read_json(binding['vocal_project']), correction)
    check = validate_reviewed_beats(fresh_vocal)
    if check is not None and not check['valid']:
        raise ValueError('人声首句拍点复核失败：' + str(check['errors']))
    cache_dir = Path(cache_dir); cache_dir.mkdir(parents=True, exist_ok=True)
    for source in binding['sources'].values():
        token = 'v1_' + source['sha256'][:16] + '_22050_512_24_96'
        cached = sorted((ROOT / 'test_outputs/accompaniment_runs').glob('*/features/' + token + '.json'))
        if cached:
            for suffix in ('.json', '.npz'):
                src = cached[0].with_suffix(suffix); dst = cache_dir / (token + suffix)
                if src.is_file() and src.resolve() != dst.resolve() and not dst.exists(): copy2(src, dst)
    fresh_shared = add_block_support(analyze(binding, fresh_vocal, cache_dir), fresh_vocal, cache_dir)
    fresh_shared['beat_phase_correction'] = deepcopy(correction)
    if phrase_rhythm:
        fresh_shared['phrase_rhythm'] = deepcopy(fresh_vocal['statistics']['phrase_rhythm'])
    capo = arrangements['guitar']['configuration'].get('capo_fret', 1)
    # 渴首次吉他编配：修改，避免未请求乐器阻塞所选乐器；原代码注释保留。
    # result = {'guitar': arrange_guitar(fresh_shared, fresh_vocal, capo),
    #           'piano': arrange_piano(fresh_shared, fresh_vocal)}
    # 渴首次吉他编配：新增按所选乐器执行，保留各乐器原验证。
    result = arrange_requested(fresh_shared, fresh_vocal, capo)
    # 强拍相位与伴奏同步纠错：修改，直接重排器乐会引入无关的前奏手位跳跃；原音序种子保留。
    result = seed_existing_music(shared,vocal,arrangements,fresh_shared,fresh_vocal,result)
    # 强拍相位与伴奏同步纠错：新增钢琴低音入口也共用正确拍轴，不能沿用源高音攻击序号推断Bass位置。
    # 渴首次吉他编配：修改，仅对已选择钢琴校准钢琴低音；原代码注释保留。
    # result['piano'] = align_piano_bass(fresh_shared,fresh_vocal,result['piano'])
    # 渴首次吉他编配：新增按所选乐器执行，保留各乐器原验证。
    if 'piano' in result:
        result['piano'] = align_piano_bass(fresh_shared,fresh_vocal,result['piano'])
    result['guitar']['configuration']['beat_synchronous_patterns'] = True
    return fresh_shared, fresh_vocal, result
