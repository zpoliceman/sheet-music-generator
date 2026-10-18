"""尾段原声局部补证：首次已验拍轴接入既有稳定右手、长段阅读和三类实际文件验收。"""
# 尾段原声局部补证：新增首次交付末阶段复用现有公共核心，不另建音乐判据，不用于旧工程重编。
from copy import deepcopy
from pathlib import Path
from score_export import read_json,save_json,sha256
from source_meter_selection import fingerprint


# 4/4可选右手与实时谱面试听：修改首次最终交付接口，选择直接进入最终编译，避免被默认型覆盖。
# def finish_first_delivery(shared,vocal,arrangements,work,output):
def finish_first_delivery(shared,vocal,arrangements,work,output,right_hand_plan=None):
    # 尾段原声局部补证：新增首先重放源拍轴，再保存阶段来源；失败不能丢掉已完成的和声／器乐结果。
    from source_meter_entry import require_calibrated_source
    from source_timing_acceptance import require_isolated_output
    from source_accompaniment_quality import validate_source_coverage
    from accompaniment_analysis import SongClock
    from accompaniment_arrange import validate_playability
    from revise_guitar_patterns import revise
    from export_timing_revision import export_revision
    root=Path(__file__).resolve().parents[1]
    work=require_isolated_output(work,root);output=require_isolated_output(output,root)
    if vocal.get('first_source_meter_correction',{}).get('version')!=2:
        raise ValueError('首次稳定交付只接受新版严格来源投影，不覆盖旧工程')
    source_check=require_calibrated_source(vocal,shared['input_binding'])
    # 尾段原声局部补证：新增实际编配硬核查；纯尾响内仍有新拨弦或琴键时不能导出为已通过候选。
    # 尾段原声局部补证：修改使用各入口共用守卫，避免仅首次路线执行、重导又丢失尾响限制。
    # from first_generation_tail import verified_tail_observation
    # terminal=verified_tail_observation(vocal,shared['input_binding'])
    # if terminal:
    #     clock=SongClock(vocal)
    #     conflicts={name:[note['id'] for note in value['notes'] if clock.seconds(note['start_tick'])>=terminal['start_seconds']-1e-6]
    #                for name,value in arrangements.items()}
    #     if any(conflicts.values()):raise ValueError('已证实尾响内仍有新编配攻击：'+str(conflicts))
    from first_generation_tail import require_terminal_arrangements
    terminal_check=require_terminal_arrangements(shared,vocal,arrangements)
    seed={'schema_version':1,'artifact_kind':'first_generation_preexport_candidate','title':vocal['title'],
          'shared_analysis':deepcopy(shared),'accepted_vocal_project':deepcopy(vocal),'arrangements':deepcopy(arrangements),
          'music_acceptance':{'status':'needs_review','publication_allowed':False,
                              'scope':'source_clock_and_terminal_coverage_verified_whole_music_requires_review'}}
    path=work/'first_delivery_source'/fingerprint(seed)[:24]/'project.json'
    if path.exists() and read_json(path)!=seed:
        raise ValueError('首次末阶段来源不能覆盖')
    if not path.exists():save_json(path,seed)
    # 尾段原声局部补证：新增演唱伴奏先沿用已实施的段级固定型，再导出；不用未整理的原型事件去冒充最终右手。
    # 4/4可选右手与实时谱面试听：修改仅显式选择时增加参数，未选沿用原稳定型交付。
    # pattern=revise(path,output,work/'features')
    pattern=(revise(path,output,work/'features') if right_hand_plan is None else
             revise(path,output,work/'features',right_hand_plan=right_hand_plan))
    project_path=output/'project.json'
    project=read_json(project_path)
    # 尾段原声局部补证：新增三类输出共用同一实际工程和同一来源拍轴；钢琴不重新编配，和弦分析保持。
    selected=('vocal','guitar','piano') if 'piano' in arrangements else ('vocal','guitar')
    checks=export_revision(project_path,output,instruments=selected)
    coverage=validate_source_coverage(project['shared_analysis'],project['accepted_vocal_project'],project['arrangements'])
    playability={name:validate_playability(value,SongClock(project['accepted_vocal_project']))
                 for name,value in project['arrangements'].items()}
    # 尾段原声局部补证：修改持久化保护比较，JSON把元组规范成列表，按同一规范化内容比较而非误判Python容器类型；实际音符和导出仍另逐项验证。
    # if (project['shared_analysis']!=shared or project['accepted_vocal_project']!=vocal
    #         or any(project['arrangements'].get(name)!=value for name,value in arrangements.items() if name!='guitar')):
    if (fingerprint(project['shared_analysis'])!=fingerprint(shared) or fingerprint(project['accepted_vocal_project'])!=fingerprint(vocal)
            or any(fingerprint(project['arrangements'].get(name))!=fingerprint(value) for name,value in arrangements.items() if name!='guitar')):
        raise ValueError('首次末阶段改变原拍轴、共享和弦或非吉他编配')
    if not coverage['valid'] or not all(row['valid'] for row in playability.values()):
        raise ValueError('首次末阶段实际覆盖或演奏失败')
    result={'output':str(output),'valid':True,'status':'candidate_artifacts_passed','music_status':'needs_review',
            'normal_publication_allowed':False,'source_meter_entry_check':source_check,'source_coverage_quality':coverage,
            'playability':playability,'section_patterns':pattern['section_patterns'],'artifacts':checks,
            'staged_source':str(path),'staged_source_sha256':sha256(path),
            'original_voice_shared_harmony_and_piano_preserved':True,'pitch_chord_decoder_called_by_finalizer':False}
    # 尾段原声局部补证：新增实际零攻击证据，不能用来源标记代替检查最终两乐器。
    result['terminal_decay_acceptance']=require_terminal_arrangements(project['shared_analysis'],project['accepted_vocal_project'],project['arrangements'])
    save_json(output/'first_generation_delivery.json',result)
    return result


def main():
    # 尾段原声局部补证：新增显式阶段恢复CLI，只接已保存首次来源工程，继续同一末阶段而不重复推理。
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--staged-project',type=Path,required=True)
    parser.add_argument('--analysis-dir',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    # 4/4可选右手与实时谱面试听：新增阶段恢复入口同样支持最终选型。
    parser.add_argument('--right-hand-plan',type=Path)
    args=parser.parse_args()
    project=read_json(args.staged_project)
    if project.get('artifact_kind')!='first_generation_preexport_candidate':
        raise ValueError('恢复入口只接受首次生成阶段工程，旧曲谱继续原保护路线')
    # 4/4可选右手与实时谱面试听：修改恢复CLI传递计划，旧未选择行为保持。
    # result=finish_first_delivery(project['shared_analysis'],project['accepted_vocal_project'],project['arrangements'],
    #                              args.analysis_dir,args.output)
    result=finish_first_delivery(project['shared_analysis'],project['accepted_vocal_project'],project['arrangements'],
                                 args.analysis_dir,args.output,right_hand_plan=args.right_hand_plan)
    print(result['output'])


if __name__=='__main__':
    # 尾段原声局部补证：新增脚本入口。
    main()
