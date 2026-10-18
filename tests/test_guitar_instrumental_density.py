"""器乐填充密度随主体伴奏：新增真实攻击格、上下文、持音恢复及来源篡改反例。"""
from pathlib import Path
from copy import deepcopy
import tempfile,sys,unittest
import numpy as np
import soundfile as sf
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT/'tools'),str(ROOT/'tests')]
from test_guitar_instrumental_flow import music,plan
from guitar_instrumental_density import build_density_plan,summarize
from guitar_instrumental_flow import apply_flow,validate_flow,arrange_flow
from guitar_instrumental_register import fingerprint
from score_export import save_json,read_json,sha256
from accompaniment_export import build_musicxml,parse_musicxml_notes,write_midi,validate_midi

TEMP=ROOT/'test_outputs/accompaniment_runs/instrumental_density_tests';TEMP.mkdir(parents=True,exist_ok=True)


# 器乐填充密度随主体伴奏：新增自拟C调正文，所有事件都有独立已知右手时值，持续音与攻击数分开。
def with_ordinary(durations):
    s,v,g=music();g['notes']=[n for n in g['notes'] if n['id']!='normal'];g['attack_events']=[g['attack_events'][0]]
    tick=1920
    for i,d in enumerate(durations):
        pid={120:'arp_4_4_sixteenth_up',240:'arp_4_4_up',480:'arp_4_4_sparse'}[d]
        n={'id':f'ordinary_{i}','pitch_midi':64,'string':1,'fret':0,'finger':0,'hand_position':1,
            'start_tick':tick,'end_tick':tick+d,'velocity':70,'role':'harmony','source':'self_composed',
            'chord_id':'h1','right_hand_pattern_id':pid,'right_hand_slot':0}
        g['notes'].append(n);g['attack_events'].append({'start_tick':tick,'kind':'arpeggio','chord_id':'h1','stroke':None,
            'source_note_ids':[n['id']],'right_hand_pattern_id':pid,'right_hand_duration_ticks':d,'right_hand_duration_source':'regular_pattern_slot'})
        tick+=d
    s['sections'][1]['end_tick']=tick;v['statistics'].update(total_ticks=tick,measure_count=(tick+1919)//1920)
    return s,v,g


def adaptive_plan(s,v,g,activity=None):
    p=plan(s,activity);p['density_plan']=build_density_plan(s,v,g);return p


class InstrumentalDensityTests(unittest.TestCase):
    def test_quarter_backing_selects_quarter_fill(self):
        s,v,g=with_ordinary([480]*16);p=build_density_plan(s,v,g)
        self.assertEqual(p['global_density']['step_ticks'],480);self.assertEqual(p['instrumental_profiles'][0]['step_ticks'],480)

    def test_eighth_backing_selects_eighth_fill(self):
        s,v,g=with_ordinary([240]*32);self.assertEqual(build_density_plan(s,v,g)['global_density']['step_ticks'],240)

    def test_sustained_sixteenth_backing_selects_sixteenth_fill(self):
        s,v,g=with_ordinary([120]*64);self.assertEqual(build_density_plan(s,v,g)['global_density']['step_ticks'],120)

    # 器乐填充密度随主体伴奏：新增混合型反例，短音数量更多不代表基本密度为十六分。
    def test_eighth_sixteenth_mixed_uses_eighth_base(self):
        s,v,g=with_ordinary([240,120,120]*16);self.assertEqual(build_density_plan(s,v,g)['global_density']['step_ticks'],240)

    def test_simultaneous_chord_tones_count_as_one_attack(self):
        s,v,g=with_ordinary([480]*16);before=build_density_plan(s,v,g)
        for n in list(g['notes']):
            if n['id'].startswith('ordinary_'):
                for i in range(3):g['notes'].append({**n,'id':n['id']+f'_chord_{i}'})
        self.assertEqual(build_density_plan(s,v,g),before)

    def test_string_sustain_duration_does_not_determine_attack_density(self):
        s,v,g=with_ordinary([240]*32);before=build_density_plan(s,v,g)
        for n in g['notes']:
            if n['id'].startswith('ordinary_'):n['end_tick']+=1440
        self.assertEqual(build_density_plan(s,v,g),before)

    def test_instrumental_feature_in_vocal_section_cannot_speed_up_fill(self):
        s,v,g=with_ordinary([480]*16);before=build_density_plan(s,v,g)
        for i in range(30):
            t=1980+i*120;g['notes'].append({**g['notes'][0],'id':f'feature_{i}','role':'instrumental_melody','start_tick':t,'end_tick':t+120})
            g['attack_events'].append({'start_tick':t,'right_hand_duration_ticks':120,'right_hand_duration_source':'regular_pattern_slot'})
        self.assertEqual(build_density_plan(s,v,g),before)

    def test_short_fast_exception_does_not_change_quarter_song(self):
        s,v,g=with_ordinary([480]*16+[120]*4);self.assertEqual(build_density_plan(s,v,g)['global_density']['step_ticks'],480)

    def test_insufficient_body_evidence_keeps_historical_fallback(self):
        s,v,g=with_ordinary([480]*2);p=build_density_plan(s,v,g)
        self.assertFalse(p['global_density']['reliable']);self.assertEqual(p['global_density']['step_ticks'],240)

    def test_no_body_patterns_has_no_song_name_default(self):
        s,v,g=music();p=build_density_plan(s,v,g);self.assertEqual(p['global_density']['step_ticks'],240)
        s['title']='任意其他歌曲';v['title']='Changed';self.assertEqual(build_density_plan(s,v,g),p)

    # 器乐填充密度随主体伴奏：新增相邻段不同密度，前奏／间奏准备后段，尾奏沿用前段，段内不逐和弦切换。
    def test_nearest_stable_section_is_used_once_for_whole_instrumental(self):
        s,v,g=with_ordinary([480]*8+[240]*16)
        s['sections']=[{'kind':'intro','start_tick':0,'end_tick':1920},{'kind':'vocal','start_tick':1920,'end_tick':5760},
            {'kind':'interlude','start_tick':5760,'end_tick':7680},{'kind':'vocal','start_tick':7680,'end_tick':11520},
            {'kind':'outro','start_tick':11520,'end_tick':13440}]
        for e in g['attack_events']:
            if e['start_tick']>=5760:e['start_tick']+=1920
        for n in g['notes']:
            if n['start_tick']>=5760:n['start_tick']+=1920;n['end_tick']+=1920
        p=build_density_plan(s,v,g);self.assertEqual([x['step_ticks'] for x in p['instrumental_profiles']],[480,240,240])

    def test_compound_meter_keeps_eighth_unit_or_whole_compound_pulse(self):
        rows=[{'duration_ticks':240}]*24;self.assertEqual(summarize(rows,[6,8])['step_ticks'],240)
        self.assertEqual(summarize([{'duration_ticks':720}]*12,[6,8])['step_ticks'],720)

    def test_quarter_fill_only_starts_on_quarter_grid(self):
        s,v,g=with_ordinary([480]*16);a,r=arrange_flow(s,v,g,adaptive_plan(s,v,g));fills=[n for n in a['notes'] if n.get('instrumental_flow_fill')]
        self.assertTrue(fills);self.assertTrue(all(n['start_tick']%480==0 for n in fills));self.assertTrue(all(n['flow_pattern']=='lower_common_480_ticks' for n in fills))
        self.assertGreater(len({n['pitch_midi']%12 for n in fills}),1)
        self.assertEqual([n for n in a['notes'] if n['id'].startswith('ordinary_')],[n for n in g['notes'] if n['id'].startswith('ordinary_')])

    # 器乐填充密度随主体伴奏：新增正确弱拍旋律已覆盖该格时，不额外插入强拍低音造成两次攻击。
    def test_existing_offbeat_melody_consumes_quarter_slot(self):
        s,v,g=with_ordinary([480]*16);g['notes'][0]['end_tick']=480
        g['notes'].append({**g['notes'][0],'id':'offbeat_lead','start_tick':600,'end_tick':720})
        a,_=arrange_flow(s,v,g,adaptive_plan(s,v,g));self.assertFalse(any(n.get('instrumental_flow_fill') and n['start_tick']==480 for n in a['notes']))

    def test_rest_and_ringout_still_exclude_all_new_fill(self):
        s,v,g=with_ordinary([480]*16);activity=[{'start_seconds':0,'end_seconds':10,'state':'source_rest'}]
        # 器乐填充密度随主体伴奏：修改，夹具原列表未按同刻ID排序，按音符身份验证实际字段不变；原断言保留。
        # a,r=arrange_flow(s,v,g,adaptive_plan(s,v,g,activity));self.assertEqual(r['added_notes'],0);self.assertEqual(a['notes'],g['notes'])
        a,r=arrange_flow(s,v,g,adaptive_plan(s,v,g,activity));self.assertEqual(r['added_notes'],0)
        self.assertEqual({n['id']:n for n in a['notes']},{n['id']:n for n in g['notes']})

    # 器乐填充密度随主体伴奏：新增真实填充前来源恢复，不能只删除旧填音却把原低音截断遗留。
    def test_upgrade_restores_original_sustain_before_refilling_and_is_idempotent(self):
        with tempfile.TemporaryDirectory(dir=TEMP) as tmp:
            folder=Path(tmp);s,v,g=with_ordinary([480]*16);wave=folder/'tone.wav';time=np.arange(14*11025)/11025
            sf.write(wave,.1*np.sin(2*np.pi*130.81*time),11025);s['input_binding']={'sources':{'accompaniment':{'path':str(wave),'sha256':sha256(wave),'offset_seconds':0}}}
            parent=folder/'base.json';save_json(parent,{'shared_analysis':s,'accepted_vocal_project':v,'arrangements':{'guitar':g}})
            legacy,_=apply_flow(s,v,g,parent,folder/'v1');previous=folder/'legacy.json';save_json(previous,{'shared_analysis':s,'accepted_vocal_project':v,'arrangements':{'guitar':legacy}})
            actual,_=apply_flow(s,v,legacy,previous,folder/'v2',follow_density=True)
            self.assertEqual(actual['instrumental_flow']['version'],2);self.assertTrue(validate_flow(s,v,actual,replay=True)['valid'])
            self.assertGreater(next(n['end_tick'] for n in actual['notes'] if n['id']=='bass'),next(n['end_tick'] for n in legacy['notes'] if n['id']=='bass'))
            again,_=apply_flow(s,v,actual,previous,folder/'v2',follow_density=True);self.assertEqual(again,actual)
            corrupt=deepcopy(actual);path=Path(corrupt['instrumental_flow']['activity_plan_path']);p=read_json(path)
            p['density_plan']['instrumental_profiles'][0]['step_ticks']=120;save_json(path,p);corrupt['instrumental_flow']['activity_plan_sha256']=sha256(path)
            self.assertFalse(validate_flow(s,v,corrupt)['valid']);self.assertTrue(validate_flow(s,v,legacy,replay=True)['valid'])

    def test_quarter_density_actual_xml_midi_match_and_melody_holds(self):
        s,v,g=with_ordinary([480]*16);a,_=arrange_flow(s,v,g,adaptive_plan(s,v,g));root,_=build_musicxml(s,v,a);notes,check=parse_musicxml_notes(root)
        self.assertTrue(check['valid']);self.assertEqual(notes['melody']['end_tick'],960)
        with tempfile.TemporaryDirectory(dir=TEMP) as tmp:
            path=Path(tmp)/'score.mid';write_midi(path,a,v);self.assertTrue(validate_midi(path,a,v)['valid'])


if __name__=='__main__':unittest.main(verbosity=2)
