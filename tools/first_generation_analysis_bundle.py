"""歌词自动加载与伴随声部音区保护：正常入口读取来源绑定的分析文件清单。"""
# 歌词自动加载与伴随声部音区保护：新增通用清单；不按歌名或历史目录搜索文件，声明过的修正丢失必须报错。
from copy import deepcopy
from pathlib import Path
from score_export import read_json, save_json, sha256
from source_meter_selection import fingerprint

NAME = 'analysis_bundle.json'
KIND = 'first_generation_analysis_bundle'


# 歌词自动加载与伴随声部音区保护：修改清单同时携带认可伴随声部参考；不复制其旋律或代替正常编配。
# def save_bundle(shared_path, words_path=None):
def save_bundle(shared_path, words_path=None, companion_reference=None):
    # 歌词自动加载与伴随声部音区保护：新增缓存产出时自动登记，下一次正常入口无需记住单独的词音参数。
    shared_path = Path(shared_path).resolve()
    # 歌词自动加载与伴随声部音区保护：新增写入边界，只能在隔离分析工作区另存，不改正常谱库的分析文件。
    from source_timing_acceptance import require_isolated_output
    require_isolated_output(shared_path.parent, Path(__file__).resolve().parents[1])
    shared = read_json(shared_path)
    # 歌词自动加载与伴随声部音区保护：新增缓存内的必需文件声明，整张清单被漏带时也须报错，不能默默降级旧词位。
    requirements = {'version': 1, 'word_correction_sha256': sha256(words_path) if words_path is not None else None,
                    'companion_reference_sha256': companion_reference['sha256'] if companion_reference else None}
    # 歌词自动加载与伴随声部音区保护：新增先拒绝旧清单不一致，不能写坏已有共享分析后才报错。
    if (shared_path.parent / NAME).exists() and shared.get('analysis_input_requirements') != requirements:
        raise ValueError('已有分析清单不允许原地改变必需输入，请另存版本')
    if shared.get('analysis_input_requirements') != requirements:
        shared['analysis_input_requirements'] = requirements
        save_json(shared_path, shared)
    value = {'artifact_kind': KIND, 'version': 1, 'shared_analysis_sha256': sha256(shared_path),
             'input_binding_sha256': fingerprint(shared['input_binding']), 'required_word_correction': words_path is not None}
    if words_path is not None:
        words_path = Path(words_path).resolve()
        value['word_correction'] = {'path': str(words_path), 'sha256': sha256(words_path)}
    # 歌词自动加载与伴随声部音区保护：新增来源绑定参考，后续生成自动沿用，不能靠调用者重复记参数。
    if companion_reference is not None:
        value['companion_reference'] = deepcopy(companion_reference)
    path = shared_path.parent / NAME
    if path.exists() and read_json(path) != value:
        raise ValueError('分析清单已经存在且内容不同，请另存完整缓存')
    if not path.exists():
        save_json(path, value)
    return path


def read_bundle(shared_path):
    # 歌词自动加载与伴随声部音区保护：新增统一读取和完整文件身份检查；显式更换文件、缺声明或删清单都不能静默放过。
    shared_path = Path(shared_path).resolve()
    shared = read_json(shared_path)
    path = shared_path.parent / NAME
    declared = shared.get('analysis_input_requirements', {})
    if not path.is_file():
        if declared.get('word_correction_sha256') or declared.get('companion_reference_sha256'):
            raise ValueError('共享分析要求的文件清单缺失，不能退回旧音乐')
        return None
    bundle = read_json(path)
    if (bundle.get('artifact_kind') != KIND or bundle.get('version') != 1
            or bundle.get('shared_analysis_sha256') != sha256(shared_path)
            or bundle.get('input_binding_sha256') != fingerprint(shared['input_binding'])):
        raise ValueError('已有分析文件清单与共享分析来源不一致')
    expected = {'version': 1, 'word_correction_sha256': (bundle.get('word_correction') or {}).get('sha256'),
                'companion_reference_sha256': (bundle.get('companion_reference') or {}).get('sha256')}
    if declared != expected:
        raise ValueError('共享分析的必需文件与清单不一致')
    for key in ('word_correction', 'companion_reference'):
        record = bundle.get(key)
        if record and (not Path(record['path']).is_file() or sha256(record['path']) != record['sha256']):
            raise ValueError('分析清单中的必需文件缺失或已经改变：' + key)
    return bundle


def resolve_companion(shared_path):
    # 歌词自动加载与伴随声部音区保护：新增正常入口自动接收同源参考，没有清单的旧缓存不自动猜测历史版本。
    bundle = read_bundle(shared_path) if shared_path is not None else None
    return deepcopy(bundle.get('companion_reference')) if bundle else None


def resolve_words(shared_path, explicit_path=None):
    # 歌词自动加载与伴随声部音区保护：新增声明修正优先保护；显式参数与清单冲突也拒绝，不静默回退旧字位。
    if shared_path is None:
        return Path(explicit_path).resolve() if explicit_path is not None else None
    shared_path = Path(shared_path).resolve()
    # 歌词自动加载与伴随声部音区保护：修改统一检查整张清单，缺失必需内容不允许回退。
    # path = shared_path.parent / NAME
    # if not path.is_file():
    bundle = read_bundle(shared_path)
    if bundle is None:
        return Path(explicit_path).resolve() if explicit_path is not None else None
    # 歌词自动加载与伴随声部音区保护：删除重复读取并注释保留，由上方read_bundle逐项严格核验。
    # bundle = read_json(path)
    # shared = read_json(shared_path)
    # if (bundle.get('artifact_kind') != KIND or bundle.get('version') != 1
    #         or bundle.get('shared_analysis_sha256') != sha256(shared_path)
    #         or bundle.get('input_binding_sha256') != fingerprint(shared['input_binding'])):
    #     raise ValueError('已有分析文件清单与共享分析来源不一致')
    correction = bundle.get('word_correction')
    if bundle.get('required_word_correction') and correction is None:
        raise ValueError('分析清单声明必需歌词修正却没有文件，停止生成')
    if correction is None:
        return Path(explicit_path).resolve() if explicit_path is not None else None
    candidate = Path(correction['path'])
    if not candidate.is_file() or sha256(candidate) != correction['sha256']:
        raise ValueError('分析清单中的必需歌词修正缺失或已改变，不能退回旧词位')
    if explicit_path is not None and sha256(explicit_path) != correction['sha256']:
        raise ValueError('明确指定的歌词修正与分析清单冲突')
    return candidate.resolve()


# 歌词自动加载与伴随声部音区保护：修改通用整理入口可登记已有认可编配，文件仅作为同源约束，不绕过新生成。
# def package(shared_path, legacy_words, base_voice, output):
def package(shared_path, legacy_words, base_voice, output, approved_project=None):
    # 歌词自动加载与伴随声部音区保护：新增旧缓存的一次性通用打包，不改原共享分析、旧字音或原声。
    import shutil
    from first_generation_word_cache import register_cache
    from source_timing_acceptance import require_isolated_output
    output = require_isolated_output(Path(output), Path(__file__).resolve().parents[1])
    if output.exists():
        raise ValueError('打包不能覆盖已有分析版本')
    shared = read_json(shared_path)
    output.mkdir(parents=True)
    target = output / 'shared_analysis.json'
    shutil.copy2(shared_path, target)
    if (Path(shared_path).parent / 'features').is_dir():
        shutil.copytree(Path(shared_path).parent / 'features', output / 'features')
    words = register_cache(legacy_words, base_voice, shared['input_binding'], output / 'reusable_word_supplement.json') if legacy_words else None
    # 歌词自动加载与伴随声部音区保护：新增自动携带认可伴随音区参考，仍由初次配音逐项验证音乐相同。
    reference = {'path': str(Path(approved_project).resolve()), 'sha256': sha256(approved_project)} if approved_project else None
    # save_bundle(target, words)
    save_bundle(target, words, reference)
    return target


def main():
    # 歌词自动加载与伴随声部音区保护：新增只接文件参数的缓存整理入口，曲目只在用户选择的输入路径中出现。
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--shared-analysis', type=Path, required=True)
    parser.add_argument('--word-supplement', type=Path)
    parser.add_argument('--base-voice', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    # 歌词自动加载与伴随声部音区保护：新增仅用户选定的来源参考参数，不读取曲名分支。
    parser.add_argument('--approved-project', type=Path)
    args = parser.parse_args()
    if bool(args.word_supplement) != bool(args.base_voice):
        raise ValueError('整理旧字音需同时提供原字音与当时完整基准')
    # 歌词自动加载与伴随声部音区保护：修改将同源认可参考写入独立分析包，原文件不变。
    # print(package(args.shared_analysis, args.word_supplement, args.base_voice, args.output))
    print(package(args.shared_analysis, args.word_supplement, args.base_voice, args.output, args.approved_project))


if __name__ == '__main__':
    main()
