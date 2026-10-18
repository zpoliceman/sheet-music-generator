"""器乐背景休止与旋律突出：独立背景休止、声部力度、实际记谱及来源篡改反例。"""
from copy import deepcopy
from pathlib import Path
from collections import Counter
import json, sys, tempfile, unittest
import xml.etree.ElementTree as ET
import numpy as np
import soundfile as sf
import mido
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'tools'),str(ROOT/'tests')]
from test_guitar_instrumental_flow import music
from test_score_export import project_from,note,char
from guitar_instrumental_expression import (derive_expression,apply_expression,validate_expression,
    settings_for,reference_vocal,expression_parent)
from guitar_instrumental_flow import apply_flow,validate_flow
from accompaniment_export import build_musicxml,guitar_row,write_midi,synthesize,SVG_NS
from accompaniment_analysis import SongClock
from score_export import save_json,sha256,build_musicxml as vocal_xml,validate_score

TEMP=ROOT/'test_outputs/accompaniment_runs/expression_tests';TEMP.mkdir(parents=True,exist_ok=True)


# 器乐背景休止与旋律突出：新增自拟C开放手型、旋律与低弦填充，正文另有一个已知不应修改的音。
def prepared(folder,intervals=(),suppress=False):
    shared,vocal,guitar=music();path=folder/'source.wav';rate=11025;t=np.arange(rate*5)/rate
    sf.write(path,.1*np.sin(2*np.pi*130.81*t),rate)
    shared['input_binding']['sources']={name:{'path':str(path),'sha256':sha256(path),'offset_seconds':0.} for name in ('mix','accompaniment')}
    guitar['notes'].append({'id':'fill','start_tick':960,'end_tick':1200,'pitch_midi':40,'string':6,'fret':0,
        'finger':0,'hand_position':1,'velocity':63,'role':'harmony','source':'arranged_lower_arpeggio','chord_id':'h0','instrumental_flow_fill':True})
    guitar['attack_events'].append({'start_tick':960,'note_ids':['fill']})
    # 器乐背景休止与旋律突出：新增用于实际渲染的完整自拟攻击字段，旧音乐夹具只为声部测试提供了最小集合。
    for event in guitar['attack_events']:
        event.update(kind='arpeggio',chord_id='h0' if event['start_tick']<1920 else 'h1',stroke=None)
    parent=folder/'parent.json';save_json(parent,{'shared_analysis':shared,'accepted_vocal_project':vocal,'arrangements':{'guitar':guitar}})
    review=folder/'review.json'
    save_json(review,{'schema_version':1,'source_mix_sha256':sha256(path),
        'rest_intervals':[{'start_seconds':a,'end_seconds':b,'reason':'自拟背景音复核'} for a,b in intervals],
        'suppress_unlyric_reference_notes':suppress})
    return shared,vocal,guitar,parent,review


class InstrumentalExpressionTests(unittest.TestCase):
    # 器乐背景休止与旋律突出：新增独立的旋律／填充力度真值，同时普通唱段、低音、音高与时间全部保持。
    def test_melody_emphasis_and_soft_fill_leave_normal_and_pitch_time_unchanged(self):
        with tempfile.TemporaryDirectory(dir=TEMP) as tmp:
            s,v,g,parent,review=prepared(Path(tmp));before=deepcopy((s,v,g))
            actual,_=apply_expression(s,v,g,parent,review);values={n['id']:n for n in actual['notes']}
            self.assertEqual(values['melody']['velocity'],106);self.assertTrue(values['melody']['melody_accent'])
            self.assertEqual(values['fill']['velocity'],50);self.assertFalse(values['fill'].get('melody_accent',False))
            for n in g['notes']:
                self.assertEqual((values[n['id']]['pitch_midi'],values[n['id']]['start_tick'],values[n['id']]['end_tick']),
                    (n['pitch_midi'],n['start_tick'],n['end_tick']))
            self.assertEqual(values['normal'],g['notes'][3]);self.assertEqual(values['bass'],g['notes'][1])
            self.assertEqual((s,v,g),before)

    # 器乐背景休止与旋律突出：新增中间休止截断／恢复需落到可读网格，真正音符不能穿过休止。
    def test_reviewed_middle_rest_splits_sustain_without_micro_notes(self):
        with tempfile.TemporaryDirectory(dir=TEMP) as tmp:
            s,v,g,parent,review=prepared(Path(tmp),[(.3,.7)])
            actual,report=apply_expression(s,v,g,parent,review)
            self.assertEqual(report['rest_tick_intervals'],[[240,720]])
            self.assertTrue(any(n['id']=='melody_expression_part_2' and n['start_tick']==720 for n in actual['notes']))
            self.assertTrue(all(n['end_tick']<=240 or n['start_tick']>=720 for n in actual['notes'] if n['start_tick']<1920))
            self.assertTrue(all((n['end_tick']-n['start_tick'])>=120 for n in actual['notes']))
            self.assertTrue(validate_expression(s,v,actual)['valid'])

    # 器乐背景休止与旋律突出：新增空复核不是默认删前段，任何歌曲没有复核都保留原有旋律和完整音数。
    def test_no_review_has_no_default_silence(self):
        with tempfile.TemporaryDirectory(dir=TEMP) as tmp:
            s,v,g,parent,_=prepared(Path(tmp));actual,report=apply_expression(s,v,g,parent)
            self.assertEqual({n['id'] for n in actual['notes']},{n['id'] for n in g['notes']})
            self.assertFalse(report['removed_note_ids']);self.assertFalse(report['rest_tick_intervals'])

    # 器乐背景休止与旋律突出：新增正文内的主旋律型填句仍采用原力度，不把角色标签当全部段落的加重命令。
    def test_instrumental_role_in_vocal_section_is_not_automatically_accented(self):
        with tempfile.TemporaryDirectory(dir=TEMP) as tmp:
            s,v,g,_,review=prepared(Path(tmp));g['notes'][3]['role']='instrumental_melody';g['notes'][3]['instrumental_flow_fill']=True
            actual,_=derive_expression(s,v,g,settings_for(s,v,review))
            self.assertEqual(next(n for n in actual['notes'] if n['id']=='normal'),g['notes'][3])

    # 器乐背景休止与旋律突出：新增不在复核内的原有细节音不被顺手删除，表现层没有未授权节奏简化。
    def test_existing_short_notes_outside_rest_are_preserved(self):
        with tempfile.TemporaryDirectory(dir=TEMP) as tmp:
            s,v,g,_,review=prepared(Path(tmp));g['notes'][0]['end_tick']=60
            actual,report=derive_expression(s,v,g,settings_for(s,v,review))
            self.assertFalse(report['removed_note_ids']);self.assertEqual(next(n for n in actual['notes'] if n['id']=='melody')['end_tick'],60)

    # 器乐背景休止与旋律突出：新增已经很强的主音不因新目标上限而减弱。
    def test_existing_maximum_velocity_is_not_lowered(self):
        with tempfile.TemporaryDirectory(dir=TEMP) as tmp:
            s,v,g,_,review=prepared(Path(tmp));g['notes'][0]['velocity']=127
            actual,_=derive_expression(s,v,g,settings_for(s,v,review));self.assertEqual(next(n for n in actual['notes'] if n['id']=='melody')['velocity'],127)

    # 器乐背景休止与旋律突出：新增实际XML跨小节续音只在首个音符有重音，不能被误写成断奏或重拨。
    def test_xml_accent_only_on_first_fragment_not_staccato(self):
        with tempfile.TemporaryDirectory(dir=TEMP) as tmp:
            # 器乐背景休止与旋律突出：修改，旧测试边界2000含20tick不可记谱残片；改为真实十六分跨小节120tick。
            # s,v,g,_,review=prepared(Path(tmp));g['notes'][0]['end_tick']=2000
            s,v,g,_,review=prepared(Path(tmp));g['notes'][0]['end_tick']=2040
            g['notes'][3].update(pitch_midi=59,string=2,fret=0)
            actual,_=derive_expression(s,v,g,settings_for(s,v,review));root,mapping=build_musicxml(s,v,actual)
            fragments=[n for n in root.findall('part/measure/note') if mapping.get(n.get('id'))=='melody']
            accents=[n for n in fragments if n.find('notations/articulations/accent') is not None]
            self.assertEqual(len(accents),1);self.assertTrue(accents[0].get('id').endswith('_fragment_0'))
            self.assertFalse(root.findall('.//staccato'));self.assertGreater(len(fragments),1)

    # 器乐背景休止与旋律突出：新增实际SVG黑点坐标与对应主旋律音对齐，填充／续音不冒充重音。
    def test_visible_dot_matches_melody_start_and_x(self):
        with tempfile.TemporaryDirectory(dir=TEMP) as tmp:
            s,v,g,parent,review=prepared(Path(tmp));actual,_=apply_expression(s,v,g,parent,review)
            root=ET.fromstring(guitar_row(s,v,actual,1,2));ns='{'+SVG_NS+'}'
            dots=[n for n in root.iter(ns+'circle') if n.get('class')=='melody-accent']
            self.assertEqual([d.get('data-note-id') for d in dots],['melody'])
            group=next(n for n in root.iter(ns+'g') if n.get('id')=='melody')
            self.assertEqual(float(dots[0].get('cx')),float(group.find(ns+'text').get('x')))
            self.assertEqual(dots[0].get('fill'),'black');self.assertEqual(dots[0].get('data-start-tick'),'0')

    # 器乐背景休止与旋律突出：新增真实SMF的音量／起音核验，显示黑点与实际力度必须一起改变。
    def test_actual_midi_has_emphasis_soft_fill_and_no_attacks_in_rest(self):
        with tempfile.TemporaryDirectory(dir=TEMP) as tmp:
            path=Path(tmp);s,v,g,parent,review=prepared(path,[(0.,.5)])
            actual,_=apply_expression(s,v,g,parent,review);write_midi(path/'actual.mid',actual,v)
            attacks=[]
            for track in mido.MidiFile(path/'actual.mid').tracks:
                tick=0
                for message in track:
                    tick+=message.time
                    if message.type=='note_on' and message.velocity:attacks.append((tick,message.note,message.velocity))
            self.assertTrue(all(t>=480 for t,_,_ in attacks))
            # 器乐背景休止与旋律突出：修改，旧测试把普通和声音70误写为旋律90，真实正文力度必须保持70。
            # self.assertIn((480,64,106),attacks);self.assertIn((960,40,50),attacks);self.assertIn((1920,64,90),attacks)
            self.assertIn((480,64,106),attacks);self.assertIn((960,40,50),attacks);self.assertIn((1920,64,70),attacks)
            self.assertEqual(Counter(attacks),Counter((n['start_tick'],n['pitch_midi'],n['velocity']) for n in actual['notes']))

    # 器乐背景休止与旋律突出：新增真实PCM静音与正文基准增益保护，整体归一化不能把所有普通音被动放大。
    def test_actual_preview_silence_and_normal_part_reference_gain(self):
        with tempfile.TemporaryDirectory(dir=TEMP) as tmp:
            path=Path(tmp);s,v,g,parent,review=prepared(path,[(0.,.5)])
            actual,_=apply_expression(s,v,g,parent,review)
            synthesize(path/'old.wav',g,v);metadata=synthesize(path/'new.wav',actual,v)
            before,rate=sf.read(path/'old.wav');after,_=sf.read(path/'new.wav')
            self.assertTrue(np.all(after[:round(.5*rate)]==0))
            self.assertEqual(metadata['headroom_scale'],1.)
            self.assertLessEqual(float(np.abs(before[round(2.1*rate):round(2.2*rate)]-after[round(2.1*rate):round(2.2*rate)]).max()),1/32768)

    # 器乐背景休止与旋律突出：新增幂等及真实力度／黑点篡改拒绝，不允许重复执行不断改变音量。
    def test_idempotence_and_velocity_accent_tampering_rejected(self):
        with tempfile.TemporaryDirectory(dir=TEMP) as tmp:
            s,v,g,parent,review=prepared(Path(tmp));actual,_=apply_expression(s,v,g,parent,review)
            again,_=apply_expression(s,v,actual,parent,review);self.assertEqual(actual,again)
            for field,value in (('velocity',1),('melody_accent',False)):
                tampered=deepcopy(actual);next(n for n in tampered['notes'] if n['id']=='melody')[field]=value
                self.assertFalse(validate_expression(s,v,tampered)['valid'])
            tampered=deepcopy(actual);next(n for n in tampered['notes'] if n['id']=='normal')['velocity']=100
            self.assertFalse(validate_expression(s,v,tampered)['valid'])

    # 器乐背景休止与旋律突出：新增真实父文件和人工复核改写后拒绝，不能凭缓存元数据蒙混通过。
    def test_parent_and_review_file_tampering_rejected(self):
        with tempfile.TemporaryDirectory(dir=TEMP) as tmp:
            s,v,g,parent,review=prepared(Path(tmp));actual,_=apply_expression(s,v,g,parent,review)
            review.write_text(review.read_text('utf-8')+' ','utf-8');self.assertFalse(validate_expression(s,v,actual)['valid'])
        with tempfile.TemporaryDirectory(dir=TEMP) as tmp:
            s,v,g,parent,review=prepared(Path(tmp));actual,_=apply_expression(s,v,g,parent,review)
            parent.write_text(parent.read_text('utf-8')+' ','utf-8');self.assertFalse(validate_expression(s,v,actual)['valid'])

    # 器乐背景休止与旋律突出：新增错误录音SHA和正文／越界／逆序窗口拒绝，复核不能跨歌曲强套。
    def test_wrong_source_and_invalid_or_vocal_rest_windows_rejected(self):
        with tempfile.TemporaryDirectory(dir=TEMP) as tmp:
            s,v,g,parent,review=prepared(Path(tmp));data=json.loads(review.read_text('utf-8'));original=deepcopy(data)
            data['source_mix_sha256']='0'*64;save_json(review,data)
            with self.assertRaisesRegex(ValueError,'SHA'):apply_expression(s,v,g,parent,review)
            for intervals in ([(2.,3.)],[(-1.,.5)],[(1.,.2)],[(0.,5.)],[(0.,1.),(.5,1.5)]):
                data=deepcopy(original);data['rest_intervals']=[{'start_seconds':a,'end_seconds':b} for a,b in intervals];save_json(review,data)
                with self.subTest(intervals=intervals),self.assertRaises(ValueError):apply_expression(s,v,g,parent,review)

    # 器乐背景休止与旋律突出：新增真实原低弦来源链依旧核验，表现不是绕过旧音高／来源账本的出口。
    def test_old_flow_chain_still_checked_and_ledger_removal_rejected(self):
        with tempfile.TemporaryDirectory(dir=TEMP) as tmp:
            path=Path(tmp);s,v,g,parent,review=prepared(path)
            flow,_=apply_flow(s,v,g,parent,path/'features');flow_parent=path/'flow.json'
            save_json(flow_parent,{'shared_analysis':s,'accepted_vocal_project':v,'arrangements':{'guitar':flow}})
            actual,_=apply_expression(s,v,flow,flow_parent,review)
            self.assertTrue(validate_flow(s,v,actual,replay=True)['valid'])
            tampered=deepcopy(actual);tampered.pop('instrumental_flow')
            self.assertFalse(validate_expression(s,v,tampered)['valid'])
            s['input_binding']['sources']['accompaniment']['path']=str(path/'changed.wav')
            self.assertFalse(validate_flow(s,v,actual,replay=True)['valid'])

    # 器乐背景休止与旋律突出：新增参考行仅删除复核背景中的无歌词音，真实歌词／认可快照／节拍不改。
    def test_reference_suppresses_only_unlyric_background_with_valid_xml(self):
        with tempfile.TemporaryDirectory(dir=TEMP) as tmp:
            s,old,g,parent,review=prepared(Path(tmp),[(0.,1.)],True)
            p=project_from([note('wind',.2,.5,77),note('voice',2.2,2.5,64)],[char(0,'春',2.2,2.5)],4)
            p['timing']=deepcopy(old['timing']);p['lyrics']={'characters':[char(0,'春',2.2,2.5)]}
            p['notation']=deepcopy(old['notation'])
            self.assertTrue(any(n.get('lyric_index') is None for n in p['quantized_notes']))
            save_json(parent,{'shared_analysis':s,'accepted_vocal_project':p,'arrangements':{'guitar':g}})
            actual,_=apply_expression(s,p,g,parent,review);before=deepcopy(p);reference=reference_vocal(p,actual)
            self.assertEqual(p,before);self.assertEqual(reference['timing'],p['timing'])
            self.assertEqual([n for n in reference['quantized_notes'] if n.get('lyric_index') is not None],
                [n for n in p['quantized_notes'] if n.get('lyric_index') is not None])
            self.assertEqual(len(reference['instrumental_expression_reference']['excluded_unlyric_note_ids']),1)
            self.assertTrue(validate_score(reference,vocal_xml(reference))['valid'])
            self.assertEqual(reference['lyrics'],p['lyrics'])

    # 器乐背景休止与旋律突出：新增有挂词人声的背景假标记拒绝，不能以清理风铃为由删唱词。
    def test_reference_review_cannot_suppress_real_lyric_notes(self):
        with tempfile.TemporaryDirectory(dir=TEMP) as tmp:
            s,v,g,parent,review=prepared(Path(tmp),[(0.,1.)],True)
            with self.assertRaisesRegex(ValueError,'挂歌词'):apply_expression(s,v,g,parent,review)

    # 器乐背景休止与旋律突出：新增源攻击身份事件的真实兼容反例，不能丢失正常右手型／四分时值。
    def test_normal_source_identity_events_keep_all_pattern_fields(self):
        with tempfile.TemporaryDirectory(dir=TEMP) as tmp:
            path=Path(tmp);s,v,g,parent,review=prepared(path,[(0.,.5)])
            event=next(e for e in g['attack_events'] if e['start_tick']==1920)
            event.pop('note_ids');event.update(source_note_ids=['original_attack_a'],right_hand_duration_ticks=480,
                right_hand_duration_source='regular_pattern_slot',right_hand_pattern_id='arp_4_4_sparse',right_hand_slot=0)
            save_json(parent,{'shared_analysis':s,'accepted_vocal_project':v,'arrangements':{'guitar':g}})
            actual,_=apply_expression(s,v,g,parent,review)
            group=[e for e in actual['attack_events'] if e['start_tick']==1920]
            self.assertEqual(group,[event]);self.assertTrue(validate_expression(s,v,actual)['valid'])
            changed=deepcopy(actual);group=next(e for e in changed['attack_events'] if e['start_tick']==1920);group['right_hand_duration_ticks']=240
            self.assertFalse(validate_expression(s,v,changed)['valid'])


if __name__=='__main__':unittest.main(verbosity=2)
