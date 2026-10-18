"""演唱段稳定右手型：从已认可工程另存固定右手吉他谱及原唱合播。"""
# 演唱段稳定右手型：新增保护入口，不执行人声／音高／和弦识别，不更新正常谱库。
from copy import deepcopy
from pathlib import Path
import argparse

from accompaniment_analysis import extract_features
from score_export import read_json, save_json, sha256
from source_timing_acceptance import require_isolated_output
from guitar_section_patterns import arrange_section_patterns, assess_section_patterns, POLICY

ROOT=Path(__file__).resolve().parents[1]


def has_section_patterns(project):
    # 演唱段稳定右手型：新增顶层丢字段仍能识别窄范围工程，禁止回到整曲重分析分支。
    guitar=project.get('arrangements',{}).get('guitar',{})
    return bool(project.get('vocal_pattern_revision') or guitar.get('section_patterns') or
                guitar.get('configuration',{}).get('stable_vocal_patterns'))


# 4/4可选右手与实时谱面试听：修改接口新增显式计划；未传时保留原调用及默认结果。
# def revise(project_path, output, feature_cache=None):
def revise(project_path, output, feature_cache=None, right_hand_plan=None):
    # 演唱段稳定右手型：新增唯一公共编排入口，已修版本普通重导保持音符不再套型。
    project_path=Path(project_path).resolve();output=require_isolated_output(output,ROOT)
    if output.exists() and any(output.iterdir()):raise ValueError('输出目录已有内容，请另存新版本')
    original=read_json(project_path); original_sha=sha256(project_path)
    # 4/4可选右手与实时谱面试听：新增选型及已选型重导入口，先于旧inherited短路。
    from guitar_pattern_selection import has_selection
    if right_hand_plan is not None or has_selection(original):
        from revise_guitar_selection import revise_selection
        return revise_selection(project_path,output,right_hand_plan,feature_cache)
    inherited=has_section_patterns(original)
    if inherited:
        check=assess_section_patterns(original)
        if not check['valid']:raise ValueError('既有段落型已失效：'+str(check['errors']))
        from guitar_source_bass_acceptance import require_changed_bass_source
        require_changed_bass_source(original,original.get('guitar_source_bass_acceptance'))
        source=original['vocal_pattern_source']; baseline_path=Path(source['project']);baseline_sha=source['project_sha256'];baseline=read_json(baseline_path)
    else:
        # 演唱段稳定右手型：新增保留原低音可信祖先检查，不能用失败稿自比刷新成通过。
        from revise_guitar_readability import protected_baseline
        protected_baseline(original,project_path)
        baseline_path=project_path;baseline_sha=original_sha;baseline=original
    sources=original['shared_analysis']['input_binding']['sources'];bindings={}
    for name,source in sources.items():
        digest=sha256(source['path'])
        if digest!=source['sha256']:raise ValueError('原曲来源已改变：'+name)
        bindings[name]={'path':source['path'],'sha256':digest}
    cache=Path(feature_cache) if feature_cache else output.parent/'features'
    features={name:extract_features(sources[name],cache,name) for name in ('mix','accompaniment','bass','six_guitar') if name in sources}
    if inherited:
        revised=deepcopy(original); audit={'status':'exact_pattern_music_reexport','music_changed':False}
    else:
        revised,audit=arrange_section_patterns(original,features)
        revised['vocal_pattern_source']={'project':str(project_path),'project_sha256':original_sha,
                                        'verified_sources':bindings,'no_pitch_or_harmony_reanalysis':True}
        revised['readability_source']={'project':str(project_path),'project_sha256':original_sha,
            'baseline_project':str(baseline_path),'baseline_project_sha256':baseline_sha,
            'verified_sources':bindings,'no_pitch_or_harmony_reanalysis':True}
    # 演唱段稳定右手型：新增排版派生先于全材料原低音摘要，避免显示字段使真实来源检查过期。
    from revise_guitar_register import prepare_reading_layout
    layout=prepare_reading_layout(revised)
    pattern_check=assess_section_patterns(revised,baseline)
    if not pattern_check['valid']:raise ValueError('实际段落右手型验收失败：'+str(pattern_check['errors']))
    from guitar_source_bass_acceptance import assess_changed_bass_source,require_changed_bass_source
    bass_check=assess_changed_bass_source(revised,baseline,features.get('bass'))
    revised['guitar_source_bass_acceptance']=bass_check
    output.mkdir(parents=True,exist_ok=True)
    save_json(output/'pattern_revision.json',audit);save_json(output/'section_pattern_acceptance.json',pattern_check)
    save_json(output/'guitar_source_bass_acceptance.json',bass_check);save_json(output/'reading_layout.json',layout)
    save_json(output/'project.json',revised)
    require_changed_bass_source(revised,bass_check)
    from guitar_variable_repeat import build_repeat_plan
    from guitar_readability_acceptance import assess_guitar_readability,require_guitar_readability
    plan=build_repeat_plan(revised)
    preflight=assess_guitar_readability(revised,repeat_plan=plan,baseline_project=baseline)
    save_json(output/'guitar_readability_preflight.json',preflight)
    require_guitar_readability(revised,preflight,final=False)
    from export_timing_revision import export_revision
    export_revision(output/'project.json',output,instruments=('guitar',))
    final=assess_guitar_readability(revised,repeat_plan=read_json(output/'guitar/repeat_plan.json'),
                                   output_dir=output,baseline_project=baseline)
    save_json(output/'guitar_readability_acceptance.json',final);require_guitar_readability(revised,final)
    if sha256(project_path)!=original_sha or sha256(baseline_path)!=baseline_sha:
        raise ValueError('处理期间来源工程改变，候选不得采用')
    revised['guitar_readability_acceptance']=final
    revised['section_pattern_acceptance']=pattern_check
    revised['guitar_score_layout']={'mode':'repeat_folded','plan':'guitar/repeat_plan.json','full_score':'guitar/score_full.html'}
    save_json(output/'project.json',revised)
    result={'output':str(output),'valid':True,'music_status':'needs_review','normal_entry_changed':False,
            'policy':POLICY,'section_patterns':pattern_check,'readability':final}
    save_json(output/'revision_report.json',result)
    return result


def main():
    # 演唱段稳定右手型：新增CLI参数；所有修改都须从绑定原工程另存。
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    # 4/4可选右手与实时谱面试听：修改CLI使选择真正传到公共编译与产物验收。
    # parser.add_argument('--feature-cache',type=Path);args=parser.parse_args()
    # print(revise(args.project,args.output,args.feature_cache)['output'])
    parser.add_argument('--feature-cache',type=Path)
    parser.add_argument('--right-hand-plan',type=Path)
    args=parser.parse_args()
    print(revise(args.project,args.output,args.feature_cache,right_hand_plan=args.right_hand_plan)['output'])


if __name__=='__main__':
    # 演唱段稳定右手型：新增脚本执行保护。
    main()
