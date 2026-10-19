"""将现有默认吉他谱另存为参考弹唱谱结构的PDF及逐页JPG。"""
from __future__ import annotations
import argparse
from collections import Counter
from datetime import datetime,timezone,timedelta
import hashlib
import html
import itertools
import json
import os
import re
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile
from xml.etree import ElementTree as ET

HTML=Path(__file__).resolve().parents[1]
ROOT=HTML.parent
PAGE_W=195*96/25.4
PAGE_H=282*96/25.4


def safe_title(title):
    value=re.sub(r'[^\w\u4e00-\u9fff .（）()\-]+','_',title).strip(' .')[:96]
    return value or '曲谱'


def actions(root):
    return Counter(tuple(sorted((k,v) for k,v in e.attrib.items() if k.startswith('data-action-') or k=='data-note-ids')) for e in root.iter() if e.get('data-action-kind'))


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def save(path,data):path.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


def browser_render(input_html,pdf):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser=p.chromium.launch(executable_path='C:/Program Files/Google/Chrome/Application/chrome.exe',headless=True)
        page=browser.new_page(viewport={'width':1000,'height':1400})
        errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
        page.goto(input_html.resolve().as_uri(),wait_until='load');page.evaluate('document.fonts.ready');page.emulate_media(media='print')
        bounds=page.evaluate('''() => [...document.querySelectorAll('.sheet')].map((sheet,index)=>{
            const footer=sheet.querySelector('footer').getBoundingClientRect(),rows=[...sheet.querySelectorAll('.music-row')];
            return {page:index+1,rows:rows.length,last_music_bottom:rows.at(-1).getBoundingClientRect().bottom,footer_top:footer.top,
                horizontal_overflow:sheet.scrollWidth-sheet.clientWidth,charts:sheet.querySelectorAll('[data-inline-chart]').length};
        })''')
        save(pdf.parent/'evidence/browser_layout.json',{'passed':not errors and all(b['last_music_bottom']<=b['footer_top']+.5 and b['horizontal_overflow']<=1 for b in bounds),'page_errors':errors,'pages':bounds})
        assert not errors,errors
        assert all(b['last_music_bottom']<=b['footer_top']+.5 and b['horizontal_overflow']<=1 and 1<=b['rows']<=5 for b in bounds),bounds
        collisions=page.evaluate('''() => {
            const problems=[];let count=0;
            function box(e){let b=e.getBoundingClientRect();return {text:e.textContent,x:b.x,y:b.y,width:b.width,height:b.height};}
            function record(kind,unit,a,b){problems.push({kind,measure:unit.dataset.printMeasure,a,b});}
            function pairs(kind,unit,list){const boxes=list.map(box).sort((a,b)=>a.x-b.x);
                for(let i=1;i<boxes.length;i++){const a=boxes[i-1],b=boxes[i];
                    if(Math.min(a.y+a.height,b.y+b.height)-Math.max(a.y,b.y)>1 && a.x+a.width>b.x+.35)record(kind,unit,a,b);
                }
            }
            for(const unit of document.querySelectorAll('[data-print-measure]')){
                const matrix=unit.getScreenCTM(),left=new DOMPoint(0,0).matrixTransform(matrix).x;
                const right=new DOMPoint(+unit.dataset.barWidth,0).matrixTransform(matrix).x;
                const diagrams=[...unit.querySelectorAll(':scope > [data-inline-chart]')];count+=diagrams.length;
                for(const e of diagrams){const b=box(e);if(b.x<left-.8 || b.x+b.width>right+.8)record('diagram_clipped',unit,b,{left,right});}
                pairs('diagram_overlap',unit,diagrams);
                for(const alt of unit.querySelectorAll('[data-variant-source-measure]')){
                    const charts=[...alt.querySelectorAll('[data-inline-chart]')];count+=charts.length;pairs('variant_diagram_overlap',unit,charts);
                    for(const chart of charts){const b=box(chart);if(b.x<left-.8 || b.x+b.width>right+.8)record('variant_diagram_clipped',unit,b,{left,right});}
                    const staff=alt.querySelector('[data-shared-tab]');
                    if(charts.length && Math.max(...charts.map(e=>e.getBoundingClientRect().bottom))>staff.getBoundingClientRect().top-1)record('variant_diagram_tab_overlap',unit,charts.map(box),box(staff));
                }
                for(const tab of unit.querySelectorAll('[data-shared-tab]'))for(let string=1;string<=6;string++)pairs('tab_same_string_overlap',unit,[...tab.querySelectorAll('g[data-note-id][data-string="'+string+'"] > text')]);
                for(const layer of unit.querySelectorAll('svg[data-vocal-pass]')){
                    pairs('numeral_overlap',unit,[...layer.querySelectorAll('g.vocal-time-glyph > text')]);
                    pairs('lyric_overlap',unit,[...layer.querySelectorAll('text')].filter(t=>+t.getAttribute('y')>=160 && +t.getAttribute('y')<=185 && /[\u4e00-\u9fff]/.test(t.textContent)));
                }
                const tab=unit.querySelector('[data-shared-tab]'),voices=[...unit.querySelectorAll('svg[data-vocal-pass]')];
                if(tab && voices.length && tab.getBoundingClientRect().bottom>voices[0].getBoundingClientRect().top+.5)record('tab_vocal_overlap',unit,box(tab),box(voices[0]));
                if(diagrams.length && Math.max(...diagrams.map(e=>e.getBoundingClientRect().bottom))>tab.getBoundingClientRect().top-1)record('diagram_tab_overlap',unit,diagrams.map(box),box(tab));
            }
            return {passed:!problems.length,inline_diagrams_checked:count,issues:problems};
        }''')
        save(pdf.parent/'evidence/text_collision_check.json',collisions)
        assert collisions['passed'],collisions['issues'][:12]
        page.pdf(path=str(pdf),prefer_css_page_size=True,print_background=True,display_header_footer=False,tagged=True)
        browser.close()


def collect_semantics(root):
    notes=Counter();vocal=Counter()
    for e in root.iter():
        if e.get('data-note-id'):notes[tuple(e.get(k) for k in ('data-note-id','data-string','data-fret','data-start-tick','data-continuation'))]+=1
        if e.get('data-event-id'):vocal[tuple(e.get(k) for k in ('data-event-id','data-part','data-start-tick','data-grace'))]+=1
    return notes,vocal


def rhythm(root):
    return Counter(tuple(e.get(k) for k in ('data-rhythm-tick','data-rhythm-duration','data-flags')) for e in root.iter() if e.get('data-rhythm-tick') is not None)


def verify_charts(units,rendered_roots):
    from .layout import NS
    originals=[c for u in units for cs in [u['charts'],*[a['charts'] for a in u.get('variants',[])]] for c in cs]
    rendered=[c for root in rendered_roots for c in root.iter(NS+'g') if c.get('data-inline-chart')=='true']
    assert len(originals)==len(rendered)
    for source,output in zip(originals,rendered):
        assert output.get('data-chart-key')==source['key']
        assert output.get('data-start-tick')==source['node'].get('data-start-tick')
        center=float(source['node'].find(NS+'text').get('x'))
        expected=[]
        for e in source['node'].iter():
            if e.get('class') in ('string-line','fret-line','pressed-string','string-status','barre'):
                expected.append(e)
        actual=[e for e in output.iter() if e.get('class') in ('string-line','fret-line','pressed-string','string-status','barre')]
        assert len(expected)==len(actual)
        for a,b in zip(expected,actual):
            assert a.tag==b.tag and a.get('class')==b.get('class') and a.text==b.text
            for attr in ('x','x1','x2','cx'):
                if a.get(attr) is not None:assert abs(float(b.get(attr))-(float(a.get(attr))-center))<.002
            for attr in ('y','y1','y2','cy'):
                if a.get(attr) is not None:assert abs(float(b.get(attr))-(float(a.get(attr))-70)*.9)<.002
    return len(rendered)


def verify_strums(roots,project):
    from .notation import NS
    events={e['id']:e for e in project['arrangements']['guitar'].get('selected_pattern_actions',[]) if e['kind']=='strum'}
    count=0;notes=[]
    for root in roots:
        for tab in root.iter():
            if tab.get('data-shared-tab')!='true':continue
            ys=sorted(set(float(e.get('y1')) for e in tab if e.get('class')=='tab-string-line'))
            for g in tab.iter(NS+'g'):
                if g.get('data-action-kind')!='strum':continue
                event=events[g.get('data-action-id')];strings=event['strings']
                shaft=g.find(NS+"line[@class='strum-shaft']");head=g.find(NS+"polyline[@class='strum-head']")
                assert shaft is not None and head is not None and g.find(NS+'text') is None,'扫弦必须为实际跨弦箭头。'
                assert len(ys)==6 and g.get('data-direction')==event['direction'] and g.get('data-strings')==','.join(map(str,strings))
                tail,tip=(ys[max(strings)-1],ys[min(strings)-1]) if event['direction']=='down' else (ys[min(strings)-1],ys[max(strings)-1])
                assert abs(float(shaft.get('y1'))-tail)<.01 and abs(float(shaft.get('y2'))-tip)<.01,'扫弦方向或跨弦范围错误。'
                x=float(shaft.get('x1'));assert abs(x-float(shaft.get('x2')))<.01
                points=[tuple(map(float,p.split(','))) for p in head.get('points').split()]
                assert len(points)==3 and abs(points[1][0]-x)<.01 and abs(points[1][1]-tip)<.01
                assert points[0][0]<x<points[2][0] and all((p[1]-tip)*(1 if tip<tail else -1)>0 for p in (points[0],points[2]))
                rhythms=[e for e in tab if e.get('data-rhythm-tick')==str(event['start_tick'])]
                assert rhythms and any(abs(float(e.get('x1'))-x)<.01 for e in rhythms),'扫弦箭头偏离实际拍位。'
                count+=1;notes.extend(event['note_ids'])
    return {'passed':True,'arrows':count,'swept_note_references':len(notes),'direction_and_strings_read_from_actual_geometry':True}

def choose_pages(heights):
    best=None
    for pages in (3,4):
        for counts in itertools.product((4,5),repeat=pages):
            if sum(counts)!=len(heights):continue
            begin=0;used=[]
            for number,count in enumerate(counts):
                used.append(sum(heights[begin:begin+count])+(72 if number==0 else 22)+16);begin+=count
            if max(used)>PAGE_H-2:continue
            candidate=(max(used)-min(used),counts)
            if best is None or candidate<best:best=candidate
        if best:return best[1]
    n=len(heights)
    for pages in range(1,n+1):
        dp={(0,0):(0.,[])}
        for page in range(1,pages+1):
            budget=PAGE_H-(72 if page==1 else 22)-18
            for end in range(1,n+1):
                candidates=[]
                for count in range(1,min(5,end)+1):
                    previous=dp.get((page-1,end-count))
                    if previous is None:continue
                    used=sum(heights[end-count:end])
                    if used>budget:continue
                    cost=previous[0]+((budget-used)/budget)**2+(1.2 if count==1 and n>1 else 0)
                    candidates.append((cost,previous[1]+[count]))
                if candidates:dp[page,end]=min(candidates,key=lambda c:c[0])
        if (pages,n) in dp:return tuple(dp[pages,n][1])
    raise ValueError('单行谱面过高，需要增加断行，不能裁剪音符或变奏。')



def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path);parser.add_argument('--output',type=Path)
    parser.add_argument('--reference-dir',type=Path,help='只读排版参考图片目录；不参与音乐或断行决策')
    parser.add_argument('--print-html',type=Path);parser.add_argument('--pdf',type=Path)
    args=parser.parse_args()
    if args.print_html:browser_render(args.print_html,args.pdf);return
    from PIL import Image,ImageStat
    from pypdf import PdfReader
    from .layout import original_parts,prepare_reference,reference_partition,make_reference_row,NS,LYRIC_SIZE,TAB_SIZE,CHART_SCALE
    source=args.source.resolve();output=args.output.resolve()
    assert source.is_relative_to(ROOT) and (output.is_relative_to(HTML/'output') or output.is_relative_to(HTML/'runtime'))
    assert not output.exists(),'请另用新目录，不能覆盖之前的样张。'
    output.mkdir(parents=True);evidence=output/'evidence';evidence.mkdir()
    references=sorted(p for p in args.reference_dir.resolve().iterdir() if p.suffix.lower() in ('.jpg','.jpeg','.png')) if args.reference_dir else []
    reference_hashes={str(p):sha(p) for p in references}
    if args.reference_dir:assert references,'指定参考目录中没有图片。'
    original_source=source
    project=json.loads((source/'project.json').read_text(encoding='utf-8'))
    from .input import notation_source
    source,notation_upgraded=notation_source(source,output,project)
    voice=project['accepted_vocal_project'];guitar=project['arrangements']['guitar']
    units,charts,plan,source_hashes,markers=original_parts(source)
    for path in (source/'project.json',source/'guitar/repeat_plan.json',source/'guitar/score.html'):source_hashes[str(path)]=sha(path)
    for u in units:prepare_reference(u,charts)
    # 以实际字形宽度选择行数；不以歌名、固定小节号或固定歌词规定断行。
    rows=None
    for count in range(max(1,(len(units)+4)//5),len(units)+1):
        partition=reference_partition(units,count)
        if not partition:continue
        scale=min(.65,PAGE_W/(partition[0]+36))
        if scale*LYRIC_SIZE*.75<8.7:continue
        candidate=[make_reference_row(units[a:b],charts,PAGE_W/scale) for a,b in partition[2]]
        try:page_counts=choose_pages([h*scale for _,h,_ in candidate])
        except ValueError:continue
        rows=candidate;spans=partition[2];break
    assert rows,'当前小节密度无法按可读字号排版，已停止导出，原谱保持。'
    title=voice['title'].partition(' - ')[2] or voice['title'];artist=voice['title'].partition(' - ')[0];file_title=safe_title(title)
    capo=guitar['configuration'].get('capo_fret',0)
    key=voice['notation']['key']['jianpu_one'].replace('b','♭').replace('#','♯')
    shape_pc=(voice['notation']['key']['jianpu_one_pc']-capo)%12
    shape=('C','C♯','D','E♭','E','F','F♯','G','A♭','A','B♭','B')[shape_pc]
    tempo=voice['timing'].get('steady_tempo_bpm')
    meta=f'原调 1={key}　4/4'+(f'　♩≈{tempo:.0f}' if isinstance(tempo,(int,float)) else '')+f'　选用{shape}调指型　变调夹：{capo}品'
    pages=[];layout_rows=[];roots=[];at=0;page_diagrams=[]
    notes=Counter();vocals=Counter();rhythms=Counter()
    for number,count in enumerate(page_counts,1):
        music=[];diagram_count=0
        for index in range(at,at+count):
            root,height,details=rows[index];a,b=spans[index];roots.append(root)
            root.set('width',f'{PAGE_W:g}');root.set('height',f'{height*scale:g}');root.set('style',f'display:block;width:{PAGE_W:g}px;height:{height*scale:g}px')
            content=ET.tostring(root,encoding='unicode');(evidence/f'row_{index+1:02}.svg').write_text(content,encoding='utf-8')
            music.append('<div class="music-row">'+content+'</div>')
            n,v=collect_semantics(root);notes.update(n);vocals.update(v);rhythms.update(rhythm(root))
            diagram_count+=sum(len(u['charts']) for u in units[a:b])
            layout_rows.append({'row':index+1,'page':number,'bar_count':b-a,'source_measures':[u['number'] for u in units[a:b]],'display_measures':[u['display_number'] for u in units[a:b]],'height_pixels':height*scale,'details':details})
        if number==1:heading='<header class="first"><h1>'+html.escape(title)+'</h1><div class="artist">'+html.escape(artist)+'</div><div class="meta">'+html.escape(meta)+'</div></header>'
        else:heading='<header class="continued"><span>'+html.escape(title)+'</span><span>吉他伴奏谱</span></header>'
        pages.append('<section class="sheet">'+heading+'<div class="music">'+''.join(music)+'</div><footer>'+str(number)+'</footer></section>')
        page_diagrams.append(diagram_count);at+=count
    expected_notes=Counter();expected_vocals=Counter();expected_rhythm=Counter();expected_cjk=Counter()
    for u in units:
        n,_=collect_semantics(u['tab']);expected_notes.update(n);expected_rhythm.update(rhythm(u['tab']))
        for alt in u.get('variants',[]):
            n,_=collect_semantics(alt['tab']);expected_notes.update(n);expected_rhythm.update(rhythm(alt['tab']))
        for layer in u['voices']:
            _,v=collect_semantics(layer);expected_vocals.update(v)
            for e in layer.iter(NS+'text'):expected_cjk.update(c for c in (e.text or '') if '\u4e00'<=c<='\u9fff')
    assert notes==expected_notes and vocals==expected_vocals and rhythms==expected_rhythm
    expected_actions=Counter();actual_actions=Counter()
    for u in units:
        expected_actions.update(actions(u['tab']))
        for a in u.get('variants',[]):expected_actions.update(actions(a['tab']))
    for r in roots:actual_actions.update(actions(r))
    assert actual_actions==expected_actions,'扫弦或合拨动作身份发生改变。'
    strum_check=verify_strums(roots,project)
    save(evidence/'strum_geometry_check.json',strum_check)
    actual_markers=Counter((e.get('data-print-marker'),int(e.get('data-first')),int(e.get('data-last'))) for r in roots for e in r.iter() if e.get('data-print-marker'))
    assert actual_markers==Counter((m['kind'],m['first'],m['last']) for m in markers),'最终反复符号缺失或重复。'
    diagram_count=verify_charts(units,roots)
    save(evidence/'notation_binding_check.json',{'passed':True,'tab_marks':sum(notes.values()),'vocal_glyph_parts':sum(vocals.values()),'rhythm_marks':sum(rhythms.values()),'action_marks':sum(actual_actions.values()),'layout_id':'guitar-accompaniment-v1','layout_approved':True,'inline_diagrams':diagram_count,'strum_arrows_checked':strum_check['arrows'],'explicit_variant_bars':sum(len(u.get('variants',[])) for u in units),'diagram_geometry_and_finger_positions_preserved':True,'navigation_markers_preserved':True,'variant_count':sum(len(u.get('variants',[])) for u in units)})
    styles='''@page{size:A4 portrait;margin:0}*{box-sizing:border-box}body{margin:0;font-family:"Microsoft YaHei",sans-serif;color:#111;background:#eee}.sheet{width:210mm;height:297mm;padding:7.5mm;background:#fff;display:flex;flex-direction:column;break-after:page;overflow:hidden}.sheet:last-child{break-after:auto}header{flex:none}header.first{height:72px}h1{font-family:SimSun,"Microsoft YaHei",serif;font-size:27px;line-height:30px;text-align:center;letter-spacing:5px;font-weight:600;margin:0}.artist{text-align:center;font-family:SimSun,serif;font-size:15px;line-height:21px}.meta{font-size:11.5px;line-height:21px;white-space:nowrap}.continued{height:22px;font-size:10px;display:flex;justify-content:space-between;align-items:start;color:#333}.music{flex:1;min-height:0;display:flex;flex-direction:column;justify-content:space-between}.music-row{flex:none;margin:0;padding:0;break-inside:avoid}footer{flex:0 0 16px;height:16px;text-align:center;line-height:16px;font-family:Arial;font-size:11px}@media screen{.sheet{margin:16px auto;box-shadow:0 2px 10px #0002}}@media print{body{background:white}.sheet{margin:0;box-shadow:none}}'''
    print_html=output/'吉他伴奏谱_参考弹唱版式.html'
    print_html.write_text('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>'+html.escape(title)+' · 吉他伴奏谱</title><style>'+styles+'</style><body>'+''.join(pages)+'</body></html>',encoding='utf-8')
    pdf=output/f'{file_title}_吉他伴奏谱_参考版式.pdf'
    env={**os.environ,'PYTHONIOENCODING':'utf-8','PYTHONDONTWRITEBYTECODE':'1'}
    result=subprocess.run([str(HTML/'.venv/Scripts/python.exe'),'-m','printing.engine','--print-html',str(print_html),'--pdf',str(pdf)],capture_output=True,text=True,encoding='utf-8',errors='replace',env=env,cwd=str(HTML))
    (evidence/'chrome_print.txt').write_text(result.stdout+result.stderr,encoding='utf-8');assert result.returncode==0,'浏览器检查未通过，查看evidence/chrome_print.txt'
    reader=PdfReader(str(pdf));assert len(reader.pages)==len(page_counts)
    text='\n'.join(p.extract_text() for p in reader.pages);actual_cjk=Counter(c for c in text if '\u4e00'<=c<='\u9fff')
    missing={c:n-actual_cjk[c] for c,n in expected_cjk.items() if actual_cjk[c]<n};assert not missing,missing
    for page in reader.pages:
        assert abs(float(page.mediabox.width)-595.28)<2 and abs(float(page.mediabox.height)-841.89)<2
        for ref in page['/Resources'].get('/Font',{}).get_object().values():
            f=ref.get_object();desc=f.get('/DescendantFonts',[])
            for entry in ([v.get_object() for v in desc] or [f]):
                if entry.get('/Subtype')=='/Type3':continue
                fd=entry.get('/FontDescriptor');assert fd and any(k in fd.get_object() for k in ('/FontFile','/FontFile2','/FontFile3'))
    images=output/'JPG';images.mkdir()
    import pypdfium2 as pdfium
    document=pdfium.PdfDocument(str(pdf));image_paths=[]
    try:
        for index in range(len(document)):
            page=document[index];bitmap=page.render(scale=300/72)
            target=images/f'{file_title}_吉他伴奏谱_{index+1:02}.jpg'
            bitmap.to_pil().convert('RGB').save(target,format='JPEG',quality=95,optimize=True,dpi=(300,300))
            bitmap.close();page.close();image_paths.append(target)
    finally:document.close()
    (evidence/'pdf_to_jpg.txt').write_text('PDFium直接逐页渲染最终PDF，300 DPI，JPEG质量95。\n',encoding='utf-8')
    assert len(image_paths)==len(page_counts)
    for p in image_paths:
        with Image.open(p) as im:assert im.width>2400 and im.height>3400 and ImageStat.Stat(im.convert('L')).stddev[0]>5
    archive=output/f'{file_title}_吉他伴奏谱_参考版式_JPG.zip'
    with zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_STORED) as z:
        for p in image_paths:z.write(p,arcname=p.name)
    with zipfile.ZipFile(archive) as z:
        assert z.testzip() is None
        for p in image_paths:assert hashlib.sha256(z.read(p.name)).hexdigest()==sha(p)
    for path,value in {**source_hashes,**reference_hashes}.items():assert sha(Path(path))==value,path
    verification={'checked_at':datetime.now(timezone(timedelta(hours=8))).isoformat(),'passed':True,'source_project':str(original_source/'project.json'),'legacy_notation_upgraded':notation_upgraded,'reference_images':reference_hashes,'pages':len(page_counts),'rows':len(rows),'rows_per_page':list(page_counts),'bars_per_row':[r['bar_count'] for r in layout_rows],
        'layout':'行内指型图、上方六线谱、下方演唱简谱及歌词','lyric_font_points':scale*LYRIC_SIZE*.75,'tab_font_points':scale*TAB_SIZE*.75,'chord_grid_width_mm':55*CHART_SCALE*scale*25.4/96,'paper':'A4纵向','margin_mm':7.5,'dpi':300,
        'printed_measures':len(units),'source_full_measures':len(plan['actual_measure_timeline']),'tab_marks':sum(notes.values()),'vocal_glyph_parts':sum(vocals.values()),'rhythm_marks':sum(rhythms.values()),'source_chinese_glyphs':sum(expected_cjk.values()),'source_lyrics_no_missing':not missing,
        'layout_id':'guitar-accompaniment-v1','layout_approved':True,'inline_diagrams':diagram_count,'explicit_variant_bars':sum(len(u.get('variants',[])) for u in units),'page_diagram_counts':page_diagrams,'unique_grips':len(charts),'meter_changes':[{'source_measure':u['number'],'display_measure':u['display_number'],'meter':u['meter']} for u in units if u['show_meter']],'repeat_markers':markers,'source_hashes':source_hashes,
        'pdf_fonts_embedded':True,'jpg_zip_matches':True,'music_reanalysed':False,'music_rearranged':False,'physical_print_tested':False,'specific_output_approved':False,'needs_visual_review':True,'layout_rows':layout_rows,'output_pdf':pdf.name,'jpg_zip':archive.name}
    save(output/'verification.json',verification)
    index='<html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>'+html.escape(title)+' · 参考弹唱版式</title><style>body{font:16px/1.7 Microsoft YaHei,sans-serif;max-width:1000px;margin:24px auto;padding:0 16px;background:#f0f1f2;color:#203345}a{color:#166b62}img{display:block;width:100%;margin:20px 0;box-shadow:0 2px 8px #0002}</style><h1>'+html.escape(title)+' · 吉他伴奏谱</h1><p>默认吉他弹唱排版：行内指型图在上，六线谱居中，演唱简谱和歌词在下。'+str(len(page_counts))+'页，原音乐与默认右手不变。</p><p><a href="'+pdf.name+'">打开PDF</a>　<a href="'+archive.name+'">下载逐页JPG</a></p>'+''.join('<a href="JPG/'+p.name+'"><img src="JPG/'+p.name+'" alt="第'+str(i)+'页"></a>' for i,p in enumerate(image_paths,1))
    (output/'index.html').write_text(index,encoding='utf-8')
    print(json.dumps({k:verification[k] for k in ('pages','rows','rows_per_page','bars_per_row','lyric_font_points','chord_grid_width_mm','inline_diagrams')},ensure_ascii=False))

if __name__=='__main__':main()