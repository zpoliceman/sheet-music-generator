"""通用段落强拍与乐句节奏修复：新增源音段的音乐结构，不以歌词内容识别重复。"""
from collections import defaultdict
from copy import deepcopy
import math
import statistics

VERSION = 1
POLICY = {'version': VERSION, 'minimum_units': 4, 'minimum_distinct_pitches': 3,
          'minimum_length_ratio': .65, 'pitch_tolerance': 1., 'minimum_pitch_support': .8,
          'maximum_rhythm_log_error': .48, 'phase_bin_quarters': .25,
          'phase_tolerance_quarters': .35, 'minimum_phase_witnesses': 2,
          'minimum_phase_support': .7, 'minimum_phase_change_quarters': .75,
          'section_gap_bars': 1., 'phase_prior': 'earliest_supported_musical_occurrence'}


# 通用段落强拍与乐句节奏修复：新增独立音乐单位；文字仅保留在审计，不参与匹配代价。
def source_units(pieces, characters, mapping, timing):
    by_word = defaultdict(list)
    for n in pieces:
        if n.get('lyric_index') is not None and not n.get('grace'):
            by_word[n['lyric_index']].append(n)
    origin = timing.get('score_start_quarter', 0.)
    q = lambda s: mapping.seconds_to_quarters(s)-origin
    output = []
    for c in characters:
        notes = sorted(by_word.get(c['index'], []), key=lambda n:n['start_seconds'])
        if not notes:
            continue
        core = max(notes, key=lambda n:(n.get('role')=='main', n['end_seconds']-n['start_seconds']))
        begin, end = notes[0]['start_seconds'], max(n['end_seconds'] for n in notes)
        phones = [p for p in c.get('phonemes', []) if not p.get('skipped')]
        phone = c.get('start_seconds')
        phone = begin if phone is None else float(phone)
        output.append({'index':c['index'], 'line':c.get('line_index', 0), 'text':c.get('text',''),
                       'pitch':core['pitch_midi'], 'start_seconds':begin, 'end_seconds':end,
                       'onset_seconds':phone, 'onset_q':q(phone), 'voiced_q':q(begin),
                       'end_q':q(end), 'notes':notes,
                       'phoneme_span':None if c.get('end_seconds') is None else q(c['end_seconds'])-q(phone),
                       'has_phonemes':bool(phones)})
    return sorted(output, key=lambda w:w['start_seconds'])


# 通用段落强拍与乐句节奏修复：新增音乐单位序列动态对齐，容许一个字多音和局部增删。
def align_motifs(left, right):
    n, m = len(left), len(right)
    if min(n,m)<POLICY['minimum_units'] or min(n,m)/max(n,m)<POLICY['minimum_length_ratio']:
        return None
    if min(len({w['pitch'] for w in left}),len({w['pitch'] for w in right}))<POLICY['minimum_distinct_pitches']:
        return None
    candidates = {b['pitch']-a['pitch'] for a,b in zip(left[:3],right[:3])}
    results = []
    for transpose in sorted(candidates):
        table = [[(math.inf, ()) for j in range(m+1)] for i in range(n+1)]
        table[0][0] = (0., ())
        for i in range(n+1):
            for j in range(m+1):
                cost, pairs = table[i][j]
                if i<n and j<m:
                    delta = abs(right[j]['pitch']-left[i]['pitch']-transpose)
                    value = cost+min(3.,delta/1.5)
                    if value<table[i+1][j+1][0]:table[i+1][j+1]=(value,pairs+((i,j),))
                if i<n and cost+1.3<table[i+1][j][0]:table[i+1][j]=(cost+1.3,pairs)
                if j<m and cost+1.3<table[i][j+1][0]:table[i][j+1]=(cost+1.3,pairs)
        cost, pairs = table[n][m]
        if len(pairs)<max(POLICY['minimum_units'],math.ceil(.75*min(n,m))):continue
        transpose = statistics.median(right[j]['pitch']-left[i]['pitch'] for i,j in pairs)
        support = sum(abs(right[j]['pitch']-left[i]['pitch']-transpose)<=POLICY['pitch_tolerance'] for i,j in pairs)/max(n,m)
        if support<POLICY['minimum_pitch_support']:continue
        ratios = []
        for (a,b),(c,d) in zip(pairs,pairs[1:]):
            x = left[c]['onset_seconds']-left[a]['onset_seconds']
            y = right[d]['onset_seconds']-right[b]['onset_seconds']
            if x>.05 and y>.05:ratios.append(math.log(y/x))
        center = statistics.median(ratios) if ratios else 0.
        rhythm = statistics.median(abs(x-center) for x in ratios) if ratios else 0.
        if rhythm>POLICY['maximum_rhythm_log_error']:continue
        results.append({'pairs':pairs, 'transpose':transpose, 'pitch_support':support,
                        'rhythm_log_error':rhythm, 'duration_ratio':math.exp(center),
                        'cost':cost/max(n,m)+rhythm})
    return min(results, key=lambda r:(-r['pitch_support'],r['cost'])) if results else None


# 通用段落强拍与乐句节奏修复：新增环形相位聚合，二拍附近跨正负边界不会错误相互抵消。
def phase_vote(values, bar):
    if not values:return None
    step = POLICY['phase_bin_quarters']
    centers = [i*step for i in range(round(bar/step))]
    distance = lambda a,b:abs((a-b+bar/2)%bar-bar/2)
    center = min(centers, key=lambda c:(-sum(distance(v,c)<=POLICY['phase_tolerance_quarters'] for v in values),
                                      sum(min(distance(v,c),1.) for v in values),c))
    support = sum(distance(v,center)<=POLICY['phase_tolerance_quarters'] for v in values)/len(values)
    return {'phase':center, 'support':support, 'values':list(values)}


# 通用段落强拍与乐句节奏修复：新增源发声空档分段；短呼吸不切成新段，不强制每四小节一句。
def source_sections(units, bar):
    sections = []
    for unit in units:
        if not sections or unit['voiced_q']-sections[-1]['units'][-1]['end_q']>=bar*POLICY['section_gap_bars']:
            sections.append({'id':len(sections), 'units':[]})
        sections[-1]['units'].append(unit)
    for section in sections:
        section.update(first_index=section['units'][0]['index'],last_index=section['units'][-1]['index'],
                       start_seconds=section['units'][0]['start_seconds'],
                       end_seconds=max(w['end_seconds'] for w in section['units']))
    return sections


# 通用段落强拍与乐句节奏修复：新增跨歌词的短句/段落索引，输出匹配证据及首拍候选而非人工答案。
def infer_form(pieces, characters, mapping, timing, bar_quarters):
    units = source_units(pieces,characters,mapping,timing)
    by_line = defaultdict(list)
    for unit in units:by_line[unit['line']].append(unit)
    lines = [{'line':i,'units':ws,'start_seconds':ws[0]['start_seconds']} for i,ws in sorted(by_line.items())]
    sections = source_sections(units,bar_quarters)
    section_for = {w['index']:s['id'] for s in sections for w in s['units']}
    matches = []
    for j,target in enumerate(lines):
        found = []
        for i,ref in enumerate(lines[:j]):
            if target['start_seconds']-ref['start_seconds']<2.:continue
            match = align_motifs(ref['units'],target['units'])
            if match:found.append((i,match))
        if not found:continue
        i,match = min(found,key=lambda p:(-p[1]['pitch_support'],round(p[1]['cost'],1),p[0]))
        ref = lines[i]
        phases = [target['units'][b]['onset_q']-ref['units'][a]['onset_q'] for a,b in match['pairs']]
        vote = phase_vote(phases,bar_quarters)
        matches.append({'reference_line':ref['line'],'target_line':target['line'],
                        'reference_section':section_for[ref['units'][0]['index']],
                        'target_section':section_for[target['units'][0]['index']],
                        'reference_indices':[ref['units'][a]['index'] for a,b in match['pairs']],
                        'target_indices':[target['units'][b]['index'] for a,b in match['pairs']],
                        **{k:deepcopy(v) for k,v in match.items() if k!='pairs'}, 'phase_vote':vote})
    decisions = []
    for section in sections:
        witnesses = [m for m in matches if m['target_section']==section['id'] and m['reference_section']<section['id']
                     and m['phase_vote']['support']>=POLICY['minimum_phase_support']]
        # 通用段落强拍与乐句节奏修复：修改，保留原相对投票；多次过门要累加参照段已经确认的相位。
        # vote = phase_vote([m['phase_vote']['phase'] for m in witnesses],bar_quarters)
        vote = phase_vote([m['phase_vote']['phase']+decisions[m['reference_section']]['phase_delta_quarters']
                           for m in witnesses],bar_quarters)
        phase = vote['phase'] if vote else 0.
        # 通用段落强拍与乐句节奏修复：修改，保留原半小节试验；任何拍号按其大拍支持一拍/两拍等相位。
        # delta = round(phase/(bar_quarters/2))*(bar_quarters/2) if bar_quarters else 0.
        from rhythm_notation import MeterTree
        tree = MeterTree.from_meter(timing['meter'],timing.get('beat_groups'))
        beat = tree.groups[0]*tree.unit_ticks/480
        delta = round(phase/beat)*beat if bar_quarters else 0.
        # 通用段落强拍与乐句节奏修复：修改，原单次环绕保留；连续过门相位沿上一段展开，缺证据不撤销已确认的累计修正。
        # if delta>=bar_quarters:delta-=bar_quarters
        # if delta>bar_quarters/2:delta-=bar_quarters
        previous_delta=decisions[-1]['phase_delta_quarters'] if decisions else 0.
        difference=(delta-previous_delta+bar_quarters/2)%bar_quarters-bar_quarters/2
        if abs(difference+bar_quarters/2)<1e-8:difference=bar_quarters/2
        delta=previous_delta+difference
        trusted = (len(witnesses)>=POLICY['minimum_phase_witnesses'] and vote and
                   vote['support']>=POLICY['minimum_phase_support'])
        decisions.append({'section':section['id'],'first_index':section['first_index'],'last_index':section['last_index'],
                          'start_seconds':section['start_seconds'],'end_seconds':section['end_seconds'],
                          # 通用段落强拍与乐句节奏修复：修改，原不足证据归零保留；不足证据延续上一累计相位。
                          # 'phase_delta_quarters':delta if trusted else 0., 'witness_count':len(witnesses),
                          'phase_delta_quarters':delta if trusted else previous_delta, 'witness_count':len(witnesses),
                          'phase_support':vote['support'] if vote else 0.,
                          'witness_lines':[m['target_line'] for m in witnesses],
                          'status':'supported_phase_change' if trusted and abs(delta-previous_delta)>=POLICY['minimum_phase_change_quarters'] else 'retain_acoustic_clock'})
    return {'version':VERSION,'policy':deepcopy(POLICY),'matches':matches,'sections':decisions,
            'text_used_for_matching':False,'source_note_count':len(pieces),'units':units,'lines':lines}
