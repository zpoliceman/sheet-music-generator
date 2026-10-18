"""跨歌曲和弦复用与器乐准备：明确恢复源调，为未移调原歌手合播生成独立人声输入。"""
# 跨歌曲和弦复用与器乐准备：新增通用源调准备，不读取曲名、歌词或参考谱。
from copy import deepcopy
from pathlib import Path
import argparse
from score_export import key_definition, read_json, save_json, sha256

ROOT = Path(__file__).resolve().parents[1]
NAMES = ['C', 'Db', 'D', 'Eb', 'E', 'F', 'Gb', 'G', 'Ab', 'A', 'Bb', 'B']
# 跨歌曲和弦复用与器乐准备：新增小调等音拼写选择，避免把F#小调误拼为不支持的Gb小调。
MINOR_NAMES = ['C', 'C#', 'D', 'Eb', 'E', 'F', 'F#', 'G', 'Ab', 'A', 'Bb', 'B']


# 跨歌曲和弦复用与器乐准备：新增确定性移调反算；只改变记谱音高/调号，原音段与音乐身份保持。
def restore_source_pitch(original, source_path, source_sha256):
    if any(original.get(k) for k in ('performance_clock_correction', 'structural_clock_correction',
                                     'local_clock_correction', 'beat_phase_correction', 'grid_correction')):
        raise ValueError('源调准备应在伴奏拍轴派生之前执行，不能绕过历史派生保护。')
    notation = original['notation']; shift = notation.get('transpose_semitones', 0)
    if not isinstance(shift, int):
        raise ValueError('只接受明确整数半音的已有移调声明。')
    target, source = notation['key'], notation['source_key']
    if target['mode'] != source['mode'] or (target['tonic_pc']-shift) % 12 != source['tonic_pc']:
        raise ValueError('目标调、源调与声明移调不一致，不能猜测恢复音高。')
    result = deepcopy(original)
    for layer in ('quantized_notes', 'events'):
        for note in result[layer]:
            if note.get('pitch_midi') is not None:
                note['pitch_midi'] -= shift
                if not 1 <= note['pitch_midi'] <= 127:
                    raise ValueError('恢复源调后音高超出MIDI音域。')
    prepared = result['notation']; prepared['key'] = deepcopy(source)
    prepared['target_key'] = source['label']; prepared['transpose_semitones'] = 0
    if 'jianpu_reference_midi' in prepared:
        prepared['jianpu_reference_midi'] -= shift
    for segment in prepared.get('key_segments', []):
        old = segment['key']
        # 跨歌曲和弦复用与器乐准备：新增保留局部转调关系，不把整曲统一替换为一个源调。
        # 跨歌曲和弦复用与器乐准备：修改，旧共用大调拼写保留；局部小调也按有效等音定义恢复。
        # restored = key_definition(NAMES[(old['tonic_pc']-shift) % 12]+':'+old['mode'])
        names = MINOR_NAMES if old['mode'] == 'minor' else NAMES
        restored = key_definition(names[(old['tonic_pc']-shift) % 12]+':'+old['mode'])
        segment['key'] = restored
    if result.get('overrides') is not None:
        result['overrides']['key'] = source['label']
    result['accompaniment_source_pitch'] = {
        'version': 1, 'source_project': str(Path(source_path).resolve()), 'source_project_sha256': source_sha256,
        'previous_target_key': target['label'], 'restored_source_key': source['label'],
        'reversed_transpose_semitones': shift, 'actual_pitch_change_semitones': -shift,
        'singer_audio_pitch_shift_semitones': 0, 'lyrics_and_rhythm_changed': False,
        'raw_audio_and_source_note_fields_changed': False,
        'method': 'reverse_declared_target_transposition_before_accompaniment_analysis'}
    return result


# 跨歌曲和弦复用与器乐准备：新增源调派生的严格重建，不能只信一段声明或新文件自身摘要。
def validate_source_pitch_project(project):
    record = project.get('accompaniment_source_pitch')
    if not record:
        return True
    try:
        source = Path(record['source_project'])
        if sha256(source) != record['source_project_sha256']:
            return False
        expected = restore_source_pitch(read_json(source), source, record['source_project_sha256'])
        return expected == project
    except (OSError, ValueError, KeyError, TypeError):
        return False


# 跨歌曲和弦复用与器乐准备：新增显式另存CLI，既有目标调人声谱和原歌手音频不改写。
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--vocal-project', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(); source = args.vocal_project.resolve(); output = args.output.resolve()
    allowed = ROOT/'test_outputs/accompaniment_runs'
    if not output.is_relative_to(allowed) or output == source:
        raise ValueError('源调输入必须另存到独立的伴奏分析缓存目录。')
    prepared = restore_source_pitch(read_json(source), source, sha256(source))
    if not validate_source_pitch_project(prepared):
        raise ValueError('源调输入无法确定性重建。')
    output.parent.mkdir(parents=True, exist_ok=True); save_json(output, prepared)
    print({'output': str(output), 'key': prepared['notation']['key']['label'],
           'actual_pitch_change_semitones': prepared['accompaniment_source_pitch']['actual_pitch_change_semitones']})


if __name__ == '__main__':
    main()
