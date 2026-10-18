"""结构稳定伴奏与人声合播：规整分解型的实际攻击格与混合时值。"""
# 结构稳定伴奏与人声合播：新增独立格点工具，—表示延续上一格而非新增拨弦。
def pattern_schedule(pattern):
    step = int(pattern['step_ticks']); slots = pattern['slots']
    active = [i for i, token in enumerate(slots) if token != '-']
    result = []
    for index, slot in enumerate(active):
        following = active[index + 1] if index + 1 < len(active) else len(slots)
        result.append({'slot': slot, 'offset': slot * step,
                       'duration': (following - slot) * step, 'token': slots[slot]})
    return result


# 结构稳定伴奏与人声合播：新增按实际位置取时值，混合型不能统一写成十六分。
def pattern_duration(pattern, slot):
    row = next((r for r in pattern_schedule(pattern) if r['slot'] == slot), None)
    return row['duration'] if row else int(pattern['step_ticks'])


# 结构稳定伴奏与人声合播：新增完整拍的候选核查，允许八分/十六分同梁而不容纳附点。
def validate_regular_pattern(pattern):
    rows = pattern_schedule(pattern); errors = []
    if not rows or rows[0]['offset'] != 0: errors.append('missing_first_beat_attack')
    for row in rows:
        if row['duration'] not in (120, 240, 480): errors.append('non_regular_duration')
        if row['offset'] // 480 != (row['offset'] + row['duration'] - 1) // 480:
            errors.append('slot_crosses_beat')
    return {'valid': not errors, 'errors': errors, 'attack_count': len(rows)}
