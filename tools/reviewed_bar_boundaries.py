"""局部两拍过渡听辨修订：冻结演奏，仅重排有来源听辨约束的局部小节线。"""
# 局部两拍过渡听辨修订：新增独立记谱分组层；不把人工局部答案写入自动选拍器，不重编任何音符。
from copy import deepcopy
from pathlib import Path
import shutil
from score_export import read_json, save_json, sha256
from accompaniment_analysis import SongClock
from source_timing_revision import rebuild_events
from source_timing_acceptance import require_isolated_output

ROOT=Path(__file__).resolve().parents[1]
KEY='bar_boundary_revision'


def planned_timeline(project, review):
    # 局部两拍过渡听辨修订：新增封闭窗口内的2／4拍顺序重排；两端、总拍数、拍速及小节数量均不得变化。
    timeline=deepcopy(project['accepted_vocal_project']['timing']['measure_timeline'])
    clock=SongClock(project['accepted_vocal_project']); touched=set();changes=[]
    if not review.get('edits'):raise ValueError('缺少明确局部小节分组复核')
    for edit in review['edits']:
        first=edit['first_measure'];old=edit['old_beats'];new=edit['new_beats']
        if not isinstance(first,int) or first<1 or first+len(old)-1>len(timeline):raise ValueError('复核小节范围无效')
        if sorted(old)!=sorted(new) or any(b not in (2,4) for b in old) or old==new:
            raise ValueError('只允许保留总拍数和小节数量的2／4拍顺序重排')
        indices=set(range(first-1,first-1+len(old)))
        if touched&indices:raise ValueError('局部复核窗口重叠')
        touched|=indices;rows=timeline[first-1:first-1+len(old)]
        if any(m['pickup'] for m in rows) or [(m['end_tick']-m['start_tick'])//480 for m in rows]!=old:
            raise ValueError('复核不是当前小节分组或企图改动弱起')
        start=rows[0]['start_tick'];end=rows[-1]['end_tick'];tick=start
        for m,beats in zip(rows,new):
            m.update(start_tick=tick,end_tick=tick+beats*480,meter=[beats,4],
                start_seconds=clock.seconds(tick),end_seconds=clock.seconds(tick+beats*480))
            tick=m['end_tick']
        if tick!=end:raise ValueError('局部修改没有回到原结束边界')
        constraints=[]
        if not edit.get('beat_constraints'):raise ValueError('局部改线必须给出听辨约束，不能只有小节号')
        for anchor in edit['beat_constraints']:
            t=clock.tick(anchor['source_seconds']);m=next((m for m in rows if m['start_tick']-.01<=t<m['end_tick']-.01),None)
            if m is None:raise ValueError('听辨锚点不在局部窗口内')
            actual=1+(t-m['start_tick'])/480
            if abs(actual-anchor['beat'])>.002:raise ValueError('新小节线未满足实际听辨拍位')
            constraints.append({**anchor,'actual_beat':actual,'internal_measure':m['number']})
        changes.append({'id':edit['id'],'first_measure':first,'old_beats':old,'new_beats':new,
            'start_tick':start,'end_tick':end,'start_seconds':clock.seconds(start),'end_seconds':clock.seconds(end),
            'constraints':constraints,'scope':'local_notation_grouping_only'})
    return timeline,changes


def _derive(base, review, source, review_path):
    # 局部两拍过渡听辨修订：新增派生记谱事件，不改accepted_vocal_project或任何实际演奏对象及祖先证明。
    if KEY in base:raise ValueError('已有边界修订须沿原来源合并复核，不能叠加未说明的分组层')
    timeline,changes=planned_timeline(base,review)
    voice=deepcopy(base['accepted_vocal_project']);rebuild_events(voice,timeline)
    # 局部两拍过渡听辨修订：新增局部以外记谱语义保护；其它入口的特殊记法不能被整表重切静默改掉。
    touched={n for c in changes for n in range(c['first_measure'],c['first_measure']+len(c['new_beats']))}
    def outside(events):
        return [{k:v for k,v in e.items() if k!='id'} for e in events if e['measure'] not in touched]
    if outside(voice['events'])!=outside(base['accepted_vocal_project']['events']):
        raise ValueError('局部窗口外的记谱会改变，需先保留该来源的特殊记法')
    revised=deepcopy(base)
    revised[KEY]={'version':1,'source_project':str(source),'source_project_sha256':sha256(source),
        'review':str(review_path),'review_sha256':sha256(review_path),'measure_timeline':timeline,
        # 局部两拍过渡听辨修订：修改派生歌词索引随事件同步，原词音归属仍冻结。
        # 'events':voice['events'],'changes':changes,'source_performance_unchanged':True,
        'events':voice['events'],'lyric_mapping':voice['lyric_mapping'],'changes':changes,'source_performance_unchanged':True,
        'instruments':['vocal','guitar'],'piano_notation_not_revised':True}
    revised['music_acceptance']={'status':'needs_review','publication_allowed':False,
        'scope':'source_bound_local_barlines_existing_music_retained',
        'unresolved':['new_local_barline_output_listening_pending','piano_listening_deferred_by_user'],
        'reviewed_prior_music':deepcopy(review.get('accepted_scope',{}))}
    return revised


def verify_revision(project, verify_source=True):
    # 局部两拍过渡听辨修订：新增从受保护原工程逐字段重放；改音高、词音、和声、节拍秒数或隐藏复核修改均拒绝。
    revision=project.get(KEY)
    if not revision or revision.get('version')!=1:raise ValueError('缺少局部小节复核来源')
    source=Path(revision['source_project']);review_path=Path(revision['review'])
    if not source.is_file() or sha256(source)!=revision['source_project_sha256']:raise ValueError('原音乐工程缺失或改变')
    if not review_path.is_file() or sha256(review_path)!=revision['review_sha256']:raise ValueError('小节听辨记录缺失或改变')
    base=read_json(source);review=read_json(review_path)
    if review.get('source_project_sha256')!=sha256(source) or review.get('mix_sha256')!=base['shared_analysis']['input_binding']['sources']['mix']['sha256']:
        raise ValueError('听辨不属于当前原曲／工程')
    expected=_derive(base,review,source,review_path)
    if project!=expected:raise ValueError('局部小节修订超出了绑定复核，或改变了受保护音乐')
    if verify_source:
        from revise_guitar_reading import verify_reading_source
        verify_reading_source(base,source)
    return {'valid':True,'source_project':str(source),'source_project_sha256':sha256(source),
        'entire_voice_arrangements_shared_analysis_unchanged':True,'changes':revision['changes'],
        'scope':'bound_local_grouping_not_new_whole_music_certificate'}


def notation_voice(project):
    # 局部两拍过渡听辨修订：新增所有局部声乐绘图共用同一派生事件，歌词／延音跨线重切，实际挂词和音符不变。
    voice=project['accepted_vocal_project'];revision=project.get(KEY)
    if not revision:return voice
    # 局部两拍过渡听辨修订：修改记谱视图同步派生挂词索引，不改变原quantized_notes。
    # return {**voice,'events':revision['events'],'timing':{**voice['timing'],'measure_timeline':revision['measure_timeline']}}
    return {**voice,'events':revision['events'],'lyric_mapping':revision['lyric_mapping'],
        'timing':{**voice['timing'],'measure_timeline':revision['measure_timeline']}}


def display_pattern_project(project):
    # 局部两拍过渡听辨修订：新增记忆表按新局部小节注明衔接；不借挪线重新安排右手。
    if KEY not in project:return project
    guitar=project['arrangements']['guitar'];plan=deepcopy(guitar.get('section_patterns'))
    if not plan:return project
    changed={n for c in project[KEY]['changes'] for n in range(c['first_measure'],c['first_measure']+len(c['new_beats']))}
    for section in plan['sections']:section['arranged_measures']=[n for n in section['arranged_measures'] if n not in changed]
    plan['arranged_measures']=[n for n in plan['arranged_measures'] if n not in changed]
    existing={e['measure'] for e in plan['exceptions']}
    plan['exceptions'] += [{'measure':n,'reason':'reviewed_local_barline_existing_pattern_preserved'} for n in sorted(changed-existing)]
    # 局部两拍过渡听辨修订：新增弱起显示号换算，记忆表与正文使用同一小节号；只改显示副本。
    offset=int(project[KEY]['measure_timeline'][0]['pickup'])
    if offset:
        for section in plan['sections']:section['arranged_measures']=[n-offset for n in section['arranged_measures']]
        plan['arranged_measures']=[n-offset for n in plan['arranged_measures']]
        for exception in plan['exceptions']:exception['measure']-=offset
    return {**project,'arrangements':{**project['arrangements'],'guitar':{**guitar,'section_patterns':plan}}}


def refresh_pattern_guides(project, folder):
    # 局部两拍过渡听辨修订：新增冻结阅读重导时同步显示副表；所有实际音符及音乐文件保持。
    import re
    from guitar_section_patterns import pattern_guide_html
    if KEY not in project:return
    guide=pattern_guide_html(project)
    if not guide:return
    for name in ('score.html','score_full.html'):
        path=Path(folder)/name
        if not path.is_file():continue
        text=path.read_text('utf8')
        text,count=re.subn(r'<section class="vocal-pattern-guide".*?</section>',lambda _:guide,text,flags=re.S)
        if count!=1:raise ValueError('现有阅读谱缺少唯一固定右手表，不能静默遗漏小节号同步')
        path.write_text(text,'utf8')


def assess_local_patterns(project):
    # 局部两拍过渡听辨修订：新增新小节的实际起音／弦序记录，原稳定右手验收继续对完整未改音乐执行。
    revision=project.get(KEY)
    if not revision:return {'valid':True,'status':'not_requested'}
    rows=[];errors=[];notes=project['arrangements']['guitar']['notes']
    for change in revision['changes']:
        for m in revision['measure_timeline'][change['first_measure']-1:change['first_measure']-1+len(change['new_beats'])]:
            ns=sorted((n for n in notes if m['start_tick']<=n['start_tick']<m['end_tick']),key=lambda n:n['start_tick'])
            starts=sorted({n['start_tick'] for n in ns})
            if any(b-a<120 for a,b in zip(starts,starts[1:])):errors.append('local_guitar_attacks_shorter_than_sixteenth')
            rows.append({'number':m['number'],'beats':m['meter'][0],'attack_offsets':[t-m['start_tick'] for t in starts],
                'strings':[n['string'] for n in ns],'note_values':sorted({n['end_tick']-n['start_tick'] for n in ns}),
                'unchanged_existing_boundary_music':True})
    return {'valid':not errors,'errors':errors,'measures':rows,'scope':'current_bar_offsets_with_frozen_approved_right_hand'}


def export_reviewed(project_path, output):
    # 局部两拍过渡听辨修订：新增真正公共重导；重新出小节／拍号／复用版面，试听逐文件复制，不重新合成。
    project=read_json(project_path);check=verify_revision(project)
    output=require_isolated_output(output,ROOT)
    if output.exists() and any(output.iterdir()):raise ValueError('局部小节新版必须另存空目录')
    output.mkdir(parents=True,exist_ok=True);save_json(output/'project.json',project)
    save_json(output/'bar_boundary_protection.json',check)
    from export_timing_revision import export_revision
    result=export_revision(output/'project.json',output,instruments=('vocal','guitar'),
        preserve_audio_from=Path(project[KEY]['source_project']).parent)
    save_json(output/'bar_boundary_acceptance.json',{'source_protection':check,
        'actual_local_patterns':assess_local_patterns(project),'export':result,
        'normal_entry_updated':False,'music_status':'needs_review'})
    return result


def revise(project_path, review_path, output):
    # 局部两拍过渡听辨修订：新增显式审核文件与原音绑定，普通生成不读取曲名或固定秒数。
    source=Path(project_path).resolve();review_path=Path(review_path).resolve()
    base=read_json(source);review=read_json(review_path)
    if review.get('source_project_sha256')!=sha256(source):raise ValueError('小节复核来源工程不一致')
    revised=_derive(base,review,source,review_path);verify_revision(revised)
    output=require_isolated_output(output,ROOT)
    if output.exists() and any(output.iterdir()):raise ValueError('局部小节新版必须另存空目录')
    # 局部两拍过渡听辨修订：新增临时输入只位于新的隔离目录外侧，不能覆盖源谱。
    output.parent.mkdir(parents=True,exist_ok=True)
    candidate=output.parent/(output.name+'_input.json')
    if candidate.exists():raise ValueError('输入候选已存在，另存新版')
    save_json(candidate,revised)
    return export_reviewed(candidate,output)
