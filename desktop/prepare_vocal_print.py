"""从最终伴奏工程读取同一份人声，生成独立简谱打印页，不重新分析歌曲。"""
import argparse
from collections import Counter
import hashlib
import html
import json
from pathlib import Path
import sys
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from score_export import read_json
from accompaniment_export import vocal_row
from beat_phase_alignment import score_row_ranges, display_measure
from metrical_timing import selected_quarter_tempo


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    source = args.source.resolve()
    output = args.output.resolve()
    if not source.is_relative_to(ROOT) or not output.is_relative_to(ROOT / 'HTML/runtime'):
        raise ValueError('打印来源必须在本工程中，工作文件必须在HTML/runtime中。')
    output.mkdir(parents=True, exist_ok=False)
    original = source.read_bytes()
    project = read_json(source)
    from guitar_instrumental_expression import reference_vocal
    vocal = reference_vocal(project['accepted_vocal_project'],project['arrangements']['guitar'])
    draft_caption = '待校对自动草稿 · ' if project.get('automatic_draft') else ''
    rows = []
    glyphs = Counter()
    total=vocal['statistics']['measure_count']
    first=1
    ranges=[]
    while first<=total:
        last=first if first==1 and vocal['timing'].get('initial_pickup_measure') else min(first+3,total)
        scene=vocal_row(vocal,first,last)
        scene.width=max(box['x']+box['width'] for box in scene.measure_boxes.values())+16
        # 源绘图每小节较宽；减少一行小节数，以A4纸上的歌词至少约8磅为准。
        while scene.width>1350 and last>first:
            last-=1
            scene=vocal_row(vocal,first,last)
            scene.width=max(box['x']+box['width'] for box in scene.measure_boxes.values())+16
        ranges.append((first,last,scene))
        first=last+1
    for first,last,scene in ranges:
        svg = scene.svg()
        xml = ET.fromstring(svg)
        xml.set('style','display:block;width:'+str(min(100.,scene.width/1350*100))+'%;height:auto')
        svg=ET.tostring(xml,encoding='unicode')
        for e in xml.iter():
            if e.tag.endswith('}text'):
                glyphs.update(c for c in ''.join(e.itertext()) if '\u4e00' <= c <= '\u9fff')
        rows.append('<section class="music-row"><div class="measure-label">第' + display_measure(vocal, first) + '—' + display_measure(vocal, last) + '小节</div>' + svg + '</section>')
    title = vocal['title']
    meter = vocal['timing']['meter']
    key = vocal['notation']['key']['jianpu_one'].replace('b', '♭').replace('#', '♯')
    metadata = '1=' + key + f'　{meter[0]}/{meter[1]}　♩={selected_quarter_tempo(vocal):g}'
    heading = '<h1>' + html.escape(title) + ' · 简谱</h1><p>' + html.escape(metadata) + '</p>'
    continued = '<p class="continued">' + html.escape(title) + ' · 简谱（续）</p>'
    css = """@page{size:A4 portrait;margin:0}*{box-sizing:border-box}body{margin:0;color:#111;font-family:"Microsoft YaHei",sans-serif}.sheet{width:210mm;height:297mm;padding:10mm;display:flex;flex-direction:column;break-after:page;overflow:hidden}.sheet:last-child{break-after:auto}header{flex:none}h1{font-size:23px;text-align:center;margin:0 0 8px}header p{font-size:13px;margin:0 0 10px}.continued{font-size:12px}main{flex:1;min-height:0;display:flex;flex-direction:column;gap:12px}.music-row{flex:none;break-inside:avoid}.measure-label{font-size:10px;color:#444;margin-bottom:2px}svg{display:block;width:100%;height:auto}footer{flex:none;text-align:center;height:16px;font:11px/16px Arial}@media screen{body{background:#eee}.sheet{background:white;margin:16px auto;box-shadow:0 1px 10px #0002}}"""
    page = output / '简谱.html'
    page.write_text('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>' + html.escape(title) + ' · 简谱</title><style>' + css + '</style><body><template id="first-header">' + heading + '</template><template id="continued-header">' + continued + '</template><div id="vocal-rows" style="width:190mm">' + ''.join(rows) + '</div></body></html>', encoding='utf-8')
    manifest = {'title': title, 'draft_caption': draft_caption, 'rows': len(rows), 'source': str(source), 'source_sha256': hashlib.sha256(original).hexdigest(), 'chinese_glyphs': dict(glyphs), 'html': str(page), 'music_reanalysed': False}
    (output / 'source.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    if source.read_bytes() != original:
        raise ValueError('排版期间源工程发生变化。')


if __name__ == '__main__':
    main()
