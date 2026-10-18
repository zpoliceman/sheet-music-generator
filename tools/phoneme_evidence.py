"""字音归属修复：新增TIFA音素证据传递与旧缓存回填，保留原字界。"""
import argparse
import copy
import hashlib
import json
import math
from pathlib import Path
from workspace_location import local_path

# 字音归属修复：新增普通话声母识别；单音素音节不因m/n等标签丢失核音。
INITIALS = frozenset('b p m f d t n l g k h j q x zh ch sh r z c s y y0 w'.split())
VOICED_INITIALS = frozenset('m n l r y y0 w'.split())

# 字音归属修复：新增只读哈希与JSON接口，缓存证据必须可追溯。
def sha256(path):
    digest = hashlib.sha256()
    with local_path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def read_json(path):
    return json.loads(local_path(path).read_text(encoding='utf-8-sig'))

# 字音归属修复：新增音素的全局秒坐标与发音角色；不按文字长度分摊时间。
def character_phonemes(states, offset):
    records = []
    for state in states:
        start, end = float(state['start_seconds']), float(state['end_seconds'])
        if not all(math.isfinite(v) for v in (start, end, offset)) or end < start:
            raise ValueError('音素时间无效，不能伪造挂词证据。')
        token = str(state['phoneme'])
        language, _, phone = token.partition('/')
        if not phone:
            language, phone = 'unknown', token
        role = 'nucleus'
        if language == 'zh' and len(states) > 1 and phone in INITIALS:
            role = 'voiced_initial' if phone in VOICED_INITIALS else 'initial'
        # 中文版本冻结与英文融合验证：注释保留被替换的原实现。
        # elif language != 'zh':
            # role = 'unknown'
        # 中文版本冻结与英文融合验证：新增中英文兼容实现。
        elif language == 'en':
            from english_lyrics import ENGLISH_VOWELS, ENGLISH_VOICED_CONSONANTS
            role = 'nucleus' if phone in ENGLISH_VOWELS else ('voiced_initial' if phone in ENGLISH_VOICED_CONSONANTS else 'initial')
        elif language != 'zh':
            role = 'unknown' 
        records.append({'phoneme': token, 'role': role,
                        'start_seconds': start + offset, 'end_seconds': end + offset,
                        'skipped': end <= start, 'timing_source': 'tifa_raw_state'})
    return records

# 字音归属修复：新增一致性校验；不允许不同音源、不同歌词、重复字的owner串位。
def enrich(lyrics, report):
    result = copy.deepcopy(lyrics)
    source = result.get('source', {})
    if not source.get('sha256') or report.get('source', {}).get('sha256') != source['sha256']:
        raise ValueError('音素报告与歌词音频来源不一致。')
    if abs(report['source'].get('offset_seconds', 0) - source.get('offset_seconds', 0)) > 1e-6:
        raise ValueError('音素报告与歌词全局时间偏移不一致。')
    if report.get('cache_key', {}).get('text_sha256') != result.get('cache_key', {}).get('text_sha256'):
        raise ValueError('音素报告与歌词文本哈希不一致。')
    chars = result['characters']
    jobs = report.get('phrase_reports')
    if jobs is None:
        jobs = [dict(report, job_id=None, crop=source, original_source=source)]
    by_job = {j.get('job_id'): j for j in jobs if j.get('status') != 'failed'}
    loaded = {}
    provenance = []
    for char in chars:
        # 连续转调识别与不确定调性保护：只为报告中明确隔离的语言留空音素；来源/时间校验仍严格。
        if char.get('method')=='unsupported_language_unaligned':
            if char.get('line_index') not in report.get('backend_unaligned_line_indices',[]) or char.get('start_seconds') is not None or char.get('end_seconds') is not None or char.get('group_id') is not None or 'backend_unsupported_text' not in char.get('warnings',[]):
                raise ValueError('未支持语言标记与真实报告不一致。')
            char['phonemes']=[];char['warnings']=list(dict.fromkeys(char['warnings']+['phoneme_unavailable_unsupported_language']))
            continue
        key = char.get('phrase_job_id')
        job = by_job.get(key)
        # 中文版本冻结与英文融合验证：注释保留被替换的原实现。
        # if job is None or not job.get('raw_alignment'):
            # raise ValueError('缓存缺少实际音素报告，不能声称已使用音素证据。')
        # 中文版本冻结与英文融合验证：新增中英文兼容实现。
        if job is None and char.get('line_index') in report.get('unassigned_window_line_indices', []) and char.get('method') == 'alignment_missing' and char.get('start_seconds') is None and char.get('end_seconds') is None and char.get('group_id') is None and not char.get('phoneme_source'):
            char['phonemes'] = []
            char['warnings'] = list(dict.fromkeys(char.get('warnings', []) + ['phoneme_unavailable_no_supported_window']))
            continue
        if job is None or not job.get('raw_alignment'):
            raise ValueError('缓存缺少实际音素报告，不能声称已使用音素证据。')
        if key not in loaded:
            crop = job.get('crop', source)
            original = job.get('original_source', source)
            if original.get('sha256') != source['sha256']:
                raise ValueError('音素裁剪所属原音频不一致。')
            path = Path(job['raw_alignment'])
            raw = read_json(path)
            if raw.get('source', {}).get('sha256') != crop.get('sha256'):
                raise ValueError('原音素文件与裁剪音频哈希不一致。')
            if abs(raw['source'].get('offset_seconds', 0) - crop.get('offset_seconds', 0)) > 1e-6:
                raise ValueError('原音素文件裁剪坐标不一致。')
            if not local_path(crop['path']).is_file() or sha256(crop['path']) != crop['sha256']:
                raise ValueError('音素裁剪音频不存在或字节被修改。')
            values = raw.get('results', [])
            if len(values) != 1:
                raise ValueError('不能猜测多个音素结果的歌词身份。')
            loaded[key] = (values[0], float(crop.get('offset_seconds', 0)))
            provenance.append({'job_id': key, 'path': str(path.resolve()), 'sha256': sha256(path),
                               'crop_sha256': crop['sha256'], 'offset_seconds': crop.get('offset_seconds', 0)})
        value, offset = loaded[key]
        # 字音归属修复：新增按原G2P owner取音素，不能按文字搜索重复字。
        # 第三首《我不难过》跨歌曲验证：修改空group_id处理，原代码保留；完全跳过的字只使用可核对的原始owner，不造时间。
        # owner = int(str(char['group_id']).rsplit('_', 1)[1])
        suffix = str(char.get('group_id')).rsplit('_', 1)[-1]
        evidence_owner = (char.get('phoneme_source') or {}).get('word_owner')
        if suffix.isdigit():
            owner = int(suffix)
            if evidence_owner is not None and evidence_owner != owner:
                raise ValueError('音素owner与分组身份冲突。')
        elif isinstance(evidence_owner, int) and evidence_owner > 0:
            owner = evidence_owner
        else:
            raise ValueError('缺少可核对的原始音素owner，不能猜测未定位字身份。')
        # 字音归属修复：修改，原宽泛降级会掩盖重复字owner串位，注释保留。
        # if not 1 <= owner <= len(value['texts']) or value['texts'][owner - 1] != char['text']:
        # # 字音归属修复：新增多字词明确回退，绝不将同一个词范围均分成逐字音素。
        # char['phonemes'] = []
        # char.setdefault('warnings', []).append('phoneme_character_owner_unavailable')
        # continue
        if not 1 <= owner <= len(value['texts']):
            raise ValueError('音素owner超出实际文本。')
        owner_text = value['texts'][owner - 1]
        # 中文版本冻结与英文融合验证：注释保留被替换的原实现。
        # if owner_text != char['text']:
        # 中文版本冻结与英文融合验证：新增中英文兼容实现。
        from lyrics_tokens import lyric_match_key
        if lyric_match_key(owner_text) != lyric_match_key(char['text']):
            if len(owner_text) > 1 and char['text'] in owner_text and 'shared_word_span' in char.get('warnings', []):
                char['phonemes'] = []
                char.setdefault('warnings', []).append('phoneme_character_owner_unavailable')
                continue
            raise ValueError('音素owner与字符身份不一致。')
        states = [s for s in value['phoneme_states'] if s['word_owner'] == owner]
        # 中文版本冻结与英文融合验证：注释保留被替换的原实现。
        # if not states or any(s['text'] != char['text'] for s in states):
        # 中文版本冻结与英文融合验证：新增中英文兼容实现。
        if not states or any(lyric_match_key(s['text']) != lyric_match_key(char['text']) for s in states):
            raise ValueError('音素owner与字符不一致。')
        char['phonemes'] = character_phonemes(states, offset)
        char['phoneme_source'] = {'job_id': key, 'word_owner': owner, 'timestep_seconds': job.get('model_timestep_seconds', .01)}
    result['phoneme_provenance'] = {'version': 1, 'source_sha256': source['sha256'],
                                  'raw_files': provenance, 'reference_score_used': False,
                                  'timing_kind': 'model_estimates_not_manual_ground_truth'}
    return result

# 字音归属修复：新增独立派生文件入口，旧characters.json和原始模型音素不覆盖。
# 中文版本冻结与英文融合验证：旧字母级缓存不能充当新英文整词对齐，必须核对规范单位序列。
def validate_reference_units(lyrics, reference):
    from lyrics_tokens import text_units
    expected = [(u['text'], u['kind']) for line in reference['lines'] for u in text_units(line)]
    actual = [(c['text'], c.get('unit_kind', 'character')) for c in lyrics['characters']]
    if actual != expected:
        raise ValueError('缓存歌词单位与当前规范原文不一致；英文必须按单词重新真实对齐。')
    if [c['index'] for c in lyrics['characters']] != list(range(len(expected))):
        raise ValueError('缓存公开歌词索引不完整或逆序。')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--characters', type=Path, required=True)
    parser.add_argument('--alignment-report', type=Path, required=True)
    # 中文版本冻结与英文融合验证：注释保留被替换的原实现。
    # parser.add_argument('--output', type=Path, required=True)
    # 中文版本冻结与英文融合验证：新增中英文兼容实现。
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--reference-file', type=Path)
    args = parser.parse_args()
    # 中文版本冻结与英文融合验证：注释保留被替换的原实现。
    # lyrics, report = read_json(args.characters), read_json(args.alignment_report)
    # 中文版本冻结与英文融合验证：新增中英文兼容实现。
    lyrics, report = read_json(args.characters), read_json(args.alignment_report)
    if args.reference_file:
        validate_reference_units(lyrics, read_json(args.reference_file))
    # 字音归属修复：新增显式近似后端兼容；缺音素时仅保留旧字界并报告。
    if 'tifa' not in lyrics.get('alignment_status', '').lower():
        result = copy.deepcopy(lyrics)
        result['phoneme_provenance'] = {'version': 1, 'status': 'unavailable_non_tifa_backend', 'reference_score_used': False}
    else:
        result = enrich(lyrics, report)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'status': 'phoneme_evidence_derived', 'characters': len(result['characters']),
                      'with_phonemes': sum(bool(c.get('phonemes')) for c in result['characters']),
                      'output': str(args.output.resolve())}, ensure_ascii=False))
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
