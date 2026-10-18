"""慢拍单位与两曲最小修订：延音规整后复核既有器乐和弦图，不把图示变成额外按弦。"""
# 慢拍单位与两曲最小修订：新增仅撤回造成实际换把失败的器乐整副指型，音符与和弦标记保持。
from copy import deepcopy
from guitar_grip_policy import grip_position_path


def reconcile_instrumental_charts(guitar, vocal):
    # 慢拍单位与两曲最小修订：新增沿用既有数字TAB后备语义；唱段图式由稳定右手实际配音处理。
    result = deepcopy(guitar); removed = []
    for _ in range(len(guitar.get('fingering_diagrams', [])) + 1):
        check = grip_position_path(result, vocal)
        if check['valid']:
            result['hand_positions'] = check['positions']
            result['grip_hand_positions'] = deepcopy(check['positions'])
            break
        chart = next((d for d in result.get('fingering_diagrams', []) if d['id'] == check.get('chart_id')), None)
        if chart is None:
            break
        a, b = chart['start_tick'], chart['end_tick']
        active = [n for n in result['notes'] if n['start_tick'] < b and n['end_tick'] > a]
        if not active or any(n.get('section') == 'vocal' and n.get('role') != 'instrumental_melody' for n in active):
            break
        result['fingering_diagrams'] = [d for d in result['fingering_diagrams'] if d['id'] != chart['id']]
        regions = []
        for region in result.get('notation_regions', []):
            x, y = region['start_tick'], region['end_tick']
            if x >= b or y <= a:
                regions.append(region); continue
            if x < a:
                regions.append({**deepcopy(region), 'end_tick': a})
            middle = {**deepcopy(region), 'start_tick': max(x, a), 'end_tick': min(y, b),
                      'mode': 'solo_tab', 'reason': 'preserved_sustain_requires_actual_instrumental_fingering'}
            middle.pop('common_grip_id', None)
            regions.append(middle)
            if y > b:
                regions.append({**deepcopy(region), 'id': region['id'] + '_after_local_grip', 'start_tick': b})
        result['notation_regions'] = regions
        removed.append({'chart': chart, 'failure': check, 'actual_notes_unchanged': True,
                        'display': 'numeric_tab_preserves_all_played_frets'})
    if result['notes'] != guitar['notes']:
        raise ValueError('器乐指型显示调整不得改变实际音符')
    return result, {'removed_instrumental_charts': removed, 'actual_notes_unchanged': True,
                    'hand_path': {k: v for k, v in check.items() if k != 'positions'}}
