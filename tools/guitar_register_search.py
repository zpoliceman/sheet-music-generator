"""保音持续按弦与整句八度衔接：后续用弦检查、候选分层及有界局部重规划。"""
from __future__ import annotations

# 保音持续按弦与整句八度衔接：新增通用搜索策略；不读取曲名、歌词或固定音乐位置。
from bisect import bisect_left, bisect_right
from collections import defaultdict

SEARCH_POLICY = {
    'version': 2, 'name': 'sustained_strings_lookahead_local_replanning',
    'lookahead_measures': 4, 'replan_measures': [2, 4],
    'local_width_multipliers': [4, 8], 'maximum_local_width': 1152,
    'preserve_all_note_ids_attacks_and_releases': True,
    # 保音持续按弦与整句八度衔接：新增真实横按／分指备选也属于版本化策略，旧工作候选验收不能沿用。
    'retain_barre_and_individual_finger_structures': True,
    'hard_maximum_fret': 12, 'automatic_high_fret_fallback': False,
    'failure_means': 'bounded_search_not_found_not_proven_impossible',
}


# 保音持续按弦与整句八度衔接：新增来源根音域的完整下降八度候选；不依赖先降一次的20品临时结果。
def source_octave_candidates(arrangement, notes=None):
    if arrangement['configuration'].get('source_register_input_version') != 2:
        return (0, -12, -24)
    from accompaniment_arrange import TUNING
    melody = [note['pitch_midi'] for note in (arrangement['notes'] if notes is None else notes)
              if note['role'] == 'instrumental_melody']
    maximum = max(melody, default=min(TUNING.values()))
    octaves = max(2, (maximum - min(TUNING.values())) // 12)
    return tuple(-12 * octave for octave in range(octaves + 1))


class RegisterSearch:
    # 保音持续按弦与整句八度衔接：新增每次规划独立上下文，历史重放不启用，缓存不写回音乐。
    # 歌词自动加载与伴随声部音区保护：修改前瞻接收同一初次音区约束，旧调用默认空约束。
    # def __init__(self, shared, arrangement, editable, phrases, ticks, maximum_fret, width):
    def __init__(self, shared, arrangement, editable, phrases, ticks, maximum_fret, width, companion_locks=None):
        self.companion_locks = companion_locks or {}
        self.arrangement = arrangement
        self.notes = {note['id']: note for note in arrangement['notes']}
        self.editable = editable
        self.phrase_for = {identity: phrase for phrase in phrases for identity in phrase['note_ids']}
        self.ticks = ticks
        self.width = width
        self.maximum_fret = maximum_fret
        self.bar = shared['statistics']['bar_ticks']
        self.attacks = sorted({note['start_tick'] for note in arrangement['notes']})
        self.active_at = {}
        self.future_cache = {}
        self.location_cache = {}
        self.checkpoints = {}
        self.failed_counts = defaultdict(int)
        self.windows = []
        self.recoveries = []
        self.stats = {'future_checks': 0, 'future_cache_hits': 0, 'future_rejected': 0,
                      'diverse_state_groups': 0}

    # 保音持续按弦与整句八度衔接：新增后续持续占弦必要条件；只排除已证实连瞬时和弦也无法成立的状态。
    def future_possible(self, tick, active, shifts):
        from accompaniment_arrange import grip_info
        from guitar_capo import capo_at
        from guitar_instrumental_register import locations, role_order_valid
        active_key = tuple(sorted(active.items()))
        key = (tick, active_key, tuple(sorted(shifts.items())))
        if key in self.future_cache:
            self.stats['future_cache_hits'] += 1
            return self.future_cache[key]
        self.stats['future_checks'] += 1
        horizon = min(max((self.notes[identity]['end_tick'] for identity in active), default=tick),
                      tick + SEARCH_POLICY['lookahead_measures'] * self.bar)
        future_ticks = self.attacks[bisect_right(self.attacks, tick):bisect_left(self.attacks, horizon)]
        for future in future_ticks:
            held = {identity: loc for identity, loc in active.items() if self.notes[identity]['end_tick'] > future}
            if not held:
                continue
            if future not in self.active_at:
                self.active_at[future] = tuple(note for note in self.notes.values()
                                              if note['start_tick'] <= future < note['end_tick'])
            flexible = [note for note in self.active_at[future] if note['start_tick'] > tick]
            capo = capo_at(self.arrangement, future)
            choices = []
            for note in flexible:
                phrase = self.phrase_for.get(note['id'])
                domain = ((shifts[phrase['id']],) if phrase and phrase['id'] in shifts else
                          tuple(phrase.get('octave_candidates', (0, -12, -24))) if phrase else (0,))
                options = []
                for shift in domain:
                    location_key = (note['id'], capo, shift)
                    if location_key not in self.location_cache:
                        self.location_cache[location_key] = locations(
                            note, capo, shift, self.maximum_fret, self.editable,
                            # 歌词自动加载与伴随声部音区保护：新增完整前瞻同样不能抬高已保护伴随音。
                            self.arrangement['configuration'].get('instrumental_register_voicing_version', 1),
                            self.companion_locks.get(note['id']))
                    options.extend((loc, phrase['id'] if phrase else None, shift)
                                   for loc in self.location_cache[location_key])
                choices.append((note, tuple(options)))
            choices.sort(key=lambda row: (len(row[1]), row[0]['id']))

            # 保音持续按弦与整句八度衔接：新增不删音的局部组合检验，未来未知指法保持乐观，不把近似检查当充分证明。
            def possible(index, occupied, known_shifts):
                if index == len(choices):
                    return True
                note, options = choices[index]
                used_strings = {loc[0] for loc in occupied.values()}
                for loc, phrase_id, shift in options:
                    if loc[0] in used_strings or (phrase_id in known_shifts and known_shifts[phrase_id] != shift):
                        continue
                    combined = {**occupied, note['id']: loc}
                    if not role_order_valid(combined, self.notes):
                        continue
                    if grip_info({value[0]: value[1] for value in combined.values()}) is None:
                        continue
                    next_shifts = {**known_shifts, phrase_id: shift} if phrase_id else known_shifts
                    if possible(index + 1, combined, next_shifts):
                        return True
                return False

            # 保音持续按弦与整句八度衔接：新增换夹后的实体品位换算，持续音不得因相对品数混用而被误判。
            from accompaniment_arrange import TUNING
            held = {identity: (loc[0], loc[2] - TUNING[loc[0]] - capo, loc[2], loc[3])
                    for identity, loc in held.items()}
            # 保音持续按弦与整句八度衔接：修改偏好范围，仅可编配器乐受4品试探限制；原唱段固定音不被误拒绝。
            # if any(not 0 <= loc[1] <= self.maximum_fret for loc in held.values()) or not possible(0, held, shifts):
            if any(loc[1] < 0 or identity in self.editable and loc[1] > self.maximum_fret
                   for identity, loc in held.items()) or not possible(0, held, shifts):
                self.future_cache[key] = False
                self.stats['future_rejected'] += 1
                return False
        self.future_cache[key] = True
        return True

    # 保音持续按弦与整句八度衔接：新增局部搜索检查点，回看时恢复真实持续音与手指，而非只恢复拍号或手位。
    def remember(self, index, nodes, previous_tick):
        self.checkpoints[index] = (list(nodes), previous_tick)

    # 保音持续按弦与整句八度衔接：新增只在失败附近扩展候选预算；上限和音符时值始终不变。
    def active_width(self, index):
        return max([self.width] + [width for start, end, width in self.windows if start <= index <= end])

    # 保音持续按弦与整句八度衔接：新增按持续弦位和按指关系分层，同一占弦的细微图式差异不能挤光另一条路线。
    def select(self, ranked, index):
        width = self.active_width(index)
        next_tick = self.ticks[index + 1] if index + 1 < len(self.ticks) else self.ticks[index] + 1
        buckets = defaultdict(list)
        for candidate in ranked:
            sustained = []
            for identity, loc in sorted(candidate['active'].items()):
                if self.notes[identity]['end_tick'] <= next_tick:
                    continue
                finger = next((i for i, unit in enumerate(candidate['fingers']) if (loc[0], loc[1]) in unit), -1)
                sustained.append((identity, loc, finger))
            signature = (tuple(sorted(candidate['shifts'].items())), tuple(sustained))
            buckets[signature].append(candidate)
        self.stats['diverse_state_groups'] += len(buckets)
        # 保音持续按弦与整句八度衔接：新增轮流保留组内手位，先选不同持续占弦再填同组细微变体。
        selected = []
        queues = []
        for bucket in buckets.values():
            by_position = {}
            for candidate in bucket:
                by_position.setdefault(candidate['position'], candidate)
            primary = list(by_position.values())
            used = {id(candidate) for candidate in primary}
            queues.append(primary + [candidate for candidate in bucket if id(candidate) not in used])
        for level in range(width):
            any_added = False
            for queue in queues:
                if level < len(queue):
                    selected.append(queue[level])
                    any_added = True
                    if len(selected) == width:
                        return selected
            if not any_added:
                break
        return selected

    # 保音持续按弦与整句八度衔接：新增有界局部重新求解，恢复窗口前状态，必要时沿长音和自然乐句起点扩展。
    def recover(self, failed_index, nodes):
        tick = self.ticks[failed_index]
        attempt = self.failed_counts[tick]
        # 保音持续按弦与整句八度衔接：新增4品仅偏好试探，局部重规划集中在硬12品阶段，避免把偏好误作硬要求。
        if self.maximum_fret < SEARCH_POLICY['hard_maximum_fret']:
            return None
        if attempt >= len(SEARCH_POLICY['replan_measures']) or failed_index == 0:
            return None
        self.failed_counts[tick] += 1
        begin = tick - SEARCH_POLICY['replan_measures'][attempt] * self.bar
        for node in nodes:
            for identity in node['active']:
                begin = min(begin, self.notes[identity]['start_tick'])
            for phrase in self.phrase_for.values():
                if phrase['id'] in node['shifts']:
                    begin = min(begin, phrase['start_tick'])
        # 保音持续按弦与整句八度衔接：新增跨窗延音闭包，不在音中途截断或强换弦以伪造局部成功。
        while True:
            crossing = [note['start_tick'] for note in self.notes.values()
                        if note['start_tick'] < begin < note['end_tick']]
            earlier = min([begin] + crossing)
            if earlier == begin:
                break
            begin = earlier
        start = max(0, bisect_left(self.ticks, begin))
        available = [index for index in self.checkpoints if index <= start]
        if not available:
            return None
        start = max(available)
        restored, previous_tick = self.checkpoints[start]
        end = bisect_right(self.ticks, tick + self.bar * 2)
        width = min(SEARCH_POLICY['maximum_local_width'],
                    self.width * SEARCH_POLICY['local_width_multipliers'][attempt])
        self.windows.append((start, end, width))
        self.recoveries.append({'failed_tick': tick, 'restart_tick': self.ticks[start],
                                'end_tick': self.ticks[min(end, len(self.ticks) - 1)],
                                'local_beam_width': width, 'attempt': attempt + 1,
                                'notes_or_releases_changed': False})
        for index in list(self.checkpoints):
            if index > start:
                del self.checkpoints[index]
        return start, list(restored), previous_tick

    # 保音持续按弦与整句八度衔接：新增实际策略执行证据，失败仍只报告有限搜索未找到。
    def report(self):
        return {'policy': dict(SEARCH_POLICY), 'statistics': dict(self.stats),
                'local_replanning': list(self.recoveries),
                'failure_is_impossibility_proof': False}
