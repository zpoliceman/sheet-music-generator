"""最小拍轴与词音伴奏修复：可变小节隔离谱、MIDI和原唱合播。"""
# 最小拍轴与词音伴奏修复：新增时间适配器，复用现有音符／标准XML写出；不改变旧版导出政策。
from copy import deepcopy
from collections import defaultdict
from pathlib import Path
from workspace_location import local_path
import argparse
import base64
import html
import json
import math
import re
import xml.etree.ElementTree as ET
import numpy as np
import score_export as score
import accompaniment_export as export
from accompaniment_analysis import SongClock
from guitar_chord_diagrams import draw_diagram, left_hand_fret
from accompaniment_vocal_playback import align_samples, write_ogg, write_singing_preview
from staff_export import RENDER_OPTIONS, write_mxl
from source_timing_acceptance import require_isolated_output
# 吉他编配规则闭环修复：新增统一真实小节、吉他专用和声与长段规划适配入口。
from guitar_variable_repeat import guitar_shared_view, measure_timeline, build_repeat_plan, validate_repeat_plan

NS = '{http://www.w3.org/2000/svg}'


def shift_rows(rows, start):
    # 最小拍轴与词音伴奏修复：新增单小节视图平移；含延音的负起点保留，不把续音重发。
    output = deepcopy(rows)
    for row in output:
        for key in ('start_tick', 'end_tick', 'tick', 'draw_tick', 'display_end_tick'):
            if key in row:
                row[key] -= start
    return output


def local_view(project, measure, instrument=None):
    # 最小拍轴与词音伴奏修复：新增每小节适配既有写出器，长度由边界表决定；不再用编号乘固定1920。
    # 局部两拍过渡听辨修订：修改使用重新跨线分割的记谱事件，原歌词／音符演奏字段不改。
    # voice = project['accepted_vocal_project']
    from reviewed_bar_boundaries import notation_voice
    voice = notation_voice(project)
    start, end = measure['start_tick'], measure['end_tick']
    local = {**voice, 'statistics': {**voice['statistics'], 'bar_ticks': end - start, 'total_ticks': end - start, 'measure_count': 1},
             # 吉他编配规则闭环修复：修改局部拍轴保留原偏移；旧固定起点式注释保留。
             # 'timing': {**voice['timing'], 'score_start_quarter': start / 480, 'meter': [(end - start) // 480, 4],
             'timing': {**voice['timing'], 'score_start_quarter': voice['timing']['score_start_quarter'] + start / 480, 'meter': [(end - start) // 480, 4],
                        'initial_pickup_measure': False, 'measure_number_offset': 0},
             'notation': deepcopy(voice['notation']),
             'events': shift_rows([e for e in voice['events'] if e['measure'] == measure['number']], start),
             'tempo_events': [{**t, 'tick': t['tick'] - start} for t in voice['tempo_events'] if start <= t['tick'] < end]}
    for event in local['events']:
        event.update(measure=1, offset_ticks=event['start_tick'])
    if not local['tempo_events'] or local['tempo_events'][0]['tick'] != 0:
        # 吉他编配规则闭环修复：修改旧原点丢失式，旧固定小节工程同样保持实际秒时钟。
        # local['tempo_events'].insert(0, {'tick': 0, 'bpm': SongClock(voice).mapping.tempo_at(start / 480)})
        local['tempo_events'].insert(0, {'tick': 0, 'bpm': SongClock(voice).mapping.tempo_at(voice['timing']['score_start_quarter'] + start / 480)})
    # 吉他编配规则闭环修复：新增局部调性沿用已认可来源，不丢失跨曲旧谱的实际转调。
    local['notation']['key'] = SongClock(voice).key(start)
    # 新曲慢拍生成与转调标签同步：新增显式新时间派生同步数字1的参考音；旧工程显示按历史版本保留。
    if voice.get('time_only_key_projection', {}).get('version') == 1:
        _, reference = score.notation_at(voice, measure=measure['number'])
        local['notation']['jianpu_reference_midi'] = reference
    local['notation']['key_segments'] = []
    if instrument is None:
        return local, None, None
    # 吉他编配规则闭环修复：修改每小节全量复制审计大字段，旧式保留；只复制随后改时的演奏视图。
    # arrangement = deepcopy(project['arrangements'][instrument])
    arrangement = {**project['arrangements'][instrument], 'configuration': deepcopy(project['arrangements'][instrument]['configuration'])}
    arrangement['notes'] = shift_rows([n for n in arrangement['notes'] if n['start_tick'] < end and n['end_tick'] > start], start)
    for field in ('pedal', 'notation_regions', 'fingering_diagrams'):
        arrangement[field] = shift_rows(arrangement.get(field, []), start)
    # 4/4可选右手与实时谱面试听：新增局部XML动作采用同一原始小节偏移，固定ID及完整音符不改。
    if arrangement.get('selected_pattern_actions'):
        arrangement['selected_pattern_actions'] = shift_rows(arrangement['selected_pattern_actions'], start)
    # 4/4可选右手与实时谱面试听：新增自然释放投影同样平移到局部XML坐标，原实际音值保留在工程。
    if arrangement.get('natural_release_notation'):
        arrangement['natural_release_notation']=[{**p,'actual_end_tick':p['actual_end_tick']-start,
            'notation_end_tick':p['notation_end_tick']-start} for p in arrangement['natural_release_notation']
            if any(n['id']==p['note_id'] for n in arrangement['notes'])]
    arrangement['configuration']['capo_segments'] = shift_rows(arrangement['configuration'].get('capo_segments', []), start)
    # 吉他编配规则闭环修复：修改和声消费者接入吉他专用简化层，原共享／钢琴材料不变。
    # shared = {**project['shared_analysis'], 'timing': local['timing'], 'statistics': local['statistics'],
    #           'harmony': shift_rows(project['shared_analysis']['harmony'], start),
    # 钢琴同步已认可词音：修改钢琴采用已验收的既有和声整理层，原吉他／共享选择式保留。
    # source_shared = guitar_shared_view(project) if instrument == 'guitar' else project['shared_analysis']
    source_shared = guitar_shared_view(project) if instrument == 'guitar' else project['shared_analysis']
    if instrument == 'piano' and 'piano_label_revision' in project['arrangements']['piano']:
        source_shared = {**source_shared, 'harmony': project['arrangements']['piano']['readable_harmony']}
    shared = {**source_shared, 'timing': local['timing'], 'statistics': local['statistics'],
              'harmony': shift_rows(source_shared['harmony'], start),
              'sections': shift_rows(project['shared_analysis']['sections'], start), '_phrase_harmony_view': True,
              'measure_textures': [{'section': next((s['kind'] for s in project['shared_analysis']['sections']
                                                   if s['start_tick'] <= start < s['end_tick']), 'vocal'), 'kind': 'arpeggio'}]}
    return local, shared, arrangement


def build_xml(project, instrument=None):
    # 最小拍轴与词音伴奏修复：新增按实际2/4、4/4和弱起拼接；每小节独立验时，完整展开不产生短段跳转。
    # 吉他编配规则闭环修复：修改旧时间修订专用表读取，固定拍工程也使用真实派生边界。
    # timeline = project['accepted_vocal_project']['timing']['measure_timeline']
    timeline = measure_timeline(project)
    root = None
    for measure in timeline:
        voice, shared, arrangement = local_view(project, measure, instrument)
        piece = score.build_musicxml(voice) if instrument is None else export.build_musicxml(shared, voice, arrangement)[0]
        if root is None:
            root = deepcopy(piece)
            root.find('part').clear()
            root.find('part').set('id', 'P1')
        node = piece.find('part/measure')
        # 钢琴同步已认可词音：新增钢琴加九和弦只用标准kind及degree表达，避免渲染成add9(add9)；吉他写出保持。
        if instrument == 'piano':
            for harmony_node in node.findall('harmony'):
                kind = harmony_node.find('kind')
                if (kind is not None and kind.get('text') in ('add9', 'madd9')
                        and any(d.findtext('degree-value') == '9' for d in harmony_node.findall('degree'))):
                    kind.attrib.pop('text', None)
        # 局部词音归属修订：新增轻声字以文字方向记入口，绝不为音高未定字生成假音符或MIDI。
        if instrument is None:
            for cue in project['accepted_vocal_project'].get('unpitched_lyric_cues', []):
                if measure['start_tick'] <= cue['start_tick'] < measure['end_tick']:
                    direction = ET.Element('direction', {'placement': 'above', 'id': cue['id']})
                    score.tag(score.tag(direction, 'direction-type'), 'words', cue['text'] + '（轻声，音高未定）')
                    score.tag(direction, 'offset', cue['start_tick'] - measure['start_tick'])
                    node.insert(1, direction)
            # 两处我局部词音核对：新增局部短下滑的XML演唱提示，保留原音段且不伪造固定终止音。
            for note in project['accepted_vocal_project']['quantized_notes']:
                if (note.get('pitch_motion', {}).get('kind') == 'short_falling_glide'
                        and measure['start_tick'] <= note['start_tick'] < measure['end_tick']):
                    direction = ET.Element('direction', {'placement': 'above', 'id': note['id'] + '.pitch_motion'})
                    text = project['accepted_vocal_project']['lyrics']['characters'][note['lyric_index']]['text']
                    score.tag(score.tag(direction, 'direction-type'), 'words', text + '：短下滑（落音未定）')
                    score.tag(direction, 'offset', note['start_tick'] - measure['start_tick'])
                    node.insert(1, direction)
        # 最小拍轴与词音伴奏修复：修改对外小节号，原内部编号保留；弱起编号0，正文从1起，简谱和钢琴显示一致。
        # node.set('number', str(measure['number']))
        node.set('number', str(measure['number'] - int(timeline[0]['pickup'])))
        node.set('text', '弱起' if measure['pickup'] else str(measure['number'] - int(timeline[0]['pickup'])))
        if measure['pickup']:
            node.set('implicit', 'yes')
            node.find('attributes/time/beats').text = '4'
        for item in node.iter():
            if item.get('id'):
                item.set('id', f"m{measure['number']}_" + item.get('id'))
        for direction in list(node.findall('direction')):
            words = direction.find('direction-type/words')
            # 最小拍轴与词音伴奏修复：修改隐藏速度字样的操作，原删整段式保留；声音速度必须完整留下。
            # if words is not None and ('自动草稿' in (words.text or '') or (measure['number'] > 1 and 'BPM' in (words.text or ''))):
            if words is not None and '自动草稿' in (words.text or ''):
                node.remove(direction)
            elif measure['number'] > 1 and (direction.find('direction-type/metronome') is not None
                                            or (words is not None and 'BPM' in (words.text or ''))):
                direction.find('direction-type').clear()
                score.tag(direction.find('direction-type'), 'words', '', **{'print-object': 'no'})
        if measure['number'] > 1:
            for barline in list(node.findall('barline')):
                node.remove(barline)
        root.find('part').append(node)
    for node in list(root.find('part'))[:-1]:
        for barline in list(node.findall('barline')):
            node.remove(barline)
    # 最小拍轴与词音伴奏修复：新增整曲唯一终止线；局部适配器的小节终止线不重复进入正文。
    score.tag(score.tag(root.findall('part/measure')[-1], 'barline', location='right'), 'bar-style', 'light-heavy')
    # 最小拍轴与词音伴奏修复：新增合并单小节适配时重复的谱号／调号／拍号；真实2/4和返回4/4继续显示。
    previous_attributes = {}
    for measure in root.findall('part/measure'):
        attrs = measure.find('attributes')
        if attrs is None:
            continue
        for item in list(attrs):
            key = (item.tag, item.get('number'))
            value = ET.tostring(item, encoding='unicode')
            if previous_attributes.get(key) == value:
                attrs.remove(item)
            else:
                previous_attributes[key] = value
        if not len(attrs):
            measure.remove(attrs)
    return root


def inspect_xml(root, timeline, instrument=None):
    # 最小拍轴与词音伴奏修复：新增独立游标读回，双手backup、同起chord和弱起按实际长度校验。
    errors, rows = [], []
    for expected, measure in zip(timeline, root.findall('part/measure')):
        cursor, highest = 0, 0
        for node in measure:
            duration = int(node.findtext('duration', '0'))
            if node.tag == 'backup':
                cursor -= duration
            elif node.tag == 'forward':
                cursor += duration
            elif node.tag == 'note' and node.find('grace') is None and node.find('chord') is None:
                cursor += duration
            highest = max(highest, cursor)
            if cursor < 0:
                errors.append('negative_cursor_' + str(expected['number']))
        length = expected['end_tick'] - expected['start_tick']
        if highest != length or cursor != length:
            errors.append('measure_duration_' + str(expected['number']))
        rows.append({'measure': expected['number'], 'expected_ticks': length, 'actual_ticks': highest})
    if len(rows) != len(timeline):
        errors.append('missing_measure')
    return {'valid': not errors, 'errors': errors, 'measure_durations': rows}


def svg_node(parent, kind, text=None, **attrs):
    # 最小拍轴与词音伴奏修复：新增可核验SVG节点，属性保留实际音符身份／拍位。
    node = ET.SubElement(parent, NS + kind, {key.replace('_', '-'): str(value) for key, value in attrs.items()})
    if text is not None:
        node.text = str(text)
    return node


# 吉他编配规则闭环修复：修改单遍接口，原接口保留；同段各遍沿同一真实时间列叠人声。
# def render_row(project, measures, guitar=False):
def render_row(project, measures, guitar=False, vocal_measures=None):
    # 最小拍轴与词音伴奏修复：新增同一拍位坐标的人声与TAB，沿用已有简谱字形和节奏规则。
    pieces, total_width = [], 15
    # 吉他编配规则闭环修复：新增各遍共用留白，伴奏仅绘一次，允许人声／歌词细节不同。
    from guitar_repeat_score import union_cells
    from guitar_time_alignment import annotate_vocal_glyphs
    layers = vocal_measures or [measures]
    extra = (len(layers) - 1) * 190 if guitar else 0
    for column, measure in enumerate(measures):
        voice, shared, arrangement = local_view(project, measure, 'guitar')
        # 吉他编配规则闭环修复：修改旧单层布局，保留旧式并联合所有遍次的真实字形空间。
        # scene = export.vocal_row(voice, 1, 1)
        # scene = export.joint_guitar_layout(scene, arrangement if guitar else {'notes': []}, voice['statistics']['bar_ticks'], 1, 1)
        scenes = [export.vocal_row(local_view(project, layer[column])[0], 1, 1) for layer in layers]
        drawing = arrangement if guitar else {'notes': []}
        drawing = {**drawing, '_repeat_cells': union_cells(scenes, drawing, voice['statistics']['bar_ticks'], [])}
        scenes = [export.joint_guitar_layout(scene, drawing, voice['statistics']['bar_ticks'], 1, 1) for scene in scenes]
        scene = scenes[0]
        box = scene.measure_boxes[1]
        width = box['width'] + 26
        # 吉他编配规则闭环修复：修改行元数据保存所有遍次，原单scene项保留。
        # pieces.append((measure, voice, arrangement, scene, box, total_width, width))
        pieces.append((column, measure, voice, arrangement, scenes, box, total_width, width))
        total_width += width
    # 吉他编配规则闭环修复：修改高度按真实人声遍次扩展，旧固定高度保留。
    # root = ET.Element(NS + 'svg', {'viewBox': f'0 0 {total_width + 15:g} {500 if guitar else 250}',
    #                               'width': str(total_width + 15), 'height': '500' if guitar else '250',
    height = (500 if guitar else 250) + extra
    root = ET.Element(NS + 'svg', {'viewBox': f'0 0 {total_width + 15:g} {height}',
                                  'width': str(total_width + 15), 'height': str(height),
                                  # 最小拍轴与词音伴奏修复：新增弱起行的原生宽度上限，避免单小节被放大到整行。
                                  # 最小拍轴与词音伴奏修复：修改所有参考行的最小可读比例，原仅上限式保留；密集正文可横向查看。
                                  # 'style': f'max-width:{total_width + 15:g}px'})
                                  'style': f'min-width:{(total_width + 15) * .64:g}px;max-width:{total_width + 15:g}px'})
    # 吉他编配规则闭环修复：修改背景／解包为动态层数，原式保留。
    # svg_node(root, 'rect', x=0, y=0, width=total_width + 15, height=500 if guitar else 250, fill='white')
    # for measure, voice, arrangement, scene, box, left, width in pieces:
    svg_node(root, 'rect', x=0, y=0, width=total_width + 15, height=height, fill='white')
    for column, measure, voice, arrangement, scenes, box, left, width in pieces:
        start, end = measure['start_tick'], measure['end_tick']
        local_width = box['width']
        def x(tick):
            return left + 13 + export.tick_x(box, tick - start) - box['x']
        # 吉他编配规则闭环修复：修改显示号兼容派生边界，原必需时间修订字段式保留。
        # label = '弱起' if measure['pickup'] else str(measure['number'] - int(project['accepted_vocal_project']['timing']['measure_timeline'][0]['pickup']))
        label = '弱起' if measure['pickup'] else str(measure['number'] - int(measure_timeline(project)[0]['pickup']))
        svg_node(root, 'text', label + (' 2/4' if measure['meter'] == [2, 4] else ''), x=left + 8, y=19,
                 font_size=14, font_family='Microsoft YaHei, sans-serif', fill='#566a74')
        # 新曲慢拍生成与转调标签同步：新增完整小节处的转调提示，与已有真实调号及音符相同，不移任何音。
        original_voice = project['accepted_vocal_project']
        if (original_voice.get('time_only_key_projection', {}).get('version') == 1
                and any(s['start_measure'] == measure['number'] and measure['number'] > 1
                        for s in original_voice['notation'].get('key_segments', []))):
            svg_node(root, 'text', '转1=' + voice['notation']['key']['jianpu_one'], x=left + 55, y=19,
                     font_size=17, font_family='Microsoft YaHei, sans-serif', fill='#205a98')
        # 吉他编配规则闭环修复：修改原单遍嵌套层，原代码保留为注释；各遍原音符身份／歌词完整。
        # nested = svg_node(root, 'svg', x=left, y=145 if guitar else 34, width=width, height=190,
        #                   style=f'width:{width:g}px;height:190px;max-width:none',
        #                   viewBox=f"{box['x'] - 13:g} 0 {width:g} 190")
        # inner = ET.fromstring(scene.svg())
        # for node in inner:
        #     for child in node.iter():
        #         if child.get('id'):
        #             child.set('id', f"row_m{measure['number']}_" + child.get('id'))
        #     nested.append(node)
        for layer_index, scene in enumerate(scenes):
            source_measure = layers[layer_index][column]
            nested = svg_node(root, 'svg', x=left, y=(145 if guitar else 34) + layer_index * 190,
                              width=width, height=190, style=f'width:{width:g}px;height:190px;max-width:none',
                              viewBox=f"{box['x'] - 13:g} 0 {width:g} 190", data_vocal_pass=layer_index + 1,
                              data_source_measure=source_measure['number'], data_shared_measure=measure['number'])
            inner = ET.fromstring(scene.svg())
            annotate_vocal_glyphs(inner, scene)
            for node in inner:
                for child in node.iter():
                    if child.get('id'):
                        child.set('id', f"row_m{measure['number']}_pass{layer_index + 1}_" + child.get('id'))
                nested.append(node)
            # 局部词音归属修订：新增各遍原来源的轻声字入口，使用同一时间列，仅占人声层上方提示空间。
            for cue in project['accepted_vocal_project'].get('unpitched_lyric_cues', []):
                if source_measure['start_tick'] <= cue['start_tick'] < source_measure['end_tick']:
                    at = x(start + cue['start_tick'] - source_measure['start_tick'])
                    cy = (145 if guitar else 34) + layer_index * 190 + 24
                    svg_node(root, 'text', cue['text'] + '（轻声）', x=at, y=cy, font_size=15,
                             text_anchor='middle', fill='#47616e', data_unpitched_lyric=cue['character_index'],
                             data_cue_tick=cue['start_tick'], data_pitch_unspecified='true')
                    svg_node(root, 'line', x1=at, y1=cy + 5, x2=at, y2=cy + 19,
                             stroke='#82929d', stroke_width=.8, stroke_dasharray='2 2')
            # 两处我局部词音核对：新增短下滑的独立演唱箭头，与原音符共用时间列，吉他TAB及节奏不变。
            for note in project['accepted_vocal_project']['quantized_notes']:
                if (note.get('pitch_motion', {}).get('kind') == 'short_falling_glide'
                        and source_measure['start_tick'] <= note['start_tick'] < source_measure['end_tick']):
                    at = x(start + note['start_tick'] - source_measure['start_tick'])
                    cy = (145 if guitar else 34) + layer_index * 190 + 24
                    svg_node(root, 'text', '↘ 短下滑', x=at, y=cy, font_size=15,
                             text_anchor='middle', fill='#47616e', data_pitch_motion='short_falling_glide',
                             data_motion_note_id=note['id'], data_character_index=note['lyric_index'])
            if len(scenes) > 1 and column == 0:
                svg_node(root, 'text', f'{layer_index + 1}.', x=left + 1, y=207 + layer_index * 190,
                         font_size=14, fill='#47616e', data_pass_label=layer_index + 1)
        if not guitar:
            continue
        # 吉他编配规则闭环修复：新增唯一TAB容器下移，为多遍人声留足空间，图式仍在顶部。
        tab_root = svg_node(root, 'g', transform=f'translate(0,{extra})', data_shared_tab='true')
        diagrams = []
        for chart in arrangement.get('fingering_diagrams', []):
            if chart['start_tick'] >= end - start or chart['end_tick'] <= 0:
                continue
            draw = max(0, chart['start_tick'])
            diagram = {**chart, 'draw_tick': draw + start, 'display_end_tick': min(end, chart['end_tick'] + start),
                       'display_id': f"time_diagram_{measure['number']}_{draw}"}
            if diagrams and diagrams[-1]['draw_tick'] == diagram['draw_tick']:
                diagrams[-1] = diagram
            else:
                diagrams.append(diagram)
        # 最小拍轴与词音伴奏修复：新增只显示确实使用的图式，邻近图空间不足时保持名字并将完整图放到附表。
        previous_x = -1000
        # 保音持续按弦与整句八度衔接：新增实际可见图式表；空间不足仅有名称的图式不能让TAB继续写无法解释的x。
        visible_diagrams = []
        for chart in diagrams:
            cx = x(chart['draw_tick'])
            if cx - previous_x >= 72:
                root.append(draw_diagram(chart, cx))
                previous_x = cx
                visible_diagrams.append(chart)
            else:
                svg_node(root, 'text', chart['shape_name'], x=cx, y=140, font_size=13, text_anchor='middle', fill='#254c48')
        for string in range(1, 7):
            y = 337 + (string - 1) * 18
            # 吉他编配规则闭环修复：修改六线谱归属并增加反复符号真实边界标记，旧式保留。
            # svg_node(root, 'line', x1=left + 13, y1=y, x2=left + 13 + local_width, y2=y, stroke='#7c8b94', stroke_width=.8)
            svg_node(tab_root, 'line', x1=left + 13, y1=y, x2=left + 13 + local_width, y2=y,
                     stroke='#7c8b94', stroke_width=.8, **{'class': 'tab-string-line'})
        # 最小拍轴与词音伴奏修复：修改谱线边界，原拍位留白坐标式保留；小节线与人声栏边界对齐，时间列仍留字形边距。
        # for tick in (start, end):
        #     svg_node(root, 'line', x1=x(tick), y1=332, x2=x(tick), y2=432, stroke='#596e7a')
        for edge in (left + 13, left + 13 + local_width):
            # 吉他编配规则闭环修复：修改绘制容器，旧root式保留。
            # svg_node(root, 'line', x1=edge, y1=332, x2=edge, y2=432, stroke='#596e7a')
            svg_node(tab_root, 'line', x1=edge, y1=332, x2=edge, y2=432, stroke='#596e7a')
        for beat in range(0, end - start, 480):
            # 吉他编配规则闭环修复：修改拍号提示跟随TAB层，旧root式保留。
            # svg_node(root, 'text', str(beat // 480 + 1), x=x(start + beat), y=489,
            svg_node(tab_root, 'text', str(beat // 480 + 1), x=x(start + beat), y=489,
                     font_size=11, text_anchor='middle', fill='#82929d')
        attacks = defaultdict(list)
        # 扫弦箭头与实际弦组记谱修正：新增实际扫弦攻击集合，用跨弦箭头代替该次攻击的柱式x／品数。
        from guitar_strum_notation import swept_note_ids
        swept_ids = swept_note_ids(project['arrangements']['guitar'])
        for note in project['arrangements']['guitar']['notes']:
            if note['start_tick'] < start < note['end_tick']:
                # 吉他编配规则闭环修复：修改跨小节续音跟随TAB，旧root式保留。
                # svg_node(root, 'text', '(' + str(note['fret']) + ')', x=x(start) + 7, y=341 + (note['string'] - 1) * 18,
                svg_node(tab_root, 'text', '(' + str(note['fret']) + ')', x=x(start) + 7, y=341 + (note['string'] - 1) * 18,
                         font_size=12, text_anchor='middle', fill='#6d7c82', data_note_id=note['id'], data_continuation='true')
            if not start <= note['start_tick'] < end:
                continue
            # 扫弦箭头与实际弦组记谱修正：新增扫弦只参与真实节奏计数；合拨及分解仍逐弦绘制。
            if note['id'] in swept_ids:
                attacks[note['start_tick']].append(note)
                continue
            at = x(note['start_tick'])
            # 保音持续按弦与整句八度衔接：修改只用当前确实画出的指型解释x，未画出的图保留和弦名、TAB记实品。
            # chart = next((c for c in diagrams if c['draw_tick'] <= note['start_tick'] < c['display_end_tick']), None)
            chart = next((c for c in visible_diagrams if c['draw_tick'] <= note['start_tick'] < c['display_end_tick']), None)
            held = chart is not None and note['fret'] == left_hand_fret(chart, note['string'])
            value = 'x' if held else str(note['fret'])
            # 吉他编配规则闭环修复：修改实际弦品字形跟随TAB，旧root式保留。
            # group = svg_node(root, 'g', data_note_id=note['id'], data_string=note['string'], data_fret=note['fret'], data_start_tick=note['start_tick'])
            group = svg_node(tab_root, 'g', data_note_id=note['id'], data_string=note['string'], data_fret=note['fret'], data_start_tick=note['start_tick'])
            y = 337 + (note['string'] - 1) * 18
            svg_node(group, 'rect', x=at - 8, y=y - 9, width=16, height=19, fill='white')
            svg_node(group, 'text', value, x=at, y=y + 6, font_size=18, text_anchor='middle', fill='#163a45')
            if note.get('melody_accent'):
                svg_node(group, 'circle', cx=at, cy=323, r=3, fill='black')
            attacks[note['start_tick']].append(note)
        rhythms = []
        # 4/4可选右手与实时谱面试听：修改显式型按动作占时画节奏，逐弦余音单独连线；旧默认沿用原长度规则。
        # ticks = sorted(attacks)
        # for index, tick in enumerate(ticks):
        #     length = min(min(n['end_tick'] for n in attacks[tick]), ticks[index + 1] if index + 1 < len(ticks) else end, end) - tick
        from guitar_pattern_performance import rhythm_events as selected_rhythm_events, draw_action_marks
        for tick, length in selected_rhythm_events(project['arrangements']['guitar'],start,end,attacks):
            # 吉他编配规则闭环修复：修改旧32／64分回退为明确拒绝；真实密集拨弦必须在编配层处理。
            # flags = 0 if length >= 480 else 1 if length >= 240 else 2 if length >= 120 else 3 if length >= 60 else 4
            if length < 120:
                raise ValueError('吉他真实音值短于十六分，拒绝用少画连梁掩盖：' + str((measure['number'], tick, length)))
            flags = 0 if length >= 480 else 1 if length >= 240 else 2
            at = x(tick)
            # 吉他编配规则闭环修复：修改节奏符干跟随TAB并记录真实音值，旧root式保留。
            # svg_node(root, 'line', x1=at, y1=435, x2=at, y2=466, stroke='#273c48', stroke_width=1.2)
            svg_node(tab_root, 'line', x1=at, y1=435, x2=at, y2=466, stroke='#273c48', stroke_width=1.2,
                     data_rhythm_duration=length, data_rhythm_tick=tick, data_flags=flags)
            rhythms.append((tick, at, flags))
        for index, (tick, at, flags) in enumerate(rhythms):
            right = rhythms[index + 1] if index + 1 < len(rhythms) else None
            joined = right is not None and (tick - start) // 480 == (right[0] - start) // 480
            for level in range(flags):
                other = right[1] if joined and right[2] > level else at + 9
                # 吉他编配规则闭环修复：修改横梁跟随TAB，旧root式保留。
                # svg_node(root, 'line', x1=at, y1=465 - level * 5, x2=other, y2=465 - level * 5, stroke='#273c48', stroke_width=2)
                svg_node(tab_root, 'line', x1=at, y1=465 - level * 5, x2=other, y2=465 - level * 5, stroke='#273c48', stroke_width=2)
        # 4/4可选右手与实时谱面试听：新增同一TAB上标出扫向、合拨、空扫／制音及完整余音。
        draw_action_marks(tab_root,project['arrangements']['guitar'],start,end,x)
    return ET.tostring(root, encoding='unicode')


def piano_svg(xml_root):
    # 最小拍轴与词音伴奏修复：新增直接渲染真实小节XML，避免原固定小节编号裁谱适配器再次改动拍位。
    import verovio
    toolkit = verovio.toolkit()
    options = {**RENDER_OPTIONS, 'pageWidth': 2700, 'pageHeight': 1700, 'scale': 50, 'breaks': 'none',
               'adjustPageHeight': True, 'header': 'none', 'footer': 'none'}
    if not toolkit.setOptions(options) or not toolkit.loadData(ET.tostring(xml_root, encoding='unicode')):
        raise ValueError('可变小节钢琴渲染失败：' + toolkit.getLog())
    if toolkit.getPageCount() != 1:
        raise ValueError('钢琴四小节参考行意外分页')
    return toolkit.renderToSVG(1)


def write_meter_events(path, timeline):
    # 最小拍轴与词音伴奏修复：新增MIDI真实换拍号；不以单一4/4元信息掩盖谱上的两拍过门。
    import mido
    midi = mido.MidiFile(str(path))
    first = midi.tracks[0]
    tick, values = 0, []
    for message in first:
        tick += message.time
        if message.type != 'time_signature':
            values.append((tick, 2 if message.type == 'end_of_track' else 0, message))
    previous = None
    expected = []
    for measure in timeline:
        meter = (4, 4) if measure['pickup'] else tuple(measure['meter'])
        if meter != previous:
            values.append((measure['start_tick'], -2, mido.MetaMessage('time_signature', numerator=meter[0], denominator=meter[1])))
            expected.append((measure['start_tick'], *meter))
            previous = meter
    first.clear()
    prior = 0
    for tick, priority, message in sorted(values, key=lambda r: (r[0], r[1])):
        first.append(message.copy(time=tick - prior))
        prior = tick
    midi.save(str(path))
    observed, tick = [], 0
    for message in mido.MidiFile(str(path)).tracks[0]:
        tick += message.time
        if message.type == 'time_signature':
            observed.append((tick, message.numerator, message.denominator))
    if observed != expected:
        raise ValueError('MIDI实际换拍号与小节边界不一致')
    return observed


def trim_excerpt_continuations(root):
    # 最小拍轴与词音伴奏修复：新增四小节视觉节选的外接延音／踏板边界处理；完整XML与试听不变。
    notes = root.findall('part/measure/note')
    pitches = defaultdict(list)
    for node in notes:
        if node.find('pitch') is not None:
            pitches[(node.findtext('staff', '1'), ET.tostring(node.find('pitch')))].append(node)
    for group in pitches.values():
        for node, kind in ((group[0], 'stop'), (group[-1], 'start')):
            for tie in list(node.findall('tie')):
                if tie.get('type') == kind:
                    node.remove(tie)
            for tied in list(node.findall('notations/tied')):
                if tied.get('type') == kind:
                    node.find('notations').remove(tied)
    starts = []
    for measure in root.findall('part/measure'):
        for direction in list(measure.findall('direction')):
            pedal = direction.find('direction-type/pedal')
            if pedal is None:
                continue
            if pedal.get('type') == 'start':
                starts.append((measure, direction))
            elif not starts:
                measure.remove(direction)
            else:
                starts.pop(0)
    for measure, direction in starts:
        measure.remove(direction)


# 吉他编配规则闭环修复：修改可选乐器导出接口，原整套签名保留；不删除工程中其它声部。
# def export_revision(project_path, output):
def write_variable_repeat_score(project, folder):
    # 吉他编配规则闭环修复：新增长段计划实际印刷，复用既有符号和独立展开验收；不改任何演奏数据。
    from guitar_repeat_marks import marker_specs, draw_annotations, validate_marks
    from guitar_repeat_score import draw_marker, REPEAT_STYLE, REPEAT_SCRIPT
    plan = build_repeat_plan(project)
    validation = validate_repeat_plan(plan, project)
    if not validation['valid']:
        raise ValueError('长段反复计划未通过：' + str(validation['errors']))
    timeline = measure_timeline(project)
    pickup = int(timeline[0]['pickup'])
    source = (folder / 'score.html').read_text('utf-8')
    # 相似长段复用与默认阅读修复：新增幂等清理仅属于展开页的提示和返回链接，避免刷新后带入主阅读谱。
    source=re.sub(r'<div[^>]*data-layout-notice="unfolded"[^>]*>.*?</div>','',source,flags=re.S)
    source=source.replace('<a href="score.html">长段阅读谱</a>','').replace('<a href="score.html">复用阅读谱</a>','')
    # 相似长段复用与默认阅读修复：修改展开对照页增加明显身份及阅读谱入口，不能让无折叠页被误认为主阅读谱。
    # full = source.replace('<nav>', '<nav><a href="score.html">长段阅读谱</a>', 1)
    # 相似长段复用与默认阅读修复：修改提示增加专属身份，刷新不重复或污染主阅读页。
    # full_notice=('<div class="notice no-print"><strong>当前是完整展开对照版：所有小节按原曲顺序写出。</strong> '
    full_notice=('<div class="notice no-print" data-layout-notice="unfolded"><strong>当前是完整展开对照版：所有小节按原曲顺序写出。</strong> '
                 '<a href="score.html" style="display:inline-block;padding:8px 14px;background:#315b48;color:white;border-radius:6px">'
                 '打开复用阅读谱（反复／房子／D.S.）</a></div>')
    full = source.replace('<nav>', full_notice+'<nav><a href="score.html">复用阅读谱</a>', 1)
    (folder / 'score_full.html').write_text(full, 'utf-8')
    first_row = source.index('<section class="score-row')
    prefix = source[:first_row]
    prefix = prefix.replace('<nav>', '<nav><a href="score_full.html">完整展开谱</a>', 1)
    # 吉他编配规则闭环修复：新增保留通用播放器脚本尾部，折叠只替换谱行与阅读导航。
    last_row_end = source.rindex('</section>') + len('</section>')
    suffix = source[last_row_end:]
    specs = marker_specs(plan); printed_rows = []; html_rows = []; payload = []
    def span_label(first, last):
        return '弱起' if first == last == 1 and pickup else f'第{first - pickup}–{last - pickup}小节'
    for line, block in enumerate(plan['blocks'], 1):
        first, last = block['canonical_first'], block['canonical_last']
        canonical = timeline[first - 1:last]
        layers = [timeline[o['first'] - 1:o['last']] for o in block['occurrences']]
        root = ET.fromstring(render_row(project, canonical, True, vocal_measures=layers))
        width, original_height = float(root.get('width')), float(root.get('height'))
        # 完整乐句与实际时长复用：修改仅有导航符号的行预留上下空间；普通行不因启用复用额外加70像素空白。
        # height = original_height + 70
        has_marks=bool(specs.get(block['id']))
        height = original_height + (70 if has_marks else 0)
        outer = ET.Element(NS + 'svg', {'width': str(width), 'height': str(height),
                                       'viewBox': f'0 0 {width:g} {height:g}',
                                       'style': f'min-width:{width * .64:g}px;max-width:{width:g}px',
                                       'data-block-id': block['id']})
        svg_node(outer, 'rect', width=width, height=height, fill='white')
        wrapper = svg_node(outer, 'g', **{'class': 'repeat-block', 'data-block-id': block['id'],
                                        'id': 'block-' + block['id'], 'height': height})
        # 完整乐句与实际时长复用：修改正文纵向偏移与实际符号预留一致，不改变音符之间的相对位置。
        # body = svg_node(wrapper, 'g', transform='translate(0,40)')
        body = svg_node(wrapper, 'g', transform='translate(0,40)' if has_marks else 'translate(0,0)')
        for child in root:
            if child.tag != NS + 'rect':
                body.append(child)
        draw_annotations(wrapper, specs.get(block['id'], []), draw_marker)
        # 相似长段复用与默认阅读修复：新增将真实各遍变奏并列画出，音乐对象和原曲顺序不变。
        from guitar_repeat_variants import append_variant_tabs
        append_variant_tabs(outer,wrapper,project,plan,block,render_row,timeline)
        svg = ET.tostring(outer, encoding='unicode')
        (folder / 'rows' / f'repeat_{line:03}.svg').write_text(svg, 'utf-8')
        printed_rows.append({'line': line, 'blocks': [block['id']], 'guitar': svg})
        label = span_label(first, last)
        if block.get('display_label'):
            label += ' · ' + block['display_label']
        controls = []
        for occurrence in block['occurrences']:
            start = timeline[occurrence['first'] - 1]['start_seconds']
            end = timeline[occurrence['last'] - 1]['end_seconds']
            occurrence_name = span_label(occurrence['first'], occurrence['last'])
            payload.append({**occurrence, 'label': occurrence_name, 'origin': 0.,
                            'section_label': block.get('display_label', '').replace(' · 续', ''),
                            'start_second': start, 'end_second': end})
            caption = ('第' + str(occurrence['pass']) + '遍 · ') if len(layers) > 1 else ''
            controls.append('<span class="repeat-occurrence" data-occurrence-id="' + occurrence['id'] + '"><button data-singing-second="'
                            + str(max(0., start)) + '">' + html.escape(caption + occurrence_name + ' 试听') + '</button></span>')
        html_rows.append('<section class="score-row guitar-score-row repeat-score-row" style="overflow-x:auto;--score-native-width:'
                         + str(width) + '"><header>' + html.escape(label) + '</header><div class="repeat-navigation no-print">'
                         + ''.join(controls) + '</div>' + svg + '</section>')
    mark_validation = validate_marks(plan, printed_rows)
    # 吉他编配规则闭环修复：新增从实际渲染结果核对各遍人声和唯一TAB的逐小节覆盖。
    layer_errors = []
    for block, row in zip(plan['blocks'], printed_rows):
        root = ET.fromstring(row['guitar'])
        source_measures = [int(n.get('data-source-measure')) for n in root.iter() if n.get('data-vocal-pass')]
        expected = [m for offset in range(block['length_bars']) for o in block['occurrences'] for m in [o['first'] + offset]]
        if source_measures != expected:
            layer_errors.append('多遍人声层未覆盖全部来源小节：' + block['id'])
        tab_ids = [n.get('data-note-id') for n in root.iter() if n.get('data-string')]
        # 扫弦箭头与实际弦组记谱修正：新增复用阅读谱从真实箭头／指型读取扫弦音，不能把合法箭头误判为漏音。
        from guitar_strum_notation import read_visible_strums
        swept,arrow_errors=read_visible_strums(root,project['arrangements']['guitar'])
        tab_ids.extend(note[0] for note in swept)
        layer_errors.extend(arrow_errors)
        start, end = timeline[block['canonical_first'] - 1]['start_tick'], timeline[block['canonical_last'] - 1]['end_tick']
        # 相似长段复用与默认阅读修复：修改实际TAB覆盖需同时包含明确变奏，不把省略的第二遍差异漏掉。
        # expected_ids = [n['id'] for n in project['arrangements']['guitar']['notes'] if start <= n['start_tick'] < end]
        from guitar_repeat_variants import block_variants
        printed_spans=[(start,end)]+[(timeline[v['source_measure']-1]['start_tick'],timeline[v['source_measure']-1]['end_tick'])
                                    for v in block_variants(plan,block)]
        expected_ids = [n['id'] for n in project['arrangements']['guitar']['notes'] if any(a<=n['start_tick']<b for a,b in printed_spans)]
        if sorted(tab_ids) != sorted(expected_ids):
            layer_errors.append('共用TAB出现漏音或重复字形：' + block['id'])
    if not mark_validation['valid'] or layer_errors:
        raise ValueError('实际长段谱面未通过：' + str(mark_validation['errors'] + layer_errors))
    # 相似长段复用与默认阅读修复：新增独立核对实际变奏说明和来源，不能仅凭候选字段宣称差异已保留。
    from guitar_repeat_variants import validate_variant_tabs
    variant_validation=validate_variant_tabs(project,plan,printed_rows)
    if not variant_validation['valid']:raise ValueError('实际变奏谱面未通过：'+str(variant_validation['errors']))
    payload.sort(key=lambda item: item['first'])
    lookup = {o['id']: o for o in payload}
    navigation = ''.join('<a href="#block-' + lookup[r['occurrence_id']]['block_id'] + '" data-focus-occurrence="'
                         + r['occurrence_id'] + '">' + html.escape(r['label'] + ' · ' + span_label(r['first'], r['last'])) + '</a>'
                         for r in plan['reading_route'])
    notice = ('<p>共用' + str(plan['folded_blocks']) + '段，省去' + str(plan['saved_bars']) + '个重复书写小节。共用段各遍人声上下排列，六线谱共用。</p>'
              # 相似长段复用与默认阅读修复：修改无合格长段的说明，实际已同时检查精确共用与少量明确变奏。
              # if plan['folded_blocks'] else '<p>已检查长段复用；当前实际伴奏没有满足至少8小节连续相同且沿乐句边界的段落，本谱顺序写出。</p>')
              if plan['folded_blocks'] else '<p>已检查完整长段及少量变奏的复用；当前没有兼顾实际音乐与清楚读法的合格长段，本谱顺序写出。</p>')
    # 相似长段复用与默认阅读修复：修改读法加入本小节替换规则，不让变奏被误当额外追加或短回跳。
    # legend = '<details class="no-print"><summary>反复读法</summary><p>普通反复奏两遍，一、二房子保留不同结尾；D.S.回指定记号，To Coda／Fine只在回跳后执行。试听与下载保持完整原曲顺序。</p></details>'
    variation_notice=(f'<p>其中{plan.get("variant_printed_bars",0)}个小节各遍奏法不同，已在对应行下方标明；第二遍只替换该小节，不多弹一小节，也不另作短回跳。</p>'
                      if plan.get('variant_printed_bars') else '')
    legend = '<details class="no-print"><summary>反复读法</summary><p>普通反复奏两遍，一、二房子保留不同结尾；D.S.回指定记号，To Coda／Fine只在回跳后执行。试听与下载保持完整原曲顺序。</p></details>'
    # 相似长段复用与默认阅读修复：修改主阅读页显示明确变奏数量和读法；原顺序保留。
    # page = prefix + '<style>' + REPEAT_STYLE + '</style>' + notice + legend
    page = prefix + '<style>' + REPEAT_STYLE + '</style>' + '<p><strong>复用阅读谱</strong> · 试听仍为完整原曲顺序</p>'+notice+variation_notice+legend
    page += '<div class="repeat-controls no-print"><label><input id="repeat-follow" type="checkbox" checked>播放时跟随乐段</label><div id="repeat-now"></div></div>'
    page += '<div class="repeat-route no-print">' + navigation + '</div>' + ''.join(html_rows)
    page += '<script>window.guitarRepeatRoute=' + json.dumps(payload, ensure_ascii=False).replace('</', '<\\/') + ';</script><script>' + REPEAT_SCRIPT + '</script>' + suffix
    (folder / 'score.html').write_text(page, 'utf-8')
    validation.update(print_marks=mark_validation, complete_vocal_layers_and_unique_tab=True,
                      chronological_musicxml_midi_audio_unchanged_by_repeat=True)
    # 相似长段复用与默认阅读修复：新增实际变奏图元验收随最终交付保存。
    validation['explicit_variants']=variant_validation
    score.save_json(folder / 'repeat_plan.json', plan)
    score.save_json(folder / 'repeat_validation.json', validation)
    # 相似长段复用与默认阅读修复：新增仅清理当前输出目录内已被新分行替代的派生SVG，旧版本目录不操作。
    expected_rows={(folder/'rows'/f'repeat_{number:03}.svg').resolve() for number in range(1,len(printed_rows)+1)}
    for stale in (folder/'rows').glob('repeat_*.svg'):
        if stale.resolve() not in expected_rows and stale.parent.resolve()==(folder/'rows').resolve():stale.unlink()
    return validation


# 新曲慢拍生成与转调标签同步：新增按实际字形宽度分行，显式新预览使用；不会压缩音符或改变时间列。
def readable_notation_blocks(project, measures, native_width_budget=2000, maximum_bars=4):
    rows, current, width = [], [], 30.
    for measure in measures:
        single = ET.fromstring(render_row(project, [measure]))
        addition = float(single.get('width')) - 30.
        if current and (len(current) >= maximum_bars or width + addition > native_width_budget):
            rows.append(current)
            current, width = [], 30.
        current.append(measure)
        width += addition
    if current:
        rows.append(current)
    return rows


# 局部两拍过渡听辨修订：修改显式原样音频继承，仅允许通过完整音乐冻结验证的局部分组工程。
# def export_revision(project_path, output, instruments=None):
def export_revision(project_path, output, instruments=None, preserve_audio_from=None):
    # 最小拍轴与词音伴奏修复：新增独立交付，音乐未决标志始终随谱面／工程保存，禁止调用正常入口更新。
    import soundfile as sf
    root_dir = Path(__file__).resolve().parents[1]
    output = require_isolated_output(output, root_dir)
    output.mkdir(parents=True, exist_ok=True)
    project = score.read_json(project_path)
    voice = project['accepted_vocal_project']
    # 4/4可选右手与实时谱面试听：新增实际选型守卫先于旧时间层证据；旧认证在来源版本验证。
    from guitar_pattern_selection import has_selection, legacy_source, require_selection
    selection_active = has_selection(project)
    if selection_active:require_selection(project)
    # 局部两拍过渡听辨修订：新增无重合成的原音频继承守卫；并验证新边界不能改变任何实际音乐字段。
    if project.get('bar_boundary_revision'):
        from reviewed_bar_boundaries import verify_revision
        # 4/4可选右手与实时谱面试听：修改仅授权右手新版本使用已绑定的旧分组来源。
        # verify_revision(project)
        verify_revision(legacy_source(project) if selection_active else project)
    if preserve_audio_from is not None:
        import shutil
        if not project.get('bar_boundary_revision'):raise ValueError('只有冻结音乐的局部小节修订可继承原试听')
        preserve_audio_from=Path(preserve_audio_from).resolve()
        if preserve_audio_from!=Path(project['bar_boundary_revision']['source_project']).parent.resolve():
            raise ValueError('试听不是绑定的原工程')
    # 慢拍单位与两曲最小修订：新增普通时间导出同样验证完整共享分析的原工程投影，不可只保留新摘要。
    if voice.get('meter_unit_correction'):
        from meter_unit_entry import verify_projected_shared
        # 4/4可选右手与实时谱面试听：修改原单位投影在祖先重放，新声部与时间保护由选型守卫验证。
        # verify_projected_shared(project)
        verify_projected_shared(legacy_source(project) if selection_active else project)
    # 吉他编配规则闭环修复：新增所有实际导出前运行同一硬验收，错误先留隔离证据，禁止继续写出。
    # 尾段原声局部补证：新增实际两乐器尾部守卫；既有v1及已认可旧工程无此新来源层，继续原策略。
    if voice.get('first_source_meter_correction',{}).get('version')==2:
        from first_generation_tail import require_terminal_arrangements
        require_terminal_arrangements(project['shared_analysis'],voice,project['arrangements'])
    from guitar_readability_acceptance import assess_guitar_readability, require_guitar_readability
    selected = tuple(instruments) if instruments is not None else ('vocal', *project['arrangements'])
    if not selected or any(i != 'vocal' and i not in project['arrangements'] for i in selected):
        raise ValueError('导出乐器为空或不存在于当前工程')
    # 钢琴同步已认可词音：新增所有钢琴实际导出前核对派生和声来源，失效时停止，不能沿用旧标记。
    if 'piano' in selected and 'piano_label_revision' in project['arrangements']['piano']:
        from piano_harmony_readability import assess_piano_labels
        piano_labels = assess_piano_labels(project)
        if not piano_labels['valid']:
            raise ValueError('钢琴和声标记验收失败：' + str(piano_labels['errors']))
    if 'guitar' in selected:
        preflight = assess_guitar_readability(project, repeat_plan=build_repeat_plan(project))
        score.save_json(output / 'guitar_readability_preflight.json', preflight)
        require_guitar_readability(project, preflight, final=False)
    # 吉他编配规则闭环修复：修改原仅时间修订输入，旧原始拍轴工程也能隔离回归。
    # timeline = voice['timing']['measure_timeline']
    # duration = voice['time_only_revision']['source_duration_seconds']
    timeline = measure_timeline(project)
    binding = project['shared_analysis']['input_binding']
    duration = voice.get('time_only_revision', {}).get('source_duration_seconds', binding['sources']['mix']['duration_seconds'])
    source = binding['sources']['vocals']
    if score.sha256(source['path']) != source['sha256']:
        raise ValueError('合播原唱来源已改变')
    raw, rate = sf.read(local_path(source['path']), dtype='float32', always_2d=True)
    original_voice, placement = align_samples(raw, rate, 22050, source.get('offset_seconds', 0.), math.ceil(duration * 22050))
    # 最小拍轴与词音伴奏修复：新增统一试听增益，分离原唱允许浮点峰值大于1，写16bit前不能截掉瞬态；原始文件保持。
    voice_scale = min(1., .97 / max(1e-9, float(np.max(abs(original_voice)))))
    original_voice *= voice_scale
    alignment = {'sample_rate': 22050, 'source_sha256': source['sha256'], 'frames': len(original_voice),
                 'origin_song_seconds': 0., 'channels': original_voice.shape[1], 'duration_seconds': duration,
                 'placement': placement, 'voice_scale': voice_scale, 'vocal_kind': 'original_separated_singer_audio'}
    audio = output / 'audio'
    audio.mkdir(exist_ok=True)
    # 局部两拍过渡听辨修订：修改仅局部分组模式复制原唱；旧导出仍按原路线处理。
    # sf.write(audio / 'original_vocals.wav', original_voice, 22050, subtype='PCM_16')
    # write_ogg(audio / 'original_vocals.ogg', original_voice, 22050)
    # score.save_json(audio / 'vocal_alignment.json', alignment)
    if preserve_audio_from is None:
        sf.write(audio / 'original_vocals.wav', original_voice, 22050, subtype='PCM_16')
        write_ogg(audio / 'original_vocals.ogg', original_voice, 22050)
        score.save_json(audio / 'vocal_alignment.json', alignment)
    else:
        shutil.copytree(preserve_audio_from/'audio',audio,dirs_exist_ok=True)
    checks = {}
    links = []
    # 吉他编配规则闭环修复：修改原固定全套导出；指定guitar时保留原工程人声／钢琴但只交付所选文件。
    # for instrument in ('vocal', *project['arrangements']):
    # 吉他编配规则闭环修复：所选乐器已在读取音乐后校验，避免编码原唱后才发现无效请求。
    for instrument in selected:
        folder = output / instrument
        folder.mkdir(exist_ok=True)
        (folder / 'rows').mkdir(exist_ok=True)
        is_voice = instrument == 'vocal'
        xml = build_xml(project, None if is_voice else instrument)
        check = inspect_xml(xml, timeline, None if is_voice else instrument)
        if not check['valid']:
            raise ValueError('实际小节XML时值校验失败：' + str((instrument, check['errors'][:8])))
        ET.indent(xml)
        ET.ElementTree(xml).write(folder / 'score.musicxml', encoding='utf-8', xml_declaration=True)
        # 最小拍轴与词音伴奏修复：修改适配器传参，原路径调用保留；压缩器接收实际XML字节并回读验证。
        # write_mxl(folder / 'score.mxl', folder / 'score.musicxml')
        write_mxl(folder / 'score.mxl', (folder / 'score.musicxml').read_bytes())
        if is_voice:
            score.write_midi(folder / 'score.mid', voice)
            # 最小拍轴与词音伴奏修复：修改旋律试听使用实际发声区间，原记谱时值式保留；声母记谱连贯不填造发声。
            # arrangement = {'instrument': 'piano', 'notes': [{**n, 'velocity': 80, 'hand': 'right'} for n in voice['quantized_notes']], 'pedal': []}
            arrangement = {'instrument': 'piano', 'notes': [{**n, 'start_tick': n['playback_start_tick'], 'end_tick': n['playback_end_tick'],
                                                           'velocity': 80, 'hand': 'right'} for n in voice['quantized_notes']], 'pedal': []}
        else:
            arrangement = project['arrangements'][instrument]
            export.write_midi(folder / 'score.mid', arrangement, voice)
            check['midi'] = export.validate_midi(folder / 'score.mid', arrangement, voice)
            if not check['midi']['valid']:
                raise ValueError('MIDI实际音符读回失败：' + str(check['midi']['errors']))
        check['midi_meter_events'] = write_meter_events(folder / 'score.mid', timeline)
        # 局部两拍过渡听辨修订：修改实际音符未变时不重新合成，后续对复制文件执行同样的原曲同步检查。
        # export.synthesize(folder / 'preview.wav', arrangement, voice)
        # preview, preview_rate = sf.read(folder / 'preview.wav', always_2d=True, dtype='float32')
        if preserve_audio_from is None:
            export.synthesize(folder / 'preview.wav', arrangement, voice)
        else:
            for file in (preserve_audio_from/instrument).iterdir():
                # 局部两拍过渡听辨修订：修改复制试听时同时保留离线播放器与内嵌伴奏数据，避免文件存在但合播失效。
                # if file.is_file() and (file.suffix.lower() in ('.wav','.ogg','.mp3') or file.name=='singing_preview.json'):
                if file.is_file() and (file.suffix.lower() in ('.wav','.ogg','.mp3') or file.name in ('singing_preview.json','singing_player.js')):
                    shutil.copy2(file,folder/file.name)
            # 局部两拍过渡听辨修订：新增完整合播依赖检查；缺失源播放器须明确失败，不能输出失效按钮。
            if not is_voice and not (folder/'singing_player.js').is_file():
                raise ValueError('原试听缺少离线合播播放器，不能导出失效试听入口')
        preview, preview_rate = sf.read(folder / 'preview.wav', always_2d=True, dtype='float32')
        # 吉他编配规则闭环修复：修改源音频原点；旧谱可能从负拍预备开始，试听始终按原曲0秒放置。
        # preview, _ = align_samples(preview, preview_rate, 22050, 0., len(original_voice))
        # 局部两拍过渡听辨修订：修改已按原曲0秒保存的音频不得再次施加负弱起偏移或重复编码。
        # preview, preview_placement = align_samples(preview, preview_rate, 22050, SongClock(voice).audio_origin_seconds, len(original_voice))
        # check['preview_source_placement'] = preview_placement
        # sf.write(folder / 'preview.wav', preview, 22050, subtype='PCM_16')
        # if not is_voice:
        #     write_singing_preview(folder, folder / 'preview.wav', original_voice, alignment)
        if preserve_audio_from is None:
            preview, preview_placement = align_samples(preview, preview_rate, 22050, SongClock(voice).audio_origin_seconds, len(original_voice))
            check['preview_source_placement'] = preview_placement
            sf.write(folder / 'preview.wav', preview, 22050, subtype='PCM_16')
            if not is_voice:write_singing_preview(folder, folder / 'preview.wav', original_voice, alignment)
        else:
            if preview_rate!=22050 or len(preview)!=len(original_voice):raise ValueError('原试听时长／采样率与原唱不一致')
            check['preview_source_placement']={'origin_song_seconds':0.,'byte_identical_to_bound_source':True}
        rows = []
        # 最小拍轴与词音伴奏修复：新增弱起独立行，之后每行最多四小节，完整展开避免零碎回跳。
        blocks = ([timeline[:1]] if timeline[0]['pickup'] else [])
        regular = timeline[1:] if timeline[0]['pickup'] else timeline
        # 保音持续按弦与整句八度衔接：修改展开谱沿用相同显示行宽，原4小节分组保留，钢琴／人声及旧工程不改。
        # blocks.extend(regular[i:i + 4] for i in range(0, len(regular), 4))
        line_bars = project['arrangements']['guitar']['configuration'].get('maximum_bars_per_reading_line', 4) if instrument == 'guitar' else 4
        # 保音持续按弦与整句八度衔接：修改展开谱与反复谱共用逐行预算；其它乐器及无预算旧工程仍原4小节。
        # blocks.extend(regular[i:i + line_bars] for i in range(0, len(regular), line_bars))
        if instrument == 'guitar':
            from guitar_repeat_readability import reading_line_end
            cursor = 0
            while cursor < len(regular):
                last = reading_line_end(project['arrangements']['guitar'], regular[cursor]['number'], regular[-1]['number'])
                finish = cursor + last - regular[cursor]['number'] + 1
                blocks.append(regular[cursor:finish])
                cursor = finish
        # 新曲慢拍生成与转调标签同步：修改显式新预览的声乐／钢琴分行，原固定行数保留供历史重导。
        # else:
        #     blocks.extend(regular[i:i + line_bars] for i in range(0, len(regular), line_bars))
        # 慢拍单位与两曲最小修订：修改慢拍投影也按实际字列宽度分行；合并后不能仍固定四小节而横向裁掉歌词。
        # elif project.get('source_preview_layout', {}).get('version') == 1:
        elif (project.get('source_preview_layout', {}).get('version') == 1
              or voice.get('meter_unit_correction')):
            blocks.extend(readable_notation_blocks(project, regular))
        else:
            blocks.extend(regular[i:i + line_bars] for i in range(0, len(regular), line_bars))
        for measures in blocks:
            first, last = measures[0]['number'], measures[-1]['number']
            svg = render_row(project, measures, instrument == 'guitar')
            # 最小拍轴与词音伴奏修复：新增在拼接钢琴SVG之前解析原生宽度；嵌套SVG不能用字符串截断解析。
            native_width = ET.fromstring(svg).get('width')
            (folder / 'rows' / f'voice_{first:03}_{last:03}.svg').write_text(svg, 'utf-8')
            if instrument == 'piano':
                subset = deepcopy(xml)
                # 最小拍轴与词音伴奏修复：修改裁谱按内部顺序，原按显示号式保留；弱起显示0不能改变实际选取范围。
                # for measure in list(subset.find('part')):
                #     if not first <= int(measure.get('number')) <= last:
                for index, measure in enumerate(list(subset.find('part')), 1):
                    if not first <= index <= last:
                        subset.find('part').remove(measure)
                # 最小拍轴与词音伴奏修复：新增节选首端的完整大谱表属性，整曲去重后节选仍需自己的谱号／调号。
                holder = ET.Element('temporary')
                export.xml_attributes(holder, voice['notation']['key'], measures[0]['meter'], 'piano', initial=True)
                first_measure = subset.find('part/measure')
                old_attributes = first_measure.find('attributes')
                if old_attributes is not None:
                    first_measure.remove(old_attributes)
                first_measure.insert(0, holder[0])
                trim_excerpt_continuations(subset)
                staff = piano_svg(subset)
                (folder / 'rows' / f'staff_{first:03}_{last:03}.svg').write_text(staff, 'utf-8')
                svg += staff
            # 最小拍轴与词音伴奏修复：修改吉他行最小可读比例，原无原生宽度式保留；密集行可横向查看。
            # rows.append(f'<section class="score-row"><header>第{first}–{last}小节 ...'
            # 最小拍轴与词音伴奏修复：删除不支持嵌套的开发解析式，原式保留；宽度在上方从完整XML读取。
            # native_width = ET.fromstring(svg.split('</svg>')[0] + '</svg>').get('width') if instrument != 'piano' else None
            row_class = 'score-row guitar-score-row' if instrument == 'guitar' else 'score-row'
            # 最小拍轴与词音伴奏修复：修改为单一style属性，旧分支式保留；三类谱都明确横向溢出，打印由下方覆盖。
            # row_style = f' style="--score-native-width:{native_width}"' if instrument == 'guitar' else ''
            row_style = f' style="overflow-x:auto;--score-native-width:{native_width}"'
            # 最小拍轴与词音伴奏修复：新增三类谱面都可横向查看，原仅吉他溢出样式保留于通用旧CSS。
            # 最小拍轴与词音伴奏修复：修改重复style属性，原式保留：<section class="{row_class}"{row_style} style="overflow-x:auto">。
            # 最小拍轴与词音伴奏修复：新增正文显示号一致的行标题，内部索引继续用于文件／定位。
            display_first, display_last = first - int(timeline[0]['pickup']), last - int(timeline[0]['pickup'])
            label = '弱起' if first == last == 1 and timeline[0]['pickup'] else f'第{display_first}–{display_last}小节'
            rows.append(f'<section class="{row_class}"{row_style}><header>{label} · {measures[0]["start_seconds"]:.2f}秒 '
                        # 吉他编配规则闭环修复：修改负秒预备拍定位按钮钳至录音0秒，原时间仍显示。
                        # f'<button data-player="singing" data-second="{measures[0]["start_seconds"]}">从这里试听</button></header>{svg}</section>')
                        f'<button data-player="singing" data-second="{max(0., measures[0]["start_seconds"])}">从这里试听</button></header>{svg}</section>')
        label = '人声简谱' if is_voice else '吉他简谱与六线谱' if instrument == 'guitar' else '钢琴双手伴奏'
        # 最小拍轴与词音伴奏修复：修改开发时固定说明，原句保留；速度及未决歌词全部从当前工程取得，不含歌曲专用文案。
        # intro = (f'<h1>{html.escape(voice["title"])} · {label}</h1><p>隔离候选 · 四分音符约64/分</p>'
        #          '<p class="notice">两处“我”的挂词归属仍待核验。</p>'
        # 吉他编配规则闭环修复：修改旧谱未存steady字段时从其原时钟读取，不重估速度。
        # bpm = voice['timing']['steady_tempo_bpm']
        bpm = voice['timing'].get('steady_tempo_bpm', SongClock(voice).mapping.tempo_at(voice['timing']['score_start_quarter']))
        pending = project.get('music_acceptance', {}).get('unresolved', [])
        pending_text = '；'.join('第' + str(row['character_index'] + 1) + '字“' + voice['lyrics']['characters'][row['character_index']]['text'] + '”'
                                for row in pending if 'character_index' in row)
        intro_notice = (f'入拍前{timeline[0]["start_seconds"]:.2f}秒保留原声。' if timeline[0]['start_seconds'] > 0 else '')
        intro = (f'<h1>{html.escape(voice["title"])} · {label}</h1><p>隔离候选 · 1={voice["notation"]["key"]["jianpu_one"]} · 四分音符约{bpm:g}/分</p>'
                 '<p class="notice">' + html.escape(intro_notice + ('挂词归属待核验：' + pending_text + '。' if pending_text else '')
                 + '本版尚未通过整曲音乐验收。') + '</p>'
                 '<nav><a href="../index.html">本次候选</a><a href="score.musicxml">MusicXML</a><a href="score.mxl">MXL</a><a href="score.mid">MIDI</a></nav>'
                 # 最小拍轴与词音伴奏修复：修改简谱定位播放器身份，原无ID试听保留；行定位按钮可实际找到旋律播放器。
                 # '<div class="toolbar"><p>伴奏试听</p><audio controls src="preview.wav"></audio>'
                 # 最小拍轴与词音伴奏修复：修改播放器为普通文档流，原固定工具栏式保留；定位后不遮挡目标谱行。
                 # + '<div class="toolbar"><p>' + ('旋律试听' if is_voice else '伴奏试听') + '</p><audio id="'
                 + '<div class="toolbar" style="position:static"><p>' + ('旋律试听' if is_voice else '伴奏试听') + '</p><audio id="'
                 + ('singing' if is_voice else 'preview') + '" controls src="preview.wav"></audio>'
                 + ('' if is_voice else '<p>原唱与伴奏</p><audio id="singing" controls src="singing_preview.wav"></audio>')
                 + '<p>原唱</p><audio controls src="../audio/original_vocals.ogg"></audio></div>')
        # 演唱段稳定右手型：新增固定型记忆表，折叠／展开谱共用；旧稿无段落计划时保持页面原样。
        if instrument=='guitar':
            from guitar_section_patterns import pattern_guide_html
            intro+=pattern_guide_html(project)
        # 最小拍轴与词音伴奏修复：新增打印时取消屏幕最小宽度，四小节阅读行按纸张宽度排版。
        print_style = '<style>@media print{.score-row>svg{min-width:0!important;max-width:100%!important}.score-row{overflow:visible!important}}</style>'
        (folder / 'score.html').write_text(export.html_page(voice['title'] + ' · ' + label, print_style + intro + ''.join(rows)), 'utf-8')
        # 吉他编配规则闭环修复：新增实际调用长段规划并验证可见符号，完整展开页作为附页保留。
        if instrument == 'guitar':
            check['repeat'] = write_variable_repeat_score(project, folder)
        checks[instrument] = check
        links.append(f'<p><a href="{instrument}/score.html">{label}</a></p>')
    # 吉他编配规则与统一验收修复：修改真实终检前只记待验，避免后续失败仍留下valid=true。
    # score.save_json(output / 'export_validation.json', {'valid': True, 'checks': checks, 'music_accepted': False})
    score.save_json(output / 'export_validation.json', {'valid': False, 'status': 'pending_final_artifact_checks',
                                                       'checks': checks, 'music_accepted': False})
    # 演唱段稳定右手型：修改新编配页名称，不把只改右手的任务误称为重新修改拍轴。
    # (output / 'index.html').write_text(export.html_page(voice['title'] + ' · 时间修订候选',
    #     '<h1>' + html.escape(voice['title']) + ' · 时间修订候选</h1><p>已验证拍轴；整曲音乐尚待验收，原版本和正常入口保持。</p>' + ''.join(links)), 'utf-8')
    revision_label='演唱段稳定右手候选' if project.get('vocal_pattern_revision') else '时间修订候选'
    revision_notice=('沿用已认可拍轴、小节和人声；本轮整理演唱伴奏右手。' if project.get('vocal_pattern_revision') else '已验证拍轴；')
    # 局部两拍过渡听辨修订：新增准确交付说明，不能把只改小节线说成又重编了右手。
    if project.get('bar_boundary_revision'):
        revision_label='局部小节修订'
        revision_notice='仅调整局部小节线；音符、词音、和弦与试听沿用已认可版本。钢琴本轮未调整。'
    # 4/4可选右手与实时谱面试听：新增与实际授权一致的候选说明。
    if selection_active:
        revision_label='右手演奏型候选'
        revision_notice='沿用原拍轴、人声、和弦及器乐；已按所选4/4右手型修改指定演唱段。'
    (output / 'index.html').write_text(export.html_page(voice['title']+' · '+revision_label,
        '<h1>'+html.escape(voice['title'])+' · '+revision_label+'</h1><p>'+revision_notice+
        '整曲音乐尚待验收，原版本和正常入口保持。</p>'+''.join(links)), 'utf-8')
    # 最小拍轴与词音伴奏修复：新增沿用既有双轨独立音量播放器，不把本轮时间修订降级为只能听固定混音。
    complete_shared_player(output)
    # 吉他编配规则闭环修复：新增真实XML／MIDI／TAB／路线回读共用终检，预检不能代替实际文件。
    if 'guitar' in selected:
        final_check = assess_guitar_readability(project, repeat_plan=score.read_json(output / 'guitar/repeat_plan.json'), output_dir=output)
        score.save_json(output / 'guitar_readability_acceptance.json', final_check)
        require_guitar_readability(project, final_check)
        checks['guitar']['readability_acceptance'] = final_check
        # 吉他编配规则与统一验收修复：修改所有所选乐器完成后统一写通过；旧分支内写入保留。
        # score.save_json(output / 'export_validation.json', {'valid': True, 'checks': checks, 'music_accepted': False})
    score.save_json(output / 'export_validation.json', {'valid': True, 'status': 'actual_artifacts_passed',
                                                       'checks': checks, 'music_accepted': False})
    return checks


def main():
    # 最小拍轴与词音伴奏修复：新增只接受隔离路径的通用命令行。
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    # 吉他编配规则闭环修复：新增显式仅重导所选乐器，不触碰其它工程材料。
    parser.add_argument('--instruments', nargs='+', choices=('vocal', 'guitar', 'piano'))
    # 最小拍轴与词音伴奏修复：新增可重放的仅谱面刷新；必须先读回现有MIDI与工程一致，不能借此跳过音乐变更的导出。
    parser.add_argument('--refresh-visual-only', action='store_true')
    # 最小拍轴与词音伴奏修复：新增仅重新编码原唱／合播，伴奏音频与全部MIDI／谱面身份必须保持。
    parser.add_argument('--refresh-original-audio-only', action='store_true')
    args = parser.parse_args()
    # 最小拍轴与词音伴奏修复：修改显式导出模式，原整套调用保留。
    # export_revision(args.project, args.output)
    if args.refresh_original_audio_only:
        refresh_original_singer(args.project, args.output)
    elif args.refresh_visual_only:
        refresh_visual_rows(args.project, args.output)
    else:
        # 吉他编配规则闭环修复：修改CLI传递选定声部，旧全套调用保留。
        # export_revision(args.project, args.output)
        export_revision(args.project, args.output, instruments=args.instruments)


def refresh_visual_rows(project_path, output):
    # 最小拍轴与词音伴奏修复：新增按相同工程重画实际SVG，不重复合成音频，保留全部音乐与验收状态。
    root_dir = Path(__file__).resolve().parents[1]
    output = require_isolated_output(output, root_dir)
    project = score.read_json(project_path)
    voice = project['accepted_vocal_project']
    if not (output / 'export_validation.json').is_file():
        raise ValueError('没有完整导出，不能仅刷新谱面')
    # 吉他编配规则闭环修复：新增刷新也须先验当前真实音乐和已有产物，防止绕过硬门槛。
    # 相似长段复用与默认阅读修复：修改刷新前先独立验实际完整音乐文件，不用过期阅读计划拦住合法重排；刷新后仍完整验新计划。
    # verify_existing_guitar_delivery(project, output)
    verify_existing_guitar_delivery(project, output, refreshing_layout=True)
    # 吉他编配规则闭环修复：修改旧强制全乐器遍历，保留原式；只刷新既有实际交付。
    # for instrument, arrangement in project['arrangements'].items():
    for instrument, arrangement in ((i, a) for i, a in project['arrangements'].items() if (output / i / 'score.mid').is_file()):
        if not export.validate_midi(output / instrument / 'score.mid', arrangement, voice)['valid']:
            raise ValueError('工程音乐与现有MIDI不一致，必须完整重导')
    # 吉他编配规则闭环修复：修改旧固定全套／仅主谱式，完整展开层更新后重建实际反复页。
    # for instrument in ('vocal', *project['arrangements']):
    #     path = output / instrument / 'score.html'
    for instrument in (i for i in ('vocal', *project['arrangements']) if (output / i / 'score.html').is_file()):
        folded = instrument == 'guitar' and (output / instrument / 'repeat_plan.json').is_file()
        path = output / instrument / ('score_full.html' if folded else 'score.html')
        page = path.read_text('utf-8')
        # 最小拍轴与词音伴奏修复：新增只更新既有XML显示编号，不重生成音乐；MIDI已在上方独立确认与工程一致。
        xml_path = output / instrument / 'score.musicxml'
        xml = ET.parse(xml_path).getroot()
        # 吉他编配规则闭环修复：修改固定／可变边界共用入口，原直接字段保留。
        # timeline = voice['timing']['measure_timeline']
        timeline = measure_timeline(project)
        # 相似长段复用与默认阅读修复：修改显示编号无变化则不重写XML／MXL，原音乐文件逐字节保留。
        # for index, measure in enumerate(xml.findall('part/measure'), 1):
        #     measure.set('number', str(index - int(timeline[0]['pickup'])))
        # ET.ElementTree(xml).write(xml_path, encoding='utf-8', xml_declaration=True)
        # write_mxl(output / instrument / 'score.mxl', xml_path.read_bytes())
        numbering_changed=False
        for index, measure in enumerate(xml.findall('part/measure'), 1):
            wanted=str(index-int(timeline[0]['pickup']))
            if measure.get('number')!=wanted:measure.set('number',wanted);numbering_changed=True
        if numbering_changed:
            ET.ElementTree(xml).write(xml_path, encoding='utf-8', xml_declaration=True)
            write_mxl(output / instrument / 'score.mxl', xml_path.read_bytes())
        for file in sorted((output / instrument / 'rows').glob('voice_*.svg')):
            first, last = map(int, file.stem.split('_')[1:])
            # 吉他编配规则闭环修复：修改既有时间表访问，原式保留。
            # measures = [m for m in voice['timing']['measure_timeline'] if first <= m['number'] <= last]
            measures = [m for m in timeline if first <= m['number'] <= last]
            before = file.read_text('utf-8')
            after = render_row(project, measures, instrument == 'guitar')
            if before not in page:
                raise ValueError('页面与独立SVG不一致，不能不透明覆盖')
            page = page.replace(before, after, 1)
            file.write_text(after, 'utf-8')
            display_first, display_last = first - int(timeline[0]['pickup']), last - int(timeline[0]['pickup'])
            label = '弱起' if first == last == 1 and timeline[0]['pickup'] else f'第{display_first}–{display_last}小节'
            page = page.replace(f'<header>第{first}–{last}小节 · {measures[0]["start_seconds"]:.2f}秒',
                                f'<header>{label} · {measures[0]["start_seconds"]:.2f}秒', 1)
            if instrument == 'piano':
                staff_file = output / instrument / 'rows' / f'staff_{first:03}_{last:03}.svg'
                old_staff = staff_file.read_text('utf-8')
                subset = deepcopy(xml)
                for index, measure in enumerate(list(subset.find('part')), 1):
                    if not first <= index <= last:
                        subset.find('part').remove(measure)
                holder = ET.Element('temporary')
                export.xml_attributes(holder, voice['notation']['key'], measures[0]['meter'], 'piano', initial=True)
                front = subset.find('part/measure')
                if front.find('attributes') is not None:
                    front.remove(front.find('attributes'))
                front.insert(0, holder[0])
                trim_excerpt_continuations(subset)
                new_staff = piano_svg(subset)
                if old_staff not in page:
                    raise ValueError('钢琴页面与独立声部SVG不一致')
                page = page.replace(old_staff, new_staff, 1)
                staff_file.write_text(new_staff, 'utf-8')
        path.write_text(page, 'utf-8')
        # 吉他编配规则闭环修复：新增刷新后真实复用规划／印刷层重建，不能只更新展开附件。
        if folded:
            (output / instrument / 'score.html').write_text(page, 'utf-8')
            write_variable_repeat_score(project, output / instrument)
    # 最小拍轴与词音伴奏修复：新增幂等补全播放器，不重新编码或修改音乐。
    complete_shared_player(output)
    # 吉他编配规则闭环修复：新增实际刷新文件终检。
    verify_existing_guitar_delivery(project, output)


# 相似长段复用与默认阅读修复：修改内部刷新预检可分离旧布局，默认与刷新终检仍要求真实完整反复产物。
# def verify_existing_guitar_delivery(project, output):
def verify_existing_guitar_delivery(project, output, refreshing_layout=False):
    # 吉他编配规则闭环修复：新增谱面／原唱刷新共用入口；缺计划不能借刷新宣称复用通过。
    from guitar_readability_acceptance import assess_guitar_readability, require_guitar_readability
    if not (output / 'guitar/score.html').is_file():
        return
    plan_path = output / 'guitar/repeat_plan.json'
    # 相似长段复用与默认阅读修复：修改实际音乐XML／MIDI／展开TAB和硬门槛预检，终检再加当前反复图元和路线。
    # plan = score.read_json(plan_path) if plan_path.is_file() else None
    # assessment = assess_guitar_readability(project, repeat_plan=plan, output_dir=output)
    # score.save_json(output / 'guitar_readability_acceptance.json', assessment)
    plan = score.read_json(plan_path) if plan_path.is_file() and not refreshing_layout else None
    assessment = assess_guitar_readability(project, repeat_plan=plan, output_dir=output,require_repeat=not refreshing_layout)
    score.save_json(output / ('guitar_readability_refresh_input.json' if refreshing_layout else 'guitar_readability_acceptance.json'), assessment)
    require_guitar_readability(project, assessment)


def complete_shared_player(output):
    # 最小拍轴与词音伴奏修复：新增复用已有共同时钟播放器及原唱数据，实际谱行按来源秒定位，声音文件保持。
    output = Path(output)
    encoded = base64.b64encode((output / 'audio/original_vocals.ogg').read_bytes()).decode('ascii')
    (output / 'audio/vocal_buffer.js').write_text('// 最小拍轴与词音伴奏修复：新增完整原唱同源试听数据。\nwindow.accompanimentVocalBuffer='
                                                + json.dumps(encoded) + ';\n', 'utf-8')
    native = '<p>原唱与伴奏</p><audio id="singing" controls src="singing_preview.wav"></audio>'
    # 吉他编配规则闭环修复：修改旧只补主页面式，完整展开附页同样使用独立原唱／伴奏音量。
    # for instrument in ('guitar', 'piano'):
    #     path = output / instrument / 'score.html'
    for instrument, page_name in ((i, p) for i in ('guitar', 'piano') for p in ('score.html', 'score_full.html')):
        path = output / instrument / page_name
        if not path.is_file():
            continue
        page = path.read_text('utf-8')
        if 'id="singing-player"' not in page:
            if native not in page:
                raise ValueError('候选页播放器结构已改变，不能静默替换')
            page = page.replace(native, export.singing_player_html(), 1)
        page = re.sub(r'<button data-player="singing" data-second="([0-9.]+)">', r'<button data-singing-second="\1">', page)
        path.write_text(page, 'utf-8')


def refresh_original_singer(project_path, output):
    # 最小拍轴与词音伴奏修复：新增原唱浮点峰值修正的可重放步骤；不重算或修改伴奏／人声旋律音符。
    import soundfile as sf
    root_dir = Path(__file__).resolve().parents[1]
    output = require_isolated_output(output, root_dir)
    project = score.read_json(project_path)
    voice = project['accepted_vocal_project']
    source = project['shared_analysis']['input_binding']['sources']['vocals']
    # 吉他编配规则闭环修复：新增仅原唱刷新同样核对既有真实谱面与硬门槛。
    verify_existing_guitar_delivery(project, output)
    if score.sha256(source['path']) != source['sha256']:
        raise ValueError('原唱来源已改变')
    # 吉他编配规则闭环修复：修改已存在声部范围，原强制全乐器式保留。
    # for instrument, arrangement in project['arrangements'].items():
    for instrument, arrangement in ((i, a) for i, a in project['arrangements'].items() if (output / i / 'score.mid').is_file()):
        if not export.validate_midi(output / instrument / 'score.mid', arrangement, voice)['valid']:
            raise ValueError('音乐已改变，不能仅更新原唱编码')
    raw, rate = sf.read(local_path(source['path']), dtype='float32', always_2d=True)
    # 吉他编配规则闭环修复：修改原仅时间修订来源，兼容已确认旧拍轴原曲时长。
    # duration = voice['time_only_revision']['source_duration_seconds']
    duration = voice.get('time_only_revision', {}).get('source_duration_seconds', project['shared_analysis']['input_binding']['sources']['mix']['duration_seconds'])
    samples, placement = align_samples(raw, rate, 22050, source.get('offset_seconds', 0.), math.ceil(duration * 22050))
    scale = min(1., .97 / max(1e-9, float(np.max(abs(samples)))))
    samples *= scale
    meta = {'sample_rate': 22050, 'source_sha256': source['sha256'], 'frames': len(samples), 'channels': samples.shape[1],
            'duration_seconds': duration, 'origin_song_seconds': 0., 'voice_scale': scale,
            'placement': placement, 'vocal_kind': 'original_separated_singer_audio'}
    sf.write(output / 'audio/original_vocals.wav', samples, 22050, subtype='PCM_16')
    write_ogg(output / 'audio/original_vocals.ogg', samples, 22050)
    score.save_json(output / 'audio/vocal_alignment.json', meta)
    # 吉他编配规则闭环修复：修改只刷新实际交付声部，原全部式保留。
    # for instrument in project['arrangements']:
    for instrument in (i for i in project['arrangements'] if (output / i / 'preview.wav').is_file()):
        write_singing_preview(output / instrument, output / instrument / 'preview.wav', samples, meta)
    complete_shared_player(output)


if __name__ == '__main__':
    main()
