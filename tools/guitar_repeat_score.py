"""重复乐句折叠与多遍挂词：多遍简谱／歌词共用六线谱与可定位的反复阅读页。"""
from collections import defaultdict
from copy import deepcopy
import html
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET
from accompaniment_analysis import SongClock
from beat_phase_alignment import display_measure
from guitar_chord_diagrams import visible_diagrams
from guitar_instrumental_expression import reference_vocal
from guitar_repeat_plan import build_repeat_plan, validate_repeat_plan
from guitar_time_alignment import layout_shared_time, annotate_vocal_glyphs, visible_x
from score_export import save_json

NS = '{http://www.w3.org/2000/svg}'
LAYER_STEP = 136


# 重复乐句折叠与多遍挂词：新增各遍的只读显示投影，源事件身份／歌词不变，绝不用于MIDI或音频。
def occurrence_scene(vocal, arrangement, block, occurrence):
    from accompaniment_export import vocal_row
    bar = vocal['statistics']['bar_ticks']; shift = (block['canonical_first'] - occurrence['first']) * bar
    projected = deepcopy(reference_vocal(vocal, arrangement))
    projected['events'] = [{**event, 'measure': event['measure'] + shift // bar,
                             'start_tick': event['start_tick'] + shift}
                            for event in projected['events'] if occurrence['first'] <= event['measure'] <= occurrence['last']]
    return vocal_row(projected, block['canonical_first'], block['canonical_last'])


# 重复乐句折叠与多遍挂词：新增各遍字形的最大留白；音值／字数不同仍与唯一伴奏保持同拍位置。
def union_cells(scenes, arrangement, bar, charts):
    result = defaultdict(dict)
    for scene in scenes:
        for number, box in scene.measure_boxes.items():
            grace_ids = {event['id'] for event in box['events'] if event['grace']}
            for beat in box['beats']:
                groups = defaultdict(list)
                for glyph in beat['glyphs']: groups[glyph['tick']].append(glyph)
                groups.setdefault(beat['start_tick'], [])
                for tick, glyphs in groups.items():
                    main = [g for g in glyphs if g['id'] not in grace_ids]
                    grace = [g for g in glyphs if g['id'] in grace_ids]
                    left = max([17.] + [g['x'] - g['left'] for g in main])
                    right = max([17.] + [g['right'] - g['x'] for g in main])
                    edge = left
                    for glyph in reversed(grace):
                        delta = edge + glyph['right'] - glyph['x'] + 6
                        edge = delta + glyph['x'] - glyph['left']
                    cell = result[number].setdefault(tick, {'left': 17., 'right': 17.})
                    cell['left'] = max(cell['left'], left, edge); cell['right'] = max(cell['right'], right)
    for number, cells in result.items():
        begin = (number - 1) * bar
        for note in arrangement['notes']:
            if begin <= note['start_tick'] < begin + bar:
                cells.setdefault(note['start_tick'] - begin, {'left': 17., 'right': 17.})
        for chart in charts:
            if begin <= chart['draw_tick'] < begin + bar:
                cell = cells.setdefault(chart['draw_tick'] - begin, {'left': 17., 'right': 17.})
                cell['left'] = max(cell['left'], 49.); cell['right'] = max(cell['right'], 49.)
    return dict(result)


# 重复乐句折叠与多遍挂词：新增原事件／原秒定位，折叠坐标和音源秒时间明确分开。
# 吉他长段反复与流畅阅读：修改旧单遍也编号的接口，原签名注释保留；只在共用音乐层显示遍次。
# def annotate_layer(group, occurrence, source_events, bar, label):
def annotate_layer(group, occurrence, source_events, bar, label, show_pass=True):
    group.set('class', 'repeat-vocal-layer'); group.set('data-occurrence-id', occurrence['id'])
    group.set('data-pass', str(occurrence['pass'])); group.set('data-source-first', str(occurrence['first']))
    for glyph in group.iter(NS + 'g'):
        identity = glyph.get('data-event-id')
        if identity in source_events:
            source = source_events[identity]; part = int(glyph.get('data-part', 0))
            glyph.set('data-source-start-tick', str(source['start_tick'] + part * 480))
            # 重复乐句折叠与多遍挂词：新增可见歌词身份，直接核对文字和音符中心，不能仅核音符标签。
            lyric = source.get('lyric') or {}
            if part == 0 and lyric.get('text'):
                center = glyph.find(NS + 'text').get('x')
                match = next((text for text in group.iter(NS + 'text') if text.text == lyric['text'] and
                              text.get('font-size') == '20' and text.get('x') == center), None)
                if match is not None: match.set('data-lyric-event-id', identity)
    # 吉他长段反复与流畅阅读：修改单独段落的错误遍次提示，原图元保留；第二房子不会再出现第一遍标签。
    # node = ET.SubElement(group, NS + 'text', {'x': '26', 'y': '104', 'font-size': '15',
    #     'font-family': 'Microsoft YaHei, sans-serif', 'fill': '#4a596b', 'text-anchor': 'middle'})
    if not show_pass: return
    node = ET.SubElement(group, NS + 'text', {'class': 'repeat-pass-number', 'x': '26', 'y': '104', 'font-size': '15',
        'font-family': 'Microsoft YaHei, sans-serif', 'fill': '#4a596b', 'text-anchor': 'middle'})
    node.text = str(occurrence['pass']) + '.'
    ET.SubElement(group, NS + 'title').text = label


# 重复乐句折叠与多遍挂词：新增纯SVG反复符号，避免Windows缺音乐字体导致方框。
def draw_marker(parent, kind, x, label):
    group = ET.SubElement(parent, NS + 'g', {'class': 'repeat-marker', 'data-marker-kind': kind,
                                           'transform': f'translate({x:g},17)'})
    if kind == 'segno':
        ET.SubElement(group, NS + 'path', {'d': 'M11,-9 C-2,-14 -6,-1 4,0 C15,0 12,12 -1,8 M-6,10 L14,-12',
                                         'stroke': '#14243b', 'fill': 'none', 'stroke-width': '2'})
        for cx, cy in ((-7, -5), (14, 5)):
            ET.SubElement(group, NS + 'circle', {'cx': str(cx), 'cy': str(cy), 'r': '1.8', 'fill': '#14243b'})
    else:
        ET.SubElement(group, NS + 'circle', {'cx': '3', 'cy': '0', 'r': '8', 'fill': 'none', 'stroke': '#14243b', 'stroke-width': '1.5'})
        ET.SubElement(group, NS + 'path', {'d': 'M-10,0 H16 M3,-13 V13', 'stroke': '#14243b', 'fill': 'none', 'stroke-width': '1.5'})
    ET.SubElement(group, NS + 'text', {'x': '23', 'y': '4', 'font-size': '15', 'font-weight': 'bold',
        'font-family': 'Microsoft YaHei, sans-serif'}).text = label
    return group


# 重复乐句折叠与多遍挂词：新增音符／线条的身份前缀，单页面不同来源小节不会出现重复SVG id。
def prefix_ids(root, prefix):
    identities = {node.get('id'): prefix + node.get('id') for node in root.iter() if node.get('id')}
    for node in root.iter():
        # 重复乐句折叠与多遍挂词：新增实际音符来源身份，并使黑点／指型引用命中前缀后的图元。
        if node.get('data-string') and node.get('id') and not node.get('data-source-note-id'):
            node.set('data-source-note-id', node.get('id'))
        if node.get('data-note-id') in identities:
            node.set('data-source-note-id', node.get('data-note-id')); node.set('data-note-id', identities[node.get('data-note-id')])
        if node.get('data-diagram-id') in identities: node.set('data-diagram-id', identities[node.get('data-diagram-id')])
        if node.get('id') in identities: node.set('id', identities[node.get('id')])
        for key, value in list(node.attrib.items()):
            if value.startswith('#') and value[1:] in identities: node.set(key, '#' + identities[value[1:]])
            elif value.startswith('url(#') and value[5:-1] in identities: node.set(key, 'url(#' + identities[value[5:-1]] + ')')


# 重复乐句折叠与多遍挂词：新增多遍垂直排版，唯一TAB整体下移而指型／拍列不动。
def render_block(shared, vocal, arrangement, block, layer_count, marker_kinds):
    from accompaniment_export import guitar_row, instrumental_guitar_row
    source_events = {e['id']: e for e in reference_vocal(vocal, arrangement)['events']}
    first, last = block['canonical_first'], block['canonical_last']; bar = vocal['statistics']['bar_ticks']
    scenes = [occurrence_scene(vocal, arrangement, block, occurrence) for occurrence in block['occurrences']]
    charts = visible_diagrams(shared, arrangement, first, last)
    cells = union_cells(scenes, arrangement, bar, charts)
    drawing = {**deepcopy(arrangement), '_repeat_cells': cells, '_row_diagram_markers': charts}
    scenes = [layout_shared_time(scene, drawing, bar) for scene in scenes]
    drawing['_repeat_scene'] = scenes[0]
    root = ET.fromstring(guitar_row(shared, vocal, drawing, first, last))
    tab_only = root.get('data-instrumental-tab-only') == 'true'
    extra = 0 if tab_only else (layer_count - 1) * LAYER_STEP
    body = root.find(NS + "g[@class='score-body']")
    offset = float(re.search(r'translate\(0,([-\d.]+)\)', body.get('transform'))[1])
    body.set('transform', f'translate(0,{offset + extra:g})')
    primary = next((n for n in body.iter(NS + 'g') if n.get('id') == 'repeat-vocal-main'), None)
    if primary is not None and not tab_only:
        primary.set('transform', f'translate(0,{-extra:g})')
        # 吉他长段反复与流畅阅读：修改旧首行固定第一遍标号，注释保留；独立段落不标共用遍次。
        # annotate_layer(primary, block['occurrences'][0], source_events, bar, '第1遍人声与歌词')
        annotate_layer(primary, block['occurrences'][0], source_events, bar, '人声与歌词', show_pass=len(block['occurrences']) > 1)
        # 重复乐句折叠与多遍挂词：新增各遍内的局部身份前缀，避免同一小节组在不同人声层重复id。
        prefix_ids(primary, block['occurrences'][0]['id'] + '-')
        for index, (scene, occurrence) in enumerate(zip(scenes[1:], block['occurrences'][1:]), 1):
            layer_root = ET.fromstring(scene.svg()); annotate_vocal_glyphs(layer_root, scene)
            layer = ET.Element(NS + 'g', {'transform': f'translate(0,{offset + index * LAYER_STEP:g})'})
            # 重复乐句折叠与多遍挂词：新增只复制实际字形层，背景矩形不会覆盖前一遍或伴奏。
            for child in list(layer_root):
                if child.tag != NS + 'rect': layer.append(child)
            annotate_layer(layer, occurrence, source_events, bar, '第' + str(occurrence['pass']) + '遍人声与歌词')
            prefix_ids(layer, occurrence['id'] + '-')
            root.append(layer)
    width = float(root.get('width')); height = float(root.get('height')) + extra + 36
    outer = ET.Element(NS + 'svg', {'width': str(width), 'height': str(height), 'viewBox': f'0 0 {width:g} {height:g}',
                                   'data-block-id': block['id'], 'data-shared-tab': 'true'})
    ET.SubElement(outer, NS + 'rect', {'width': str(width), 'height': str(height), 'fill': 'white'})
    contents = ET.SubElement(outer, NS + 'g', {'transform': 'translate(0,36)'})
    for child in list(root):
        if child.tag != NS + 'rect': contents.append(child)
    # 重复乐句折叠与多遍挂词：修改标题位置，旧固定52保留；反复目标符号位于乐段起点。
    # title = ET.SubElement(outer, NS + 'text', {'x': '52', 'y': '20', 'font-size': '16', 'font-weight': 'bold',
    title = ET.SubElement(outer, NS + 'text', {'x': str(52 + len(marker_kinds) * 105), 'y': '20', 'font-size': '16', 'font-weight': 'bold',
        'font-family': 'Microsoft YaHei, sans-serif', 'fill': '#14243b'})
    # 吉他长段反复与流畅阅读：修改分块标题，原每行字母标段保留；完整音乐段落跨行延续。
    # title.text = block['id'] + (' · 共' + str(len(block['occurrences'])) + '遍' if len(block['occurrences']) > 1 else '')
    title.text = block.get('display_label', block['id'])
    # 重复乐句折叠与多遍挂词：修改符号锚点，旧靠段尾保留；Segno／Coda明确放在起始小节左侧。
    # for index, kind in enumerate(marker_kinds): draw_marker(outer, kind, width - 150 - index * 105, block['id'])
    for index, kind in enumerate(marker_kinds): draw_marker(outer, kind, 52 + index * 105, block['id'])
    prefix_ids(outer, 'repeat-' + block['id'] + '-')
    return outer


# 重复乐句折叠与多遍挂词：新增四小节行的横向拼接，不复制伴奏、不隐藏各遍的真实歌词。
def render_lines(plan, shared, vocal, arrangement, folder):
    blocks = {b['id']: b for b in plan['blocks']}; occurrences = {o['id']: o for o in plan['route']}
    # 吉他长段反复与流畅阅读：修改旧全D.S.标记集合，注释保留；由实际音乐段落生成普通反复／房子／D.S.边界。
    # segnos = {occurrences[j['to_occurrence']]['block_id'] for j in plan['jumps']}
    # codas = {occurrences[j['continue_occurrence']]['block_id'] for j in plan['jumps'] if j['continue_occurrence']}
    from guitar_repeat_marks import marker_specs, draw_annotations
    marks = marker_specs(plan)
    rows = []
    for index, names in enumerate(plan['lines'], 1):
        layers = max(len(blocks[name]['occurrences']) for name in names)
        # 吉他长段反复与流畅阅读：修改逐行重复Segno／Coda，原代码注释保留；只在完整段落实际起止印符号。
        # parts = [render_block(shared, vocal, arrangement, blocks[name], layers,
        #                      (['segno'] if name in segnos else []) + (['coda'] if name in codas else [])) for name in names]
        parts = [render_block(shared, vocal, arrangement, blocks[name], layers, []) for name in names]
        for name, part in zip(names, parts): draw_annotations(part, marks.get(name, []), draw_marker)
        width = sum(float(part.get('width')) for part in parts) + 12 * (len(parts) - 1)
        height = max(float(part.get('height')) for part in parts)
        root = ET.Element(NS + 'svg', {'width': str(width), 'height': str(height), 'viewBox': f'0 0 {width:g} {height:g}',
                                      'class': 'repeat-score-svg', 'data-printed-bars': str(sum(blocks[n]['length_bars'] for n in names))})
        x = 0
        for part in parts:
            group = ET.SubElement(root, NS + 'g', {'transform': f'translate({x:g},0)', 'class': 'repeat-block',
                                                 'data-block-id': part.get('data-block-id'), 'id': 'block-' + part.get('data-block-id')})
            for child in part: group.append(child)
            x += float(part.get('width')) + 12
        svg = ET.tostring(root, encoding='unicode'); path = folder / f'line_{index:03}.svg'; path.write_text(svg, 'utf-8')
        rows.append({'line': index, 'blocks': names, 'width': width, 'height': height, 'guitar': svg, 'file': str(path)})
    return rows


# 重复乐句折叠与多遍挂词：新增按真实原编号显示各遍范围，弱起没有被虚增一小节。
def occurrence_label(vocal, occurrence):
    first, last = display_measure(vocal, occurrence['first']), display_measure(vocal, occurrence['last'])
    if first == '弱起': return '弱起预备'
    return '原第' + first + ('–' + last if first != last else '') + '小节'


# 重复乐句折叠与多遍挂词：新增各遍的配对跳转文案，To Coda仅按指定回跳生效。
def exit_caption(plan, occurrence):
    lookup = {o['id']: o for o in plan['route']}; jumps = {j['id']: j for j in plan['jumps']}
    exit = occurrence['exit']; target = lookup.get(exit['target_occurrence'])
    destination = (target['block_id'] + '第' + str(target['pass']) + '行') if target else '结束'
    # 吉他长段反复与流畅阅读：新增普通反复及第二房子去向，不用D.S.连接短小节。
    # 吉他长段反复与流畅阅读：修改泛称目标，原文案保留；页面指令和印刷段落名称相同。
    # if exit['kind'] == 'repeat': return '反复：回到共用段起点，奏第二遍'
    group = next((g for g in plan['repeat_groups'] if g['id'] == exit.get('jump_id')), None)
    if exit['kind'] == 'repeat': return '反复：回到' + group['label'] + '起点，奏第二遍'
    if exit['kind'] == 'volta_skip': return '第二遍跳过第一房子，接第二房子'
    if exit['kind'] in ('ds_al_coda', 'ds_al_fine'):
        jump = jumps[exit['jump_id']]; stop = lookup[jump['until_occurrence']]
        ending = lookup.get(jump['continue_occurrence'])
        end_text = 'To Coda ' + ending['block_id'] if ending else 'Fine'
        # 吉他长段反复与流畅阅读：修改旧碎片字母去向，原文案注释保留；与实际Segno／Coda长段标记一致。
        # return ('D.S. ' + target['block_id'] + (' al Coda' if ending else ' al Fine') +
        #         '：回到' + destination + '，奏至' + stop['block_id'] + '第' + str(stop['pass']) + '行的' + end_text)
        return ('D.S. al Coda：回到' + group['label'] + '，奏第二遍后转入后续段') if ending else ('D.S. al Fine：回到' + group['label'] + '，奏第二遍至Fine结束')
    # 吉他长段反复与流畅阅读：修改转尾目标文案，旧字母目标注释保留。
    # if exit['kind'] == 'to_coda': return 'To Coda ' + target['block_id'] + '：跳至' + destination
    if exit['kind'] == 'to_coda': return 'To Coda：本次回跳演奏完毕，转入后续段'
    if exit['kind'] == 'fine': return 'Fine：结束'
    return '接' + destination if target else '结束'


# 重复乐句折叠与多遍挂词：新增页面跟随与定位，播放仍使用原曲完整时间，绝不把折叠小节当音频秒。
REPEAT_SCRIPT = r'''
// 重复乐句折叠与多遍挂词：新增各遍选择、跳转及完整原唱播放高亮。
(() => {
 const data = window.guitarRepeatRoute; if (!data) return;
 let selected = null;
 const focus = (id, scroll=false) => {
  const entry = data.find(item => item.id===id); if (!entry) return;
  selected=id; document.querySelectorAll('[data-occurrence-id]').forEach(node => node.classList.toggle('repeat-active',node.dataset.occurrenceId===id));
  document.querySelectorAll('.repeat-block').forEach(node => node.classList.toggle('repeat-block-active',node.dataset.blockId===entry.block_id));
  const target=document.getElementById('block-'+entry.block_id);
  if (scroll && target) target.closest('.score-row').scrollIntoView({block:'start',behavior:'smooth'});
  // 吉他长段反复与流畅阅读：修改旧内部字母位置提示，注释保留；按完整共用段及实际演奏遍次提示。
  // const state=document.getElementById('repeat-now'); if(state) state.textContent=`乐段${entry.block_id}，第${entry.pass}行（${entry.label}）`;
  const state=document.getElementById('repeat-now'); if(state) state.textContent=entry.section_label?`${entry.section_label}，第${entry.pass}遍（${entry.label}）`:`当前演奏（${entry.label}）`;
 };
 document.querySelectorAll('[data-focus-occurrence]').forEach(node => node.addEventListener('click',event => {event.preventDefault();focus(node.dataset.focusOccurrence,true)}));
 document.querySelectorAll('.repeat-occurrence button').forEach(button => button.addEventListener('click',()=>focus(button.closest('[data-occurrence-id]').dataset.occurrenceId)));
 const follow=()=>{
  let seconds=null;
  if(document.getElementById('singing-player')?.dataset.playing==='true') seconds=window.singingPlayback?.position();
  else {const audio=document.getElementById('preview');const original=document.getElementById('original');
    if(audio && !audio.paused) seconds=audio.currentTime; else if(original && !original.paused) seconds=original.currentTime-data[0].origin;
  }
  // 重复乐句折叠与多遍挂词：修改边界比较，旧精确包含保留；六位秒标签至多半微秒误差，不应高亮上一遍。
  // if(seconds!==null && Number.isFinite(seconds)) {const entry=data.find(item=>item.start_second<=seconds && seconds<item.end_second);
  if(seconds!==null && Number.isFinite(seconds)) {let entry=null;for(const candidate of data){if(candidate.start_second<=seconds+.000001&&seconds<candidate.end_second+.000001)entry=candidate;}
   if(entry && entry.id!==selected) focus(entry.id,document.getElementById('repeat-follow')?.checked);
  }
  requestAnimationFrame(follow);
 };window.guitarRepeatDisplay={focus,get selected(){return selected},route:data}; focus(data[0].id);follow();
})();
'''

REPEAT_STYLE = '''
/* 重复乐句折叠与多遍挂词：新增读谱与打印留白，控件不遮谱，各遍高亮不改变字形位置。 */
.repeat-route{display:flex;gap:7px;flex-wrap:wrap;padding:10px 0;line-height:2}.repeat-route a{border:1px solid #bcc9cf;border-radius:5px;padding:2px 8px;color:#18334b;text-decoration:none}.repeat-route .repeat-active{background:#d9edf6;border-color:#25648b}
.repeat-navigation{display:flex;flex-wrap:wrap;gap:10px;margin:8px 0}.repeat-block-control{flex:1 1 250px;border-left:3px solid #d9e3e8;padding-left:10px}.repeat-occurrence{padding:4px 6px;margin:4px 0;border-radius:5px}.repeat-occurrence.repeat-active{background:#eef7fc}.repeat-occurrence button{font-size:12px;padding:4px 6px;margin:3px}
.repeat-instructions{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:10px;font-size:13px;color:#334b5c}.repeat-instructions p{margin:5px 0}.repeat-vocal-layer.repeat-active text{fill:#14597c}.repeat-block-active{outline:none}.repeat-score-svg{display:block;width:100%;height:auto;min-width:calc(var(--score-native-width)*.64px)}
.repeat-score-row{scroll-margin-top:12px;overflow-x:auto}.repeat-legend{font-size:14px;line-height:1.8}.repeat-overview summary{cursor:pointer;font-weight:bold}#repeat-now{font-size:14px;padding:7px 0}.repeat-controls{font-size:14px}
@media print{.repeat-score-row{overflow:visible;break-inside:avoid;max-width:100%}.repeat-score-row svg{min-width:0!important;max-height:none!important;width:100%;height:auto}.repeat-block-control button,.repeat-controls,#repeat-now{display:none}.repeat-navigation{font-size:11px;gap:6px}.repeat-block-control{flex-basis:150px}.repeat-instructions{font-size:10px;grid-template-columns:repeat(2,1fr)}.repeat-route{font-size:11px;gap:4px}.repeat-route a{border:0;padding:0;color:black}.repeat-vocal-layer text{fill:initial}.repeat-overview{display:block}.score-row{margin:3mm 0}.repeat-instructions p{margin:2px 0}}
'''


# 重复乐句折叠与多遍挂词：新增合并谱，保留原样展开页和原曲顺序MusicXML／MIDI下载。
# 重复乐句折叠与多遍挂词：修改谱页入口，旧签名保留；延续源拍轴的未决说明。
# def write_repeat_html(folder, vocal, arrangement, plan, rows, full_html):
def write_repeat_html(folder, vocal, arrangement, plan, rows, full_html, source_clock_review=None):
    from accompaniment_export import html_page, play_buttons, PLAYER_SCRIPT
    # 原曲拍轴与歌词拍位通用修复：修改，旧反复定位音频起点保留；新层谱首拍与完整原唱的前沿统一映射。
    # clock = SongClock(vocal); bar = vocal['statistics']['bar_ticks']; origin = clock.seconds(0)
    clock = SongClock(vocal); bar = vocal['statistics']['bar_ticks']; origin = clock.audio_origin_seconds
    title = vocal['title'] + ' · 吉他反复谱'
    # 重复乐句折叠与多遍挂词：新增从已验收页复用离线原唱播放器，歌曲资源路径／编码完全相同。
    toolbar_start = full_html.index('<div class="toolbar">'); first_row = full_html.index('<section class="score-row')
    toolbar = full_html[toolbar_start:first_row]
    body = '<h1>' + html.escape(title) + '</h1>'
    body += '<p>人声简谱与歌词按各遍上下排列，共用下方六线谱；数字行号对应各遍。器乐段及实际不同的伴奏另列。</p>'
    capos = arrangement['configuration'].get('capo_segments', [])
    capo_text = '；'.join(('弱起预备' if display_measure(vocal, s['start_measure']) == '弱起' else '原第' + display_measure(vocal, s['start_measure']) + '小节') +
                         '起夹' + str(s['capo_fret']) + '品' for s in capos) or '变调夹第' + str(arrangement['configuration']['capo_fret']) + '品'
    # 重复乐句折叠与多遍挂词：修改长谱头字符串为括号续行，旧两行表达式保留。
    # body += '<p>1=' + html.escape(vocal['notation']['key']['jianpu_one']) + ' · ' + '/'.join(map(str, vocal['timing']['meter'])) +
    #     ' · 起始 ♩=' + str(round(clock.mapping.tempo_at(clock.origin), 1)) + '，随原曲变化 · 标准调弦 E–A–D–G–B–E · ' + html.escape(capo_text) + '</p>'
    body += ('<p>1=' + html.escape(vocal['notation']['key']['jianpu_one']) + ' · ' + '/'.join(map(str, vocal['timing']['meter'])) +
        ' · 起始 ♩=' + str(round(clock.mapping.tempo_at(clock.origin), 1)) + '，随原曲变化 · 标准调弦 E–A–D–G–B–E · ' + html.escape(capo_text) + '</p>')
    # 重复乐句折叠与多遍挂词：新增保留原有黑点／背景休止和未决拍轴说明，排版不会掩盖音乐证据状态。
    if arrangement.get('instrumental_expression'):
        from guitar_instrumental_expression import expression_caption
        body += '<p>' + html.escape(expression_caption(arrangement)) + '</p>'
    if arrangement.get('regular_rhythm'):
        body += '<p>符干／横梁表示右手起音；沿弦细线表示延响，括号品数表示续音无需重拨。</p>'
    if arrangement.get('instrumental_expression') and arrangement.get('instrumental_expression', {}).get('version'):
        body += '<p class="repeat-legend">器乐主旋律上方黑点为旋律重音提示，保持原音值；低弦填充按较弱力度演奏。</p>'
    if source_clock_review:
        body += '<p class="notice">部分拍位尚待听审：本版保留校准前的人声拍轴，请结合原唱检查重拍及歌词位置。</p>'
    body += '<nav><a href="../index.html">乐谱入口</a><a href="score_full.html">完整展开谱</a><a href="../review.html">逐小节复核</a><a href="score.musicxml" download>MusicXML（原曲顺序）</a><a href="accompaniment.mid" download>MIDI（原曲顺序）</a><a href="chords.html">指型目录</a><a href="rhythm_guide.html">节奏图例</a><button onclick="window.print()">打印反复谱</button></nav>'
    # 吉他长段反复与流畅阅读：修改旧D.S.说明，注释保留；先解释普通反复和一二房子。
    # body += '<details class="repeat-legend no-print"><summary>反复与读谱说明</summary><p>D.S.表示回到指定Segno符号；按提示唱相应行，走到该遍的To Coda后跳至同名Coda。第一次遇到To Coda不跳，只有配对回跳后的指定遍执行；Fine只在对应回跳中结束。乐段字母是明确的跳转目标。</p><p>x表示沿用当前手型拨响该弦，含无需松手的空弦；需换指才用实际品数。独奏区全部用品数。所有品数相对当前变调夹；八分／十六分横梁和延音细线按原谱保持。</p><p>各遍的小号倚音、延音、歌词及节奏差别分别保留。原唱与伴奏仍按完整原曲顺序播放，点击对应遍试听即可；折叠不会缩短音频。</p><p>反复含义参考<a href="https://handbook.musescore.org/notation/repeats/jumps-and-markers">MuseScore官方说明</a>。</p></details>'
    body += '<details class="repeat-legend no-print"><summary>反复与读谱说明</summary><p>遇到反复结束线，回到对应反复起点演奏第二遍。一、二房子表示不同结尾：第一遍奏第一房子，第二遍跳过第一房子奏第二房子。共用段跨行时继续向下读，按相应人声行唱。</p><p>如有D.S.，回到指定Segno共用段；To Coda和Fine只在这次回跳后执行，分别转入后续段或结束。</p><p>x表示沿用当前手型拨响该弦；需换指才用实际品数。品数相对当前变调夹。各遍歌词、倚音和延音分别保留，原唱与伴奏按完整原曲顺序播放。</p></details>'
    body += '<p>' + str(plan['expanded_bars']) + '个原曲小节 → ' + str(plan['printed_bars']) + '个伴奏印刷小节，共' + str(plan['folded_blocks']) + '处共用段。开头弱起如有，仍独立列出。</p>'
    body += toolbar + '<div class="repeat-controls no-print"><label><input id="repeat-follow" type="checkbox" checked>播放时跟随当前乐段</label><div id="repeat-now" aria-live="polite"></div></div>'
    # 吉他长段反复与流畅阅读：修改旧碎片字母路线标题，注释保留；完整段落路线直接显示演奏遍次。
    # body += '<div class="repeat-overview"><strong>演奏顺序（字母后的数字为人声行号）</strong><div class="repeat-route">'
    body += '<div class="repeat-overview"><strong>演奏顺序</strong><div class="repeat-route">'
    payload = []
    # 吉他长段反复与流畅阅读：修改碎片字母概览，原逐块导航注释保留；概览只列完整演奏段，播放器仍逐行定位。
    # for occurrence in plan['route']:
    #     label = occurrence_label(vocal, occurrence)
    #     body += '<a href="#block-' + occurrence['block_id'] + '" data-focus-occurrence="' + occurrence['id'] + '" data-occurrence-id="' + occurrence['id'] + '" title="' + html.escape(label) + '">' + occurrence['block_id'] + str(occurrence['pass']) + '</a><span aria-hidden="true">→</span>'
    by_id = {o['id']: o for o in plan['route']}
    for segment in plan['reading_route']:
        occurrence = by_id[segment['occurrence_id']]; label = occurrence_label(vocal, segment)
        body += '<a href="#block-' + occurrence['block_id'] + '" data-focus-occurrence="' + occurrence['id'] + '" title="' + html.escape(label) + '">' + html.escape(segment['label'] + ' · ' + label) + '</a><span aria-hidden="true">→</span>'
    for occurrence in plan['route']:
        label = occurrence_label(vocal, occurrence)
        # 吉他长段反复与流畅阅读：新增当前演奏段落名，只用于阅读定位，不改变原秒时间。
        printed_block = next(b for b in plan['blocks'] if b['id'] == occurrence['block_id'])
        section_label = printed_block.get('display_label', '').replace(' · 续', '')
        payload.append({**occurrence, 'label': label, 'origin': origin,
                        'section_label': section_label,
                        'start_second': clock.seconds((occurrence['first'] - 1) * bar) - origin,
                        'end_second': clock.seconds(occurrence['last'] * bar) - origin})
    body += '<span>结束</span></div></div>'
    by_block = {b['id']: b for b in plan['blocks']}; by_occurrence = {o['id']: o for o in plan['route']}
    for row in rows:
        body += '<section class="score-row guitar-score-row repeat-score-row" id="repeat-line-' + str(row['line']) + '" style="--score-native-width:' + str(row['width']) + '">'
        # 重复乐句折叠与多遍挂词：修改试听工具显示，旧展开控件保留；默认收起，优先展示曲谱。
        # body += '<header><span>乐段' + ' · '.join(row['blocks']) + '</span></header><div class="repeat-navigation no-print">'
        # 吉他长段反复与流畅阅读：修改旧每行独立乐段标题，注释保留；用实际小节范围及共用段续行指示。
        # body += '<header><span>乐段' + ' · '.join(row['blocks']) + '</span></header><details class="repeat-audition no-print"><summary>展开各遍试听</summary><div class="repeat-navigation">'
        first_block, last_block = by_block[row['blocks'][0]], by_block[row['blocks'][-1]]
        row_label = occurrence_label(vocal, {'first': first_block['canonical_first'], 'last': last_block['canonical_last']})
        body += '<header><span>' + html.escape(row_label) + '</span></header><details class="repeat-audition no-print"><summary>展开各遍试听</summary><div class="repeat-navigation">'
        for name in row['blocks']:
            # 吉他长段反复与流畅阅读：修改内部字母试听标题，原标题注释保留；独立段只显示实际范围。
            # block = by_block[name]; body += '<div class="repeat-block-control"><b>' + name + '</b>'
            block = by_block[name]; body += '<div class="repeat-block-control"><b>' + html.escape(block.get('display_label') or occurrence_label(vocal, block['occurrences'][0])) + '</b>'
            for occurrence in block['occurrences']:
                # 吉他长段反复与流畅阅读：修改旧按行号唱的试听文案，注释保留；只有共用层才标实际演奏遍次。
                # body += '<div class="repeat-occurrence" data-occurrence-id="' + occurrence['id'] + '"><a href="#block-' + name + '" data-focus-occurrence="' + occurrence['id'] + '">第' + str(occurrence['pass']) + '行 · ' + occurrence_label(vocal, occurrence) + '</a><br>'
                pass_label = ('第' + str(occurrence['pass']) + '遍 · ') if len(block['occurrences']) > 1 else ''
                body += '<div class="repeat-occurrence" data-occurrence-id="' + occurrence['id'] + '"><a href="#block-' + name + '" data-focus-occurrence="' + occurrence['id'] + '">' + pass_label + occurrence_label(vocal, occurrence) + '</a><br>'
                body += play_buttons(vocal, occurrence['first'], singing=(folder / 'singing_preview.wav').exists()) + '</div>'
            body += '</div>'
        # 重复乐句折叠与多遍挂词：修改容器收尾，旧工具栏闭合保留；试听折叠容器不包括谱面。
        # body += '</div>' + row['guitar'] + '<div class="repeat-instructions">'
        body += '</div></details>' + row['guitar'] + '<div class="repeat-instructions">'
        for name in row['blocks']:
            # 吉他长段反复与流畅阅读：修改每行强制去向表，注释保留；普通续行不重复展示路线说明。
            # body += '<div><b>' + name + ' · 各遍去向</b>'
            exits = [by_occurrence[o['id']] for o in by_block[name]['occurrences'] if by_occurrence[o['id']]['exit']['kind'] not in ('continue', 'end')]
            if not exits: continue
            body += '<div>'
            for occurrence in by_block[name]['occurrences']:
                # 吉他长段反复与流畅阅读：修改冗长逐遍路线文本，注释保留；只保留实际分支边界。
                # body += '<p>' + str(occurrence['pass']) + '. ' + occurrence_label(vocal, occurrence) + '；' + html.escape(exit_caption(plan, by_occurrence[occurrence['id']])) + '</p>'
                if by_occurrence[occurrence['id']]['exit']['kind'] not in ('continue', 'end'):
                    body += '<p>第' + str(occurrence['pass']) + '遍：' + html.escape(exit_caption(plan, by_occurrence[occurrence['id']])) + '</p>'
            body += '</div>'
        body += '</div></section>'
    encoded = json.dumps(payload, ensure_ascii=False).replace('</', '<\\/')
    body += '<script>window.guitarRepeatRoute=' + encoded + ';</script>'
    page = html_page(title, body, PLAYER_SCRIPT + REPEAT_SCRIPT).replace('</style>', REPEAT_STYLE + '</style>', 1)
    (folder / 'score.html').write_text(page, 'utf-8')


# 重复乐句折叠与多遍挂词：新增实际SVG逐字形回读，检查各遍身份、对应弦品与跨声部时间列。
# 重复乐句折叠与多遍挂词：修改独立验证入口，旧签名保留；提供真实共享区段以重判器乐隐藏。
# def validate_repeat_rows(plan, rows, vocal, arrangement):
def validate_repeat_rows(plan, rows, vocal, arrangement, storage_shared):
    source = reference_vocal(vocal, arrangement); events = {e['id']: e for e in source['events']}
    # 重复乐句折叠与多遍挂词：修改验证集合，旧音符身份检查保留；增加可见歌词与实际TAB实音。
    # blocks = {b['id']: b for b in plan['blocks']}; errors = []; actual = set(); aligned = 0; max_error = 0.; identities = set()
    blocks = {b['id']: b for b in plan['blocks']}; errors = []; actual = set(); aligned = 0; max_error = 0.; identities = set()
    actual_lyrics = set(); notes_by_id = {n['id']: n for n in arrangement['notes']}
    from score_export import notation_at, jianpu_pitch
    for row in rows:
        root = ET.fromstring(row['guitar']); parents = {c: p for p in root.iter() for c in p}
        for node in root.iter():
            if node.get('id'):
                if node.get('id') in identities: errors.append('重复SVG身份：' + node.get('id'))
                identities.add(node.get('id'))
        for group in root.iter(NS + 'g'):
            if group.get('class') != 'repeat-block': continue
            block = blocks[group.get('data-block-id')]; bar = vocal['statistics']['bar_ticks']; guitar_x = defaultdict(list)
            represented_notes = set()
            for note in group.iter(NS + 'g'):
                if note.get('data-string'):
                    guitar_x[int(note.get('data-start-tick'))].append(visible_x(note.find(NS + 'text'), parents))
                    identity = note.get('data-source-note-id'); original = notes_by_id.get(identity)
                    if not original or identity in represented_notes:
                        errors.append('共用TAB存在额外／重复音符：' + str(identity)); continue
                    represented_notes.add(identity)
                    if (int(note.get('data-start-tick')), int(note.get('data-end-tick')), int(note.get('data-string'))) != (original['start_tick'], original['end_tick'], original['string']):
                        errors.append('共用TAB实音／时值被改变：' + identity)
            expected_notes = {n['id'] for n in arrangement['notes'] if (block['canonical_first'] - 1) * bar <= n['start_tick'] < block['canonical_last'] * bar}
            if represented_notes != expected_notes: errors.append('共用TAB存在音符遗漏：' + block['id'])
            layers = [g for g in group.iter(NS + 'g') if g.get('class') == 'repeat-vocal-layer']
            for layer in layers:
                occurrence = next(o for o in block['occurrences'] if o['id'] == layer.get('data-occurrence-id'))
                shift = (block['canonical_first'] - occurrence['first']) * bar
                for glyph in layer.iter(NS + 'g'):
                    if glyph.get('class') != 'vocal-time-glyph': continue
                    identity = glyph.get('data-event-id'); part = int(glyph.get('data-part')); key = (occurrence['id'], identity, part)
                    event = events.get(identity)
                    if not event or not occurrence['first'] <= event['measure'] <= occurrence['last'] or key in actual:
                        errors.append('各遍音符身份无效／重复：' + str(key)); continue
                    actual.add(key); tick = event['start_tick'] + part * 480 + shift
                    if int(glyph.get('data-start-tick')) != tick or int(glyph.get('data-source-start-tick')) != tick - shift:
                        errors.append('折叠拍位／原拍位无效：' + str(key))
                    key_definition, reference = notation_at(source, measure=event['measure'])
                    expected_text = '–' if part else str(jianpu_pitch(event['pitch_midi'], key_definition, reference)[0])
                    if glyph.find(NS + 'text').text != expected_text: errors.append('可见简谱音高改变：' + str(key))
                    if not event['grace']:
                        x = visible_x(glyph.find(NS + 'text'), parents)
                        for tx in guitar_x[tick]:
                            error = abs(x - tx); max_error = max(max_error, error); aligned += 1
                            if error > .02: errors.append('共同时间列偏移：' + str(key))
                for text in layer.iter(NS + 'text'):
                    identity = text.get('data-lyric-event-id')
                    if not identity: continue
                    event = events.get(identity); lyric_key = (occurrence['id'], identity)
                    if not event or text.text != (event.get('lyric') or {}).get('text') or lyric_key in actual_lyrics:
                        errors.append('可见歌词被改动／重复：' + str(lyric_key))
                    actual_lyrics.add(lyric_key)
    expected = set()
    # 重复乐句折叠与多遍挂词：新增仅真实器乐行隐藏参考声部，所有挂词及普通音必须出现在某一遍。
    from accompaniment_export import instrumental_guitar_row
    from phrase_harmony_plan import arrangement_view
    # 重复乐句折叠与多遍挂词：修改共享输入来源，旧隐藏字段保留；只信任真实输入，拒绝SVG自报。
    # shared = arrangement_view(plan['_validation_shared'], vocal) if '_validation_shared' in plan else None
    shared = arrangement_view(storage_shared, vocal)
    for block in plan['blocks']:
        for occurrence in block['occurrences']:
            for event in events.values():
                if occurrence['first'] <= event['measure'] <= occurrence['last']:
                    for part in range({'whole': 4, 'half': 2}.get(event['type'], 1)):
                        expected.add((occurrence['id'], event['id'], part))
    # 重复乐句折叠与多遍挂词：新增器乐隐藏声部的期望集合按实际块独立判定，不能直接跳过缺失的挂词。
    # 重复乐句折叠与多遍挂词：修改隐藏条件，旧按缺失反推保留；真实器乐及无演唱才能隐藏参考行。
    # hidden = {b['id'] for b in plan['blocks'] if not any(o['id'] == key[0] for o in b['occurrences'] for key in actual)}
    hidden = {b['id'] for b in plan['blocks'] if bool(arrangement.get('notation_regions')) and
              instrumental_guitar_row(shared, source, b['canonical_first'], b['canonical_last'])}
    for block in plan['blocks']:
        if block['id'] not in hidden: continue
        for occurrence in block['occurrences']:
            selected = [e for e in events.values() if occurrence['first'] <= e['measure'] <= occurrence['last']]
            if any(e.get('lyric', {}).get('text') or e['pitch_midi'] is not None for e in selected):
                errors.append('错误隐藏了实际人声／歌词：' + occurrence['id'])
            else: expected = {key for key in expected if key[0] != occurrence['id']}
    if expected != actual: errors.append('各遍简谱字形存在缺失／额外项：' + str(len(expected ^ actual)))
    expected_lyrics = {(o['id'], e['id']) for b in plan['blocks'] for o in b['occurrences'] for e in events.values()
                       if o['first'] <= e['measure'] <= o['last'] and (e.get('lyric') or {}).get('text')}
    if expected_lyrics != actual_lyrics: errors.append('各遍可见歌词存在遗漏／额外项：' + str(len(expected_lyrics ^ actual_lyrics)))
    # 吉他长段反复与流畅阅读：新增真实印刷符号回读，不能只检查JSON路线。
    from guitar_repeat_marks import validate_marks
    marker_check = validate_marks(plan, rows); errors.extend(marker_check['errors'])
    return {'valid': not errors, 'errors': errors, 'printed_markers': marker_check, 'vocal_glyphs': len(actual), 'aligned_onsets': aligned,
            'max_alignment_error_pixels': max_error, 'all_occurrence_glyphs_preserved': expected == actual,
            'visible_lyric_units': len(actual_lyrics), 'all_lyrics_preserved': expected_lyrics == actual_lyrics}


# 重复乐句折叠与多遍挂词：新增正式导出显示入口，完整展开页保留，录音与MIDI一字节不改。
# 旧工程功能自动升级与三曲器乐表现统一：修改展开谱来源，旧签名保留；区分重绘音乐后的新展开页与已有反复页重排。
# def write_repeat_score(folder, storage_shared, vocal, arrangement):
def write_repeat_score(folder, storage_shared, vocal, arrangement, fresh_chronological=False):
    from phrase_harmony_plan import arrangement_view
    folder = Path(folder); full_path = folder / 'score_full.html'
    # 旧工程功能自动升级与三曲器乐表现统一：修改展开页缓存，旧仅首次创建保留；新重音必须同步进入完整展开谱。
    # if not full_path.exists(): full_path.write_bytes((folder / 'score.html').read_bytes())
    if fresh_chronological or not full_path.exists(): full_path.write_bytes((folder / 'score.html').read_bytes())
    full_html = full_path.read_text('utf-8'); working = deepcopy(arrangement)
    plan = build_repeat_plan(storage_shared, vocal, working); check = validate_repeat_plan(plan, storage_shared, vocal, working)
    if not check['valid']: raise ValueError('反复路线验证失败：' + str(check['errors']))
    row_dir = folder / 'repeat_rows'; row_dir.mkdir(parents=True, exist_ok=True)
    rows = render_lines(plan, arrangement_view(storage_shared, vocal), vocal, working, row_dir)
    # 重复乐句折叠与多遍挂词：修改可见验收调用，旧四参数保留；实际区段参与隐藏条件判断。
    # geometry = validate_repeat_rows(plan, rows, vocal, working)
    geometry = validate_repeat_rows(plan, rows, vocal, working, storage_shared)
    if not geometry['valid']: raise ValueError('折叠谱可见音符／时间列校验失败：' + str(geometry['errors'][:8]))
    save_json(folder / 'repeat_plan.json', plan)
    save_json(folder / 'repeat_validation.json', {'plan': check, 'visible_score': geometry})
    # 重复乐句折叠与多遍挂词：修改调用，旧页面参数保留；未决源拍轴继续显示，音乐不重判。
    # write_repeat_html(folder, vocal, working, plan, rows, full_html)
    # 吉他长段反复与流畅阅读：修改旧总生成反复页，注释保留；无完整长段时直接采用原曲展开谱。
    # write_repeat_html(folder, vocal, working, plan, rows, full_html, storage_shared.get('source_clock_review'))
    if plan['folded_blocks']:
        write_repeat_html(folder, vocal, working, plan, rows, full_html, storage_shared.get('source_clock_review'))
    else:
        (folder / 'score.html').write_text(full_html, 'utf-8')
    return {'valid': True, 'plan': check, 'visible_score': geometry,
            'line_count': len(rows), 'chronological_score': 'score_full.html',
            'notation_only': True, 'midi_and_audio_order': 'original_recording'}
