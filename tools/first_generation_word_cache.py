"""歌词自动加载与伴随声部音区保护：相同音乐的局部词音缓存，严格保留两份来源检查。"""
# 歌词自动加载与伴随声部音区保护：新增独立版本，不改变旧词音v1/v2的严格重放含义。
from copy import deepcopy
from pathlib import Path
from score_export import read_json, save_json, sha256
from source_meter_selection import fingerprint

KIND = 'verified_first_generation_word_cache'
POLICY = {'version': 1, 'both_source_clocks_must_replay': True,
          'all_music_fields_must_match': True, 'legacy_phonemes_and_pcm_must_replay': True,
          'ignored_for_music_identity': ['first_source_meter_correction'], 'whole_music_accepted': False}


def music_identity(voice):
    # 歌词自动加载与伴随声部音区保护：新增只移除已另行逐文件重放的检查凭证；拍点、音符、字位、时长和其它全部字段均参与身份。
    value = deepcopy(voice)
    if not value.pop('first_source_meter_correction', None) or value.get('first_source_word_correction'):
        raise ValueError('可复用字音必须来自尚未局部修词的已验首次拍轴')
    return fingerprint(value)


def _file(path):
    path = Path(path).resolve()
    return {'path': str(path), 'sha256': sha256(path)}


def _read_file(record):
    if sha256(record['path']) != record['sha256']:
        raise ValueError('局部词音缓存的原基准或模型文件已经改变')
    return read_json(record['path'])


def register_cache(legacy_path, base_path, binding, output):
    # 歌词自动加载与伴随声部音区保护：新增仅用原字音／PCM另存声明，不重新执行任何音高、歌词或和弦模型。
    from first_generation_words import apply_words, base_fingerprint
    from source_meter_entry import require_calibrated_source
    from source_timing_acceptance import require_isolated_output
    output = require_isolated_output(output, Path(__file__).resolve().parents[1])
    legacy, base = read_json(legacy_path), read_json(base_path)
    require_calibrated_source(base, binding)
    if legacy.get('version') not in (1, 2) or base_fingerprint(base, legacy['version']) != legacy['base_voice_sha256']:
        raise ValueError('原局部词音与所声明的完整音乐基准不匹配')
    corrected = apply_words(base, legacy, binding)
    value = {'artifact_kind': KIND, 'version': 1, 'policy': deepcopy(POLICY),
             'binding_sha256': fingerprint(binding), 'base_voice': _file(base_path),
             'legacy_words': _file(legacy_path), 'music_identity_sha256': music_identity(base),
             'corrected_voice_music_sha256': music_identity(corrected), 'full_music_accepted': False}
    if output.exists() and read_json(output) != value:
        raise ValueError('不能覆盖已有局部词音缓存声明')
    if not output.exists():
        save_json(output, value)
    return output


def apply_cached_words(base, cache, binding):
    # 歌词自动加载与伴随声部音区保护：新增先独立重放旧／新拍轴，再完整比较音乐；不能只删SHA检查或照搬旧拍轴。
    from first_generation_words import apply_words
    from source_meter_entry import require_calibrated_source
    if (cache.get('artifact_kind') != KIND or cache.get('version') != 1 or cache.get('policy') != POLICY
            or cache.get('binding_sha256') != fingerprint(binding)):
        raise ValueError('局部词音缓存声明的来源或策略不匹配')
    original = _read_file(cache['base_voice'])
    legacy = _read_file(cache['legacy_words'])
    require_calibrated_source(original, binding)
    require_calibrated_source(base, binding)
    if music_identity(original) != cache['music_identity_sha256'] or music_identity(base) != cache['music_identity_sha256']:
        raise ValueError('实际拍点、完整音符、歌词或时长发生变化，不能使用已有局部字音')
    corrected = apply_words(original, legacy, binding)
    if music_identity(corrected) != cache['corrected_voice_music_sha256']:
        raise ValueError('原始音素／完整词音不能重建缓存结果')
    corrected['first_source_meter_correction'] = deepcopy(base['first_source_meter_correction'])
    return corrected
