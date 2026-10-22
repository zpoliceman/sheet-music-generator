"""器乐背景休止与旋律突出：原音频的通用背景筛选，明确音乐／背景／待复核三态。"""
from copy import deepcopy
from functools import lru_cache
from pathlib import Path
import math
import numpy as np
import soundfile as sf
from scipy.signal import resample_poly,find_peaks
from scipy.ndimage import maximum_filter1d,uniform_filter1d
from score_export import read_json,save_json,sha256
from accompaniment_analysis import SongClock
from guitar_instrumental_register import fingerprint

# 器乐背景休止与旋律突出：新增跨曲策略；曲名、歌词内容、前20秒答案不参与判别。
POLICY={'version':1,'sample_rate':11025,'fft_size':2048,'hop_samples':220,
    'context_seconds':6.,'window_step_seconds':.5,'minimum_background_seconds':2.,
    'sharp_flux_threshold':.14,'minimum_regular_onsets':5,'grid_tolerance_seconds':.045,
    # 器乐背景休止与旋律突出：修改，短窗偶然碰拍不能确认为稳定节奏；保留初探值 .78。
    # 器乐背景休止与旋律突出：修改自由旋律须绝大多数换音有原攻击，而非少数背景峰；保留初探 .6。
    'regularity_threshold':.85,'pitched_fraction_threshold':.6,'melody_onset_agreement':.85,
    'minimum_melody_changes':3,'noise_flatness':.08,'minimum_noise_fraction':.35,
    'minimum_background_candidate_notes':4,'minimum_onset_match_seconds':.12,
    'ambiguous_action':'preserve_and_review','sources':['mix','accompaniment','bass'],
    'scope':['intro','interlude','outro'],'no_song_specific_time_or_title':True,
    'minimum_contour_step_fraction':.7,'maximum_small_contour_interval':5,
    'minimum_noise_unpitched_fraction':.65,'maximum_background_bridge_seconds':8.,
    'minimum_confirmed_music_windows':3,'source_entry_flatness_maximum':.06,
    'pitch_attack_rise_threshold':.7,'downmix_cancellation_ratio':.35,
    'original_mix_can_veto_background':True,'bass_requires_stable_pitch':True}


# 器乐背景休止与旋律突出：新增实际声源核验和不可变分析缓存，不信任分离轨上的模型概率即旋律。
@lru_cache(maxsize=12)
def cached_curve(path,digest,offset,mtime,size):
    if sha256(path)!=digest:raise ValueError('背景筛选声源已改变。')
    # 器乐背景休止与旋律突出：修改，反相立体声不能被平均成假静音；保留初探平均式。
    # y,rate=sf.read(path,dtype='float32',always_2d=True);y=y.mean(axis=1)
    channels,rate=sf.read(path,dtype='float32',always_2d=True);y=channels.mean(axis=1)
    energies=np.sqrt(np.mean(channels**2,axis=0))
    if np.sqrt(np.mean(y**2))<float(energies.max())*POLICY['downmix_cancellation_ratio']:
        y=channels[:,int(energies.argmax())]
    divisor=math.gcd(rate,POLICY['sample_rate'])
    y=resample_poly(y,POLICY['sample_rate']//divisor,rate//divisor).astype('float32')
    count,hop=POLICY['fft_size'],POLICY['hop_samples']
    frames=np.lib.stride_tricks.sliding_window_view(np.pad(y,(0,count)),count)[::hop]
    magnitude=abs(np.fft.rfft(frames*np.hanning(count)));freq=np.fft.rfftfreq(count,1/POLICY['sample_rate'])
    band=magnitude[:,(freq>=43)&(freq<=4500)];total=band.sum(axis=1)
    positive=np.maximum(0,np.diff(band,axis=0));flux=np.r_[0,positive.sum(axis=1)]
    sharp=flux/np.maximum(1e-8,np.r_[total[0],total[:-1]])
    # 器乐背景休止与旋律突出：修改为功率谱平坦度，幅度谱与功率谱的阈值不可混用；保留探针原式。
    # flat=np.exp(np.mean(np.log(band+1e-9),axis=1))/np.maximum(1e-9,band.mean(axis=1))
    power=band**2;flat=np.exp(np.mean(np.log(power+1e-12),axis=1))/np.maximum(1e-12,power.mean(axis=1))
    indices=np.flatnonzero((freq>=65)&(freq<=2000));peak=indices[magnitude[:,indices].argmax(axis=1)]
    spectrum=np.log(magnitude+1e-9);rows=np.arange(len(frames))
    below,at,above=(spectrum[rows,np.clip(peak+d,0,spectrum.shape[1]-1)] for d in (-1,0,1))
    shift=np.clip(.5*(below-above)/np.minimum(-1e-8,below-2*at+above),-.5,.5)
    hz=(peak+shift)*POLICY['sample_rate']/count;pitch=69+12*np.log2(hz/440)
    times=np.arange(len(frames))*hop/POLICY['sample_rate']+count/(2*POLICY['sample_rate'])+offset
    rms=np.sqrt(np.mean(frames**2,axis=1));anchor=max(float(np.percentile(rms,95)),1e-8)
    peaks,_=find_peaks(sharp,height=POLICY['sharp_flux_threshold'],distance=max(1,round(.1*POLICY['sample_rate']/hop)))
    peaks=peaks[rms[peaks]>max(1e-6,anchor*.01)]
    # 器乐背景休止与旋律突出：新增各音高本频能量，防止宽频背景起伏替其它频率的候选音背书。
    power_all=magnitude**2;pitch_power=[]
    for midi in range(21,109):
        fundamental=440*2**((midi-69)/12)
        mask=abs(freq-fundamental)<=max(POLICY['sample_rate']/count*.75,fundamental*.018)
        pitch_power.append(power_all[:,mask].sum(axis=1))
    return {'times':times,'rms':rms,'sharp':sharp,'flatness':flat,'pitch':pitch,'onsets':times[peaks],
        'pitch_power':np.array(pitch_power).T,'end_seconds':offset+len(y)/POLICY['sample_rate'],'energy_anchor':anchor}


def source_curve(binding):
    path=Path(binding['path']);digest=sha256(path)
    if digest!=binding['sha256']:raise ValueError('背景筛选输入指纹不一致。')
    stat=path.stat();return cached_curve(str(path.resolve()),digest,float(binding.get('offset_seconds',0)),stat.st_mtime_ns,stat.st_size)


# 器乐背景休止与旋律突出：新增不依赖既有小节相位的原起音规律；稀疏、自由节奏不会单独被判背景。
def onset_regularity(onsets):
    if len(onsets)<POLICY['minimum_regular_onsets']:return 0.,None
    differences=np.diff(onsets);best=(0.,None)
    for period in np.arange(.2,.91,.005):
        error=abs(differences-np.maximum(1,np.round(differences/period))*period)
        score=float(np.mean(error<=min(POLICY['grid_tolerance_seconds'],period*.1)))
        if score>best[0]:best=(score,float(period))
    return best


# 器乐背景休止与旋律突出：新增候选音的本频起音对比，慢变背景频谱没有新的真实拨弦／击键。
def pitch_attack(curve,note):
    t=note['source_start_seconds'];p=note['pitch_midi']-21
    if not 0<=p<88:return 0.
    time=curve['times'];v=curve['pitch_power'][:,p]
    previous=v[(time>=t-.22)&(time<t-.08)];following=v[(time>=t-.04)&(time<t+.14)]
    if not len(following):return 0.
    before=float(np.median(previous)) if len(previous) else 0.
    after=float(np.max(following));return (after-before)/max(1e-8,after)


# 器乐背景休止与旋律突出：新增候选换音与原曲攻击交叉核验，未经原声支撑的频率漂移不能当骨干。
def window_evidence(curve,start,end,candidates=(),bass=None):
    selected=(curve['times']>=start)&(curve['times']<end);times=curve['times'][selected]
    if not len(times):return {'state':'ambiguous','reason':'source_window_missing'}
    onsets=curve['onsets'][(curve['onsets']>=start)&(curve['onsets']<end)]
    regular,period=onset_regularity(onsets)
    rms=curve['rms'][selected];active=rms>max(1e-6,curve['energy_anchor']*.005)
    pitch=curve['pitch'][selected];pitched=active&(abs(pitch-np.round(pitch))<.28)&(curve['flatness'][selected]<.06)
    pitched_fraction=float(np.mean(pitched))
    noise_fraction=float(np.mean(curve['flatness'][selected]>POLICY['noise_flatness']))
    notes=[n for n in candidates if start<=n['source_start_seconds']<end]
    # 器乐背景休止与旋律突出：修改，保留只看宽频起音的探针式；再要求该候选本频确有清楚上升。
    # match=[n for n in notes if len(curve['onsets']) and min(abs(curve['onsets']-n['source_start_seconds']))<=POLICY['minimum_onset_match_seconds']]
    match=[n for n in notes if len(curve['onsets']) and min(abs(curve['onsets']-n['source_start_seconds']))<=POLICY['minimum_onset_match_seconds'] and pitch_attack(curve,n)>=POLICY['pitch_attack_rise_threshold']]
    agreement=len(match)/max(1,len(notes));changes=len({n['pitch_midi']%12 for n in match})
    intervals=np.abs(np.diff([n['pitch_midi'] for n in match]));contour=float(np.mean(intervals<=POLICY['maximum_small_contour_interval'])) if len(intervals) else 0.
    bass_support=0.
    if bass is not None:
        b=np.interp(times,bass['times'],bass['rms'],left=0,right=0)
        bass_pitch=np.interp(times,bass['times'],bass['pitch']);bass_flat=np.interp(times,bass['times'],bass['flatness'])
        bass_support=float(np.mean((b>=bass['energy_anchor']*.04)&(b>=rms*.04)&(abs(bass_pitch-np.round(bass_pitch))<.28)&(bass_flat<.04)))
    # 器乐背景休止与旋律突出：新增清楚节奏、可核实旋律或真正低音作为正证据；没有低音不等于背景。
    rhythm=regular>=POLICY['regularity_threshold']
    melody=agreement>=POLICY['melody_onset_agreement'] and changes>=POLICY['minimum_melody_changes'] and pitched_fraction>=.35 and contour>=POLICY['minimum_contour_step_fraction']
    if rhythm or melody or bass_support>.55:
        state='music';reason='regular_source_attacks' if rhythm else ('source_supported_melody' if melody else 'pitched_bass_support')
    # 器乐背景休止与旋律突出：修改，宽带噪声中偶然的候选起音也不是旋律；需同时缺少稳定本频。
    # elif noise_fraction>=POLICY['minimum_noise_fraction'] and agreement<.35:
    elif noise_fraction>=POLICY['minimum_noise_fraction'] and pitched_fraction<1-POLICY['minimum_noise_unpitched_fraction']:
        state='background';reason='diffuse_noise_without_musical_support'
    elif len(notes)>=POLICY['minimum_background_candidate_notes'] and agreement<.35 and regular<.6:
        state='background';reason='candidate_motion_without_source_attacks'
    else:
        state='ambiguous';reason='insufficient_independent_evidence'
    return {'state':state,'reason':reason,'start_seconds':round(start,6),'end_seconds':round(end,6),
        'onsets':[round(float(t),6) for t in onsets],'regularity':round(regular,5),'period':period,
        'pitched_fraction':round(pitched_fraction,5),'noise_fraction':round(noise_fraction,5),
        'candidate_notes':len(notes),'source_onset_agreement':round(agreement,5),
        'distinct_supported_pitch_classes':changes,'bass_support':round(bass_support,5),'contour_step_fraction':round(contour,5),
        'candidate_pitch_attacks':[round(pitch_attack(curve,n),4) for n in notes]}


# 器乐背景休止与旋律突出：新增窗口分类初探输出，后续区间聚合仍须保留首个可信音乐起音。
def analyze_sections(shared,vocal,guitar):
    binding=shared['input_binding']['sources'];curves={n:source_curve(binding[n]) for n in POLICY['sources'] if n in binding}
    curve=curves.get('accompaniment',curves['mix']);clock=SongClock(vocal)
    # 器乐背景休止与旋律突出：修改，新歌已在共同分析建立源主线，无历史派生账本时同样参与筛选。
    # plan_path=guitar.get('instrumental_source_backbone',{}).get('source_plan_path');notes=[];source_plan=None
    plan_path=guitar.get('instrumental_source_backbone',{}).get('source_plan_path');notes=[];source_plan=None
    # 器乐背景休止与旋律突出：新增兼容已有共享主线的原秒字段；不能要求所有历史计划都有新模型字段。
    for original in shared.get('instrumental_melody',[]):
        if 'source_start_seconds' in original or 'start_seconds' in original:
            notes.append({**original,'source_start_seconds':original.get('source_start_seconds',original.get('start_seconds'))})
    if plan_path:
        plan=read_json(plan_path);source_plan={'path':str(Path(plan_path).resolve()),'sha256':sha256(plan_path)};notes=plan['notes']
    sections=[]
    for s in shared['sections']:
        if s['kind'] not in POLICY['scope']:continue
        a,b=max(0.,clock.seconds(s['start_tick'])),min(curves['mix']['end_seconds'],clock.seconds(s['end_tick']))
        rows=[]
        for center in np.arange(a,b,POLICY['window_step_seconds']):
            start,end=max(a,center-POLICY['context_seconds']/2),min(b,center+POLICY['context_seconds']/2)
            primary=window_evidence(curve,start,end,notes,curves.get('bass'))
            original=window_evidence(curves['mix'],start,end,notes,curves.get('bass'))
            if original['state']=='music' and primary['state']!='music':primary.update(state='music',reason='original_mix_musical_support')
            rows.append({**primary,'center_seconds':round(float(center),6),'original_mix_evidence':original})
        sections.append({'kind':s['kind'],'start_seconds':round(a,6),'end_seconds':round(b,6),'windows':rows})
    return {'version':1,'policy':deepcopy(POLICY),'source_bindings':deepcopy({n:binding[n] for n in curves}),
        'vocal_sha256':fingerprint(vocal),'sections_sha256':fingerprint(shared['sections']),
        'source_plan':source_plan,'candidate_notes_sha256':fingerprint(notes),'sections':sections}


# 器乐背景休止与旋律突出：新增背景上下文闭合，仅跨越无独立音乐证据的短窗；真实长音保留待复核。
def protect_lyric_rests(intervals, vocal):
    """Automatic background proposals cannot mask an already mapped lyric note."""
    clock=SongClock(vocal);protected=[]
    for note in vocal.get('quantized_notes',[]):
        if note.get('lyric_index') is None:continue
        begin,end=note['start_tick'],note['end_tick']
        source_begin,source_end=note.get('start_seconds'),note.get('end_seconds')
        if source_begin is not None and source_end is not None:
            begin=min(begin,clock.tick(source_begin));end=max(end,clock.tick(source_end))
        if end>begin:
            protected.append((max(0,math.floor(begin/120)*120),min(clock.total_ticks,math.ceil(end/120)*120),note['id']))
    output=[];vetoes=[]
    for interval in intervals:
        begin,end=interval['start_tick'],interval['end_tick']
        overlapping=[r for r in protected if r[0]<end and r[1]>begin]
        if not overlapping:
            output.append(deepcopy(interval));continue
        fragments=[(begin,end)]
        for left,right,_ in overlapping:
            next_fragments=[]
            for a,b in fragments:
                if right<=a or left>=b:next_fragments.append((a,b));continue
                if a<left:next_fragments.append((a,left))
                if right<b:next_fragments.append((right,b))
            fragments=next_fragments
        emitted=[]
        for a,b in fragments:
            left=max(interval['start_seconds'],clock.seconds(a));right=min(interval['end_seconds'],clock.seconds(b))
            if right-left<POLICY['minimum_background_seconds']:continue
            row=deepcopy(interval);row.update(start_tick=a,end_tick=b,start_seconds=left,end_seconds=right,lyric_boundary_protected=True)
            output.append(row);emitted.append({'start_tick':a,'end_tick':b})
        vetoes.append({'original_interval':deepcopy(interval),'protected_note_ids':sorted({r[2] for r in overlapping}),
                       'remaining_intervals':emitted,'reason':'preserve_lyric_source_and_notation_intervals'})
    return output,vetoes


def aggregate_background(plan,shared,vocal,guitar):
    clock=SongClock(vocal);sources=plan['source_bindings'];curve=source_curve(sources.get('accompaniment',sources['mix']))
    intervals=[];reviews=[];step=POLICY['window_step_seconds']
    for section in plan['sections']:
        rows=section['windows'];states=[w['state'] for w in rows];size=len(rows)
        # 器乐背景休止与旋律突出：新增连续音乐确认，避免单个偶然等间隔背景攻击强制打断背景区。
        for i in range(size):
            if states[i]!='music':continue
            left=i
            while left>0 and states[left-1]=='music':left-=1
            right=i+1
            while right<size and states[right]=='music':right+=1
            if right-left<POLICY['minimum_confirmed_music_windows'] and rows[i]['reason']=='regular_source_attacks':states[i]='ambiguous'
        # 器乐背景休止与旋律突出：新增只在两侧有明确背景时闭合弱窗，或在曲首与背景相连时闭合。
        i=0
        while i<size:
            if states[i]!='ambiguous':i+=1;continue
            j=i+1
            while j<size and states[j]=='ambiguous':j+=1
            bounded_left=(i>0 and states[i-1]=='background') or (i==0 and section['kind']=='intro' and section['start_seconds']<.1)
            bounded_right=j<size and states[j]=='background'
            if bounded_left and bounded_right and (j-i)*step<=POLICY['maximum_background_bridge_seconds']:
                for k in range(i,j):states[k]='background';rows[k]['context_decision']='bounded_background_without_confirmed_melody'
            i=j
        i=0
        while i<size:
            if states[i]!='background':
                if states[i]=='ambiguous':reviews.append({'seconds':rows[i]['center_seconds'],'kind':section['kind'],'reason':rows[i]['reason']})
                i+=1;continue
            j=i+1
            while j<size and states[j]=='background':j+=1
            a=max(section['start_seconds'],rows[i]['center_seconds']-step/2)
            # 器乐背景休止与旋律突出：修改，末窗延伸至真实段尾，不能遗留无证据的半个采样步。
            # b=min(section['end_seconds'],rows[j-1]['center_seconds']+step/2)
            b=section['end_seconds'] if j==size else min(section['end_seconds'],rows[j-1]['center_seconds']+step/2)
            following=j
            while following<size and states[following]=='ambiguous':following+=1
            if following<size and states[following]=='music' and (following-j)*step<=POLICY['maximum_background_bridge_seconds']:
                # 器乐背景休止与旋律突出：新增用本地音色和真实攻击定位入乐，不把居中窗的未来证据提前到背景中。
                lo=b;hi=min(section['end_seconds'],rows[following]['center_seconds']+POLICY['context_seconds']/2)
                onsets=curve['onsets'][(curve['onsets']>=lo)&(curve['onsets']<hi)]
                tonal=[float(t) for t in onsets if np.interp(t,curve['times'],curve['flatness'])<POLICY['source_entry_flatness_maximum']]
                if tonal:b=max(b,tonal[0])
                # 器乐背景休止与旋律突出：新增保护已认可的首个音乐骨干；其记谱起音可能早于FFT窗中心。
                nearby=[n for n in guitar['notes'] if n['role']=='instrumental_melody' and abs(clock.seconds(n['start_tick'])-b)<.22]
                if nearby:b=min(b,min(clock.seconds(n['start_tick']) for n in nearby))
            # 器乐背景休止与旋律突出：新增来源明确的音乐衰减保护，结尾噪声占比增加不代表尾音须截断。
            earlier=[w for w in rows[:i] if w['state']=='music']
            decay=False
            if section['kind']=='outro' and earlier:
                before=curve['rms'][(curve['times']>=max(section['start_seconds'],a-3))&(curve['times']<a)]
                after=curve['rms'][(curve['times']>=a)&(curve['times']<b)]
                if len(before) and len(after) and np.percentile(after,75)<np.percentile(before,75)*1.2:
                    decay=True;reviews.append({'seconds':a,'kind':section['kind'],'reason':'preserve_established_musical_decay'})
            if b-a>=POLICY['minimum_background_seconds'] and not decay:
                intervals.append({'start_seconds':round(a,6),'end_seconds':round(b,6),'reason':'原音频缺少可靠旋律／规律攻击／低音支撑，背景证据连续成立。','origin':'automatic_clarity',
                    'start_tick':0 if a==0 else max(0,math.floor(clock.tick(a)/120)*120),'end_tick':min(clock.total_ticks,math.floor((clock.tick(b)+1e-3)/120)*120)})
            if decay:
                for k in range(i,j):states[k]='ambiguous';rows[k]['context_decision']='preserve_established_musical_decay'
            i=j
        section['resolved_states']=states
    if guitar.get('configuration',{}).get('instrumental_clarity_lyric_guard_version') == 1:
        intervals,vetoes=protect_lyric_rests(intervals,vocal)
        if vetoes:plan['lyric_voice_protection']={'version':1,'vetoes':vetoes,'accepted_vocal_unchanged':True}
    plan['rest_intervals']=intervals;plan['review_windows']=reviews;plan['decision']='automatic_background_filter' if intervals else 'preserve_music_and_uncertain_sections'
    return plan


# 器乐背景休止与旋律突出：新增内容寻址原音频计划；未来重导需核验声源、拍轴与分类的确定性重放。
def build_clarity_plan(shared,vocal,guitar,cache_dir):
    plan=aggregate_background(analyze_sections(shared,vocal,guitar),shared,vocal,guitar)
    path=Path(cache_dir)/('instrumental_clarity_'+fingerprint(plan)[:24]+'.json');path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists() and fingerprint(read_json(path))!=fingerprint(plan):raise ValueError('背景筛选计划被改写。')
    if not path.exists():save_json(path,plan)
    return plan,path
