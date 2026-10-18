"""原声覆盖与选音归属通用修复：保留用户认可段落，同时完整核验新旧音乐来源。"""
# 原声覆盖与选音归属通用修复：新增来源绑定的通用段落保留层；区间由外部用户复核提供，不由歌曲名推断。
from copy import deepcopy
from functools import lru_cache
from pathlib import Path
from score_export import read_json, save_json, sha256
from guitar_instrumental_register import fingerprint

KEY = 'approved_section_preservation'


def snapshot(path, digest):
    if sha256(path) != digest:
        raise ValueError('认可段落的原工程／复核清单已改变。')
    return cached_snapshot(str(path), digest)


@lru_cache(maxsize=8)
def cached_snapshot(path, digest):
    return read_json(path)


def intersect(note, ranges):
    return any(note['start_tick'] < b and note['end_tick'] > a for a, b in ranges)


# 原声覆盖与选音归属通用修复：新增完整持续音边界保护，认可段开始前已经弹响的音不能被截断。
def reviewed_ranges(old, review):
    ranges = []
    for section in review['approved_sections']:
        a, b = section['start_tick'], section['end_tick']
        if not isinstance(a, int) or not isinstance(b, int) or not 0 <= a < b <= old['accepted_vocal_project']['statistics']['total_ticks']:
            raise ValueError('认可段落的拍位范围无效。')
        # 原声覆盖与选音归属通用修复：新增认可范围起点对齐既有真实音乐边界；原声分段点不应制造22tick等虚假休止。
        boundaries = {0}
        for arrangement in old['arrangements'].values():
            for note in arrangement['notes']:
                boundaries.update((note['start_tick'], note['end_tick']))
        for chord in old['shared_analysis'].get('arranged_harmony', old['shared_analysis']['harmony']):
            boundaries.update((chord['start_tick'], chord['end_tick']))
        a = max(t for t in boundaries if t <= a)
        held = [n for arrangement in old['arrangements'].values() for n in arrangement['notes']
                if n['start_tick'] < a < n['end_tick']]
        a = min([a] + [n['start_tick'] for n in held])
        ranges.append((a, b))
    ranges.sort()
    if not ranges or any(b > c for (a, b), (c, d) in zip(ranges, ranges[1:])):
        raise ValueError('认可段落范围为空或相互重叠。')
    return ranges


def outside_chords(chords, ranges):
    result = []
    for chord in chords:
        pieces = [(chord['start_tick'], chord['end_tick'])]
        for a, b in ranges:
            pieces = [(x, y) for left, right in pieces for x, y in
                      ((left, min(right, a)), (max(left, b), right)) if y > x] if any(
                          left < b and right > a for left, right in pieces) else pieces
        for i, (a, b) in enumerate(pieces):
            item = deepcopy(chord); item.update(start_tick=a, end_tick=b)
            if i:
                item['id'] += '.outside_' + str(i)
            result.append(item)
    return result


# 原声覆盖与选音归属通用修复：新增确定合并，音高／八度／弦品／力度／持续音全部照原认可音乐保留。
def merge(base, old, review):
    from phrase_harmony_plan import arrangement_view
    from accompaniment_analysis import SongClock
    shared = deepcopy(base['shared_analysis']); vocal = deepcopy(base['accepted_vocal_project'])
    if (review.get('version') != 1 or base['shared_analysis']['input_binding'] != old['shared_analysis']['input_binding']
            or vocal['timing'] != old['accepted_vocal_project']['timing']
            or vocal['statistics']['total_ticks'] != old['accepted_vocal_project']['statistics']['total_ticks']
            or set(base['arrangements']) != set(old['arrangements'])):
        raise ValueError('认可段落保留要求同源、同拍轴和相同乐器范围。')
    ranges = reviewed_ranges(old, review); clock = SongClock(vocal)
    chords = outside_chords(arrangement_view(shared, vocal)['harmony'], ranges)
    mapping = {}
    for chord in arrangement_view(old['shared_analysis'], old['accepted_vocal_project'])['harmony']:
        for i, (a, b) in enumerate(ranges):
            left, right = max(a, chord['start_tick']), min(b, chord['end_tick'])
            if left < right:
                item = deepcopy(chord); identity = 'approved_' + str(i) + '_' + chord['id']
                mapping[chord['id']] = identity
                item.update(id=identity, start_tick=left, end_tick=right)
                chords.append(item)
    for h in chords:
        h.update(start_seconds=clock.seconds(h['start_tick']), end_seconds=clock.seconds(h['end_tick']))
    arrangements = deepcopy(base['arrangements'])
    for name, arrangement in arrangements.items():
        if arrangement['configuration'].get('capo_segments') != old['arrangements'][name]['configuration'].get('capo_segments'):
            raise ValueError('认可段落的实际变调夹配置不一致。')
        kept = [n for n in arrangement['notes'] if not intersect(n, ranges)]
        identities = {n['id'] for n in kept}; approved = []
        for note in old['arrangements'][name]['notes']:
            if not intersect(note, ranges):
                continue
            n = deepcopy(note)
            if n['id'] in identities:
                n['id'] = 'approved_' + n['id']
            identities.add(n['id'])
            if n.get('chord_id') in mapping:
                n['chord_id'] = mapping[n['chord_id']]
            approved.append(n)
        arrangement['notes'] = sorted(kept + approved, key=lambda n: (n['start_tick'], n['id']))
        for field in ('attack_events', 'pedal'):
            def in_range(row):
                tick = row.get('start_tick', row.get('tick', 0))
                return any(a <= tick < b for a, b in ranges)
            values = [deepcopy(e) for e in arrangement.get(field, []) if not in_range(e)]
            for row in old['arrangements'][name].get(field, []):
                if in_range(row):
                    row = deepcopy(row)
                    if row.get('chord_id') in mapping:
                        row['chord_id'] = mapping[row['chord_id']]
                    values.append(row)
            if field in arrangement:
                arrangement[field] = sorted(values, key=lambda e: e.get('start_tick', e.get('tick', 0)))
    return shared, vocal, arrangements, sorted(chords, key=lambda h: h['start_tick']), ranges


# 原声覆盖与选音归属通用修复：新增通用合并入口，先验证原复核文件的工程SHA，再保存新来源快照。
def preserve_sections(shared, vocal, arrangements, review_path, cache):
    review_path = Path(review_path).resolve(); review = read_json(review_path)
    old = snapshot(review['source_project'], review['source_project_sha256'])
    base = {'shared_analysis': shared, 'accepted_vocal_project': vocal, 'arrangements': arrangements}
    stage = Path(cache).resolve() / ('approved_sections_base_' + fingerprint(base)[:20] + '.json')
    stage.parent.mkdir(parents=True, exist_ok=True)
    if not stage.exists():
        save_json(stage, base)
    elif read_json(stage) != base:
        raise ValueError('认可段落保留的原阶段不能覆盖。')
    merged, updated, outputs, chords, ranges = merge(base, old, review)
    info = {'version': 1, 'base_project': str(stage), 'base_sha256': sha256(stage),
            'review_path': str(review_path), 'review_sha256': sha256(review_path),
            'source_project': review['source_project'], 'source_project_sha256': review['source_project_sha256'],
            # 原声覆盖与选音归属通用修复：修改，统一内存与JSON的区间表示，避免重读后比对不同。
            # 'ranges': ranges, 'harmony': chords, 'song_specific_rules': False}
            'ranges': [list(r) for r in ranges], 'harmony': chords, 'song_specific_rules': False}
    merged[KEY] = deepcopy(info)
    for arrangement in outputs.values():
        arrangement[KEY] = deepcopy(info)
    return merged, updated, outputs


def musical_signature(arrangement):
    # 原声覆盖与选音归属通用修复：新增真实音乐完整比对；手位／图式属于后续重算的显示数据。
    # 原声覆盖与选音归属通用修复：修改，旧音乐字段签名保留；当前来源账本也不能被伪换或删掉。
    # return {key: arrangement.get(key) for key in ('notes', 'configuration', 'attack_events', 'pedal')}
    return {key: arrangement.get(key) for key in ('notes', 'configuration', 'attack_events', 'pedal',
        'instrumental_source_backbone', 'instrumental_register', 'instrumental_flow', 'instrumental_expression',
        'phrase_harmony_performance', 'regular_rhythm', 'right_hand_patterns', 'source_rhythm_evidence', 'structure_stability')}


@lru_cache(maxsize=8)
def replay_parent(path, digest):
    from generate_accompaniment import load_edited_project
    load_edited_project(path)
    return True


# 原声覆盖与选音归属通用修复：新增每次检查所有实际来源依赖；昂贵算法重放缓存不能掩盖原音轨或中间来源改写。
def check_dependencies(projects):
    checked = {}
    def dependency(path, digest, descend=False):
        if not isinstance(path, str) or not isinstance(digest, str) or len(digest) != 64:
            return
        path = str(Path(path).resolve())
        if path in checked:
            if checked[path] != digest:
                raise ValueError('认可来源依赖的同一路径存在不同指纹。')
            return
        if sha256(path) != digest:
            raise ValueError('认可来源的音轨／分析／中间工程依赖已改变：' + path)
        checked[path] = digest
        if descend and Path(path).suffix.lower() == '.json':
            walk(snapshot(path, digest))
    def walk(value):
        if isinstance(value, list):
            for item in value:
                walk(item)
        elif isinstance(value, dict):
            if 'path' in value and 'sha256' in value:
                dependency(value['path'], value['sha256'])
            for key, item in value.items():
                if key == 'cache_dependencies' and isinstance(item, dict):
                    for path, digest in item.items():
                        dependency(path, digest)
                if isinstance(item, str) and key.endswith(('_path', '_project')):
                    digest = value.get(key + '_sha256') or value.get(key.rsplit('_', 1)[0] + '_sha256')
                    dependency(item, digest, descend=('project' in key or 'plan' in key or 'evidence' in key))
                if isinstance(item, (dict, list)):
                    walk(item)
    for project in projects:
        walk(project)
    return len(checked)


# 原声覆盖与选音归属通用修复：新增明确的来源分层校验，保留层不靠删除旧保护账本或降低可弹性门限。
def verified_base(shared, vocal, arrangements, replay=False):
    info = shared.get(KEY)
    if not info or info.get('version') != 1:
        raise ValueError('认可段落来源层缺失或版本不符。')
    base = snapshot(info['base_project'], info['base_sha256'])
    review = snapshot(info['review_path'], info['review_sha256'])
    old = snapshot(info['source_project'], info['source_project_sha256'])
    if review['source_project'] != info['source_project'] or review['source_project_sha256'] != info['source_project_sha256']:
        raise ValueError('认可段落复核和原工程绑定不符。')
    expected_shared, expected_vocal, expected_arrangements, chords, ranges = merge(base, old, review)
    from phrase_harmony_plan import arrangement_view
    active = deepcopy(shared); active.pop(KEY, None)
    if active.pop('_phrase_harmony_view', False):
        active['harmony'] = base['shared_analysis']['harmony']
    if (active != expected_shared or vocal != expected_vocal or info['harmony'] != chords
            or info['ranges'] != [list(r) for r in ranges]):
        raise ValueError('认可段落合并的时钟、共享证据或复核范围已改变。')
    for name, arrangement in arrangements.items():
        if arrangement.get(KEY) != info or musical_signature(arrangement) != musical_signature(expected_arrangements[name]):
            raise ValueError('认可段落或其它音乐被修改：' + name)
    if replay:
        # 原声覆盖与选音归属通用修复：新增新旧两个来源完整重放，哈希正确但音乐改写的伪源也不能通过。
        # 原声覆盖与选音归属通用修复：新增缓存算法结果之前先确认完整文件依赖，篡改任意层均拒绝。
        check_dependencies([base, old])
        replay_parent(info['base_project'], info['base_sha256'])
        replay_parent(info['source_project'], info['source_project_sha256'])
    return deepcopy(base)


def validate_chain(shared, vocal, arrangement, replay, validator):
    try:
        name = arrangement.get('instrument', 'guitar')
        if name not in ('guitar', 'piano'):
            name = 'guitar'
        base = verified_base(shared, vocal, {name: arrangement}, replay)
        result = validator(base['shared_analysis'], base['accepted_vocal_project'], base['arrangements'][name], replay=replay)
        return {**(result or {}), 'valid': bool((result or {'valid': True})['valid']),
                'errors': (result or {}).get('errors', []), 'approved_sections_verified': True}
    except (OSError, KeyError, ValueError) as exc:
        return {'valid': False, 'errors': ['approved_section_preservation_invalid:' + str(exc)]}


# 原声覆盖与选音归属通用修复：新增无显式人声参数的历史节奏来源适配；实际合并音乐仍完整比对。
def validate_rhythm_chain(shared, guitar, validator):
    try:
        info = shared[KEY]
        base = snapshot(info['base_project'], info['base_sha256'])
        verified_base(shared, base['accepted_vocal_project'], {'guitar': guitar})
        # 原声覆盖与选音归属通用修复：修改，节奏音必须按基础工程的实际共同和声验证，不能误读原声学候选表。
        # result = validator(base['shared_analysis'], base['arrangements']['guitar'])
        from phrase_harmony_plan import arrangement_view
        result = validator(arrangement_view(base['shared_analysis'],base['accepted_vocal_project']), base['arrangements']['guitar'])
        return {**(result or {}), 'valid': bool((result or {'valid': True})['valid']),
                'errors': (result or {}).get('errors', []), 'approved_sections_verified': True}
    except (OSError, KeyError, ValueError) as exc:
        return {'valid': False, 'errors': ['approved_section_rhythm_invalid:' + str(exc)]}
