"""跨曲低音与强拍复用通用修复：完整终止乐句与有来源支持的和弦性质。"""
from copy import deepcopy
import math
import numpy as np
from accompaniment_analysis import CHORD_TYPES
from score_export import PPQ


# 跨曲低音与强拍复用通用修复：新增音乐终止边界，不把歌词短行/弱起或四小节排版直接当作乐句。
def phrase_ranges(shared, vocal):
    from phrase_harmony_plan import phrase_ranges as legacy_ranges
    bar = shared['statistics']['bar_ticks']; pulse = int(PPQ * 4 / shared['timing']['meter'][1])
    total = shared['statistics']['total_ticks']; result = []
    legacy = legacy_ranges(shared, vocal, source_aware=False)
    # 跨曲低音与强拍复用通用修复：新增完整唱段入口已有重复长句优先，不能用较弱和声终止证据拆散已一致的旋律。
    from phrase_harmony_plan import phrase_families
    long_families = [f for f in phrase_families(shared, vocal, legacy)
                     if len(f['members']) > 1 and all(p['start_tick'] % bar == p['end_tick'] % bar == 0
                     and p['end_tick']-p['start_tick'] >= 3*bar for p in f['members'])]
    preferred = [p for f in long_families for p in f['members']
                 if any(q['start_tick'] == math.ceil(s['start_tick']/bar)*bar for q in f['members']
                        for s in shared['sections'] if s['kind'] == 'vocal')]
    key_cuts = [s['start_tick'] for s in vocal.get('notation', {}).get('key_segments', [])[1:]]
    for section in shared['sections']:
        if section['kind'] != 'vocal':
            continue
        entry = math.ceil(section['start_tick'] / pulse) * pulse
        start = math.ceil(entry / bar) * bar; end = min(total, math.ceil(section['end_tick'] / bar) * bar)
        # 跨曲低音与强拍复用通用修复：新增弱起独立覆盖，后续完整音乐小节从真正首拍开始。
        if entry < min(start, end):
            result.append((entry, min(start, end), 'source_backed_pickup'))
        cadences = []
        for tick in range(start + bar, end, bar):
            ws = [w for w in shared['harmony_windows'] if tick <= w['start_tick'] < tick + bar]
            prior = [w for w in shared['harmony_windows'] if tick - bar <= w['start_tick'] < tick]
            if not ws or not prior:
                continue
            tonic = ws[0]['key']['tonic_pc']
            # 跨曲低音与强拍复用通用修复：修改，原只认根音会把主和弦转位经过误判成终止，保留旧条件。
            # held = sum(w['end_tick']-w['start_tick'] for w in ws if w['selected']['root_pc'] == tonic)
            held = sum(w['end_tick']-w['start_tick'] for w in ws
                       if w['selected']['root_pc'] == tonic and w['selected']['bass_pc'] == tonic)
            prepared = sum(w['end_tick']-w['start_tick'] for w in prior
                           if (w['selected']['root_pc']-tonic) % 12 in (5, 7))
            if held >= bar * .5 and prepared >= pulse:
                cadences.append(tick + bar)
        # 跨曲低音与强拍复用通用修复：新增至少两小节音乐跨度；无法识别终止时回退原音乐地标而非固定四小节。
        # 跨曲低音与强拍复用通用修复：修改，原只凭终止从首拍切分保留；已有完整重复段的边界同时参加。
        # cuts = [start]
        sealed = [p for p in preferred if start <= p['start_tick'] < p['end_tick'] <= end]
        cuts = sorted({start} | {p[k] for p in sealed for k in ('start_tick','end_tick')})
        for boundary in cadences:
            # 跨曲低音与强拍复用通用修复：修改，原只比较最后切点保留；按实际相邻边界处理并保护重复长句内部。
            # if boundary < end and boundary - cuts[-1] >= 2 * bar: cuts.append(boundary)
            left = max((x for x in cuts if x < boundary), default=start)
            if (boundary < end and boundary-left >= 2*bar
                    and not any(p['start_tick'] < boundary < p['end_tick'] for p in sealed)):
                cuts.append(boundary); cuts.sort()
        if len(cuts) == 1 and end - start > 8 * bar:
            cuts.extend(p['end_tick'] for p in legacy if start < p['end_tick'] < end and p['end_tick'] % bar == 0)
        cuts = sorted(set(cuts + [end] + [k for k in key_cuts if start < k < end]))
        result.extend((a, b, 'bass_harmony_cadence_and_complete_meter') for a, b in zip(cuts, cuts[1:]) if a < b)
    return [{'id': f'phrase_{i+1:03}', 'start_tick': a, 'end_tick': b,
             'measures': list(range(a//bar+1, math.ceil(b/bar)+1)), 'boundary_source': source}
            for i, (a, b, source) in enumerate(sorted(result))]


# 跨曲低音与强拍复用通用修复：新增只给真实持续性质音减轻复杂度惩罚，保留开放add9、m7、sus4的重要听感。
def source_scores(rows, candidates, legacy_scores):
    scores = legacy_scores.copy()
    for i, row in enumerate(rows):
        # 跨曲低音与强拍复用通用修复：修改，原跨换低音边界聚合会把下一和弦性质带入上一和弦。
        # neighborhood = rows[max(0, i-1):min(len(rows), i+2)]
        neighborhood = [r for r in rows[max(0, i-1):min(len(rows), i+2)]
                        if r is row or (r['bass'].sum() > .1 and row['bass'].sum() > .1
                                        and int(r['bass'].argmax()) == int(row['bass'].argmax()))]
        pooled = np.mean([r['chroma'] for r in neighborhood], axis=0)
        for j, (root, quality) in enumerate(candidates):
            intervals = CHORD_TYPES[quality]
            extras = max(0, len(intervals)-3)
            # 跨曲低音与强拍复用通用修复：新增来源支持的扩展音，弱噪声仍承担旧复杂度代价。
            extended = [pooled[(root+x) % 12] for x in intervals if x not in (0, 3, 4, 7)]
            if extended and min(extended) >= .08:
                scores[i, j] += .16*extras + {'add9': .28, 'm7': .04, 'sus4': .12}.get(quality, .04)
            third = (root + (3 if quality.startswith('m') else 4)) % 12
            # 跨曲低音与强拍复用通用修复：修改，原缺三音即罚会把开放G的省略拨弦写成G5，只有明确挂留四音支持才罚。
            # if quality in ('', 'm', '7', 'maj7') and pooled[third] < .065:
            if quality in ('', 'm', '7', 'maj7') and pooled[third] < .065 and pooled[(root+5)%12] >= .13:
                scores[i, j] -= .22
            if quality in ('5', 'sus2'):
                # 跨曲低音与强拍复用通用修复：新增开放基本指型先验；少弹三音本身不足以另立强力/挂二和弦。
                scores[i, j] -= .28 if quality == '5' else .18
            # 跨曲低音与强拍复用通用修复：新增强低音与根/性质证据共同支持，不能让平均复用压倒独立和声。
            if row['bass'].sum() > .1:
                scores[i, j] += .30 * row['bass'][root]
    return scores
