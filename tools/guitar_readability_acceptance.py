"""吉他编配规则与统一验收修复：实际音符、和弦、长段路线及导出硬验收。"""
# 吉他编配规则与统一验收修复：新增各入口共用验收，不根据歌曲名、旧通过标记或绘图参数判通过。
from collections import Counter, defaultdict, deque
from copy import deepcopy
from pathlib import Path
import hashlib
import json
import math
import xml.etree.ElementTree as ET

PPQ = 480
# 吉他编配规则与统一验收修复：修改验收版本，旧仅内部自洽通过不能覆盖新增原低音门槛。
# POLICY = {'version': 1, 'minimum_guitar_ticks': 120, 'minimum_harmony_ticks': 480,
# 完整乐句与实际时长复用：修改旧小节计数策略；原代码注释保留。
# POLICY = {'version': 2, 'minimum_guitar_ticks': 120, 'minimum_harmony_ticks': 480,
POLICY = {'version': 3, 'minimum_guitar_ticks': 120, 'minimum_harmony_ticks': 480,
          'maximum_fret': 12, 'preferred_chords_per_bar': 2,
          # 吉他编配规则与统一验收修复：修改策略声明并实际执行；旧无原声项式保留。
          # 'minimum_reused_bars': 8, 'minimum_uninterrupted_bars': 8, 'maximum_ds_routes': 1}
          # 完整乐句与实际时长复用：修改旧小节计数策略；原代码注释保留。
          # 'minimum_reused_bars': 8, 'minimum_uninterrupted_bars': 8, 'maximum_ds_routes': 1,
          'repeat_length_basis': 'complete_phrase_actual_seconds', 'maximum_ds_routes': 1,
          'source_bass_required_for_readability_revision': True}


def fingerprint(value):
    # 吉他编配规则与统一验收修复：新增实际内容摘要；修改数据后旧通过状态不能复用。
    # 吉他编配规则与统一验收修复：修改，历史诊断含Infinity仍须原样保护；摘要允许其稳定编码，实际音符数值另验。
    # return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'),
    #                                  allow_nan=False).encode('utf-8')).hexdigest()
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'),
                                     allow_nan=True).encode('utf-8')).hexdigest()


def actual_timeline(vocal):
    # 吉他编配规则与统一验收修复：新增只读实际边界视图，旧固定小节按原ticks派生，不改拍轴。
    if vocal['timing'].get('measure_timeline'):
        return deepcopy(vocal['timing']['measure_timeline'])
    from accompaniment_analysis import SongClock
    clock = SongClock(vocal)
    bar, total = vocal['statistics']['bar_ticks'], vocal['statistics']['total_ticks']
    return [{'number': index + 1, 'start_tick': start, 'end_tick': min(total, start + bar),
             'meter': list(vocal['timing']['meter']),
             'pickup': index == 0 and bool(vocal['timing'].get('initial_pickup_measure')),
             'start_seconds': clock.seconds(start), 'end_seconds': clock.seconds(min(total, start + bar))}
            for index, start in enumerate(range(0, total, bar))]


def actual_harmony(project):
    # 吉他编配规则与统一验收修复：新增读取实际吉他进行，原共享声学和声保持独立证据。
    guitar = project['arrangements']['guitar']
    if 'readable_harmony' in guitar:
        return guitar['readable_harmony']
    from phrase_harmony_plan import arrangement_view
    return arrangement_view(project['shared_analysis'], project['accepted_vocal_project'])['harmony']


def music_payload(project):
    # 局部两拍过渡听辨修订：新增小节改变使旧阅读验收摘要失效，不能用未改音符冒充新分组通过。
    if project.get('bar_boundary_revision'):
        return {'vocal':project['accepted_vocal_project'],'guitar':project['arrangements']['guitar'],
            'harmony':actual_harmony(project),'bar_boundary_revision':project['bar_boundary_revision']}
    # 吉他编配规则与统一验收修复：新增完整吉他数据及受保护人声的检查对象，不纳入验收结果自身。
    return {'vocal': project['accepted_vocal_project'], 'guitar': project['arrangements']['guitar'],
            'harmony': actual_harmony(project)}


def has_guitar_readability_revision(project):
    # 4/4可选右手与实时谱面试听：新增多层标记和实际音符识别，显式新型不能降级成旧未修订材料。
    from guitar_pattern_selection import has_selection
    if has_selection(project):return True
    # 吉他编配规则与统一验收修复：新增同时识别乐器内部与工程顶层标记，旧导出丢顶层不能降低验收等级。
    # 演唱段稳定右手型：修改识别新型实际音符，丢顶层或旧标记不能绕过原低音门槛。
    # return bool(project.get('guitar_readability_revision') or
    #             project.get('arrangements', {}).get('guitar', {}).get('guitar_readability_revision'))
    guitar=project.get('arrangements',{}).get('guitar',{})
    return bool(project.get('guitar_readability_revision') or guitar.get('guitar_readability_revision') or
                guitar.get('section_patterns') or guitar.get('configuration',{}).get('stable_vocal_patterns') or
                any(n.get('stable_vocal_pattern_id') for n in guitar.get('notes',[])))


def _voice_without_derived_timeline(voice):
    # 吉他编配规则与统一验收修复：新增仅忽略旧谱的派生边界表，实际拍轴／歌词／音符仍逐字段相等。
    value = deepcopy(voice)
    value['timing'].pop('measure_timeline', None)
    return value


def _protected_content(project, baseline):
    # 吉他编配规则与统一验收修复：新增完整音乐保护，不能只看某个音是否出现过。
    errors = []
    if _voice_without_derived_timeline(project['accepted_vocal_project']) != _voice_without_derived_timeline(baseline['accepted_vocal_project']):
        errors.append('protected_vocal_clock_notes_or_lyrics_changed')
    original_timeline = baseline['accepted_vocal_project']['timing'].get('measure_timeline')
    if original_timeline is not None and project['accepted_vocal_project']['timing'].get('measure_timeline') != original_timeline:
        errors.append('approved_measure_timeline_changed')
    if project['shared_analysis'] != baseline['shared_analysis']:
        errors.append('shared_source_harmony_analysis_changed')
    for name, arrangement in baseline['arrangements'].items():
        if name != 'guitar' and project['arrangements'].get(name) != arrangement:
            errors.append('protected_other_instrument_changed:' + name)
    fields = ('id', 'pitch_midi', 'string', 'fret', 'role', 'melody_accent', 'velocity')
    def instrumental(arrangement):
        return {n['id']: {field: n.get(field) for field in fields} for n in arrangement['notes']
                if n.get('section') in ('intro', 'interlude', 'outro') or n.get('role') == 'instrumental_melody'}
    before, after = map(instrumental, (baseline['arrangements']['guitar'], project['arrangements']['guitar']))
    missing = sorted(set(before) - set(after))
    changed = sorted(identity for identity in set(before) & set(after) if before[identity] != after[identity])
    if missing:
        errors.append('protected_instrumental_notes_missing')
    if changed:
        errors.append('protected_instrumental_pitch_fret_or_expression_changed')
    return {'valid': not errors, 'errors': errors, 'protected_instrumental_count': len(before),
            'missing_instrumental_ids': missing, 'changed_instrumental_ids': changed,
            'scope': '器乐必要时间规整另审；音高／弦品／力度／身份及人声原钟完整保护'}


def _xml_notes(path, timeline):
    # 吉他编配规则与统一验收修复：新增独立解释XML游标、和声音与延音链，回读实际持续范围。
    root = ET.parse(path).getroot()
    measures = root.findall('part/measure')
    errors, output, short, pending = [], [], [], {}
    if len(measures) != len(timeline):
        errors.append('xml_measure_count_mismatch')
    divisions = PPQ
    for measure, actual in zip(measures, timeline):
        divisions = int(measure.findtext('attributes/divisions', str(divisions)))
        cursor, previous_start, maximum = 0, 0, 0
        for node in measure:
            if node.tag in ('backup', 'forward'):
                duration = int(node.findtext('duration', '0')) * PPQ / divisions
                cursor += duration * (-1 if node.tag == 'backup' else 1)
                continue
            if node.tag != 'note':
                continue
            duration = int(node.findtext('duration', '0')) * PPQ / divisions
            if duration != int(duration):
                errors.append('xml_nonintegral_duration')
            duration = int(duration)
            start = previous_start if node.find('chord') is not None else cursor
            if node.find('chord') is None:
                previous_start = start
                cursor += duration
            maximum = max(maximum, start + duration)
            kind = node.findtext('type')
            if kind in ('32nd', '64th', '128th', '256th', '512th', '1024th') or 0 < duration < 120:
                short.append({'measure': measure.get('number'), 'id': node.get('id'), 'type': kind,
                              'duration_ticks': duration, 'rest': node.find('rest') is not None})
            if node.find('rest') is not None:
                continue
            pitch_node = node.find('pitch')
            if pitch_node is None:
                errors.append('guitar_xml_unpitched_note')
                continue
            pitch = (int(pitch_node.findtext('octave')) + 1) * 12 + {'C': 0, 'D': 2, 'E': 4, 'F': 5, 'G': 7, 'A': 9, 'B': 11}[pitch_node.findtext('step')] + int(pitch_node.findtext('alter', '0'))
            string_text = node.findtext('notations/technical/string')
            fret_text = node.findtext('notations/technical/fret')
            string = int(string_text) if string_text is not None else None
            fret = int(fret_text) if fret_text is not None else None
            a, b = int(actual['start_tick'] + start), int(actual['start_tick'] + start + duration)
            key = (pitch, string, fret)
            ties = {tie.get('type') for tie in node.findall('tie')}
            if 'stop' in ties:
                if key not in pending or pending[key][2] != a:
                    errors.append('xml_broken_tie_chain:' + str(node.get('id')))
                    chain = [pitch, a, b, string, fret]
                else:
                    chain = pending.pop(key)
                    chain[2] = b
            else:
                chain = [pitch, a, b, string, fret]
            if 'start' in ties:
                if key in pending:
                    errors.append('xml_duplicate_pending_tie')
                pending[key] = chain
            else:
                output.append(tuple(chain))
        if maximum != actual['end_tick'] - actual['start_tick']:
            errors.append('xml_bar_duration_mismatch:' + str(actual['number']))
    if pending:
        errors.append('xml_unclosed_tie_chain')
    return output, {'valid': not errors and not short, 'errors': errors, 'sub_sixteenth_fragments': short,
                    'actual_note_intervals': len(output), 'measure_count': len(measures)}


def _midi_notes(path):
    # 吉他编配规则与统一验收修复：新增读取真正SMF消息，允许同时同音但不丢重复攻击。
    import mido
    midi = mido.MidiFile(path)
    output, errors = [], []
    for track in midi.tracks:
        tick, active = 0, defaultdict(deque)
        for message in track:
            tick += message.time
            actual_tick = tick * PPQ / midi.ticks_per_beat
            if message.type == 'note_on' and message.velocity > 0:
                active[(message.channel, message.note)].append((int(actual_tick), message.velocity))
            elif message.type in ('note_off', 'note_on'):
                key = (message.channel, message.note)
                if not active[key]:
                    errors.append('midi_note_off_without_attack')
                else:
                    start, velocity = active[key].popleft()
                    output.append((message.note, start, int(actual_tick), velocity))
        if any(active.values()):
            errors.append('midi_unclosed_notes')
    return output, errors


# 吉他编配规则闭环修复：新增实际反复文件与主页面同时回读，JSON中的正确路线不能掩盖缺失的符号。
def _actual_repeat_print(project, folder, plan):
    from guitar_repeat_marks import validate_marks
    if plan is None:
        return {'valid': False, 'errors': ['repeat_plan_missing_for_actual_print']}
    modern = bool(plan.get('adapter_version'))
    directory = folder / ('rows' if modern else 'repeat_rows')
    prefix = 'repeat_' if modern else 'line_'
    expected = [directory / f'{prefix}{number:03}.svg' for number in range(1, len(plan['lines']) + 1)]
    # 吉他编配规则闭环修复：新增旧出口评估后确无合格长段时允许真实顺序谱；有长段就不能借此跳过印刷。
    if not modern and not directory.is_dir() and not plan.get('folded_blocks'):
        return {'valid': True, 'errors': [], 'visible_symbols': 0, 'mode': 'evaluated_unfolded_no_qualified_section'}
    missing = [path.name for path in expected if not path.is_file()]
    if missing:
        return {'valid': False, 'errors': ['repeat_print_row_missing:' + name for name in missing]}
    if not modern and not plan.get('folded_blocks') and (folder/'score_full.html').is_file():
        # 没有可复用长段时，生成器实际显示完整展开谱；repeat_rows是评估候选，
        # 不能拿没有采用的候选SVG与当前页面比较。仍核查真正显示的每一行。
        page=(folder/'score.html').read_text('utf-8')
        complete=(folder/'score_full.html').read_text('utf-8')
        visible=sorted((folder/'rows').glob('measures_*.svg'))
        errors=[]
        if page!=complete:errors.append('unfolded_actual_page_differs_from_full_score')
        if not visible:errors.append('unfolded_visible_rows_missing')
        errors.extend('unfolded_actual_page_differs_from_svg:'+path.name
                      for path in visible if path.read_text('utf-8') not in page)
        return {'valid':not errors,'errors':errors,'visible_symbols':0,
                'mode':'evaluated_unfolded_no_qualified_section',
                'actual_rows_checked':len(visible),'actual_page_matches_svg_files':not errors}
    rows = [{'guitar': path.read_text('utf-8')} for path in expected]
    result = validate_marks(plan, rows)
    page = (folder / 'score.html').read_text('utf-8')
    for path, row in zip(expected, rows):
        if row['guitar'] not in page:
            result['errors'].append('repeat_actual_page_differs_from_svg:' + path.name)
    actual_paths = set(directory.glob(prefix + '*.svg'))
    if actual_paths != set(expected):
        result['errors'].append('repeat_print_has_extra_rows')
    # 吉他编配规则闭环修复：修改旧只解码legacy折叠TAB的缺口；新版主阅读谱也必须读真实字形和横梁。
    # if not modern:
    if modern:
        timeline = actual_timeline(project['accepted_vocal_project'])
        arrangement = project['arrangements']['guitar']
        blocks = {block['id']: block for block in plan['blocks']}
        decoded_rows = []
        for path, line in zip(expected, plan['lines']):
            try:
                spans = [(timeline[blocks[identity]['canonical_first'] - 1]['start_tick'],
                          timeline[blocks[identity]['canonical_last'] - 1]['end_tick']) for identity in line]
                # 相似长段复用与默认阅读修复：新增每行真实变奏也必须从可见数字／x和图式独立读回。
                from guitar_repeat_variants import block_variants
                spans += [(timeline[v['source_measure']-1]['start_tick'],timeline[v['source_measure']-1]['end_tick'])
                          for identity in line for v in block_variants(plan,blocks[identity])]
                # 吉他编配规则闭环修复：新增按实际印刷来源选音，复用隐藏的第二遍音符不误算成漏音。
                printed = {**arrangement, 'notes': [n for n in arrangement['notes']
                                                    if any(a <= n['start_tick'] < b for a, b in spans)]}
                _, decoded = _modern_tab_rows([path], printed)
                decoded_rows.append({'file': path.name, **decoded})
            except (KeyError, ValueError, TypeError, IndexError, AttributeError) as exc:
                decoded_rows.append({'file': path.name, 'valid': False,
                                     'errors': ['modern_repeat_visible_decode_failed:' + str(exc)]})
        content_errors = [error for row in decoded_rows for error in row.get('errors', [])]
        result['visible_content'] = {'valid': not content_errors, 'errors': content_errors,
                                     'rows': decoded_rows,
                                     'scope': 'printed_canonical_actual_frets_grips_strings_and_rhythm_beams'}
        result['errors'].extend(content_errors)
        # 相似长段复用与默认阅读修复：新增文件和主页面一致之外，还核验变奏真实来源／可见替换说明。
        from guitar_repeat_variants import validate_variant_tabs
        variant_check=validate_variant_tabs(project,plan,rows)
        result['explicit_variants']=variant_check
        result['errors'].extend(variant_check['errors'])
        # 完整乐句与实际时长复用：新增实际完整谱面对比，复制正收益候选字段不能掩盖变奏／叠词令谱面更难读。
        from guitar_reading_load import assess_printed_reading_load
        reading_load=assess_printed_reading_load(folder,plan)
        result['actual_reading_load']=reading_load
        result['errors'].extend(reading_load['errors'])
    else:
        # 吉他编配规则闭环修复：新增旧反复谱沿用真实字词／弦品／共同时间列核查，不伪造新版data属性。
        from guitar_repeat_score import validate_repeat_rows
        try:
            geometry = validate_repeat_rows(plan, rows, project['accepted_vocal_project'], project['arrangements']['guitar'], project['shared_analysis'])
        except (ValueError, KeyError, TypeError, StopIteration, AttributeError) as exc:
            geometry = {'valid': False, 'errors': ['legacy_repeat_visible_decode_failed:' + str(exc)]}
        result['visible_content'] = geometry
        if not geometry['valid']:
            result['errors'].extend(geometry['errors'])
    result['valid'] = not result['errors']
    result['actual_page_matches_svg_files'] = not any('actual_page_differs' in e for e in result['errors'])
    return result


# 吉他编配规则闭环修复：新增新版TAB也读可见数字／x和真实指型黑点，不单凭隐藏data-fret通过。
def _modern_tab_rows(paths, arrangement):
    from guitar_chord_diagrams import read_diagram, left_hand_fret
    ns = '{http://www.w3.org/2000/svg}'
    observed, errors = Counter(), []
    plans = {d['id']: d for d in arrangement.get('fingering_diagrams', [])}
    for path in paths:
        root = ET.parse(path).getroot(); parents = {n: p for p in root.iter() for n in p}
        # 扫弦箭头与实际弦组记谱修正：新增从实际箭头几何与可见指型解码扫弦音，不要求恢复柱式音头。
        from guitar_strum_notation import read_visible_strums
        swept,failures=read_visible_strums(root,arrangement)
        observed.update(swept);errors.extend(failures)
        charts = []
        for node in root.iter(ns + 'g'):
            if node.get('class') != 'chord-diagram':
                continue
            try:
                chart = read_diagram(node); plan = plans[chart['plan_id']]
                if (chart['frets'] != {s: plan['frets'].get(str(s), -1) for s in range(1, 7)}
                        or chart['barre'] != plan.get('barre') or chart['position'] != plan['position']
                        or not plan['start_tick'] <= chart['start_tick'] < chart['end_tick'] <= plan['end_tick']):
                    errors.append('visible_modern_grip_differs_from_arrangement:' + chart['plan_id'])
                charts.append(chart)
            except (KeyError, ValueError, TypeError, AttributeError) as exc:
                errors.append('visible_modern_grip_invalid:' + str(exc))
        for node in root.iter(ns + 'g'):
            if not node.get('data-string'):
                continue
            try:
                identity = node.get('data-note-id'); string = int(node.get('data-string')); tick = int(node.get('data-start-tick'))
                text = node.find(ns + 'text'); glyph = text.text or ''
                lines = sorted({float(n.get('y1')) for n in parents[node].findall(ns + 'line') if n.get('class') == 'tab-string-line'})
                if len(lines) != 6 or not 1 <= string <= 6 or abs(float(text.get('y')) - 6 - lines[string - 1]) > .02:
                    errors.append('visible_modern_note_on_wrong_string:' + str(identity))
                chart = next((d for d in charts if d['start_tick'] <= tick < d['end_tick']), None)
                if glyph == 'x':
                    if chart is None:
                        raise ValueError('x缺少实际可见指型')
                    fret = left_hand_fret(chart, string)
                elif glyph.isdigit():
                    fret = int(glyph)
                else:
                    raise ValueError('实际TAB不是数字或x')
                if fret != int(node.get('data-fret')):
                    errors.append('visible_modern_fret_differs_from_metadata:' + str(identity))
                observed[(identity, string, fret, tick)] += 1
            except (KeyError, ValueError, TypeError, AttributeError, IndexError) as exc:
                errors.append('visible_modern_tab_invalid:' + str(exc))
        for node in root.iter(ns + 'line'):
            if node.get('data-rhythm-duration') is None:
                continue
            duration = int(node.get('data-rhythm-duration')); flags = int(node.get('data-flags', '0'))
            if duration < 120 or flags > 2:
                errors.append('visible_modern_rhythm_shorter_than_sixteenth')
            # 吉他编配规则闭环修复：新增从真实横梁高度与端点计层，不相信data-flags自报。
            at = float(node.get('x1')); levels = set()
            for beam in parents[node].findall(ns + 'line'):
                if beam.get('stroke-width') != '2' or abs(float(beam.get('y1')) - float(beam.get('y2'))) > .02:
                    continue
                if min(float(beam.get('x1')), float(beam.get('x2'))) - .02 <= at <= max(float(beam.get('x1')), float(beam.get('x2'))) + .02:
                    levels.add(round(float(beam.get('y1')), 2))
            expected_flags = 0 if duration >= 480 else 1 if duration >= 240 else 2
            if levels != {465 - level * 5 for level in range(expected_flags)} or flags != expected_flags:
                errors.append('visible_modern_beams_differ_from_actual_duration')
    wanted = Counter((n['id'], n['string'], n['fret'], n['start_tick']) for n in arrangement['notes'])
    if observed != wanted:
        errors.append('chronological_visible_modern_tab_differs_from_project')
    return observed, {'valid': not errors, 'errors': errors, 'actual_notes': sum(observed.values()),
                      'expected_notes': len(arrangement['notes']), 'format': 'variable_measure_visible_digits_x_and_grip'}


# 吉他编配规则闭环修复：修改终检接口接实际计划，旧三参数签名保留。
# def _actual_artifacts(project, output_dir, timeline):
def _actual_artifacts(project, output_dir, timeline, repeat_plan=None):
    # 吉他编配规则与统一验收修复：新增实际交付回读，不接受仅修改XML名字或少画连梁的假修复。
    folder = Path(output_dir) / 'guitar'
    errors, report = [], {}
    # 吉他编配规则闭环修复：修改旧固定MIDI名字，接真实旧出口accompaniment.mid而不复制假别名。
    # required = ('score.musicxml', 'score.mid', 'score.html')
    required = ('score.musicxml', 'score.html')
    missing = [name for name in required if not (folder / name).is_file()]
    midi_paths = [folder / name for name in ('score.mid', 'accompaniment.mid') if (folder / name).is_file()]
    if not midi_paths:
        missing.append('score.mid_or_accompaniment.mid')
    if missing:
        return {'valid': False, 'errors': ['artifact_missing:' + name for name in missing]}
    notes = project['arrangements']['guitar']['notes']
    actual, xml = _xml_notes(folder / 'score.musicxml', timeline)
    # 4/4可选右手与实时谱面试听：修改XML回读按独立受审的记谱视图比较，MIDI和保护检查仍使用完整实际余音。
    # expected = Counter((n['pitch_midi'], n['start_tick'], n['end_tick'], n['string'], n['fret']) for n in notes)
    from guitar_pattern_performance import notation_notes
    expected = Counter((n['pitch_midi'], n['start_tick'], n['end_tick'], n['string'], n['fret']) for n in notation_notes(project['arrangements']['guitar']))
    if Counter(actual) != expected:
        errors.append('xml_actual_notes_differ_from_project')
        xml['missing_intervals'] = [list(x) for x in (expected - Counter(actual)).elements()][:20]
        xml['extra_intervals'] = [list(x) for x in (Counter(actual) - expected).elements()][:20]
    if not xml['valid']:
        errors.append('xml_guitar_readability_failed')
    # 吉他编配规则闭环修复：修改旧只认新文件名的读回；两种文件同时存在时也必须逐份相同。
    # midi, midi_errors = _midi_notes(folder / 'score.mid')
    midi, midi_errors = _midi_notes(midi_paths[0])
    # 4/4可选右手与实时谱面试听：修改实际MIDI回读使用经方向验证的投影，XML仍逐项比较逻辑拍位与延音。
    # wanted = Counter((n['pitch_midi'], n['start_tick'], n['end_tick'], n['velocity']) for n in notes)
    from guitar_pattern_performance import performance_notes
    wanted = Counter((n['pitch_midi'], n['start_tick'], n['end_tick'], n['velocity']) for n in performance_notes(project['arrangements']['guitar']))
    if Counter(midi) != wanted:
        midi_errors.append('midi_actual_notes_differ_from_project')
    for extra_path in midi_paths[1:]:
        extra_notes, extra_errors = _midi_notes(extra_path)
        midi_errors.extend(extra_errors)
        if Counter(extra_notes) != wanted:
            midi_errors.append('additional_midi_actual_notes_differ_from_project:' + extra_path.name)
    errors.extend(midi_errors)
    tab = Counter()
    # 吉他编配规则闭环修复：修改旧仅新版TAB格式的入口，实际旧数字／x／指型由既有可见解码器解释。
    modern_paths = sorted((folder / 'rows').glob('voice_*.svg'))
    # for path in sorted((folder / 'rows').glob('voice_*.svg')):
    for path in modern_paths:
        # 扫弦箭头与实际弦组记谱修正：保留旧属性计数循环，扫弦须另经可见几何／指型回读后计入。
        # for node in ET.parse(path).getroot().iter():
        root=ET.parse(path).getroot()
        from guitar_strum_notation import read_visible_strums
        swept,failures=read_visible_strums(root,project['arrangements']['guitar'])
        tab.update(swept);errors.extend(failures)
        for node in root.iter():
            if all(node.get(field) is not None for field in ('data-note-id', 'data-string', 'data-fret', 'data-start-tick')):
                tab[(node.get('data-note-id'), int(node.get('data-string')), int(node.get('data-fret')), int(node.get('data-start-tick')))] += 1
    wanted_tab = Counter((n['id'], n['string'], n['fret'], n['start_tick']) for n in notes)
    if modern_paths:
        # 吉他编配规则闭环修复：修改旧仅隐藏属性计数式，保留原行；实际可见数字／x同样必须一致。
        # tab_report = {'valid': tab == wanted_tab, 'actual_notes': sum(tab.values()), 'expected_notes': len(notes), 'format': 'variable_measure_tab'}
        visible, tab_report = _modern_tab_rows(modern_paths, project['arrangements']['guitar'])
        # if tab != wanted_tab:
        if tab != wanted_tab or not tab_report['valid']:
            errors.append('chronological_tab_notes_differ_from_project')
    else:
        from accompaniment_export import validate_tab
        paths = sorted((folder / 'rows').glob('measures_*.svg'))
        rows = [{'guitar': path.read_text('utf-8')} for path in paths]
        try:
            tab_report = validate_tab(rows, project['arrangements']['guitar'])
        except (ValueError, KeyError, TypeError, StopIteration, AttributeError) as exc:
            tab_report = {'valid': False, 'errors': ['legacy_visible_tab_decode_failed:' + str(exc)]}
        tab_report.update(format='legacy_actual_numeric_x_and_grip', expected_notes=len(notes))
        if not paths:
            tab_report.update(valid=False, errors=['legacy_chronological_tab_rows_missing'])
        if not tab_report['valid']:
            errors.append('chronological_tab_notes_differ_from_project')
    # 吉他编配规则闭环修复：新增实际主阅读谱／外存SVG共同验符号，删除任何一侧均失败。
    print_report = _actual_repeat_print(project, folder, repeat_plan) if repeat_plan is not None else {'valid': True, 'status': 'plan_not_supplied'}
    if not print_report['valid']:
        errors.append('actual_repeat_print_failed')
    # 4/4可选右手与实时谱面试听：新增实际箭头、合拨、空扫及XML动作回读；旧无选择文件不增加要求。
    from guitar_pattern_performance import validate_action_artifacts
    action_artifacts=validate_action_artifacts(project,output_dir)
    if not action_artifacts['valid']:errors.extend(action_artifacts['errors'])
    report['selected_action_artifacts']=action_artifacts
    report.update(valid=not errors, errors=errors, xml=xml,
                  # 吉他编配规则闭环修复：修改实际格式报告，原固定新版TAB报告保留。
                  # midi={'valid': not midi_errors, 'errors': midi_errors, 'actual_notes': len(midi)},
                  # tab={'valid': tab == wanted_tab, 'actual_notes': sum(tab.values()), 'expected_notes': len(notes)})
                  midi={'valid': not midi_errors, 'errors': midi_errors, 'actual_notes': len(midi), 'files': [p.name for p in midi_paths]},
                  tab=tab_report, printed_repeat=print_report)
    return report


def assess_guitar_readability(project, repeat_plan=None, output_dir=None, baseline_project=None, require_repeat=True):
    # 吉他编配规则与统一验收修复：新增统一实际验收；require_repeat=False仅用于编配中间阶段，不能作最终交付证明。
    from accompaniment_analysis import SongClock
    from accompaniment_arrange import validate_playability
    errors, warnings = [], []
    vocal, guitar = project['accepted_vocal_project'], project['arrangements']['guitar']
    # 局部两拍过渡听辨修订：修改验收同读谱共用新局部边界；原固定时钟与音符不变。
    # timeline, clock = actual_timeline(vocal), SongClock(vocal)
    from guitar_variable_repeat import measure_timeline
    # 局部两拍过渡听辨修订：修改仅新分组走新表，普通既有工程保持原验收路径。
    # timeline, clock = measure_timeline(project), SongClock(vocal)
    timeline, clock = (measure_timeline(project) if project.get('bar_boundary_revision') else actual_timeline(vocal)), SongClock(vocal)
    if project.get('bar_boundary_revision'):
        from reviewed_bar_boundaries import verify_revision, assess_local_patterns
        # 4/4可选右手与实时谱面试听：修改旧小节认证在真实祖先重放，新选择范围另由绑定父工程逐音验收。
        # try:verify_revision(project,verify_source=False)
        from guitar_pattern_selection import has_selection, legacy_source
        original_grouping = legacy_source(project) if has_selection(project) else project
        try:verify_revision(original_grouping,verify_source=False)
        except ValueError:errors.append('reviewed_bar_boundaries_unbound_or_music_changed')
        # 4/4可选右手与实时谱面试听：修改仅旧冻结小节继续校验旧型，新显式选择在assess_selection重建。
        # errors.extend(assess_local_patterns(project).get('errors',[]))
        errors.extend(assess_local_patterns(original_grouping).get('errors',[]))
    notes = guitar['notes']
    previous = 0
    for measure in timeline:
        start, end = measure['start_tick'], measure['end_tick']
        if start != previous or end <= start or start % 120 or end % 120:
            errors.append('invalid_actual_measure_timeline:' + str(measure['number']))
        for name, tick in (('start_seconds', start), ('end_seconds', end)):
            if name in measure and abs(measure[name] - clock.seconds(tick)) > .001:
                errors.append('measure_source_clock_changed:' + str(measure['number']))
        previous = end
    if previous != vocal['statistics']['total_ticks']:
        errors.append('timeline_total_ticks_mismatch')
    grid_errors, short_notes, high = [], [], []
    # 4/4可选右手与实时谱面试听：新增只对已绑定父工程完整保留的旧自然释放作记谱投影；新攻击和新音值仍严格十六分网格。
    from guitar_pattern_selection import has_selection
    projected_releases={p['note_id']:p for p in guitar.get('natural_release_notation',[])} if has_selection(project) else {}
    if guitar.get('natural_release_notation') and not has_selection(project):
        errors.append('natural_release_projection_requires_bound_selection')
    for note in notes:
        a, b = note['start_tick'], note['end_tick']
        # 4/4可选右手与实时谱面试听：修改余音结束与独立拨弦网格分开；投影由下方assess_selection从真实父工程重建。
        # if a % 120 or b % 120:
        release=projected_releases.get(note['id'])
        natural=bool(release and release.get('actual_end_tick')==b and release.get('notation_end_tick')==((b+119)//120)*120
                     and 0<release['notation_end_tick']-b<120)
        if a % 120 or (b % 120 and not natural):
            grid_errors.append(note['id'])
        if b - a < 120:
            short_notes.append(note['id'])
        if not 0 <= note['fret'] <= 12:
            high.append(note['id'])
    attacks = sorted({note['start_tick'] for note in notes})
    gaps = [(a, b) for a, b in zip(attacks, attacks[1:]) if b - a < 120]
    for condition, kind in ((grid_errors, 'guitar_off_sixteenth_grid'), (short_notes, 'guitar_note_shorter_than_sixteenth'),
                             (gaps, 'guitar_attack_gap_shorter_than_sixteenth'), (high, 'guitar_fret_above_twelve')):
        if condition:
            errors.append(kind)
    harmony = sorted(actual_harmony(project), key=lambda h: (h['start_tick'], h['end_tick']))
    compressed = []
    for chord in harmony:
        if chord['end_tick'] <= 0 or chord['start_tick'] >= previous or chord.get('name') == 'N.C.':
            continue
        identity = (chord.get('root_pc'), chord.get('quality'), chord.get('bass_pc'), chord.get('name'))
        if compressed and compressed[-1]['identity'] == identity and compressed[-1]['end_tick'] == chord['start_tick']:
            compressed[-1]['end_tick'] = chord['end_tick']
        else:
            compressed.append({'identity': identity, **chord})
    harmony_issues = []
    for chord in compressed:
        if chord['start_tick'] % PPQ or chord['end_tick'] % PPQ or chord['end_tick'] - chord['start_tick'] < PPQ:
            harmony_issues.append({'id': chord['id'], 'kind': 'sub_beat_chord_or_offbeat_change',
                                   'start_tick': chord['start_tick'], 'end_tick': chord['end_tick']})
    for a, b in zip(compressed, compressed[1:]):
        if a['end_tick'] > b['start_tick']:
            harmony_issues.append({'id': b['id'], 'kind': 'overlapping_chord_spans'})
    crowded = []
    for measure in timeline:
        active = [h for h in compressed if h['start_tick'] < measure['end_tick'] and h['end_tick'] > measure['start_tick']]
        if len(active) > 2 and not measure['pickup']:
            crowded.append(measure['number'])
    if harmony_issues:
        errors.append('harmony_change_density_failed')
    if crowded:
        warnings.append('bars_above_preferred_two_chords_need_source_justification')
    try:
        physical = validate_playability(guitar, clock)
    except (KeyError, ValueError, TypeError) as exc:
        physical = {'valid': False, 'errors': ['playability_input_invalid:' + str(exc)]}
    if not physical['valid']:
        errors.append('physical_playability_failed')
    protection = _protected_content(project, baseline_project) if baseline_project is not None else {'status': 'not_requested'}
    if protection.get('valid') is False:
        errors.extend(protection['errors'])
    # 吉他编配规则与统一验收修复：新增原低音独立证据门槛；自洽的新和弦不能证明没有提前换根音。
    source_bass = project.get('guitar_source_bass_acceptance')
    # 吉他编配规则与统一验收修复：修改不能借旧API丢顶层标记绕过原声检查。
    # if project.get('guitar_readability_revision') and (require_repeat or output_dir is not None):
    if has_guitar_readability_revision(project) and (require_repeat or output_dir is not None):
        if source_bass is None:
            errors.append('changed_bass_source_acceptance_missing')
        else:
            from guitar_source_bass_acceptance import require_changed_bass_source
            try:
                require_changed_bass_source(project, source_bass)
            except ValueError:
                errors.append('changed_bass_source_acceptance_failed_or_stale')
    repeat = {'status': 'not_evaluated', 'valid': False}
    if repeat_plan is not None:
        if repeat_plan.get('adapter_version') or repeat_plan.get('actual_measure_timeline'):
            from guitar_variable_repeat import validate_repeat_plan
            repeat = validate_repeat_plan(repeat_plan, project)
        else:
            from guitar_repeat_plan import validate_repeat_plan as validate_old_plan
            repeat = validate_old_plan(repeat_plan, project['shared_analysis'], vocal, guitar)
        # 完整乐句与实际时长复用：修改旧小节计数策略；原代码注释保留。
        # for group in repeat_plan.get('repeat_groups', []):
        #     if group.get('length_bars', 0) < 8:
        #         errors.append('reused_section_shorter_than_eight_bars')
        # for jump in repeat_plan.get('jumps', []):
        #     if jump.get('uninterrupted_bars', 0) < 8:
        #         errors.append('uninterrupted_repeat_shorter_than_eight_bars')
        from guitar_phrase_repeat import validate_route_evidence
        errors.extend(validate_route_evidence(repeat_plan, vocal)['errors'])
        if sum(g.get('method') == 'ds' for g in repeat_plan.get('repeat_groups', [])) > 1:
            errors.append('too_many_ds_routes')
        if not repeat.get('valid'):
            errors.append('repeat_plan_invalid')
    elif require_repeat:
        errors.append('repeat_planner_not_run')
    # 吉他编配规则闭环修复：修改最终实际产物验收接入同一规划的可见符号，旧调用保留。
    # artifacts = _actual_artifacts(project, output_dir, timeline) if output_dir is not None else {'status': 'not_requested'}
    artifacts = _actual_artifacts(project, output_dir, timeline, repeat_plan) if output_dir is not None else {'status': 'not_requested'}
    if artifacts.get('valid') is False:
        errors.extend(artifacts['errors'])
    # 演唱段稳定右手型：新增独立检查实际拨弦和时值；旧曲原样重导不强制重编，新型不能只靠元数据放行。
    from guitar_section_patterns import assess_section_patterns
    section_patterns=assess_section_patterns(project)
    if not section_patterns['valid']:
        errors.extend(section_patterns.get('errors',[]))
    return {'version': POLICY['version'], 'policy': deepcopy(POLICY), 'valid': not errors,
            'status': 'passed' if not errors else 'failed', 'errors': sorted(set(errors)), 'warnings': warnings,
            'input_music_sha256': fingerprint(music_payload(project)),
            'scope': 'guitar_arrangement_and_reading_rules_only_not_whole_song_source_music_certification',
            'stage': 'export' if output_dir is not None else 'arrangement_and_repeat' if require_repeat else 'arrangement_preflight',
            'rules': ['R10', 'R15', 'R17', 'R21', 'R24', 'R26', 'R27', 'R30', 'R33', 'R34', 'R39'],
            'notes': len(notes), 'harmony': {'valid': not harmony_issues, 'errors': harmony_issues,
                                             'performed_chord_spans': len(compressed), 'bars_above_preferred_two': crowded},
            'rhythm': {'off_grid_ids': grid_errors, 'short_note_ids': short_notes, 'dense_attack_gaps': gaps},
            'register': {'maximum_fret': max((n['fret'] for n in notes), default=0),
                         'zero_to_four': sum(n['fret'] <= 4 for n in notes), 'invalid_ids': high},
            # 吉他编配规则与统一验收修复：修改结果纳入来源低音检查，旧结果式保留。
            # 'physical_playability': physical, 'protected_music': protection, 'repeat': repeat, 'artifacts': artifacts}
            'physical_playability': physical, 'protected_music': protection,
            # 演唱段稳定右手型：修改返回真实段级检查，旧仅原低音结果式保留。
            # 'source_bass': source_bass or {'status': 'not_required_for_unrevised_material'},
            'source_bass': source_bass or {'status': 'not_required_for_unrevised_material'}, 'section_patterns': section_patterns,
            'repeat': repeat, 'artifacts': artifacts}


def require_guitar_readability(project, assessment, final=True):
    # 局部两拍过渡听辨修订：新增放行时核对完整来源，派生边界不得被未校验字段冒充。
    if project.get('bar_boundary_revision'):
        from reviewed_bar_boundaries import verify_revision
        # 4/4可选右手与实时谱面试听：修改不把已授权的右手改变误判为旧冻结分组篡改。
        # verify_revision(project)
        from guitar_pattern_selection import has_selection, legacy_source, require_selection
        if has_selection(project):require_selection(project)
        verify_revision(legacy_source(project) if has_selection(project) else project)
    # 吉他编配规则与统一验收修复：新增硬门槛，过期摘要、预检冒充终检或失败一律拒绝。
    # 吉他编配规则与统一验收修复：新增直接调用放行器也核原低音及当前策略，不能旁路assess复用旧通过。
    if assessment.get('version') != POLICY['version'] or assessment.get('policy') != POLICY:
        raise ValueError('吉他验收策略已更新，必须按当前实际规则重新验收。')
    # 吉他编配规则与统一验收修复：修改放行器使用同一完整修订身份判断。
    # if project.get('guitar_readability_revision'):
    if has_guitar_readability_revision(project):
        from guitar_source_bass_acceptance import require_changed_bass_source
        require_changed_bass_source(project, project.get('guitar_source_bass_acceptance'))
    if (assessment.get('valid') is not True or assessment.get('errors')
            or assessment.get('input_music_sha256') != fingerprint(music_payload(project))
            or (final and assessment.get('stage') != 'export')):
        raise ValueError('吉他和弦／十六分／长段阅读验收未通过或已失效：' + str(assessment.get('errors', [])))
    return True
