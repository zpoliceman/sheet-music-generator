"""旧版曲谱只读适配：沿用原反复方案，仅在新目录渲染排版用矢量图。"""
import argparse,json,sys,shutil,hashlib
from pathlib import Path
import xml.etree.ElementTree as ET
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'))

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--source',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    source=a.source.resolve();output=a.output.resolve()
    assert source.is_relative_to(ROOT) and output.is_relative_to(ROOT/'HTML/runtime') and not output.exists()
    project_path=source/'project.json';digest=hashlib.sha256(project_path.read_bytes()).hexdigest()
    project=json.loads(project_path.read_text(encoding='utf-8'))
    from guitar_variable_repeat import measure_timeline
    from export_timing_revision import render_row,svg_node,NS
    from guitar_repeat_marks import marker_specs,draw_annotations
    from guitar_repeat_score import draw_marker
    from guitar_repeat_variants import append_variant_tabs
    plan=json.loads((source/'guitar/repeat_plan.json').read_text(encoding='utf-8'))
    timeline=measure_timeline(project);plan['actual_measure_timeline']=timeline
    rows=output/'guitar/rows';rows.mkdir(parents=True)
    shutil.copyfile(project_path,output/'project.json')
    (output/'guitar/repeat_plan.json').write_text(json.dumps(plan,ensure_ascii=False),encoding='utf-8')
    (output/'guitar/score.html').write_text('<!doctype html><title>只读排版数据</title>',encoding='utf-8')
    specs=marker_specs(plan)
    for index,block in enumerate(plan['blocks'],1):
        first,last=block['canonical_first'],block['canonical_last']
        layers=[timeline[o['first']-1:o['last']] for o in block['occurrences']]
        raw=ET.fromstring(render_row(project,timeline[first-1:last],True,vocal_measures=layers))
        from guitar_strum_notation import read_visible_strums
        _,errors=read_visible_strums(raw,project['arrangements']['guitar'])
        if errors:raise ValueError('只读重画后的实际扫弦箭头无效：'+str(errors[:3]))
        width=float(raw.get('width'));height=float(raw.get('height'))+(70 if specs.get(block['id']) else 0)
        outer=ET.Element(NS+'svg',{'width':str(width),'height':str(height),'viewBox':f'0 0 {width:g} {height:g}'})
        wrapper=svg_node(outer,'g',**{'class':'repeat-block','data-block-id':block['id'],'height':height})
        body=svg_node(wrapper,'g',transform='translate(0,40)' if specs.get(block['id']) else 'translate(0,0)')
        for child in raw:
            if child.tag!=NS+'rect':body.append(child)
        draw_annotations(wrapper,specs.get(block['id'],[]),draw_marker)
        append_variant_tabs(outer,wrapper,project,plan,block,render_row,timeline)
        (rows/f'repeat_{index:03}.svg').write_text(ET.tostring(outer,encoding='unicode'),encoding='utf-8')
    assert hashlib.sha256(project_path.read_bytes()).hexdigest()==digest
    print(json.dumps({'music_unchanged':True,'original_repeat_plan_preserved':True,'source_project_sha256':digest,'rows':len(plan['blocks'])}))
if __name__=='__main__':main()
