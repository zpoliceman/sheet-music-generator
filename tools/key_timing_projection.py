"""新曲慢拍生成与转调标签同步：在已修订拍轴上重定位既有调号，不重新识别调性。"""
# 新曲慢拍生成与转调标签同步：新增显式调用的通用元数据投影；历史生成入口不自动触发。
from bisect import bisect_left
from copy import deepcopy


def project_existing_key_segments(vocal):
    # 新曲慢拍生成与转调标签同步：新增仅复制调号元数据，已确认音高、字位、时间轴和演奏事件不改。
    result = deepcopy(vocal)
    sections = result.get('notation', {}).get('key_segments', [])
    if not sections:
        return result
    timeline = result.get('timing', {}).get('measure_timeline', [])
    if not result.get('time_only_revision') or not timeline:
        raise ValueError('调号投影必须使用已明确修订的拍轴和实际小节表')
    starts = [m['start_tick'] for m in timeline]
    if starts != sorted(set(starts)):
        raise ValueError('实际小节首拍不是严格递增')
    audit = []
    for index, section in enumerate(sections):
        owner = section.get('first_character_index')
        notes = [n for n in result['quantized_notes'] if owner is not None and n.get('lyric_index') == owner]
        if not notes:
            raise ValueError('转调锚点缺少已归属的原歌词音符，不能沿用旧小节编号')
        performance = min(n['start_tick'] for n in notes)
        position = 0 if index == 0 else bisect_left(starts, performance)
        if position >= len(timeline):
            raise ValueError('转调后没有完整小节首拍，需复核调号写法')
        previous = deepcopy(section)
        measure = timeline[position]
        section.update(performance_start_tick=performance, start_tick=measure['start_tick'],
                       start_measure=measure['number'],
                       pickup_before_signature=bool(index and performance < measure['start_tick']))
        audit.append({'first_character_index': owner, 'before': previous, 'after': deepcopy(section)})
    result['time_only_key_projection'] = {'version': 1, 'basis': 'existing_lyric_ownership_and_actual_measure_timeline',
        'pitch_key_or_chord_recognition_called': False, 'changes': audit}
    return result
