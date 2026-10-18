"""和弦弹唱与伴奏编配：已交付文件、真实渲染与HTML本地链接独立核验。"""
# 和弦弹唱与伴奏编配：新增只读核验主体，QA图和报告限定到reports/accompaniment。
from __future__ import annotations
import argparse
import base64
from collections import defaultdict
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlparse
import xml.etree.ElementTree as ET
import mido
import resvg_py
import verovio
from score_export import read_json,save_json,sha256
from accompaniment_analysis import SongClock
from accompaniment_arrange import validate_playability
from accompaniment_export import parse_musicxml_notes,validate_midi,validate_tab
# 常用指型与器乐独奏：新增独立复算完整指型兼容、器乐展示和换把时序。
from guitar_grip_policy import validate_grip_policy
# 常用右手伴奏型：新增正式交付的模板格位、和弦音及来源独立核验。
from guitar_right_hand_patterns import validate_patterns
# 节奏符号说明与声部对齐：新增正式交付后读取实际SVG与工程时间的对齐核验。
from guitar_time_alignment import validate_time_alignment
# 规整分解节奏与延音显示：新增交付后直接按工程起音和拍格核查普通分解。
# 结构稳定伴奏与人声合播：修改，原代码注释保留。
# from guitar_regular_rhythm import validate_regular_rhythm
from guitar_regular_rhythm import validate_regular_rhythm
# 结构稳定伴奏与人声合播：新增直接读回新交付内容。
from guitar_capo import validate_capo
from guitar_structure_validation import validate_structure
from accompaniment_vocal_playback import validate_singing_preview
from math import floor
# 相似乐句和弦框架复用：新增实际编配视图与独立保护核验，历史工程无计划时行为不变。
from phrase_harmony_plan import arrangement_view
from phrase_harmony_arrange import validate_phrase_harmony


# 强拍相位与伴奏同步纠错：新增按渲染器原生PPQ精确比较；拒绝任意容差掩盖错拍或错音。
def renderer_attacks_match(observed, expected, native_ppq):
    rounded=sorted((floor(a*native_ppq/480)*480/native_ppq,p) for a,b,p in expected)
    # 强拍相位与伴奏同步纠错：修改，原按释音排序的序列保留；攻击只比较起音/音高多重集。
    # return [(a,p) for a,b,p in observed]==rounded
    return sorted((a,p) for a,b,p in observed)==rounded


# 和弦弹唱与伴奏编配：新增HTML实际href/src读取，不把模板文字当作文件存在证据。
class Links(HTMLParser):
    def __init__(self):super().__init__();self.urls=[]
    def handle_starttag(self,tag,attrs):
        for name,value in attrs:
            if name in ('href','src') and value:self.urls.append(value)


# 和弦弹唱与伴奏编配：新增Verovio实际发声导出，避免只检查谱面ID而遗漏连音意义。
# 器乐合理分句与十二品硬限制：新增按实际获准参考视图核查显示，人声原快照与真实休止均保护。
def delivery_time_alignment(rows, arrangement, vocal, shared):
    from guitar_instrumental_expression import reference_vocal
    return validate_time_alignment(rows, arrangement, reference_vocal(vocal, arrangement), shared)


def renderer_sound_check(xml_path,arrangement):
    import io
    toolkit=verovio.toolkit()
    if not toolkit.loadData(Path(xml_path).read_text(encoding='utf-8')):raise ValueError('实际渲染导入失败。')
    mei=ET.fromstring(toolkit.getMEI());root=ET.parse(xml_path).getroot()
    expected_ties=sum(t.get('type')=='start' for t in root.findall('part/measure/note/tie'))
    actual_ties=len(mei.findall('.//{http://www.music-encoding.org/ns/mei}tie'))
    midi=mido.MidiFile(file=io.BytesIO(base64.b64decode(toolkit.renderToMIDI())))
    observed=[];errors=[]
    for track in midi.tracks:
        active={};tick=0
        for msg in track:
            tick+=msg.time
            if msg.type=='note_on' and msg.velocity:
                if (msg.channel,msg.note) in active:errors.append('renderer_overlapping_same_pitch_channel')
                active[(msg.channel,msg.note)]=tick
            elif msg.type=='note_off' or msg.type=='note_on' and not msg.velocity:
                key=(msg.channel,msg.note)
                if key in active:
                    observed.append((active.pop(key)*480/midi.ticks_per_beat,tick*480/midi.ticks_per_beat,msg.note))
        if active:errors.append('renderer_unreleased_note')
    expected=sorted((n['start_tick'],n['end_tick'],n['pitch_midi']) for n in arrangement['notes'])
    observed.sort()
    attack_equal=[(a,p) for a,b,p in observed]==[(a,p) for a,b,p in expected]
    # 和弦弹唱与伴奏编配：新增渲染器常规MIDI留出门控间隔的容差；攻击及音高要求精确。
    # 强拍相位与伴奏同步纠错：修改，原PPQ480与PPQ120直接比较保留；64分需半个原生tick，渲染器向下圆整。
    # release_diffs=[a[1]-b[1] for a,b in zip(observed,expected)] if attack_equal else []
    # if not attack_equal:errors.append('renderer_attack_or_pitch_mismatch')
    native_equal=renderer_attacks_match(observed,expected,midi.ticks_per_beat)
    release_diffs=[a[1]-b[1] for a,b in zip(observed,expected)] if native_equal else []
    if not native_equal:errors.append('renderer_attack_or_pitch_mismatch')
    if expected_ties!=actual_ties:errors.append('renderer_tie_count_mismatch')
    return {'valid':not errors,'errors':errors,'expected_notes':len(expected),'renderer_notes':len(observed),
            # 强拍相位与伴奏同步纠错：修改，原精确指标保留；不把原生圆整冒称PPQ480精确。
            # 'exact_attack_ticks_and_pitches':attack_equal,'expected_ties':expected_ties,'renderer_ties':actual_ties,
            'exact_attack_ticks_and_pitches':attack_equal,'native_resolution_attack_ticks_and_pitches':native_equal,
            'native_midi_ppq':midi.ticks_per_beat,
            'maximum_attack_rounding_project_ticks':max((abs(a[0]-b[0]) for a,b in zip(observed,expected)),default=0) if native_equal else None,
            'expected_ties':expected_ties,'renderer_ties':actual_ties,
            'release_tick_difference_range':[min(release_diffs),max(release_diffs)] if release_diffs else None,
            'release_timing_note':'渲染器试听门控与记谱时值分开；正式试听MIDI按工程精确时值导出。'}


# 和弦弹唱与伴奏编配：新增整曲可重复核验和代表性图像，原曲/原谱全程只读。
def verify(output,report_dir):
    output,report_dir=Path(output).resolve(),Path(report_dir).resolve()
    report_dir.mkdir(parents=True,exist_ok=True)
    project=read_json(output/'project.json');vocal=project['accepted_vocal_project'];arrangements=project['arrangements']
    result={'instruments':{},'link_errors':[],'manifest_errors':[],'visual_samples':[]}
    # 相似乐句和弦框架复用：新增先核原工程再派生只读视图，不回写交付文件或丢失原分析。
    if project['shared_analysis'].get('phrase_harmony_plan',{}).get('phrases'):
        result['phrase_harmony']=validate_phrase_harmony(project['shared_analysis'],vocal,arrangements)
    project={**project,'shared_analysis':arrangement_view(project['shared_analysis'],vocal)}
    for instrument,arrangement in arrangements.items():
        parsed,xml=parse_musicxml_notes(ET.parse(output/instrument/'score.musicxml').getroot())
        expected={n['id']:(n['start_tick'],n['end_tick'],n['pitch_midi']) for n in arrangement['notes']}
        if {k:(n['start_tick'],n['end_tick'],n['pitch_midi']) for k,n in parsed.items()}!=expected:
            xml['valid']=False;xml['errors'].append('project_semantics_mismatch')
        item={'xml':xml,'midi':validate_midi(output/instrument/'accompaniment.mid',arrangement,vocal),
              'playability':validate_playability(arrangement,SongClock(vocal))}
        if instrument=='piano':item['renderer_sound']=renderer_sound_check(output/instrument/'score.musicxml',arrangement)
        else:
            rows=[{'guitar':p.read_text(encoding='utf-8')} for p in sorted((output/instrument/'rows').glob('*.svg'))]
            item['tab']=validate_tab(rows,arrangement)
            # 常用指型与器乐独奏：新增策略语义验证，历史版本没有此配置时沿用原核验。
            grip=validate_grip_policy(project['shared_analysis'],arrangement,vocal)
            if grip:item['grip_policy']=grip
            # 常用右手伴奏型：新增不只核对MIDI与工程相等，另查真实模板语义。
            patterns=validate_patterns(project['shared_analysis'],arrangement)
            if patterns:item['right_hand_patterns']=patterns
            # 节奏符号说明与声部对齐：新增按真实text中心/祖先位移核查，历史无配置版本沿用既有检查。
            # 器乐合理分句与十二品硬限制：修改，旧原快照显示核查保留；器乐休止参考图与实际导出采用同一授权视图。
            # alignment=validate_time_alignment(rows,arrangement,vocal,project['shared_analysis'])
            alignment=delivery_time_alignment(rows,arrangement,vocal,project['shared_analysis'])
            if alignment:item['time_alignment']=alignment
            # 规整分解节奏与延音显示：新增规整模板真实起音检查，前奏/填句保持独立范围。
            regular=validate_regular_rhythm(project['shared_analysis'],arrangement)
            if regular:item['regular_rhythm']=regular
        # 结构稳定伴奏与人声合播：修改，原代码注释保留。
        # result['instruments'][instrument]=item
        if (output/instrument/'singing_preview.json').exists():
            item['singing_preview']=validate_singing_preview(output/instrument,project['shared_analysis'],vocal)
        if instrument=='guitar' and arrangement['configuration'].get('capo_segments'):
            item['capo']=validate_capo(arrangement,vocal,ET.parse(output/instrument/'score.musicxml').getroot())
            structure=validate_structure(project['shared_analysis'],vocal,arrangement,rows)
            if structure:item['structure']=structure
        result['instruments'][instrument]=item
    for path in output.rglob('*.html'):
        parser=Links();parser.feed(path.read_text(encoding='utf-8'))
        for url in parser.urls:
            parts=urlparse(url)
            if parts.scheme or not parts.path:continue
            target=(path.parent/unquote(parts.path)).resolve()
            if not target.exists():result['link_errors'].append({'html':str(path),'url':url})
    manifest=read_json(output/'manifest.json')
    for row in manifest['files']:
        path=output/row['path']
        if not path.exists() or sha256(path)!=row['sha256']:result['manifest_errors'].append(row['path'])
    # 和弦指型与X六线谱：修改，原固定四小节路径保留；按实际行范围找前奏、演唱与转调。
    # samples=[('guitar_intro','guitar/rows/measures_001_004.svg'),('guitar_vocal','guitar/rows/measures_009_012.svg'),
    #          ('guitar_modulation','guitar/rows/measures_081_084.svg'),('piano_intro','piano/rows/measures_001_004.svg'),
    #          ('piano_page','piano/staff_pages/page_001.svg')]
    # 强拍相位与伴奏同步纠错：修改，原固定第一行路径保留；弱起单列后首个完整前奏行从内部2开始。
    # samples=[('piano_intro','piano/rows/measures_001_004.svg'),('piano_page','piano/staff_pages/page_001.svg')]
    from beat_phase_alignment import score_row_ranges
    ranges=score_row_ranges(vocal);intro_first,intro_last=ranges[1] if vocal['timing'].get('initial_pickup_measure') else ranges[0]
    samples=[('piano_intro',f'piano/rows/measures_{intro_first:03}_{intro_last:03}.svg'),('piano_page','piano/staff_pages/page_001.svg')]
    # 小节划分与拍速层级纠错：修改，原雨天小节硬编码保留；从实际人声起点与调段找核验样张。
    # for name,measure in [('guitar_intro',1),('guitar_vocal',9),('guitar_modulation',83)]:
    bar=vocal['statistics']['bar_ticks']
    sung=[n['start_tick']//bar+1 for n in vocal['quantized_notes'] if n.get('lyric_index') is not None and not n.get('grace')]
    changes=vocal['notation'].get('key_segments',[])[1:]
    modulation=changes[0]['start_measure'] if changes else max(1,vocal['statistics']['measure_count']-3)
    # 强拍相位与伴奏同步纠错：修改，原前奏含预备弱起的取样保留；独立核对完整四小节前奏。
    # for name,measure in [('guitar_intro',1),('guitar_vocal',min(sung,default=1)),('guitar_modulation',modulation)]:
    for name,measure in [('guitar_intro',intro_first),('guitar_vocal',min(sung,default=1)),('guitar_modulation',modulation)]:
        for path in sorted((output/'guitar/rows').glob('measures_*.svg')):
            first,last=map(int,path.stem.split('_')[1:])
            if first<=measure<=last:
                samples.append((name,str(path.relative_to(output))));break
    for name,relative in samples:
        source=output/relative
        if not source.exists():continue
        target=report_dir/'visual'/(name+'.png');target.parent.mkdir(parents=True,exist_ok=True)
        target.write_bytes(resvg_py.svg_to_bytes(svg_string=source.read_text(encoding='utf-8'),width=1600,background='white'))
        result['visual_samples'].append(str(target))
    result['valid']=not result['link_errors'] and not result['manifest_errors'] and all(
        check['valid'] for instrument in result['instruments'].values() for check in instrument.values())
    # 相似乐句和弦框架复用：新增共同进行/器乐保护失败阻止交付，即使标签和MIDI自洽也不放行。
    if result.get('phrase_harmony'):result['valid']=result['valid'] and result['phrase_harmony']['valid']
    save_json(report_dir/'independent_verification.json',result)
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--report-dir',type=Path,required=True);args=parser.parse_args()
    report=verify(args.output,args.report_dir)
    print({k:v for k,v in report.items() if k not in ('visual_samples',)},flush=True)
    if not report['valid']:raise SystemExit(1)
