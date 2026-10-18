"""简谱小节对齐与人工复核汇总：保留既有音乐数据，只重排谱面并更新试听清单。"""
from __future__ import annotations

# 简谱小节对齐与人工复核汇总：新增独立重排入口，不重新执行音高/挂词推理。
import argparse
import html
import json
from pathlib import Path
import shutil
import subprocess
import sys
import score_export as score


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--score-dir',type=Path,required=True)
    parser.add_argument('--output-dir',type=Path,required=True)
    parser.add_argument('--findings',type=Path)
    parser.add_argument('--preview-range',action='append',default=[])
    args=parser.parse_args()
    source=args.score_dir.resolve();output=args.output_dir.resolve()
    if source==output:
        raise ValueError('重排应保存为独立目录，保留此前谱面')
    output.mkdir(parents=True,exist_ok=True)
    project=score.read_json(source/'project.json')
    preservation={}
    # 简谱小节对齐与人工复核汇总：新增按字节保留MusicXML/MIDI/项目/验证数据，排版不改音乐内容。
    for name in ['project.json','vocal_draft.musicxml','vocal_draft.mid','validation.json']:
        shutil.copy2(source/name,output/name)
        preservation[name]={'before':score.sha256(source/name),'after':score.sha256(output/name)}
        if preservation[name]['before']!=preservation[name]['after']:
            raise ValueError('音乐文件复制后哈希不一致')
    scene=score.render_jianpu(project)
    svg=scene.svg();(output/'jianpu.svg').write_text(svg,encoding='utf-8')
    # 第二首跨歌曲验证：修改，原首音选择注释保留；预览从首个真实挂词段开始。
    # first=min(e['measure'] for e in project['events'] if e['pitch_midi'] is not None)
    first=score.first_vocal_measure(project)
    dense=max(scene.measure_boxes,key=lambda m:len(scene.measure_boxes[m]['events']))
    ranges=[('first_vocal',max(1,first-1),min(project['statistics']['measure_count'],first+8)),
            ('dense',dense,min(project['statistics']['measure_count'],dense+7))]
    for value in args.preview_range:
        name,begin,end=value.split(':')
        if not name.replace('_','').isalnum():
            raise ValueError('预览名称必须是字母、数字或下划线')
        ranges.append((name,int(begin),int(end)))
    for name,begin,end in ranges:
        preview=score.render_jianpu(project,begin,end,True)
        preview.png(output/f'preview_{name}.png')
        (output/f'preview_{name}.svg').write_text(preview.svg(),encoding='utf-8')
    # 简谱小节对齐与人工复核汇总：新增可放大谱面的本地HTML，屏幕较窄时可横向滚动，保持音符可读。
    document='''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>TITLE · 对齐版简谱</title>
<style>body{background:#eef2f6;margin:20px;font-family:"Microsoft YaHei",sans-serif;color:#14243b}main{max-width:1600px;margin:auto;background:white;padding:24px}p{line-height:1.8}a{color:#205a98}.score-scroll{overflow-x:auto}#score-sheet{width:100%;min-width:1200px}svg{width:100%;height:auto}.controls{padding:10px;background:#f4f7fa}input{vertical-align:middle}@media print{body,main{margin:0;padding:0;background:white}.controls,.navigation{display:none}#score-sheet{width:100%!important;min-width:0}.score-scroll{overflow:visible}@page{size:landscape}}</style></head><body><main>
<p class="navigation">自动草稿，音乐内容沿用上一版，待人工复核。<a href="manual_review.html">人工复核清单与试听</a>　<a href="review.html">完整证据</a>　<a href="vocal_draft.musicxml">可编辑乐谱</a>　<a href="vocal_draft.mid">试听MIDI</a></p>
<p class="controls">每行4小节，小节边界对齐。谱面大小 <input aria-label="谱面大小" id="zoom" type="range" min="100" max="200" step="10" value="100"> <span id="zoom-label">100%</span></p>
<div class="score-scroll"><div id="score-sheet">SVG</div></div></main>
<script>// 简谱小节对齐与人工复核汇总：新增仅在本页调整谱面大小，不更改音乐数据。
document.getElementById('zoom').addEventListener('input',function(){document.getElementById('score-sheet').style.width=this.value+'%';document.getElementById('zoom-label').textContent=this.value+'%';});
</script></body></html>'''
    # 简谱按拍分组优化：新增阅读页说明，所有新导出自动使用拍内连线与拍间留白。
    document=document.replace('每行4小节，小节边界对齐。','每行4小节，小节边界对齐；同拍短音共用下划线，拍间留白。')
    document=document.replace(' · 对齐版简谱',' · 按拍分组简谱')
    document=document.replace('TITLE',html.escape(project['title']),1).replace('SVG',svg,1)
    (output/'jianpu.html').write_text(document,encoding='utf-8')
    # 十一首可编辑五线谱：新增重排后同步五线谱，不复制旧排版或修改来源MusicXML。
    from staff_export import export_staff_score
    staff_result = export_staff_score(output)
    # 简谱按拍分组优化：修改格式报告标识，原代码注释保留。
    # layout={'task':'简谱小节对齐与人工复核汇总','source_score_dir':str(source),'output_dir':str(output),
    #         'layout':scene.layout,'canvas_width':scene.width,'canvas_height':scene.height,
    #         'measure_boxes':scene.measure_boxes,'musical_files_sha256':preservation,'model_rerun':False}
    # 简谱按拍分组优化：新增任务标识及预览范围记录，音乐指纹与模型不重跑信息保留。
    layout={'task':'简谱按拍分组优化','source_score_dir':str(source),'output_dir':str(output),
            'layout':scene.layout,'canvas_width':scene.width,'canvas_height':scene.height,
            'measure_boxes':scene.measure_boxes,'musical_files_sha256':preservation,'model_rerun':False,
            'preview_ranges':[{'name':name,'first_measure':begin,'last_measure':end} for name,begin,end in ranges]}
    score.save_json(output/'layout.json',layout)
    # 简谱小节对齐与人工复核汇总：新增复用默认同源复核入口，独立评估说明只进入展示程序。
    command=[sys.executable,'-X','utf8','-B',str(Path(__file__).with_name('review_bundle.py')),
             '--analysis',project['inputs']['notes_path'],'--lyrics',project['inputs']['lyrics_path'],
             '--score-dir',str(output),'--output',str(output/'review.html')]
    if args.findings:
        command+=['--findings',str(args.findings.resolve())]
    result=subprocess.run(command,capture_output=True,text=True,encoding='utf-8')
    if result.returncode:
        raise RuntimeError(result.stderr or result.stdout)
    print(json.dumps({'output_dir':str(output),'measure_count':len(scene.measure_boxes),
                      'layout':scene.layout,'musical_data_unchanged':True,'review':json.loads(result.stdout)},ensure_ascii=False))
    return 0


if __name__=='__main__':
    raise SystemExit(main())
