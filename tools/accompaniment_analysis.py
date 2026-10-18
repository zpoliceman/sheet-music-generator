"""和弦弹唱与伴奏编配：同源多轨的和声、低音、织体与器乐旋律证据。"""
# 和弦弹唱与伴奏编配：新增通用声学分析层，无歌曲名称、人工和弦表或手填音符。
from __future__ import annotations
import argparse
from dataclasses import dataclass
from pathlib import Path
import math
import time
import numpy as np
from scipy.ndimage import gaussian_filter1d
from scipy.signal import find_peaks
from score_export import PPQ, TempoMap, read_json, save_json, sha256, key_definition

VERSION = 1
SR, HOP, LOW_MIDI, HIGH_MIDI = 22050, 512, 24, 96
PITCH_NAMES_FLAT = ('C','Db','D','Eb','E','F','Gb','G','Ab','A','Bb','B')
PITCH_NAMES_SHARP = ('C','C#','D','D#','E','F','F#','G','G#','A','A#','B')
CHORD_TYPES = {
    '': (0,4,7), 'm': (0,3,7), 'dim': (0,3,6), 'aug': (0,4,8),
    'sus2': (0,2,7), 'sus4': (0,5,7), '5': (0,7),
    '7': (0,4,7,10), 'maj7': (0,4,7,11), 'm7': (0,3,7,10),
    'm7b5': (0,3,6,10), 'dim7': (0,3,6,9), '6': (0,4,7,9), 'm6': (0,3,7,9),
    'add9': (0,4,7,2), 'madd9': (0,3,7,2), '9': (0,4,7,10,2),
    'maj9': (0,4,7,11,2), 'm9': (0,3,7,10,2), '7sus4': (0,5,7,10),
}
MAJOR_SCALE = (0,2,4,5,7,9,11)


# 和弦弹唱与伴奏编配：新增实际发声音名；变调夹指型标签由编配层另行换算。
def pc_name(pc, key):
    return (PITCH_NAMES_FLAT if key.get('fifths', 0) < 0 else PITCH_NAMES_SHARP)[pc % 12]


def chord_name(root, quality, bass, key):
    name = pc_name(root, key) + quality
    return name + ('/' + pc_name(bass, key) if bass is not None and bass != root else '')


# 和弦弹唱与伴奏编配：新增统一秒/谱拍映射，继承认可工程，不重新定拍或改人声。
class SongClock:
    def __init__(self, project):
        self.project = project
        self.mapping = TempoMap(project['timing']['knots'])
        self.origin = float(project['timing']['score_start_quarter'])
        self.bar_ticks = int(project['statistics']['bar_ticks'])
        self.total_ticks = int(project['statistics']['total_ticks'])

    def tick(self, seconds):
        return (self.mapping.seconds_to_quarters(float(seconds)) - self.origin) * PPQ

    def seconds(self, tick):
        return self.mapping.quarters_to_seconds(float(tick) / PPQ + self.origin)

    # 原曲拍轴与歌词拍位通用修复：新增统一音频起点；正时间首拍前的原声帧完整保留，旧工程沿用原时钟。
    @property
    def audio_origin_seconds(self):
        source_origin=self.seconds(0)
        # 最小拍轴与词音伴奏修复：新增显式时间修订音频起点；自由引子前沿保留，不依赖旧全曲重建字段来补静音。
        if self.project.get('time_only_revision'):
            return float(self.project['time_only_revision']['audio_origin_seconds'])
        # 尾段原声局部补证：修改首次来源投影同样使用原曲0秒，不能因首拍0.1秒而裁掉开头人声合播。
        # return min(0.,source_origin) if self.project.get('source_meter_rebuild_correction') else source_origin
        return min(0.,source_origin) if (self.project.get('source_meter_rebuild_correction')
                                        or self.project.get('first_source_meter_correction')) else source_origin

    def quantize(self, seconds, grid=120):
        return max(0, min(self.total_ticks - grid, round(self.tick(seconds) / grid) * grid))

    def key(self, tick):
        segments = self.project['notation'].get('key_segments', [])
        chosen = self.project['notation']['key']
        for segment in segments:
            if segment.get('start_tick', 0) <= tick:
                chosen = segment['key']
        return chosen


@dataclass
class Features:
    # 和弦弹唱与伴奏编配：新增缓存数据结构，帧位置仍为原音频秒时间。
    times: np.ndarray
    activations: np.ndarray
    rms: np.ndarray
    flux: np.ndarray
    attacks: list
    source: dict

    def window(self, start, end):
        a, b = np.searchsorted(self.times, [max(0, start), max(0, end)])
        return slice(min(a, len(self.times)-1), max(min(b, len(self.times)), min(a+1, len(self.times))))

    def pitch_weights(self, start, end):
        block = self.activations[:, self.window(start, end)]
        return np.mean(block, axis=1) if block.size else np.zeros(HIGH_MIDI-LOW_MIDI+1)

    def chroma(self, start, end, low=LOW_MIDI, high=HIGH_MIDI):
        weights = self.pitch_weights(start, end)
        result = np.zeros(12)
        for i, midi in enumerate(range(LOW_MIDI, HIGH_MIDI+1)):
            if low <= midi <= high:
                result[midi % 12] += weights[i]
        return result / max(1e-9, float(result.sum()))


# 和弦弹唱与伴奏编配：新增谐波模板非负分解，降低把倍频当作新音符的风险。
def harmonic_activations(cqt, min_midi=LOW_MIDI, max_midi=HIGH_MIDI, iterations=36):
    bins = np.arange(cqt.shape[0])
    templates = np.zeros((len(bins), max_midi-min_midi+1), dtype=np.float32)
    for i, midi in enumerate(range(min_midi, max_midi+1)):
        for harmonic, amplitude in enumerate((1., .62, .34, .23, .15, .11), start=1):
            center = (midi - LOW_MIDI + 12 * math.log2(harmonic)) * 3
            templates[:, i] += amplitude * np.exp(-.5 * ((bins-center) / .85) ** 2)
    # 和弦弹唱与伴奏编配：新增频带白化，避免低频能量独占所有候选；保留原幅度尺度。
    whitening = (1 + bins / max(1, len(bins))) ** .4
    templates *= whitening[:, None]
    templates /= np.maximum(1e-8, np.linalg.norm(templates, axis=0))[None, :]
    data = np.asarray(cqt, dtype=np.float32) * whitening[:, None]
    projected = templates.T @ data
    gram = templates.T @ templates
    activations = np.maximum(projected, 1e-8)
    for _ in range(iterations):
        activations *= projected / np.maximum(1e-8, gram @ activations + .025 * projected.max(axis=0, keepdims=True))
    return activations


# 和弦弹唱与伴奏编配：新增逐音攻击检测；每次攻击保留实际候选音而非固定伴奏模板。
def detect_attacks(times, activations, rms):
    smooth = gaussian_filter1d(activations, .7, axis=1)
    difference = np.maximum(0, np.diff(smooth, prepend=smooth[:, :1], axis=1))
    flux = np.sum(difference, axis=0)
    if not np.any(flux > 0):
        return [], flux
    floor = max(float(np.percentile(flux, 62)), float(flux.max()) * .008)
    peaks, _ = find_peaks(flux, distance=max(1, round(.07 * SR/HOP)), prominence=floor * .6,
                          height=floor)
    rows = []
    for index in peaks:
        if rms[index] < max(float(rms.max()) * .007, 1e-6):
            continue
        attack = difference[:, max(0,index-1):min(len(times),index+2)].max(axis=1)
        sustain = smooth[:, index:min(len(times), index+5)].mean(axis=1)
        weights = attack * .7 + sustain * .08
        order = np.argsort(weights)[::-1]
        notes = []
        for i in order:
            if weights[i] < weights[order[0]] * .22 or len(notes) >= 6:
                break
            notes.append({'pitch_midi': int(i + LOW_MIDI), 'weight': float(weights[i]),
                          'relative_weight': float(weights[i] / max(1e-9, weights[order[0]])),
                          'attack_frame': int(index), 'sustain_weight': float(sustain[i])})
        if notes:
            rows.append({'seconds': float(times[index]), 'strength': float(flux[index]), 'pitches': notes})
    return rows, flux


# 和弦弹唱与伴奏编配：新增绑定源指纹和算法版本的缓存；整曲特征保存，保留完整混合音轨。
def extract_features(source, cache_dir, name):
    import librosa
    import soundfile as sf
    from threadpoolctl import threadpool_limits
    cache_dir = Path(cache_dir); cache_dir.mkdir(parents=True, exist_ok=True)
    digest = sha256(source['path'])
    if digest != source['sha256']:
        raise ValueError(f'{name}分轨已改变，需重新绑定来源。')
    token = f'v{VERSION}_{digest[:16]}_{SR}_{HOP}_{LOW_MIDI}_{HIGH_MIDI}'
    target, metadata = cache_dir / (token+'.npz'), cache_dir / (token+'.json')
    if target.exists() and metadata.exists():
        meta = read_json(metadata)
        if meta['source_sha256'] != digest:
            raise ValueError('缓存完整指纹不一致。')
        arrays = np.load(target)
        return Features(arrays['times'], arrays['activations'], arrays['rms'], arrays['flux'], meta['attacks'], source)
    started = time.perf_counter()
    wave, sr = sf.read(source['path'], always_2d=True, dtype='float32')
    with threadpool_limits(limits=4):
        mono = librosa.resample(wave.mean(axis=1), orig_sr=sr, target_sr=SR)
        n_bins = (108-LOW_MIDI) * 3 + 1
        cqt = np.abs(librosa.cqt(mono, sr=SR, hop_length=HOP,
                      fmin=librosa.midi_to_hz(LOW_MIDI), n_bins=n_bins,
                      bins_per_octave=36, tuning=0)).astype(np.float32)
        activations = harmonic_activations(cqt)
        rms = librosa.feature.rms(y=mono, frame_length=2048, hop_length=HOP)[0][:activations.shape[1]]
        times = librosa.frames_to_time(np.arange(activations.shape[1]), sr=SR, hop_length=HOP)
        attacks, flux = detect_attacks(times, activations, rms)
    np.savez_compressed(target, times=times, activations=activations, rms=rms, flux=flux)
    save_json(metadata, {'version': VERSION, 'name': name, 'source_sha256': digest, 'source': source,
                         'attacks': attacks, 'elapsed_seconds': time.perf_counter()-started,
                         'method': '36-bin/octave CQT + harmonic-template sparse nonnegative factorization',
                         'not_a_calibrated_transcription_model': True})
    return Features(times, activations, rms, flux, attacks, source)


# 和弦弹唱与伴奏编配：新增人声先验，旋律音允许和弦外经过音/倚音，不能直接认作根音。
def vocal_chroma(project, start, end, raw=False):
    chroma = np.zeros(12)
    for note in project['quantized_notes']:
        if note.get('lyric_index') is None:
            continue
        overlap = min(end, note['end_seconds']) - max(start, note['start_seconds'])
        if overlap <= 0:
            continue
        pitch = note.get('source_pitch_midi', note['pitch_midi']) if raw else note['pitch_midi']
        weight = 1 if note.get('role') == 'main' else .35
        chroma[int(pitch) % 12] += overlap * weight
    return chroma / max(1e-9, float(chroma.sum()))


# 和弦弹唱与伴奏编配：新增全部调根及扩展和弦候选、低音转位证据与弱调内先验。
def score_chord_candidates(chroma, bass, voice, key, limit=None):
    chroma = np.asarray(chroma, dtype=float); bass = np.asarray(bass, dtype=float); voice = np.asarray(voice, dtype=float)
    chroma /= max(1e-9, float(chroma.sum())); bass /= max(1e-9, float(bass.sum()))
    scale = {(key['tonic_pc']+i) % 12 for i in MAJOR_SCALE}
    rows = []
    for root in range(12):
        for quality, intervals in CHORD_TYPES.items():
            pcs = [(root+i) % 12 for i in intervals]
            weights = np.array([1.05 if i == 0 else .65 if i in (7,6,8) else .95 for i in intervals])
            selected = chroma[pcs]
            coverage = float(selected.sum())
            # 和弦弹唱与伴奏编配：新增缺失性质音和过拟合加音惩罚；五度省略允许，三度/挂留须有证据。
            missing = sum(.16 if interval not in (7,0) else .04 for interval, value in zip(intervals, selected) if value < .035)
            # 和弦弹唱与伴奏编配：修改，旧扩展惩罚过小会把经过音记作九和弦，原式保留。
            # complexity = .075 * max(0, len(intervals)-3) + (.06 if quality == '5' else 0)
            complexity = .24 * max(0, len(intervals)-3) + (.10 if quality == '5' else 0)
            out_of_scale = sum(pc not in scale for pc in pcs) * .075
            # 和弦弹唱与伴奏编配：修改，旧根音奖励过强会把斜杠低音误认为新根音，原式保留。
            # bass_support = .9 * float(bass[root]) + .32 * float(bass[pcs].sum())
            bass_support = .34 * float(bass[root]) + .70 * float(bass[pcs].sum())
            strongest_bass = int(np.argmax(bass)) if bass.sum() else root
            if strongest_bass in pcs and strongest_bass != root:
                # 和弦弹唱与伴奏编配：修改，配合新的转位支持权重，原值保留。
                # bass_support += .18 * float(bass[strongest_bass])
                bass_support += .12 * float(bass[strongest_bass])
            emission = (2.3 * coverage + .8 * float(np.dot(weights, selected)/weights.sum()) - missing - complexity -
                        out_of_scale + bass_support + .30 * float(voice[pcs].sum()))
            rows.append({'root_pc': root, 'quality': quality, 'pitch_classes': pcs,
                         'score': emission, 'coverage': coverage, 'bass_support': bass_support,
                         'vocal_coverage': float(voice[pcs].sum()),
                         'extension_evidence': {str(i): float(chroma[(root+i)%12]) for i in intervals if i not in (0,3,4,7)}})
    rows.sort(key=lambda x:x['score'], reverse=True)
    return rows if limit is None else rows[:limit]


# 和弦弹唱与伴奏编配：新增跨窗动态规划，减少泛音噪声引起的毫无依据频繁换弦。
def decode_harmony(windows, change_penalty=.24):
    if not windows:
        return []
    costs, traces = [], []
    for index, window in enumerate(windows):
        candidates = window['candidates']
        emission = np.array([c['score'] for c in candidates])
        if not index:
            costs.append(emission); traces.append(np.full(len(candidates), -1)); continue
        previous = windows[index-1]['candidates']
        transition = np.full((len(previous), len(candidates)), -change_penalty)
        for i, a in enumerate(previous):
            for j, b in enumerate(candidates):
                if (a['root_pc'], a['quality']) == (b['root_pc'], b['quality']):
                    transition[i,j] = 0
                elif a['root_pc'] == b['root_pc']:
                    transition[i,j] = -change_penalty * .55
                elif (b['root_pc']-a['root_pc']) % 12 in (5,7):
                    transition[i,j] += .035
        joined = costs[-1][:,None] + transition
        best = np.argmax(joined, axis=0)
        costs.append(joined[best,np.arange(len(candidates))] + emission); traces.append(best)
    selected = [int(np.argmax(costs[-1]))]
    for trace in traces[:0:-1]:
        selected.append(int(trace[selected[-1]]))
    selected.reverse()
    return [dict(w['candidates'][i]) for w,i in zip(windows,selected)]


# 和弦弹唱与伴奏编配：新增由真实歌词活动得到器乐区段，避免将整段人声再次加倍写进伴奏。
def section_ranges(project, duration):
    chars = [x for x in project['lyrics']['characters'] if x.get('start_seconds') is not None and x.get('end_seconds') is not None]
    intervals = sorted((float(x['start_seconds']),float(x['end_seconds'])) for x in chars)
    groups = []
    for start,end in intervals:
        if groups and start - groups[-1][1] < 3.0:
            groups[-1][1] = max(groups[-1][1],end)
        else:
            groups.append([start,end])
    # 强拍相位与伴奏同步纠错：新增弱起前的正拍属于演唱伴奏，不因首字晚半拍而误当独奏前奏。
    if project.get('timing',{}).get('beat_phase'):
        clock=SongClock(project)
        groups=[[max(0.,clock.seconds(math.floor(clock.tick(a)/PPQ)*PPQ)),
                 min(duration,clock.seconds(math.ceil(clock.tick(b)/PPQ)*PPQ))] for a,b in groups]
    sections, cursor, interlude = [], 0., 0
    for start,end in groups:
        if start > cursor + .7:
            kind = 'intro' if cursor == 0 else 'interlude'
            interlude += kind == 'interlude'
            sections.append({'kind':kind, 'label':'前奏' if kind=='intro' else '间奏'+str(interlude),
                             'start_seconds':cursor,'end_seconds':start})
        sections.append({'kind':'vocal','label':'演唱','start_seconds':start,'end_seconds':min(duration,end)})
        cursor = end
    if cursor < duration:
        sections.append({'kind':'outro','label':'尾奏','start_seconds':cursor,'end_seconds':duration})
    return sections


def section_at(sections, seconds):
    return next((s for s in sections if s['start_seconds'] <= seconds < s['end_seconds']), sections[-1])


# 和弦弹唱与伴奏编配：新增器乐候选连续路径，保存来源及支持度，不声称多音混轨的唯一旋律已确定。
# 原曲器乐旋律骨干重提取：修改，旧逐全轨攻击且限60—84音域的实现仅保留为历史诊断，不再作为生成入口。
# def instrumental_melody(features, sections, project, clock):
def legacy_instrumental_melody(features, sections, project, clock):
    selected = features.get('six_piano', features['other'])
    other = features['other']
    rows = []
    for section in sections:
        if section['kind'] == 'vocal':
            continue
        attacks = [a for a in selected.attacks if section['start_seconds'] <= a['seconds'] < section['end_seconds']]
        if not attacks:
            attacks = [a for a in other.attacks if section['start_seconds'] <= a['seconds'] < section['end_seconds']]
        # 和弦弹唱与伴奏编配：修改，旧低音起点会将旋律路径吸附伴奏，原值保留。
        # previous = 67
        previous = 75
        for attack in attacks:
            # 和弦弹唱与伴奏编配：新增不依赖攻击候选截断的低八度基音核验，原攻击证据不变。
            time0 = attack['seconds']
            support = other.pitch_weights(time0,time0+.16)
            # 和弦弹唱与伴奏编配：修改，原直接接受高次倍频，改用低八度基音交叉证据。
            # candidates = [x for x in attack['pitches'] if 58 <= x['pitch_midi'] <= 90]
            candidates = []
            for value in attack['pitches']:
                candidate = dict(value)
                pitch = candidate['pitch_midi']
                low = next((x for x in attack['pitches'] if x['pitch_midi'] == pitch-12), None)
                if pitch >= 82 and low is not None and low['relative_weight'] >= .25:
                    continue
                if pitch>=82 and support[pitch-12-LOW_MIDI] >= .16*support[pitch-LOW_MIDI]:
                    candidate['pitch_midi']=pitch-12
                    candidate['octave_harmonic_suppression_from']=pitch
                    pitch-=12
                if 60 <= pitch <= 84:
                    candidates.append(candidate)
            if not candidates:
                continue
            # 和弦弹唱与伴奏编配：修改，核验已前移到倍频过滤之前，原两行保留。
            # time0 = attack['seconds']
            # support = other.pitch_weights(time0,time0+.16)
            # 和弦弹唱与伴奏编配：新增混合伴奏交叉支持及旋律连续性，不能只选最高泛音。
            def rank(c):
                pitch = c['pitch_midi']; acoustic = support[pitch-LOW_MIDI]
                # 和弦弹唱与伴奏编配：修改，原连续性不足以压制倍频跳进，保留原式。
                # return c['relative_weight'] + .30 * acoustic / max(1e-8,float(support.max())) - .025 * abs(pitch-previous)
                return c['relative_weight'] + .30 * acoustic / max(1e-8,float(support.max())) + .015*(pitch-60) - .075 * abs(pitch-previous)
            chosen = max(candidates,key=rank); pitch = chosen['pitch_midi']
            if chosen['relative_weight'] < .34:
                continue
            tick = clock.quantize(time0)
            if rows and rows[-1]['start_tick'] == tick:
                if chosen['relative_weight'] <= rows[-1]['support']:
                    continue
                rows.pop()
            rows.append({'id':f'instrument_melody_{len(rows)+1:05}', 'start_tick':tick,
                         'start_seconds':time0,'pitch_midi':pitch,'support':chosen['relative_weight'],
                         'source':'six_piano' if selected is features.get('six_piano') else 'other',
                         'section':section['kind'], 'role':'instrumental_melody', 'requires_listening':True})
            previous = pitch
    for i,row in enumerate(rows):
        end = rows[i+1]['start_tick'] if i+1<len(rows) and rows[i+1]['section']==row['section'] else row['start_tick']+240
        row['duration_ticks'] = max(120,min(960,end-row['start_tick']))
    return rows


# 原曲器乐旋律骨干重提取：新增全新歌曲默认从实际音轨建立多音／持续／起音主线；旧工程升级另存。
# 尾段原声局部补证：修改增加完整绑定，首次尾部结论须从实际原声决定重放，历史调用不变。
# def instrumental_melody(features,sections,project,clock,cache_dir=None):
def instrumental_melody(features,sections,project,clock,cache_dir=None,binding=None):
    from instrumental_source_melody import build_source_plan,ROOT
    cache_dir=Path(cache_dir) if cache_dir is not None else ROOT/'test_outputs/accompaniment_runs/instrumental_source_melody/features'
    # 尾段原声局部补证：修改新来源提供完整绑定；旧无拍轴补证的调用保留原输入结构。
    # shared={'input_binding':{'sources':{name:value.source for name,value in features.items()}},'sections':sections}
    shared={'input_binding':binding if binding is not None else {'sources':{name:value.source for name,value in features.items()}},'sections':sections}
    plan,_=build_source_plan(shared,project,cache_dir)
    return [{**note,'start_seconds':note['source_start_seconds'],'support':note['activation'],
             'requires_listening':True,'source_backbone_pitch_midi':note['pitch_midi']} for note in plan['notes']]


# 和弦弹唱与伴奏编配：新增实测攻击音序、同时音数、扫弦方向线索和节奏的逐小节分析。
def measure_textures(features, clock, project, sections):
    records = []
    possible = [k for k in ('six_guitar','six_piano','other') if k in features]
    for measure in range(1,project['statistics']['measure_count']+1):
        # 尾段原声局部补证：修改首次v2织体分箱读取已通过的实际短小节；历史固定小节缓存重放保持。
        # start,end = (measure-1)*clock.bar_ticks,measure*clock.bar_ticks
        timeline=project['timing'].get('measure_timeline',[])
        if project.get('first_source_meter_correction',{}).get('version')==2 and timeline:
            start,end=timeline[measure-1]['start_tick'],timeline[measure-1]['end_tick']
        else:
            start,end = (measure-1)*clock.bar_ticks,measure*clock.bar_ticks
        sec0,sec1 = clock.seconds(start),clock.seconds(end)
        energies = {name:float(features[name].rms[features[name].window(sec0,sec1)].mean()) for name in possible}
        strongest = max(energies,key=energies.get)
        # 和弦弹唱与伴奏编配：新增独立乐器源只在有能量时选用，other混轨始终保留候选。
        if strongest == 'other':
            others = [name for name in possible if name!='other' and energies[name] >= energies['other']*.16]
            if others:
                strongest = max(others,key=energies.get)
        attacks = [a for a in features[strongest].attacks if sec0 <= a['seconds'] < sec1]
        unique = {}
        for attack in attacks:
            tick = clock.quantize(attack['seconds'])
            if not start <= tick < end:
                continue
            if tick not in unique or attack['strength'] > unique[tick]['strength']:
                unique[tick] = {**attack,'tick':tick,'source':strongest}
        attack_rows = sorted(unique.values(),key=lambda x:x['tick'])
        # 小节划分与拍速层级纠错：修改，旧14次截断注释保留；4/4十六分本身就有16次，完整起音必须保留。
        # if len(attack_rows)>14:
        #     strongest_rows = sorted(attack_rows,key=lambda x:x['strength'],reverse=True)[:14]
        #     attack_rows = sorted(strongest_rows,key=lambda x:x['tick'])
        counts = [len([p for p in a['pitches'] if p['relative_weight'] > .45]) for a in attack_rows]
        intervals = np.diff([a['seconds'] for a in attack_rows])
        simultaneity = float(np.mean(counts)) if counts else 0
        texture = 'arpeggio' if len(attack_rows)>=5 and simultaneity<2.8 else 'block'
        # 和弦弹唱与伴奏编配：新增扫弦线索必须来自吉他源的密集多音攻击，不根据歌曲后段强制扫弦。
        if strongest=='six_guitar' and simultaneity>=2.8:
            texture='strum'
        if not attack_rows or max(energies.values())<.0004:
            texture='sustain' if max(energies.values())>=.00015 else 'silence'
        records.append({'measure':measure,'start_tick':start,'end_tick':end,'start_seconds':sec0,'end_seconds':sec1,
                        'section':section_at(sections,max(0,(sec0+sec1)/2))['kind'],
                        'kind':texture, 'source':strongest,'source_rms':energies,
                        'mean_simultaneous_attack_notes':simultaneity,
                        'median_inter_attack_seconds':float(np.median(intervals)) if len(intervals) else None,
                        'attack_grid_ticks':[a['tick']-start for a in attack_rows],
                        'attacks':attack_rows, 'direction':'not_resolved_from_audio',
                        'classification_kind':'heuristic_not_calibrated_requires_listening'})
    return records


# 和弦弹唱与伴奏编配：新增主分析入口，混音/完整伴奏/分轨/认可人声均参加共享和声判断。
# 局部时序与弱证据通用修复：修改，保留旧入口定义；旧策略默认保持，版本2显式启用目标音区质量。
# def analyze(binding, project, cache_dir):
def analyze(binding, project, cache_dir, harmonic_quality=False):
    clock = SongClock(project); started = time.perf_counter()
    features = {}
    for name in ('mix','accompaniment','other','bass','six_guitar','six_piano','six_other'):
        if name in binding['sources']:
            print('分析音轨:',name,flush=True)
            features[name] = extract_features(binding['sources'][name],cache_dir,name)
    # 原声覆盖与选音归属通用修复：新增局部起音复查，只修改内存派生，不改来源绑定的旧CQT缓存。
    coverage_audit = {}
    if harmonic_quality == 3:
        from source_accompaniment_quality import refine_attacks
        coverage_audit = {name: refine_attacks(f) for name, f in features.items() if name not in ('mix', 'bass')}
    weights = {'other':.30,'accompaniment':.26,'mix':.08,'six_guitar':.14,'six_piano':.14,'six_other':.08}
    windows = []
    for start in range(0,clock.total_ticks,PPQ):
        end = min(clock.total_ticks,start+PPQ)
        sec0,sec1 = clock.seconds(start),clock.seconds(end)
        # 和弦弹唱与伴奏编配：修改，旧逐轨归一化把近静音吉他噪声放大；保留旧两行。
        # chromas = {name:f.chroma(sec0+.03,sec1) for name,f in features.items() if name!='bass'}
        # mixture = sum(weights[name]*chromas[name] for name in chromas) / sum(weights[name] for name in chromas)
        # 局部时序与弱证据通用修复：修改，旧归一化/宽带门限保留为历史分支；新策略记录有效音区与弱低音质量。
        # chromas = {name:f.chroma(sec0+.03,sec1,48,84) for name,f in features.items() if name!='bass'}
        # energies = {name:float(f.rms[f.window(sec0,sec1)].mean()) for name,f in features.items() if name!='bass'}
        # active_weights = {name:weights[name] for name in chromas if energies[name] >= max(.0002,energies['accompaniment']*.02)}
        # if not active_weights:
        #     active_weights={'other':1.}
        # mixture = sum(active_weights[name]*chromas[name] for name in active_weights) / sum(active_weights.values())
        # mid_chroma = sum(active_weights[name]*features[name].chroma(sec0+.03,sec1,48,72) for name in active_weights) / sum(active_weights.values())
        # mixture = .65*mid_chroma + .35*mixture
        # bass = features['bass'].chroma(sec0,sec1,24,59)
        if harmonic_quality:
            # 跨曲低音与强拍复用通用修复：修改，旧版本1默认导入保留；只有显式版本2启用跨乐器低音。
            # from harmonic_source_quality import quality_window
            # 原声覆盖与选音归属通用修复：修改，v3继续使用有效低音音区质量，旧1／2策略保留。
            # if harmonic_quality == 2:
            if harmonic_quality in (2, 3):
                from harmonic_low_register import quality_window
            else:
                from harmonic_source_quality import quality_window
            chromas,energies,active_weights,mixture,mid_chroma,bass,source_quality=quality_window(features,sec0,sec1,weights)
        else:
            chromas = {name:f.chroma(sec0+.03,sec1,48,84) for name,f in features.items() if name!='bass'}
            energies = {name:float(f.rms[f.window(sec0,sec1)].mean()) for name,f in features.items() if name!='bass'}
            active_weights = {name:weights[name] for name in chromas if energies[name] >= max(.0002,energies['accompaniment']*.02)}
            if not active_weights:
                active_weights={'other':1.}
            mixture = sum(active_weights[name]*chromas[name] for name in active_weights) / sum(active_weights.values())
            mid_chroma = sum(active_weights[name]*features[name].chroma(sec0+.03,sec1,48,72) for name in active_weights) / sum(active_weights.values())
            mixture = .65*mid_chroma + .35*mixture
            bass = features['bass'].chroma(sec0,sec1,24,59)
        voice, raw_voice = vocal_chroma(project,sec0,sec1),vocal_chroma(project,sec0,sec1,True)
        candidates = score_chord_candidates(mixture,bass,voice,clock.key(start),limit=12)
        energy = float(features['accompaniment'].rms[features['accompaniment'].window(sec0,sec1)].mean())
        windows.append({'start_tick':start,'end_tick':end,'start_seconds':sec0,'end_seconds':sec1,
                        'key':clock.key(start), 'accompaniment_rms':energy, 'chroma':mixture.tolist(),
                        'source_chromas':{k:v.tolist() for k,v in chromas.items()},
                        'active_source_weights':active_weights, 'harmonic_mid_chroma':mid_chroma.tolist(),
                        'bass_chroma':bass.tolist(),'vocal_notated_chroma':voice.tolist(),'vocal_original_chroma':raw_voice.tolist(),
                        'candidates':candidates})
        # 局部时序与弱证据通用修复：新增版本化来源质量审计；旧策略窗口字典不增字段，保持历史可重建。
        if harmonic_quality:
            windows[-1]['harmonic_source_quality']=source_quality
    # 和弦弹唱与伴奏编配：新增同低音相邻拍聚合，避免分解音序每拍缺音造成和弦漂移。
    for index,window in enumerate(windows):
        current_bass=int(np.argmax(window['bass_chroma']))
        # 局部时序与弱证据通用修复：修改，旧零低音argmax相等会伪造共同根音；保留原条件。
        # neighbors=[windows[j]['chroma'] for j in (index-1,index+1) if 0<=j<len(windows)
        #            and int(np.argmax(windows[j]['bass_chroma']))==current_bass]
        neighbors=[windows[j]['chroma'] for j in (index-1,index+1) if 0<=j<len(windows)
                   and int(np.argmax(windows[j]['bass_chroma']))==current_bass
                   and (not harmonic_quality or (sum(window['bass_chroma'])>0 and sum(windows[j]['bass_chroma'])>0))]
        combined=np.asarray(window['chroma'])*.6
        if neighbors:
            combined+=np.mean(neighbors,axis=0)*.4
        else:
            combined/= .6
        window['decoding_chroma']=combined.tolist()
        window['candidates']=score_chord_candidates(combined,np.asarray(window['bass_chroma']),
                              np.asarray(window['vocal_notated_chroma']),window['key'],limit=12)
    choices = decode_harmony(windows)
    # 和弦弹唱与伴奏编配：新增无攻击渐弱延音保护，尾部噪声不创建无来源的新和弦。
    tone_source=features.get('six_piano',features['other'])
    reliable_attacks=[a for a in tone_source.attacks if a['strength']>=max(.01,max((r['strength'] for r in tone_source.attacks),default=0)*.006)]
    energy_floor=max(.0005,float(np.percentile(features['accompaniment'].rms,90))*.015)
    last_attack=max((a['seconds'] for a in reliable_attacks),default=binding['duration_seconds'])
    for index,window in enumerate(windows):
        if index and window['start_seconds']>last_attack+.5:
            choices[index]=dict(choices[index-1])
            window['sustained_previous_harmony_after_last_attack']=True
        window['below_harmonic_analysis_energy_floor']=window['accompaniment_rms']<energy_floor
    segments = []
    # 和弦弹唱与伴奏编配：修改，旧window.index逐次搜索，改为显式来源索引。
    # for window,choice in zip(windows,choices):
    for window_index,(window,choice) in enumerate(zip(windows,choices)):
        bass = np.asarray(window['bass_chroma']); order = np.argsort(bass)[::-1]
        bass_pc = int(order[0]) if bass[order[0]] >= .28 else choice['root_pc']
        if bass_pc not in choice['pitch_classes'] and bass[bass_pc]<.52:
            bass_pc = choice['root_pc']
        name = chord_name(choice['root_pc'],choice['quality'],bass_pc,window['key'])
        margin = choice['score'] - max((c['score'] for c in window['candidates'] if
                         (c['root_pc'],c['quality']) != (choice['root_pc'],choice['quality'])),default=choice['score'])
        identity = (choice['root_pc'],choice['quality'],bass_pc)
        window['selected'] = {**choice,'bass_pc':bass_pc,'name':name,'local_margin':margin}
        # 和弦弹唱与伴奏编配：修改，旧绝对静音门槛不能抑制尾部低能量噪声，原条件保留。
        # if window['accompaniment_rms']<.00015:
        if window['below_harmonic_analysis_energy_floor']:
            window['selected']['name']='N.C.'; identity=(-1,'',-1)
        if segments and segments[-1]['identity']==list(identity) and segments[-1]['key']['label']==window['key']['label']:
            segments[-1]['end_tick']=window['end_tick']; segments[-1]['end_seconds']=window['end_seconds']
            # 和弦弹唱与伴奏编配：修改，保留原低效索引表达式。
            # segments[-1]['window_indices'].append(len(segments) if False else windows.index(window))
            segments[-1]['window_indices'].append(window_index)
            segments[-1]['requires_review'] |= margin<.12
        else:
            segments.append({'id':f'harmony_{len(segments)+1:04}','identity':list(identity),
                             'root_pc':choice['root_pc'],'quality':choice['quality'],'pitch_classes':choice['pitch_classes'],
                             'bass_pc':bass_pc,'name':window['selected']['name'],'key':window['key'],
                             'start_tick':window['start_tick'],'end_tick':window['end_tick'],
                             'start_seconds':window['start_seconds'],'end_seconds':window['end_seconds'],
                             # 和弦弹唱与伴奏编配：修改，原搜索索引保留，改为明确窗口序号。
                             # 'window_indices':[windows.index(window)],'requires_review':margin<.12,
                             'window_indices':[window_index],'requires_review':margin<.12,
                             'bass_is_inversion':bass_pc!=choice['root_pc'],
                             'kind':'audio_inferred_not_reference_score_copy'})
    sections = section_ranges(project,binding['duration_seconds'])
    for s in sections:
        s['start_tick']=max(0,round(clock.tick(s['start_seconds']))); s['end_tick']=min(clock.total_ticks,round(clock.tick(s['end_seconds'])))
    textures = measure_textures(features,clock,project,sections)
    # 原曲器乐旋律骨干重提取：修改，新分析使用内容寻址多音证据，原调用保留供历史比对。
    # melody = instrumental_melody(features,sections,project,clock)
    # 尾段原声局部补证：修改初次器乐提取传递来源，尾响不能再次成为新旋律。
    # melody = instrumental_melody(features,sections,project,clock,Path(cache_dir)/'instrumental_source')
    melody = instrumental_melody(features,sections,project,clock,Path(cache_dir)/'instrumental_source',binding)
    result = {'schema_version':VERSION,'artifact_kind':'shared_harmony_and_accompaniment_evidence',
              'quality_status':'audio_inferred_draft_requires_musical_review', 'input_binding':binding,
              'timing':project['timing'], 'notation':{'key':project['notation']['key'],
                      'key_segments':project['notation'].get('key_segments',[]),'source_key':project['notation']['source_key'],
                      'transpose_semitones':project['notation'].get('transpose_semitones',0)},
              'statistics':project['statistics'],'sections':sections,'harmony_windows':windows,
              'harmony':segments,'measure_textures':textures,'instrumental_melody':melody,
              'method':{'harmonic_features':'CQT harmonic-template sparse nonnegative decomposition',
                        # 原曲器乐旋律骨干重提取：新增主线方法声明，原和声CQT证据保持独立。
                        'instrumental_melody':'source_bound_polyphonic_onsets_and_continuous_upper_voice_before_guitar_register',
                        'chord_decoder':'voice/bass/multiple-accompaniment evidence + continuity dynamic programming',
                        'vocal_role':'accepted_melody_prior_not_chord_root_truth', 'source_weights':weights,
                        'guitar_piano_sources':'experimental_supplement_not_independent_ground_truth',
                        'reference_images':'manual_review_only_not_algorithm_input',
                        'scope':'major-key prior; chromatic harmony permitted; no calibrated accuracy claim'},
              'elapsed_seconds':time.perf_counter()-started}
    # 局部时序与弱证据通用修复：新增派生和声质量策略，便于其它歌曲与历史策略分别核验。
    if harmonic_quality:
        # 跨曲低音与强拍复用通用修复：修改，旧策略声明保留；保存真正使用的版本以支持历史重建。
        # from harmonic_source_quality import POLICY as QUALITY_POLICY
        # 原声覆盖与选音归属通用修复：修改，v3与v2共享低音证据，另记源覆盖政策。
        # if harmonic_quality == 2:
        if harmonic_quality in (2, 3):
            from harmonic_low_register import POLICY as QUALITY_POLICY
        else:
            from harmonic_source_quality import POLICY as QUALITY_POLICY
        result['method']['harmonic_source_quality']=dict(QUALITY_POLICY)
    # 原声覆盖与选音归属通用修复：新增真实持续音证据，缺失攻击不能清空可听伴奏。
    if harmonic_quality == 3:
        from source_accompaniment_quality import POLICY as COVERAGE_POLICY, sustained_attack
        result['method']['source_coverage_quality'] = dict(COVERAGE_POLICY)
        result['source_coverage_evidence'] = coverage_audit
        for texture in textures:
            if texture['kind'] == 'sustain' and not texture['attacks']:
                attack = sustained_attack(texture, features, clock)
                if attack is not None:
                    texture['sustained_observation'] = attack
    return result


# 和弦弹唱与伴奏编配：新增独立分析命令与可重复缓存，首曲只是命令参数。
def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binding',type=Path,required=True); parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args(); binding=read_json(args.binding); project=read_json(binding['vocal_project'])
    result=analyze(binding,project,args.output/'features')
    save_json(args.output/'shared_analysis.json',result)
    print('和弦段',len(result['harmony']),'器乐候选',len(result['instrumental_melody']),flush=True)


if __name__=='__main__':
    main()
