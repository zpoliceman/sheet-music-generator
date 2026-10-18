"""重复乐句折叠与多遍挂词：已验收工程的只读音乐、另存阅读版通用入口。"""
from copy import deepcopy
import json
from pathlib import Path
from shutil import copytree
import time
import xml.etree.ElementTree as ET
# 重复乐句折叠与多遍挂词：修改摘要模块，旧不存在的模块保留；复用正式工具的摘要接口。
# from accompaniment_input import sha256
from accompaniment_sources import sha256
from score_export import read_json, save_json
from guitar_repeat_score import write_repeat_score

ROOT = Path(__file__).resolve().parents[1]


# 重复乐句折叠与多遍挂词：新增完整清单的字节核验，源音频／工程相符才允许只整理谱面。
def unchanged_package(project_path):
    path = Path(project_path).resolve(); manifest = path.parent / 'manifest.json'
    if path.name != 'project.json' or not manifest.is_file(): return False
    rows = read_json(manifest).get('files', [])
    binding = next((row for row in rows if row['path'] == 'project.json'), None)
    return bool(binding and binding['sha256'] == sha256(path))


# 重复乐句折叠与多遍挂词：新增与音乐升级参数互斥的纯排版判断，人工编辑音乐仍走完整正式导出。
def notation_only_request(args):
    # 原曲拍轴与歌词拍位通用修复：新增音乐重建／独立简谱必须走完整正式入口，不被纯反复排版分支截走。
    if getattr(args,'rebuild_source_meter',False) or getattr(args,'export_vocal',False):return False
    upgrades = ('rearrange', 'common_right_hand', 'regular_right_hand', 'structured_accompaniment',
                'correct_beat_phase', 'phrase_rhythm', 'local_beat_clock', 'structural_rhythm',
                'performance_beat_clock', 'continuous_meter', 'vocal_continuity', 'simplify_instrumental',
                'regular_instrumental', 'low_position_instrumental', 'reextract_instrumental_melody',
                'instrumental_flow', 'instrumental_flow_density', 'instrumental_expression', 'phrase_harmony')
    # 旧工程功能自动升级与三曲器乐表现统一：修改请求判定，旧仅CLI开关保留；已有反复版普通重导自动保留布局。
    # return bool(getattr(args, 'fold_repeats', False) and args.edited_project and
    inherited = (read_json(args.edited_project).get('guitar_score_layout', {}).get('mode') == 'repeat_folded') if args.edited_project else False
    return bool((getattr(args, 'fold_repeats', False) or inherited) and args.edited_project and
                all(not getattr(args, name, False) for name in upgrades) and args.capo is None and
                not getattr(args, 'bar_length_factor', None) and not getattr(args, 'instrumental_rest_review', None) and
                unchanged_package(args.edited_project))


# 重复乐句折叠与多遍挂词：新增实际XML／MIDI与全部旧文件保护，钢琴及原唱不重合成。
def generate_repeat_edition(args):
    # 旧工程功能自动升级与三曲器乐表现统一：修改依赖，旧导出接口保留；缺失功能时执行完整吉他音乐导出。
    # from accompaniment_export import parse_musicxml_notes, validate_midi
    from accompaniment_export import parse_musicxml_notes, validate_midi, export_all
    from accompaniment_project_upgrade import ensure_project_features,delivery_capabilities,validate_upgrade_scope
    from generate_accompaniment import load_edited_project, validate_output_path, write_collection_index
    started = time.perf_counter(); source = Path(args.edited_project).resolve().parent
    output = validate_output_path(args.output)
    if output.exists() or output == source or output.is_relative_to(source):
        raise ValueError('反复阅读版必须另存到尚不存在的伴奏目录。')
    if args.report and not Path(args.report).resolve().is_relative_to(ROOT / 'reports/accompaniment'):
        raise ValueError('报告需位于reports/accompaniment。')
    project = read_json(source / 'project.json'); manifest = read_json(source / 'manifest.json')
    before = {str(p): sha256(p) for p in source.rglob('*') if p.is_file()}
    for row in manifest['files']:
        path = (source / row['path']).resolve()
        if not path.is_relative_to(source) or not path.is_file() or sha256(path) != row['sha256'] or path.stat().st_size != row['bytes']:
            raise ValueError('源交付清单无效：' + row['path'])
    # 重复乐句折叠与多遍挂词：新增既有通用来源重放，不能以复制为由绕过原曲骨干／拍轴／演奏验证。
    # 旧工程功能自动升级与三曲器乐表现统一：修改仅校验后忽略返回的旧路径，保留旧调用；加载修复与能力升级贯穿复制入口。
    # load_edited_project(source / 'project.json')
    restored_fields=[]
    shared,vocal,arrangements=load_edited_project(source/'project.json',repair_missing_features=True,feature_repair_log=restored_fields)
    # 默认入口原曲节拍强制复核：新增直接调用纯排版API也不能绕过拍轴来源校正检查，输出目录创建前拒绝。
    from source_meter_entry import require_calibrated_source
    source_meter_entry_check=require_calibrated_source(vocal,shared['input_binding'])
    arrangements,feature_upgrade=ensure_project_features(shared,vocal,arrangements,source/'project.json',Path(args.analysis_dir))
    feature_upgrade['restored_missing_fields']=restored_fields
    vocal = project['accepted_vocal_project']
    for instrument, arrangement in project['arrangements'].items():
        actual, check = parse_musicxml_notes(ET.parse(source / instrument / 'score.musicxml').getroot())
        expected = {n['id']: (n['start_tick'], n['end_tick'], n['pitch_midi']) for n in arrangement['notes']}
        if ({identity: (n['start_tick'], n['end_tick'], n['pitch_midi']) for identity, n in actual.items()} != expected or
                not check['valid'] or not validate_midi(source / instrument / 'accompaniment.mid', arrangement, vocal)['valid']):
            raise ValueError('源谱／MIDI与工程实际音乐不符：' + instrument)
    copytree(source, output)
    # 器乐合理分句与十二品硬限制：新增纯重导复制包的通用本地链接重定位，原音频／XML／MIDI保持字节。
    from accompaniment_package_links import rebase_copied_html
    # 器乐合理分句与十二品硬限制：修改，旧仅执行重定位保留；记录确定的HTML结果，后续仍拒绝任何额外改写。
    # rebase_copied_html(source, output)
    relocated_html = rebase_copied_html(source, output)
    relocated_hashes = {name: sha256(output / name) for name in relocated_html}
    # 旧工程功能自动升级与三曲器乐表现统一：修改复制即出谱的旧流程保留；缺少功能重导XML／MIDI／合播，完整功能原音源幂等复制。
    # result = write_repeat_score(output / 'guitar', project['shared_analysis'], vocal, project['arrangements']['guitar'])
    accepted_validation=read_json(source/'validation.json')
    music_upgrade=feature_upgrade['changed'] or bool(restored_fields)
    if music_upgrade:
        exported=export_all(output,shared,vocal,arrangements,preserve_piano_from=source if 'piano' in arrangements else None,
                            fold_repeats=True,preserve_vocals_from=source)
        result=exported['guitar_repeat_layout'];validation={**accepted_validation,**exported}
        project=read_json(output/'project.json')
        # 旧工程功能自动升级与三曲器乐表现统一：新增严格保护逐音音乐及反复拓扑，新增表现不改变原演奏顺序。
        scope=validate_upgrade_scope(shared,vocal,read_json(source/'project.json')['arrangements'],project['arrangements'])
        if not scope['valid']:raise ValueError('功能补齐导出改变已认可音乐：'+str(scope['errors'][:6]))
    else:
        # 旧工程功能自动升级与三曲器乐表现统一：修改完整能力复制分支，旧传整个乐器字典保留；布局接口只接收吉他编配。
        # result=write_repeat_score(output/'guitar',shared,vocal,arrangements)
        result=write_repeat_score(output/'guitar',shared,vocal,arrangements['guitar'])
        validation=read_json(output/'validation.json')
    source_plan=read_json(source/'guitar/repeat_plan.json') if (source/'guitar/repeat_plan.json').exists() else None
    if source_plan is not None:
        current_plan=read_json(output/'guitar/repeat_plan.json')
        fields=('version','policy','blocks','route','jumps','lines','expanded_bars','printed_bars','saved_bars','folded_blocks')
        # 吉他长段反复与流畅阅读：修改旧反复路线必须不变的限制，注释保留；音乐保护保持，版本升级明确重新规划显示。
        # if any(source_plan.get(k)!=current_plan.get(k) for k in fields):raise ValueError('器乐功能升级改变了已认可反复路线。')
        old_version, new_version = source_plan.get('version', 1), current_plan.get('version', 1)
        if old_version > new_version: raise ValueError('禁止将阅读策略降级。')
        if old_version == new_version and any(source_plan.get(k)!=current_plan.get(k) for k in fields):
            raise ValueError('同版本反复路线出现未解释的变化。')
        result['reading_policy_migration'] = {'from_version': old_version, 'to_version': new_version,
                                             'layout_replanned': old_version != new_version}
    project['feature_capabilities']=delivery_capabilities(feature_upgrade,result)
    project['last_feature_upgrade']=feature_upgrade
    # 重复乐句折叠与多遍挂词：新增顶层纯显示资料，不在受来源保护的音符／编配对象中添加音乐字段。
    # 旧工程功能自动升级与三曲器乐表现统一：修改真实状态报告，旧固定无音乐改动声明保留；力度补齐也属于音源变化。
    # project['guitar_score_layout'] = {'mode': 'repeat_folded', 'plan': 'guitar/repeat_plan.json',
    #                                  'source_package': str(source), 'music_unchanged': True}
    project['guitar_score_layout'] = {'mode': 'repeat_folded', 'plan': 'guitar/repeat_plan.json',
                                     'source_package': str(source), 'music_unchanged': not music_upgrade,
                                     'accepted_melody_rhythm_harmony_preserved': True}
    save_json(output / 'project.json', project)
    # 旧工程功能自动升级与三曲器乐表现统一：修改验证资料，旧重新读取保留；保存当前导出及统一能力报告。
    # validation = read_json(output / 'validation.json'); validation['guitar_repeat_layout'] = result
    validation['guitar_repeat_layout']=result;validation['project_feature_upgrade']=feature_upgrade
    # 旧工程功能自动升级与三曲器乐表现统一：修改可重建交付范围，旧纯页面列表保留；实际升级允许吉他导出及复核页同步更新。
    # mutable = {'guitar/score.html', 'project.json', 'validation.json', 'manifest.json', 'index.html',
    #            'guitar/repeat_plan.json', 'guitar/repeat_validation.json'}
    mutable={'guitar/score.html','project.json','validation.json','manifest.json','index.html',
             'guitar/repeat_plan.json','guitar/repeat_validation.json'}
    # 吉他编配规则闭环修复：新增本次真实验收报告可刷新，音乐文件仍按原SHA保护。
    mutable.add('guitar_readability_acceptance.json')
    if music_upgrade:mutable.add('review.html')
    copied = []
    for path, digest in before.items():
        relative = Path(path).relative_to(source).as_posix()
        # 旧工程功能自动升级与三曲器乐表现统一：新增仅缺失功能时允许更新吉他目录，其它原唱／人声／钢琴按字节保护。
        if music_upgrade and relative.startswith('guitar/'):continue
        if relative in mutable or relative.startswith('guitar/repeat_rows/'): continue
        # 器乐合理分句与十二品硬限制：修改，旧全复制字节比较保留；只允许已确定的本地链接重定位，音乐文件继续原SHA。
        # if sha256(output / relative) != digest: raise ValueError('纯排版改变了已认可音乐：' + relative)
        expected_digest = relocated_hashes.get(relative, digest)
        if sha256(output / relative) != expected_digest: raise ValueError('纯排版改变了已认可音乐：' + relative)
        copied.append(relative)
    if any(sha256(path) != digest for path, digest in before.items()): raise ValueError('旧成果被改动。')
    validation['repeat_edition_preservation'] = {'valid': True, 'source': str(source),
        # 器乐合理分句与十二品硬限制：新增仅UI资源路径变化清单，不将HTML路径变化称为音乐变化。
        'relocated_html_files': relocated_html,
        'unchanged_copied_files': copied, 'all_vocal_and_arrangement_objects_unchanged':
            all(project[key] == read_json(source / 'project.json')[key] for key in ('accepted_vocal_project', 'shared_analysis', 'arrangements')),
        # 旧工程功能自动升级与三曲器乐表现统一：新增区分允许的重音／力度变化，认可旋律与演奏结构仍严格保持。
        'frozen_music_preserved':validate_upgrade_scope(shared,vocal,read_json(source/'project.json')['arrangements'],project['arrangements']),
        # 吉他长段反复与流畅阅读：修改旧固定路线保持声明，原值注释保留；显示策略迁移与音乐保持分别报告。
        # 'repeat_route_preserved':True,'music_feature_upgrade':music_upgrade,
        'repeat_route_preserved': not result.get('reading_policy_migration', {}).get('layout_replanned', False),
        'reading_policy_migration': result.get('reading_policy_migration'), 'music_feature_upgrade':music_upgrade,
        'original_package_bytes_unchanged': True}
    validation['repeat_edition_seconds'] = time.perf_counter() - started
    # 默认入口原曲节拍强制复核：新增快捷交付也报告真实拍轴复核依据，源音乐数据不新增自报可信标记。
    validation['source_meter_entry_check']=source_meter_entry_check
    # 吉他编配规则闭环修复：新增纯复制／只排反复入口同样验真实新产物；旧通过标记不得越过十六分等硬门槛。
    from guitar_readability_acceptance import assess_guitar_readability, require_guitar_readability
    readable=assess_guitar_readability(project,repeat_plan=read_json(output/'guitar/repeat_plan.json'),output_dir=output)
    validation['guitar_readability_acceptance']=readable
    project['guitar_readability_acceptance']=readable
    if not readable['valid']:
        validation['status']='needs_review'
        project['music_acceptance']={**project.get('music_acceptance',{}),'status':'needs_review',
                                     'reason':'guitar_readability_contract_failed','errors':readable['errors']}
    save_json(output/'guitar_readability_acceptance.json',readable)
    save_json(output/'project.json',project)
    save_json(output / 'validation.json', validation)
    # 吉他编配规则闭环修复：新增正常集合入口更新前拒绝失败候选，证据与原版本保持可查。
    require_guitar_readability(project,readable)
    index = (output / 'index.html').read_text('utf-8')
    # 吉他长段反复与流畅阅读：修改旧页继承的折叠说明，注释保留；按新计划清理过时说明再写实际阅读模式。
    # caption = ('<p>吉他采用反复折叠版：各遍人声简谱／歌词上下排列，共用伴奏；' +
    #            str(result['plan']['expanded_bars']) + '个原曲小节归并为' + str(result['plan']['printed_bars']) +
    #            '个伴奏印刷小节。<a href="guitar/score_full.html">查看完整展开谱</a>；原唱、MIDI及钢琴保持原曲顺序。</p>')
    import re
    index = re.sub(r'<p>吉他采用反复折叠版：.*?</p>', '', index)
    caption = ('<p>吉他采用长段反复阅读版，完整段落共用，短段直接写出。' +
               '<a href="guitar/score_full.html">查看完整展开谱</a>。</p>') if result['plan'].get('folded_blocks') else '<p>吉他谱按原曲顺序完整展开，连续向下阅读。</p>'
    index = index.replace('<nav>', caption + '<nav>', 1)
    (output / 'index.html').write_text(index, 'utf-8')
    save_json(output / 'manifest.json', {'schema_version': 1, 'files': [
        {'path': p.relative_to(output).as_posix(), 'sha256': sha256(p), 'bytes': p.stat().st_size}
        for p in sorted(output.rglob('*')) if p.is_file() and p.name != 'manifest.json']})
    if args.report: save_json(args.report, {'repeat_layout': result, 'preservation': validation['repeat_edition_preservation']})
    # 4/4可选右手与实时谱面试听：修改隔离重导只写候选索引，正式谱库继续使用原音乐发布守卫。
    # write_collection_index(output.parent, output / 'index.html')
    isolated_root=Path(__file__).resolve().parents[1]/'test_outputs/accompaniment_runs'
    if output.resolve().is_relative_to(isolated_root.resolve()):
        from accompaniment_export import html_page
        from urllib.parse import quote
        import html
        pages=sorted(p for p in output.parent.glob('*/index.html') if (p.parent/'manifest.json').is_file())
        links=''.join('<p><a href="'+quote(p.relative_to(output.parent).as_posix())+'">'+html.escape(p.parent.name)+'</a></p>' for p in pages)
        (output.parent/'index.html').write_text(html_page('隔离曲谱候选','<h1>隔离曲谱候选</h1><p>候选另存，整曲音乐验收状态以各版本记录为准。</p>'+links),encoding='utf-8')
    else:
        write_collection_index(output.parent,output/'index.html')
    print(json.dumps({'output': str(output), 'valid': True, **result['plan']}, ensure_ascii=False), flush=True)
    return validation
