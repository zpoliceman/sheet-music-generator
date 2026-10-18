"""十一首可编辑五线谱：同源 MusicXML/MXL、按拍连梁和本地分页五线谱。"""
# 十一首可编辑五线谱：新增通用排版层；不重新识别或修改原简谱/MIDI。
from __future__ import annotations
import argparse
import copy
from fractions import Fraction
import hashlib
import html
import json
# 十一首可编辑五线谱：新增独立输出目录的来源跳转地址。
import os
from urllib.parse import quote
from pathlib import Path
import sys
import time
import xml.etree.ElementTree as ET
import zipfile
import score_export as score

VERSION = 1
MEI_NS = {'m': 'http://www.music-encoding.org/ns/mei'}
XML_ID = '{http://www.w3.org/XML/1998/namespace}id'
RENDER_OPTIONS = {'pageWidth': 2100, 'pageHeight': 2970, 'scale': 50,
                  'pageMarginLeft': 100, 'pageMarginRight': 100,
                  'pageMarginTop': 100, 'pageMarginBottom': 100,
                  'breaks': 'auto', 'footer': 'none', 'header': 'none',
                  'condense': 'none', 'mnumInterval': 1, 'svgViewBox': True,
                  # 十一首可编辑五线谱：原词间距参数保留，增加英文整词间空白。
                  # 'font': 'Bravura', 'lyricSize': 5, 'spacingSystem': 8}
                  'font': 'Bravura', 'lyricSize': 5, 'lyricWordSpace': 3.0, 'spacingSystem': 8}
FLAGS = {'eighth': 1, '16th': 2, '32nd': 3, '64th': 4, '128th': 5}

# 十一首可编辑五线谱：新增独立 XML 音乐语义签名；忽略排版与等音拼写，保留实际音高及演唱关系。
def musical_signature(root):
    parts = root.findall('part')
    if len(parts) != 1:
        raise ValueError('五线谱入口只接受当前单声部人声项目。')
    division = None
    absolute = Fraction(0)
    records, keys, meters, tempos = [], [], [], []
    ids = set()
    for measure in parts[0].findall('measure'):
        number = int(measure.get('number'))
        attrs = measure.find('attributes')
        if attrs is not None:
            if attrs.find('transpose') is not None or int(attrs.findtext('staves', '1')) != 1:
                raise ValueError('移调乐器或多谱表不在当前导出范围。')
            if attrs.find('divisions') is not None:
                division = Fraction(attrs.findtext('divisions'))
            if attrs.find('key') is not None:
                keys.append((number, int(attrs.findtext('key/fifths', '0')), attrs.findtext('key/mode', 'major')))
            if attrs.find('time') is not None:
                meters.append((number, int(attrs.findtext('time/beats')), int(attrs.findtext('time/beat-type'))))
        if not division or division <= 0 or measure.find('backup') is not None or measure.find('forward') is not None:
            raise ValueError('五线谱需要有效 divisions 和单声部连续时值。')
        cursor = Fraction(0)
        for child in measure:
            if child.tag == 'direction':
                for sound in child.findall('sound'):
                    if sound.get('tempo'):
                        offset = Fraction(child.findtext('offset', '0')) / division
                        tempos.append((str(absolute + cursor + offset), str(Fraction(sound.get('tempo')))))
            if child.tag != 'note':
                continue
            if child.find('chord') is not None or child.find('unpitched') is not None:
                raise ValueError('当前仅导出单声部有固定音高的人声。')
            identity = child.get('id')
            if not identity or identity in ids:
                raise ValueError('音符需要唯一来源 ID，不能遗漏或重复。')
            ids.add(identity)
            pitch = child.find('pitch')
            midi = None if pitch is None else (score.PITCH_CLASS[pitch.findtext('step')] +
                    int(pitch.findtext('alter', '0')) + 12 * (int(pitch.findtext('octave')) + 1))
            grace = child.find('grace')
            duration = Fraction(child.findtext('duration', '0')) / division
            lyrics = [(x.get('number', '1'), ''.join(t.text or '' for t in x.findall('text')),
                       x.findtext('syllabic'), x.find('extend').get('type', 'start') if x.find('extend') is not None else None)
                      for x in child.findall('lyric')]
            records.append({'id': identity, 'measure': number, 'start': str(absolute + cursor),
                            'duration': str(duration), 'pitch_midi': midi,
                            'rest': child.find('rest') is not None, 'grace': grace is not None,
                            'grace_timing': dict(grace.attrib) if grace is not None else None,
                            'type': child.findtext('type'), 'dots': len(child.findall('dot')),
                            'ties': sorted(t.get('type') for t in child.findall('tie')),
                            'slurs': sorted((s.get('number', '1'), s.get('type')) for s in child.findall('notations/slur')),
                            'tuplets': ET.tostring(child.find('time-modification'), encoding='unicode') if child.find('time-modification') is not None else None,
                            'lyrics': lyrics})
            if grace is None:
                cursor += duration
        absolute += cursor
    return {'notes': records, 'keys': keys, 'meters': meters, 'tempos': tempos, 'total_quarters': str(absolute)}

# 十一首可编辑五线谱：新增按调内级数及简谱临时变音选择音名，F#调的7写E#，实际MIDI音高不变。
def staff_spelling(midi, fifths):
    major_name = next((name for name, value in score.MAJOR_FIFTHS.items() if value == fifths), None)
    if major_name is None:
        raise ValueError('调号升降号数量超出支持范围。')
    key = score.key_definition(major_name + ':major')
    degree, _, accidental = score.jianpu_pitch(midi, key, 60 + key['jianpu_one_pc'])
    letters = 'CDEFGAB'
    step = letters[(letters.index(major_name[0]) + int(degree) - 1) % 7]
    alterations = {letter: 0 for letter in letters}
    for letter in ('FCGDAEB'[:fifths] if fifths > 0 else 'BEADGCF'[:-fifths]):
        alterations[letter] = 1 if fifths > 0 else -1
    alter = alterations[step] + {'♯': 1, '♭': -1, '': 0}[accidental]
    octave = (midi - score.PITCH_CLASS[step] - alter) // 12 - 1
    if score.PITCH_CLASS[step] + alter + 12 * (octave + 1) != midi:
        raise ValueError('五线谱等音拼写改变了实际音高。')
    return step, alter, octave

# 十一首可编辑五线谱：新增跨转调延音维持起点音名，避免等音改写导致延音断开。
def respell_staff(root):
    fifths, tied = 0, None
    for measure in root.findall('part/measure'):
        key = measure.find('attributes/key')
        if key is not None:
            fifths = int(key.findtext('fifths', '0'))
        for note in measure.findall('note'):
            pitch = note.find('pitch')
            if pitch is None:
                continue
            midi = score.PITCH_CLASS[pitch.findtext('step')] + int(pitch.findtext('alter', '0')) + 12 * (int(pitch.findtext('octave')) + 1)
            ties = [x.get('type') for x in note.findall('tie')]
            spelling = tied if 'stop' in ties and tied else staff_spelling(midi, fifths)
            step, alter, octave = spelling
            if score.PITCH_CLASS[step] + alter + 12 * (octave + 1) != midi:
                raise ValueError('跨调号延音的实际音高不一致。')
            pitch.clear()
            score.tag(pitch, 'step', step)
            if alter:
                score.tag(pitch, 'alter', alter)
            score.tag(pitch, 'octave', octave)
            # 十一首可编辑五线谱：新增交由编辑器按调号计算显示升降号，避免旧拼写的accidental残留。
            for mark in list(note.findall('accidental')):
                note.remove(mark)
            # 十一首可编辑五线谱：原状态更新保留；中间倚音不能解除正在延续的主音拼写。
            # tied = spelling if 'start' in ties else None
            if note.find('grace') is None:
                tied = spelling if 'start' in ties else None

# 十一首可编辑五线谱：新增按小节、调号和八度写出必要临时升降号；排版库不能只靠pitch/alter补齐显示。
def add_staff_accidentals(root):
    fifths = 0
    names = {-2: 'flat-flat', -1: 'flat', 0: 'natural', 1: 'sharp', 2: 'double-sharp'}
    for measure in root.findall('part/measure'):
        key = measure.find('attributes/key')
        if key is not None:
            fifths = int(key.findtext('fifths', '0'))
        default = {letter: 0 for letter in 'CDEFGAB'}
        for letter in ('FCGDAEB'[:fifths] if fifths > 0 else 'BEADGCF'[:-fifths]):
            default[letter] = 1 if fifths > 0 else -1
        state = {}
        for note in measure.findall('note'):
            pitch = note.find('pitch')
            if pitch is None:
                continue
            step, octave = pitch.findtext('step'), int(pitch.findtext('octave'))
            alter = int(pitch.findtext('alter', '0')); identity = (step, octave)
            for old in list(note.findall('accidental')):
                note.remove(old)
            tied = any(mark.get('type') == 'stop' for mark in note.findall('tie'))
            if not tied and alter != state.get(identity, default[step]):
                if alter not in names:
                    raise ValueError('五线谱临时升降号超出双升/双降范围。')
                mark = ET.Element('accidental'); mark.text = names[alter]
                position = next((i for i, child in enumerate(note) if child.tag in (
                    'time-modification','stem','notehead','notehead-text','staff','beam','notations','lyric','play','listen')), len(note))
                note.insert(position, mark)
            state[identity] = alter

# 十一首可编辑五线谱：新增 XML 有序插入连梁；普通音跨歌词仍在同拍连接，休止符和拍界打断。
def add_beat_beams(root):
    division, beats, denominator = 480, 4, 4
    for measure in root.findall('part/measure'):
        attrs = measure.find('attributes')
        if attrs is not None:
            division = int(attrs.findtext('divisions', str(division)))
            beats = int(attrs.findtext('time/beats', str(beats)))
            denominator = int(attrs.findtext('time/beat-type', str(denominator)))
        beat = Fraction(4 * division, denominator)
        if denominator == 8 and beats > 3 and beats % 3 == 0:
            beat *= 3
        rows, cursor = [], Fraction(0)
        for note in measure.findall('note'):
            for old in list(note.findall('beam')):
                note.remove(old)
            grace = note.find('grace') is not None
            duration = Fraction(note.findtext('duration', '0'))
            rows.append({'node': note, 'offset_ticks': cursor, 'duration_ticks': duration,
                         'type': note.findtext('type'), 'grace': grace,
                         'pitch_midi': None if note.find('rest') is not None else 1})
            if not grace:
                cursor += duration
        for grace in (False, True):
            sequence = rows if grace else [r for r in rows if not r['grace']]
            primary = []
            run = []
            for r in sequence:
                eligible = (r['grace'] == grace and r['pitch_midi'] is not None and FLAGS.get(r['type'], 0) >= 1
                            and (grace or (r['offset_ticks'] + r['duration_ticks'] <= (r['offset_ticks'] // beat + 1) * beat)))
                previous = run[-1] if run else None
                connected = previous is not None and (previous['offset_ticks'] == r['offset_ticks'] if grace else
                             previous['offset_ticks'] + previous['duration_ticks'] == r['offset_ticks'])
                same_beat = previous is not None and previous['offset_ticks'] // beat == r['offset_ticks'] // beat
                if run and (not eligible or not connected or not same_beat):
                    primary.append(run); run = []
                if eligible:
                    run.append(r)
            if run:
                primary.append(run)
            for group in primary:
                if len(group) < 2:
                    continue
                for level in range(1, max(FLAGS.get(r['type'], 0) for r in group) + 1):
                    subgroups, sub = [], []
                    for r in group:
                        if FLAGS.get(r['type'], 0) >= level:
                            sub.append(r)
                        elif sub:
                            subgroups.append(sub); sub = []
                    if sub:
                        subgroups.append(sub)
                    for sub in subgroups:
                        for i, r in enumerate(sub):
                            label = ('begin' if i == 0 else 'end' if i == len(sub)-1 else 'continue') if len(sub) > 1 else (
                                     'backward hook' if group.index(r) > 0 else 'forward hook')
                            mark = ET.Element('beam', number=str(level)); mark.text = label
                            node = r['node']
                            position = next((j for j, child in enumerate(node) if child.tag in ('notations', 'lyric', 'play', 'listen')), len(node))
                            node.insert(position, mark)

# 十一首可编辑五线谱：新增专用A4五线谱交换文件；移除仅用于简谱的长提示，提示仍保存在来源和页面。
def build_staff_musicxml(source_root, title):
    before = musical_signature(source_root)
    root = copy.deepcopy(source_root)
    work = root.find('work')
    if work is None:
        work = ET.Element('work'); root.insert(0, work)
    work_title = work.find('work-title')
    if work_title is None:
        work_title = score.tag(work, 'work-title')
    work_title.text = title + ' · 人声五线谱'
    identification = root.find('identification')
    if identification is not None:
        for creator in list(identification.findall('creator')):
            identification.remove(creator)
        encoding = identification.find('encoding')
        if encoding is None:
            encoding = ET.Element('encoding'); identification.insert(0, encoding)
        score.tag(encoding, 'software', 'sheet_music_generator staff_export v' + str(VERSION))
    defaults = root.find('defaults')
    if defaults is not None:
        root.remove(defaults)
    defaults = ET.Element('defaults')
    root.insert(list(root).index(root.find('part-list')), defaults)
    scaling = score.tag(defaults, 'scaling')
    score.tag(scaling, 'millimeters', 7); score.tag(scaling, 'tenths', 40)
    page = score.tag(defaults, 'page-layout')
    score.tag(page, 'page-height', 1697.142857); score.tag(page, 'page-width', 1200)
    margins = score.tag(page, 'page-margins', type='both')
    for name in ('left-margin','right-margin','top-margin','bottom-margin'):
        score.tag(margins, name, 57.142857)
    score.tag(defaults, 'word-font', **{'font-family': 'Microsoft YaHei', 'font-size': '10'})
    score.tag(defaults, 'lyric-font', **{'font-family': 'Microsoft YaHei', 'font-size': '11'})
    for name in root.findall('part-list/score-part/part-name'):
        name.text = '人声'
    first_attrs = root.find('part/measure/attributes')
    if first_attrs is None:
        raise ValueError('首小节缺少谱表属性。')
    details = first_attrs.find('staff-details')
    if details is None:
        details = score.tag(first_attrs, 'staff-details')
    details.clear(); score.tag(details, 'staff-type', 'regular'); score.tag(details, 'staff-lines', 5)
    for measure in root.findall('part/measure'):
        for direction in list(measure.findall('direction')):
            words = direction.find('direction-type/words')
            if words is not None and (words.text or '').startswith('自动草稿：'):
                if direction.find('sound') is None:
                    measure.remove(direction)
            elif words is not None and (words.text or '').startswith('转1='):
                words.text = '转调：' + words.text[3:] + '大调'
                # 十一首可编辑五线谱：新增转调文字大小和上方位置，避免挤占小节编号。
                words.set('font-size', '10')
                words.set('default-y', '65')
    # 十一首可编辑五线谱：新增通用BPM文字替代预览缺失的私有音乐字体，sound仍保留原准确速度。
    for direction_type in root.findall('part/measure/direction/direction-type'):
        metronome = direction_type.find('metronome')
        if metronome is not None and metronome.findtext('beat-unit') == 'quarter':
            value = metronome.findtext('per-minute')
            direction_type.remove(metronome)
            score.tag(direction_type, 'words', 'BPM ' + format(float(value), '.6g'))
    respell_staff(root)
    # 十一首可编辑五线谱：新增必要临时变音符号，实际音高及同音延续不改变。
    add_staff_accidentals(root)
    add_beat_beams(root)
    if before != musical_signature(root):
        raise ValueError('五线谱排版改变了音高、时值、歌词、连音、拍号或调号，停止导出。')
    return root

# 十一首可编辑五线谱：新增标准压缩MXL，与未压缩MusicXML内容逐字节等价。
def write_mxl(path, musicxml):
    container = ('<?xml version="1.0" encoding="UTF-8"?>\n'
                 '<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" version="1.0">'
                 '<rootfiles><rootfile full-path="score.musicxml" media-type="application/vnd.recordare.musicxml+xml"/></rootfiles></container>')
    with zipfile.ZipFile(path, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('mimetype', 'application/vnd.recordare.musicxml', compress_type=zipfile.ZIP_STORED)
        archive.writestr('META-INF/container.xml', container)
        archive.writestr('score.musicxml', musicxml)
    with zipfile.ZipFile(path) as archive:
        if archive.read('score.musicxml') != musicxml or archive.testzip() is not None:
            raise ValueError('MXL压缩交换文件校验失败。')

# 十一首可编辑五线谱：新增实际排版导入核验，每个来源音符、词和时值必须进入五线谱。
def verify_renderer(root, mei_root):
    rendered = {n.get(XML_ID): n for n in mei_root.findall('.//m:note', MEI_NS)}
    expected = [n for n in root.findall('part/measure/note') if n.find('pitch') is not None]
    if len(rendered) != len(expected):
        raise ValueError('五线谱排版导入遗漏或新增了音符。')
    for note in expected:
        identity = note.get('id'); other = rendered.get(identity)
        if other is None:
            raise ValueError('五线谱排版丢失来源音符：' + identity)
        if other.get('pname', '').upper() != note.findtext('pitch/step') or int(other.get('oct')) != int(note.findtext('pitch/octave')):
            raise ValueError('五线谱排版改变音名或八度：' + identity)
        # 十一首可编辑五线谱：新增排版实际升降音核验，不能仅核对音名而遗漏临时升降号。
        acc = other.get('accid.ges') or other.get('accid')
        child_acc = other.find('m:accid', MEI_NS)
        if child_acc is not None:
            acc = child_acc.get('accid.ges') or child_acc.get('accid') or acc
        mei_alter = {'s': 1, 'f': -1, 'ss': 2, 'ff': -2, 'x': 2, 'n': 0, None: 0}.get(acc)
        if mei_alter != int(note.findtext('pitch/alter', '0')):
            raise ValueError('五线谱排版改变实际升降音：' + identity)
        # 十一首可编辑五线谱：新增核对显示升降号，音高ges正确不等于谱面符号已经画出。
        expected_symbol = note.findtext('accidental')
        if expected_symbol:
            shown = child_acc.get('accid') if child_acc is not None else other.get('accid')
            required = {'flat-flat':'ff','flat':'f','natural':'n','sharp':'s','double-sharp':'ss'}[expected_symbol]
            if shown != required:
                raise ValueError('五线谱缺少必要临时升降符号：' + identity)
        if note.find('grace') is None and int(other.get('dur.ppq', '0')) != int(note.findtext('duration')):
            raise ValueError('五线谱排版改变音符时值：' + identity)
        texts = [x.text or '' for x in note.findall('lyric/text')]
        # 十一首可编辑五线谱：原逐字比较保留；MEI用空syl表达延长线，不能误判新增歌词。
        # actual = [x.text or '' for x in other.findall('m:verse/m:syl', MEI_NS)]
        actual = [x.text for x in other.findall('m:verse/m:syl', MEI_NS) if x.text]
        if texts != actual:
            raise ValueError('五线谱排版改变歌词：' + identity)
    return {'pitched_note_count': len(expected), 'source_ids_preserved': True,
            'spelling_octaves_durations_and_lyrics_preserved': True}

# 十一首可编辑五线谱：新增预览转调文字垂直错开小节号，补偿排版器未采用MusicXML default-y的情况。
def lift_key_labels(svg):
    root = ET.fromstring(svg)
    changed = False
    for group in root.iter('{http://www.w3.org/2000/svg}g'):
        if 'dir' in group.get('class', '').split() and ''.join(text.strip() for text in group.itertext()).startswith('转调：'):
            group.set('transform', 'translate(0,-300) ' + group.get('transform', ''))
            changed = True
    if not changed:
        return svg
    # 十一首可编辑五线谱：新增保持浏览器可识别的默认SVG命名空间，不生成ns0:svg标签。
    ET.register_namespace('', 'http://www.w3.org/2000/svg')
    ET.register_namespace('xlink', 'http://www.w3.org/1999/xlink')
    return ET.tostring(root, encoding='unicode')

# 十一首可编辑五线谱：新增把辅助转调文字放到页面说明，SVG保留标准调号变化，避免任何小节号碰撞。
def key_labels_in_header(svg):
    root = ET.fromstring(svg)
    changed = False
    for parent in root.iter():
        for child in list(parent):
            if child.tag == '{http://www.w3.org/2000/svg}g' and 'dir' in child.get('class', '').split() and ''.join(text.strip() for text in child.itertext()).startswith('转调：'):
                parent.remove(child); changed = True
    if not changed:
        return svg
    ET.register_namespace('', 'http://www.w3.org/2000/svg')
    ET.register_namespace('xlink', 'http://www.w3.org/1999/xlink')
    return ET.tostring(root, encoding='unicode')

# 十一首可编辑五线谱：新增无网络分页阅读入口，编辑指向真正MusicXML/MXL文件，SVG只负责显示。
# 十一首可编辑五线谱：原固定同目录接口保留；另存预览正确链接到来源简谱/MIDI。
# def staff_html(title, pages):
# 十一首可编辑五线谱：原接口保留，新增页面上方的分小节调号说明。
# def staff_html(title, pages, jianpu_url='jianpu.html', midi_url='vocal_draft.mid'):
def staff_html(title, pages, jianpu_url='jianpu.html', midi_url='vocal_draft.mid', key_summary=''):
    options = ''.join(f'<option value="page-{i}">第{i}页</option>' for i in range(1, len(pages)+1))
    sections = ''.join(f'<section class="page" id="page-{i}"><div class="page-label">{html.escape(title)} · 第{i}/{len(pages)}页</div>{svg}</section>' for i, svg in enumerate(pages, 1))
    return '''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>TITLE · 五线谱</title>
<style>body{margin:0;background:#eef2f6;color:#18314b;font-family:"Microsoft YaHei",sans-serif;line-height:1.7}header{max-width:1100px;margin:24px auto;padding:20px;background:white;border-radius:8px}h1{font-size:25px;margin:0 0 10px}a{color:#205a98;margin-right:18px}p{margin:10px 0}.controls{display:flex;gap:18px;align-items:center;flex-wrap:wrap}.scroll{overflow-x:auto;padding:0 14px 30px}#score-view{width:1050px;margin:auto}.page{background:white;margin:0 auto 22px;box-shadow:0 2px 12px #d5dde6}.page svg{width:100%;height:auto;display:block}.page-label{padding:12px 22px;color:#52677b;font-size:14px}select,input{font:inherit}/* 十一首可编辑五线谱：原 svg text,svg tspan{font-family:"Microsoft YaHei","Times New Roman",serif} 注释保留，使用排版字体。 */@media print{header,.page-label{display:none}.scroll{padding:0;overflow:visible}#score-view{width:100%!important}.page{margin:0;box-shadow:none;break-after:page}.page:last-child{break-after:auto}@page{size:A4 portrait;margin:0}}</style></head><body><header><h1>TITLE · 人声五线谱</h1><p><a href="staff_score.musicxml" download>下载MusicXML（可编辑）</a><a href="staff_score.mxl" download>下载MXL（压缩可编辑）</a><a href="jianpu.html">对应简谱</a><a href="vocal_draft.mid">试听MIDI</a></p><p>用写谱软件打开MusicXML或MXL即可修改音符、时值、歌词和排版。本页用于阅读，音乐内容沿用当前简谱。</p><div class="controls"><label>跳转页 <select id="jump">OPTIONS</select></label><label>谱面大小 <input id="zoom" type="range" min="75" max="160" value="100"> <span id="zoom-label">100%</span></label></div></header><main class="scroll"><div id="score-view">SECTIONS</div></main><script>
// 十一首可编辑五线谱：新增只读页面缩放及分页定位，编辑由标准乐谱文件完成。
document.getElementById('zoom').addEventListener('input',function(){document.getElementById('score-view').style.width=(1050*this.value/100)+'px';document.getElementById('zoom-label').textContent=this.value+'%';});document.getElementById('jump').addEventListener('change',function(){document.getElementById(this.value).scrollIntoView({behavior:'smooth'});});
</script></body></html>'''.replace('TITLE', html.escape(title)).replace('OPTIONS', options).replace('SECTIONS', sections).replace('<div class="controls">', '<p>调号：'+html.escape(key_summary)+'</p><div class="controls">').replace('href="jianpu.html"', 'href="'+html.escape(jianpu_url, quote=True)+'"').replace('href="vocal_draft.mid"', 'href="'+html.escape(midi_url, quote=True)+'"')

# 十一首可编辑五线谱：新增可复用导出API和来源哈希检查；调用制谱程序时自动产生五线谱。
def export_staff_score(score_dir, output_dir=None, render=True):
    started = time.perf_counter()
    source = Path(score_dir).resolve(); output = Path(output_dir or score_dir).resolve()
    original_xml = source / 'vocal_draft.musicxml'; project_path = source / 'project.json'
    project = score.read_json(project_path)
    protected = {p: score.sha256(p) for p in (original_xml, project_path, source/'vocal_draft.mid', source/'jianpu.html', source/'jianpu.svg') if p.exists()}
    original = ET.parse(original_xml).getroot()
    title = project.get('title', '人声旋律')
    root = build_staff_musicxml(original, title)
    validation = score.validate_score(project, root)
    if not validation['valid']:
        raise ValueError('五线谱音乐结构核验未通过：' + ';'.join(validation['errors'][:5]))
    output.mkdir(parents=True, exist_ok=True)
    xml_path = output / 'staff_score.musicxml'
    if xml_path in protected or output/'staff_score.mxl' in protected:
        raise ValueError('五线谱输出不能覆盖源文件。')
    ET.indent(root, space='  ')
    data = ET.tostring(root, encoding='utf-8', xml_declaration=True)
    xml_path.write_bytes(data)
    write_mxl(output/'staff_score.mxl', data)
    renderer, renderer_check, pages = None, None, []
    if render:
        import verovio
        toolkit = verovio.toolkit()
        # 十一首可编辑五线谱：原路径导入保留；Windows库无法读取中文路径时改用同一XML字节真实导入。
        # if not toolkit.setOptions(RENDER_OPTIONS) or not toolkit.loadFile(str(xml_path)):
        if not toolkit.setOptions(RENDER_OPTIONS) or not toolkit.loadData(data.decode('utf-8')):
            raise ValueError('实际五线谱排版导入失败：' + toolkit.getLog())
        renderer = {'name': 'Verovio', 'version': toolkit.getVersion(), 'options': RENDER_OPTIONS, 'log': toolkit.getLog()}
        mei_root = ET.fromstring(toolkit.getMEI())
        renderer_check = verify_renderer(root, mei_root)
        pages_dir = output/'staff_pages'; pages_dir.mkdir(parents=True, exist_ok=True)
        visible_ids = set()
        for page_number in range(1, toolkit.getPageCount()+1):
            svg = toolkit.renderToSVG(page_number)
            # 十一首可编辑五线谱：新增仅调整转调标记显示位置，来源音符与所有音乐字段不改。
            # 十一首可编辑五线谱：原抬高方案保留；页首和密集小节无法稳定避让，改为页面说明。
            # svg = lift_key_labels(svg)
            svg = key_labels_in_header(svg)
            svg_root = ET.fromstring(svg)
            visible_ids.update(n.get('id') for n in svg_root.iter() if n.get('id'))
            pages.append(svg)
            (pages_dir/f'page_{page_number:03d}.svg').write_text(svg, encoding='utf-8')
        expected_ids = {n.get('id') for n in root.findall('part/measure/note') if n.find('pitch') is not None}
        if not pages or not expected_ids.issubset(visible_ids):
            raise ValueError('五线谱分页漏掉了来源音符。')
        renderer_check['all_pitched_source_ids_visible_in_pages'] = True
        # 十一首可编辑五线谱：原同目录链接保留；独立输出目录用正确相对路径。
        # (output/'staff.html').write_text(staff_html(title, pages), encoding='utf-8')
        links = []
        for name in ('jianpu.html', 'vocal_draft.mid'):
            try:
                url = quote(Path(os.path.relpath(source/name, output)).as_posix(), safe='/')
            except ValueError:
                url = (source/name).as_uri()
            links.append(url)
        # 十一首可编辑五线谱：原预览调用保留，转调小节和调号写入页头供读谱定位。
        # (output/'staff.html').write_text(staff_html(title, pages, *links), encoding='utf-8')
        sections = project.get('notation', {}).get('key_segments') or [{'start_measure': 1, 'key': project['notation']['key']}]
        key_summary = '；'.join('第'+str(section['start_measure'])+'小节 '+section['key']['label'].replace(':major', '大调').replace(':minor', '小调') for section in sections)
        (output/'staff.html').write_text(staff_html(title, pages, *links, key_summary=key_summary), encoding='utf-8')
    preservation = {str(p): {'before': digest, 'after': score.sha256(p)} for p, digest in protected.items()}
    if any(row['before'] != row['after'] for row in preservation.values()):
        raise ValueError('原简谱、MIDI或项目在五线谱导出期间改变。')
    signature = musical_signature(root)
    result = {'task': '十一首可编辑五线谱', 'version': VERSION, 'status': 'passed', 'title': title,
              'source_score_dir': str(source), 'output_dir': str(output), 'measure_count': project['statistics']['measure_count'],
              'page_count': len(pages), 'pitched_events': sum(n['pitch_midi'] is not None for n in signature['notes']),
              'musicxml_source_sha256': protected[original_xml], 'project_source_sha256': protected[project_path],
              'source_music_semantics_preserved': musical_signature(original) == signature,
              'mxl_exact_xml_bytes_preserved': True, 'key_signatures': signature['keys'], 'structure': validation,
              'renderer': renderer, 'renderer_import': renderer_check, 'original_files': preservation,
              'external_editor_gui_roundtrip': 'not_tested', 'editable_formats': ['MusicXML', 'MXL'],
              'seconds': time.perf_counter()-started,
              'artifacts': {'musicxml': str(xml_path), 'mxl': str(output/'staff_score.mxl'),
                            'preview': str(output/'staff.html') if render else None}}
    score.save_json(output/'staff_validation.json', result)
    return result

# 十一首可编辑五线谱：新增独立命令；既可处理当前结果，也可用于未来歌曲，无歌曲名称特判。
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--score-dir', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path)
    parser.add_argument('--xml-only', action='store_true')
    parser.add_argument('--report', type=Path)
    args = parser.parse_args()
    result = export_staff_score(args.score_dir, args.output_dir, not args.xml_only)
    if args.report:
        score.save_json(args.report, result)
    print(json.dumps({k:result[k] for k in ('status','title','measure_count','page_count','seconds','artifacts')}, ensure_ascii=False))

if __name__ == '__main__':
    main()
