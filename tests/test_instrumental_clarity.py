"""器乐背景休止与旋律突出：新增自拟原音频反例，验证通用自动筛选而非手填时间。"""
from copy import deepcopy
from pathlib import Path
import sys,tempfile,unittest
import numpy as np
import soundfile as sf
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT/'tools'),str(ROOT/'tests')]
from test_guitar_instrumental_flow import music
from instrumental_clarity import build_clarity_plan,source_curve,window_evidence,onset_regularity
from guitar_instrumental_expression import apply_expression,validate_expression
from score_export import save_json,sha256

TEMP=ROOT/'test_outputs/accompaniment_runs/clarity_tests';TEMP.mkdir(parents=True,exist_ok=True)


# 器乐背景休止与旋律突出：新增独立音乐生成真值，可替换任意曲名／节拍，不含实际歌曲答案。
def tone_wave(duration,events,rate=11025):
    output=np.zeros(round(duration*rate))
    for start,end,pitch in events:
        a,b=round(start*rate),round(end*rate);t=np.arange(b-a)/rate
        f=440*2**((pitch-69)/12);envelope=np.minimum(1,t/.01)*np.exp(-t*2)
        for k,amp in ((1,.1),(2,.028),(3,.01)):
            output[a:b]+=amp*np.sin(2*np.pi*f*k*t)*envelope
    return output


def fixture(folder,wave,events=(),kind='intro',offset=0.):
    s,v,g=music();duration=len(wave)/11025;end=round(duration*960)
    v['statistics'].update(total_ticks=end,bar_ticks=1920,measure_count=(end+1919)//1920);v['quantized_notes']=[]
    s['sections']=[{'kind':kind,'start_tick':0,'end_tick':end}]
    source=folder/'original.wav';sf.write(source,wave,11025)
    s['input_binding']['sources']={name:{'path':str(source),'sha256':sha256(source),'offset_seconds':offset} for name in ('mix','accompaniment')}
    s['instrumental_melody']=[dict(source_start_seconds=a+offset,source_end_seconds=b+offset,pitch_midi=p) for a,b,p in events]
    g['notes']=[n for n in g['notes'] if n['role']!='instrumental_melody']
    for i,(a,b,p) in enumerate(events):
        # 器乐背景休止与旋律突出：新增仅用于边界保护的实际音乐起音，不让假背景吉他音影响原曲判断。
        g['notes'].append(dict(id=f'lead_{i}',start_tick=round((a+offset)*960),end_tick=round((b+offset)*960),role='instrumental_melody',pitch_midi=p))
    return s,v,g,source


class InstrumentalClarityTests(unittest.TestCase):
    # 器乐背景休止与旋律突出：新增原噪声自动判别，无任何人工休止区间。
    def test_broadband_background_is_automatically_filtered(self):
        with tempfile.TemporaryDirectory(dir=TEMP) as tmp:
            folder=Path(tmp);wave=np.random.default_rng(41).normal(0,.035,11025*8)
            s,v,g,_=fixture(folder,wave);plan,_=build_clarity_plan(s,v,g,folder/'cache')
            self.assertEqual(len(plan['rest_intervals']),1);self.assertEqual(plan['rest_intervals'][0]['start_seconds'],0.)
            self.assertGreater(plan['rest_intervals'][0]['end_seconds'],7.5)

    # 器乐背景休止与旋律突出：新增薄音色／没有低音的规整高旋律，不能被当风铃整体删除。
    def test_high_sparse_regular_melody_without_bass_is_kept(self):
        with tempfile.TemporaryDirectory(dir=TEMP) as tmp:
            folder=Path(tmp);events=[(.2+i*.55,.65+i*.55,82+(i%4)*2) for i in range(12)]
            s,v,g,_=fixture(folder,tone_wave(8,events),events);plan,_=build_clarity_plan(s,v,g,folder/'cache')
            self.assertFalse(plan['rest_intervals']);self.assertTrue(any(w['state']=='music' for w in plan['sections'][0]['windows']))

    # 器乐背景休止与旋律突出：新增自由节奏的清楚级进旋律，由真实起音／连贯音序保护而非强制套拍。
    def test_clear_free_time_melody_is_kept(self):
        with tempfile.TemporaryDirectory(dir=TEMP) as tmp:
            folder=Path(tmp);starts=[.2,.71,1.58,2.14,3.39,4.92,5.6];pitches=[76,77,79,81,79,77,76]
            events=[(a,a+.42,p) for a,p in zip(starts,pitches)]
            s,v,g,_=fixture(folder,tone_wave(8,events),events);plan,_=build_clarity_plan(s,v,g,folder/'cache')
            self.assertFalse(plan['rest_intervals'])

    # 器乐背景休止与旋律突出：新增持续单音仅可判证据不足，不能因没有重弹判成杂乱背景。
    def test_long_held_pure_note_remains_for_review(self):
        with tempfile.TemporaryDirectory(dir=TEMP) as tmp:
            folder=Path(tmp);t=np.arange(8*11025)/11025;wave=.05*np.sin(2*np.pi*880*t)
            s,v,g,_=fixture(folder,wave,[(0,8,81)]);plan,_=build_clarity_plan(s,v,g,folder/'cache')
            self.assertFalse(plan['rest_intervals']);self.assertTrue(plan['review_windows'])

    # 器乐背景休止与旋律突出：新增反相立体声选择有效通道，避免声道相消产生假背景／休止。
    def test_antiphase_stereo_does_not_disappear(self):
        with tempfile.TemporaryDirectory(dir=TEMP) as tmp:
            folder=Path(tmp);t=np.arange(4*11025)/11025;wave=.1*np.sin(2*np.pi*440*t)
            s,v,g,source=fixture(folder,np.stack([wave,-wave],axis=1));curve=source_curve(s['input_binding']['sources']['mix'])
            self.assertGreater(float(np.median(curve['rms'])),.06)
            self.assertLess(abs(float(np.median(curve['pitch']))-69),.1)

    # 器乐背景休止与旋律突出：新增背景在乐段中间的通用筛选，不能只识别曲首。
    def test_noise_only_interlude_is_screened_too(self):
        with tempfile.TemporaryDirectory(dir=TEMP) as tmp:
            folder=Path(tmp);wave=np.random.default_rng(9).normal(0,.03,11025*6)
            s,v,g,_=fixture(folder,wave,kind='interlude');plan,_=build_clarity_plan(s,v,g,folder/'cache')
            self.assertTrue(plan['rest_intervals'])

    # 器乐背景休止与旋律突出：新增源秒偏移仍正确，真实音轨偏移不是固定开始时刻。
    def test_source_time_offset_is_respected(self):
        with tempfile.TemporaryDirectory(dir=TEMP) as tmp:
            folder=Path(tmp);wave=np.random.default_rng(8).normal(0,.03,11025*6)
            s,v,g,_=fixture(folder,wave,kind='interlude',offset=2.)
            s['sections'][0].update(start_tick=1920,end_tick=7680);v['statistics']['total_ticks']=7680
            plan,_=build_clarity_plan(s,v,g,folder/'cache');self.assertGreaterEqual(plan['rest_intervals'][0]['start_seconds'],2.)

    # 器乐背景休止与旋律突出：新增谱首真实音乐边界保护，分析窗口不能提前吃掉或延后移走首音。
    def test_noise_to_music_boundary_preserves_first_music_attack(self):
        with tempfile.TemporaryDirectory(dir=TEMP) as tmp:
            folder=Path(tmp);events=[(4.25+i*.5,4.65+i*.5,64+(i%3)*2) for i in range(10)]
            wave=tone_wave(10,events);wave[:4*11025]=np.random.default_rng(2).normal(0,.04,4*11025)
            s,v,g,_=fixture(folder,wave,events);plan,_=build_clarity_plan(s,v,g,folder/'cache')
            self.assertTrue(plan['rest_intervals']);self.assertLessEqual(plan['rest_intervals'][0]['end_seconds'],4.25)
            self.assertLessEqual(plan['rest_intervals'][0]['end_tick'],4080)

    # 器乐背景休止与旋律突出：新增孤立节奏不足以套模板，至少重复多个实际攻击。
    def test_fewer_than_five_source_attacks_cannot_certify_regular_music(self):
        self.assertEqual(onset_regularity(np.array([.2,.7,1.2,1.7])),(0.,None))
        self.assertEqual(onset_regularity(np.arange(.2,3,.5))[0],1.)

    # 器乐背景休止与旋律突出：新增原声／自动计划篡改拒绝；缓存元数据不能代替重新判别。
    def test_automatic_expression_replays_audio_and_rejects_tampering(self):
        with tempfile.TemporaryDirectory(dir=TEMP) as tmp:
            folder=Path(tmp);s,v,g=music();source=folder/'source.wav'
            sf.write(source,np.random.default_rng(15).normal(0,.03,11025*5),11025)
            s['input_binding']['sources']={n:{'path':str(source),'sha256':sha256(source),'offset_seconds':0} for n in ('mix','accompaniment')}
            v['quantized_notes']=[];parent=folder/'parent.json';save_json(parent,{'shared_analysis':s,'accepted_vocal_project':v,'arrangements':{'guitar':g}})
            actual,_=apply_expression(s,v,g,parent,clarity_dir=folder/'cache');info=actual['instrumental_expression']
            self.assertIsNone(info['review_path']);self.assertTrue(info['settings']['rest_intervals']);self.assertTrue(validate_expression(s,v,actual,replay=True)['valid'])
            plan=Path(info['clarity_plan_path']);plan.write_text(plan.read_text('utf-8')+' ','utf-8')
            self.assertFalse(validate_expression(s,v,actual,replay=True)['valid'])
            sf.write(source,np.ones(11025*5)*.03,11025)
            self.assertFalse(validate_expression(s,v,actual,replay=True)['valid'])

    # 器乐背景休止与旋律突出：新增声源路径内容变更直接拒绝，不使用旧缓存伪造稳定谱。
    def test_source_audio_changed_is_rejected(self):
        with tempfile.TemporaryDirectory(dir=TEMP) as tmp:
            folder=Path(tmp);s,v,g,source=fixture(folder,np.ones(11025*4)*.01)
            sf.write(source,np.ones(11025*4)*.02,11025)
            with self.assertRaisesRegex(ValueError,'指纹'):build_clarity_plan(s,v,g,folder/'cache')

    # 器乐背景休止与旋律突出：新增慢变、无规则旋律的风铃共振与噪声，不能把模型换频候选当新旋律。
    def test_random_chime_resonances_with_noise_are_screened(self):
        with tempfile.TemporaryDirectory(dir=TEMP) as tmp:
            folder=Path(tmp);rng=np.random.default_rng(81);time=np.arange(10*11025)/11025
            wave=rng.normal(0,.025,len(time))
            for freq,center,width in ((311.7,1.8,1.2),(847.4,3.4,1.3),(1303.1,6.6,1.7)):
                wave+=.035*np.sin(2*np.pi*freq*time)*np.exp(-((time-center)/width)**2)
            events=[(.7,1.2,73),(1.5,1.9,91),(2.7,3.1,62),(3.6,4.2,88),(5.1,5.8,65),(7.4,8.1,93)]
            s,v,g,_=fixture(folder,wave,events);plan,_=build_clarity_plan(s,v,g,folder/'cache')
            self.assertTrue(plan['rest_intervals']);self.assertGreater(sum(r['end_seconds']-r['start_seconds'] for r in plan['rest_intervals']),6)

    # 器乐背景休止与旋律突出：新增分离失败的伴奏轨不能否定原混音中的清楚音乐。
    def test_original_mix_music_vetoes_noisy_separation(self):
        with tempfile.TemporaryDirectory(dir=TEMP) as tmp:
            folder=Path(tmp);events=[(.2+i*.5,.63+i*.5,72+(i%3)*2) for i in range(14)]
            s,v,g,_=fixture(folder,tone_wave(8,events),events);separated=folder/'noisy.wav'
            sf.write(separated,np.random.default_rng(13).normal(0,.03,8*11025),11025)
            s['input_binding']['sources']['accompaniment']={'path':str(separated),'sha256':sha256(separated),'offset_seconds':0}
            plan,_=build_clarity_plan(s,v,g,folder/'cache');self.assertFalse(plan['rest_intervals'])


if __name__=='__main__':unittest.main(verbosity=2)
