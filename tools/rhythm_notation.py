"""乐句节奏与音值分组：新增共享拍号层级与音符、休止规范拆写。"""
from __future__ import annotations
from dataclasses import dataclass

PPQ = 480
DURATIONS = ((1920, 'whole', 0), (1440, 'half', 1), (960, 'half', 0),
             (720, 'quarter', 1), (480, 'quarter', 0), (360, 'eighth', 1),
             (240, 'eighth', 0), (180, '16th', 1), (120, '16th', 0),
             (90, '32nd', 1), (60, '32nd', 0), (45, '64th', 1), (30, '64th', 0))


# 乐句节奏与音值分组：新增按实际大拍表示复合拍，禁止把6/8的每一拍当作四分。
@dataclass(frozen=True)
class MeterTree:
    numerator: int
    denominator: int
    groups: tuple[int, ...]

    @classmethod
    def from_meter(cls, meter, groups=None):
        n, d = map(int, meter)
        if n <= 0 or d not in (2, 4, 8, 16):
            raise ValueError('拍号不受支持。')
        if groups is None:
            groups = (3,) * (n // 3) if d == 8 and n >= 6 and not n % 3 else (1,) * n
        groups = tuple(map(int, groups))
        if any(g <= 0 for g in groups) or sum(groups) != n:
            raise ValueError('大拍分组与拍号不符。')
        return cls(n, d, groups)

    @property
    def unit_ticks(self):
        return PPQ * 4 // self.denominator

    @property
    def bar_ticks(self):
        return self.numerator * self.unit_ticks

    @property
    def boundaries(self):
        values = [0]
        for group in self.groups:
            values.append(values[-1] + group * self.unit_ticks)
        return tuple(values)

    def beat_limits(self, tick):
        base = tick // self.bar_ticks * self.bar_ticks
        offset = tick - base
        for a, b in zip(self.boundaries, self.boundaries[1:]):
            if a <= offset < b:
                return base + a, base + b
        raise ValueError('拍点超出小节。')


# 乐句节奏与音值分组：新增从非大拍起点先显露拍界，完整长音按层级合并，附点在拍内保留。
def split_rhythm(start, end, meter=(4, 4), groups=None, rest=False):
    tree = MeterTree.from_meter(meter, groups)
    start, end = int(start), int(end)
    if start < 0 or end < start:
        raise ValueError('时值区间无效。')
    output = []
    while start < end:
        bar_start = start // tree.bar_ticks * tree.bar_ticks
        bar_end = bar_start + tree.bar_ticks
        beat_start, beat_end = tree.beat_limits(start)
        remaining = min(end, bar_end) - start
        choice = None
        for length, kind, dots in DURATIONS:
            if length > remaining:
                continue
            if length <= beat_end - start:
                choice = (length, kind, dots)
                break
            # 乐句节奏与音值分组：新增整拍长音合法合并；非整拍起点及未对齐的大时值不得掩盖拍界。
            finish = start + length - bar_start
            aligned = start == beat_start and finish in tree.boundaries
            whole_bar = start == bar_start and length == tree.bar_ticks
            power_aligned = not dots and (start - bar_start) % length == 0
            compound_aligned = dots and length % (beat_end - beat_start) == 0 and (start - bar_start) % length == 0
            if aligned and (whole_bar or power_aligned or compound_aligned):
                choice = (length, kind, dots)
                break
        if choice is None:
            raise ValueError(f'时值无法规范表示：{start}至{end}，需要明确连音或细网格。')
        length, kind, dots = choice
        output.append({'start_tick': start, 'duration_ticks': length, 'type': kind, 'dots': dots})
        start += length
    return output


# 乐句节奏与音值分组：新增按实际碎片检查覆盖与拍界，不能只校验每小节总和。
def validate_grouping(events, meter, groups=None):
    errors = []
    checked = 0
    tree = MeterTree.from_meter(meter, groups)
    for event in events:
        if event.get('grace'):
            continue
        begin = event['start_tick']
        end = begin + event['duration_ticks']
        # 通用段落强拍与乐句节奏修复：修改，保留普通拆写核验；连音按有效时长和明确窗口核验。
        # expected = split_rhythm(begin, end, meter, groups, event.get('pitch_midi') is None)
        tuplet=event.get('tuplet')
        if tuplet:
            expected=split_rhythm_tuplets(begin,end,meter,groups,event.get('pitch_midi') is None,[tuplet])
        else:
            expected = split_rhythm(begin, end, meter, groups, event.get('pitch_midi') is None)
        if len(expected) != 1 or any(expected[0][k] != event[k] for k in ('duration_ticks', 'type', 'dots')):
            errors.append('noncanonical_rhythmic_fragment:' + str(event.get('id', begin)))
        checked += 1
    # 通用段落强拍与乐句节奏修复：新增整组覆盖核验；单片时值正确不能代替完整三等分窗口。
    tuplet_groups={}
    for event in events:
        if event.get('tuplet'):tuplet_groups.setdefault(event['tuplet']['id'],[]).append(event)
    for identity,values in tuplet_groups.items():
        values=sorted(values,key=lambda e:e['start_tick']);g=values[0]['tuplet']
        if (values[0]['start_tick']!=g['start_tick'] or values[-1]['start_tick']+values[-1]['duration_ticks']!=g['end_tick']
                or any(a['start_tick']+a['duration_ticks']!=b['start_tick'] for a,b in zip(values,values[1:]))):
            errors.append('incomplete_tuplet_group:'+identity)
    return {'valid': not errors, 'errors': errors, 'checked_fragments': checked,
            'meter': list(meter), 'beat_groups': list(tree.groups),
            'notes_and_rests_checked': True}


# 通用段落强拍与乐句节奏修复：新增显式3:2窗口的规范音值；二等分区域仍用原拆写规则。
def split_rhythm_tuplets(start,end,meter=(4,4),groups=None,rest=False,tuplets=()):
    start,end=int(start),int(end)
    if start<0 or end<start:raise ValueError('连音区间无效。')
    ordered=sorted(tuplets,key=lambda g:g['start_tick'])
    tree=MeterTree.from_meter(meter,groups)
    for i,g in enumerate(ordered):
        a,b=g['start_tick'],g['end_tick']
        if (g['actual_notes']!=3 or g['normal_notes']!=2 or a>=b or tree.beat_limits(a)!=(a,b)
                or i and ordered[i-1]['end_tick']>a):raise ValueError('连音窗口必须完整且不能重叠或跨大拍。')
    output=[];at=start
    while at<end:
        active=next((g for g in ordered if g['start_tick']<=at<g['end_tick']),None)
        if not active:
            stop=min([end]+[g['start_tick'] for g in ordered if g['start_tick']>at])
            output.extend(split_rhythm(at,stop,meter,groups,rest));at=stop;continue
        stop=min(end,active['end_tick'])
        while at<stop:
            choice=None
            for nominal,kind,dots in DURATIONS:
                if nominal*2%3:continue
                length=nominal*2//3
                if length<=stop-at:
                    choice=(length,kind,dots);break
            if not choice:raise ValueError('连音内转音不能用当前精确网格表达。')
            length,kind,dots=choice
            output.append({'start_tick':at,'duration_ticks':length,'type':kind,'dots':dots,
                           'tuplet':{k:active[k] for k in ('id','start_tick','end_tick','actual_notes','normal_notes')}})
            at+=length
    return output


# 乐句节奏与音值分组：新增由同一大拍树派生XML横梁，短休止可在拍内连接，跨拍必须分组。
def xml_beams(events, meter, groups=None):
    tree=MeterTree.from_meter(meter,groups)
    flags={'eighth':1,'16th':2,'32nd':3,'64th':4}
    result={}; sequence=[e for e in events if not e.get('grace')]
    for level in range(1,5):
        runs=[];run=[]
        for event in sequence:
            previous=run[-1] if run else None
            eligible=flags.get(event['type'],0)>=level
            adjacent=previous is not None and previous['start_tick']+previous['duration_ticks']==event['start_tick']
            same=previous is not None and tree.beat_limits(previous['start_tick'])==tree.beat_limits(event['start_tick'])
            if run and (not eligible or not adjacent or not same):runs.append(run);run=[]
            if eligible:run.append(event)
        if run:runs.append(run)
        for run in runs:
            for i,event in enumerate(run):
                if len(run)==1:
                    begin,end=tree.beat_limits(event['start_tick'])
                    state='backward hook' if event['start_tick']-begin >= (end-begin)/2 else 'forward hook'
                else:state='begin' if i==0 else 'end' if i==len(run)-1 else 'continue'
                result.setdefault(event['id'],[]).append((level,state))
    return result
