"""吉他器乐低把位与指型复用：新增跨调、持续音、重复动机、八度和来源保护反例。"""
from copy import deepcopy
from pathlib import Path
import json
import tempfile
import unittest

from test_accompaniment import fixture
from accompaniment_analysis import SongClock
from accompaniment_arrange import arrange_guitar, validate_playability
from guitar_instrumental_register import (arrange_instrumental_register, bind_register_source,
    editable_notes, finger_transition, fingerprint, melodic_phrases, projected_source_note,
    unit_candidates, validate_instrumental_register)


# 吉他器乐低把位与指型复用：新增自拟多声部夹具，高音有明确低音／和声，后一小节不可改写。
def music(capo=0, pitch_shift=0, repeat=False):
    shared,vocal=fixture()
    shared['timing']=deepcopy(vocal['timing'])
    shared['sections']=[{'kind':'intro','label':'前奏','start_tick':0,'end_tick':1920},
                        {'kind':'vocal','label':'演唱','start_tick':1920,'end_tick':3840}]
    # 吉他器乐低把位与指型复用：修改，旧夹具构造触发历史A#／G#调名限制；直接为自拟源音设置夹位。
    # guitar=arrange_guitar(shared,vocal,capo)
    guitar=arrange_guitar(shared,vocal,0)
    guitar['configuration']['capo_fret']=capo
    rows=[('m0',0,240,79,1,15,'instrumental_melody'),
          ('b0',0,480,55,5,10,'bass'),('h0',0,240,64,3,9,'harmony'),
          ('m1',240,480,81,1,17,'instrumental_melody'),
          ('m2',480,720,79,1,15,'instrumental_melody'),
          ('b1',480,960,55,5,10,'bass'),
          ('normal',1920,2160,48,5,3,'harmony')]
    notes=[{'id':identity,'start_tick':start,'end_tick':end,'pitch_midi':pitch+capo+pitch_shift,
            'string':string,'fret':fret+pitch_shift,'finger':1,'hand_position':1,
            'role':role,'velocity':90 if role=='instrumental_melody' else 70,
            'source':'synthetic_music','chord_id':'h0' if start<1920 else 'h1'}
           for identity,start,end,pitch,string,fret,role in rows]
    if repeat:
        notes += [{**deepcopy(n),'id':'repeat_'+n['id'],'start_tick':n['start_tick']+960,
                   'end_tick':n['end_tick']+960} for n in notes if n['id']!='normal']
    guitar['notes']=sorted(notes,key=lambda n:(n['start_tick'],n['id']))
    guitar['hand_positions']=[{'tick':0,'position':1}]
    guitar['attack_events']=[]
    guitar['adjustments']=[]
    return shared,vocal,guitar


class InstrumentalRegisterTests(unittest.TestCase):
    # 吉他器乐低把位与指型复用：新增所有声部和拍位的独立比较，不能以少音达到低品统计。
    def test_retains_every_note_voice_pitch_class_and_time(self):
        s,v,g=music(); original=deepcopy((s,v,g))
        a,r=arrange_instrumental_register(s,v,g)
        self.assertEqual((s,v,g),original)
        old={n['id']:n for n in g['notes']};new={n['id']:n for n in a['notes']}
        self.assertEqual(set(old),set(new))
        for identity,n in old.items():
            self.assertEqual((n['pitch_midi']%12,n['role'],n['start_tick'],n['end_tick'],n['velocity']),
                             (new[identity]['pitch_midi']%12,new[identity]['role'],new[identity]['start_tick'],new[identity]['end_tick'],new[identity]['velocity']))
        self.assertGreaterEqual(r['after']['within_four'],r['before']['within_four'])
        self.assertEqual(r['after']['above_twelve'],0)

    def test_normal_singing_note_all_fields_preserved(self):
        s,v,g=music();a,_=arrange_instrumental_register(s,v,g)
        self.assertEqual(next(n for n in g['notes'] if n['id']=='normal'),next(n for n in a['notes'] if n['id']=='normal'))

    def test_each_continuous_motif_keeps_exact_intervals(self):
        s,v,g=music();a,r=arrange_instrumental_register(s,v,g)
        by_id={n['id']:n for n in a['notes']}
        for phrase in r['phrases']:
            self.assertEqual(len({by_id[i]['instrumental_register_octave_shift'] for i in phrase['note_ids']}),1)
        self.assertEqual([by_id['m1']['pitch_midi']-by_id['m0']['pitch_midi'],by_id['m2']['pitch_midi']-by_id['m1']['pitch_midi']],[2,-2])

    def test_capo_and_transposed_material_use_real_sound(self):
        for capo,shift in ((0,0),(2,0),(4,0),(0,2)):
            with self.subTest(capo=capo,shift=shift):
                s,v,g=music(capo,shift);a,r=arrange_instrumental_register(s,v,g)
                self.assertTrue(validate_playability(a,SongClock(v))['valid'])
                self.assertEqual(r['after']['above_twelve'],0)

    def test_lowest_bass_is_not_lowered_out_of_guitar_range(self):
        s,v,g=music();bass=next(n for n in g['notes'] if n['id']=='b0')
        bass.update(pitch_midi=40,string=6,fret=0)
        a,_=arrange_instrumental_register(s,v,g)
        self.assertEqual(next(n for n in a['notes'] if n['id']=='b0')['pitch_midi'],40)

    def test_same_string_sustained_notes_are_not_overwritten(self):
        s,v,g=music();a,_=arrange_instrumental_register(s,v,g)
        for string in range(1,7):
            ns=sorted((n for n in a['notes'] if n['string']==string),key=lambda n:n['start_tick'])
            self.assertTrue(all(x['end_tick']<=y['start_tick'] for x,y in zip(ns,ns[1:])))

    def test_repeated_motif_reuses_compatible_string_and_fret(self):
        s,v,g=music(repeat=True);a,r=arrange_instrumental_register(s,v,g);ns={n['id']:n for n in a['notes']}
        self.assertTrue(r['repeated_motifs'])
        self.assertEqual([(ns[i]['string'],ns[i]['fret']) for i in ['m0','m1','m2']],
                         [(ns['repeat_'+i]['string'],ns['repeat_'+i]['fret']) for i in ['m0','m1','m2']])

    def test_one_finger_move_is_counted_once(self):
        previous=(((2,1),),(),(),())
        current,changes=finger_transition(previous,(((2,2),),),())
        self.assertEqual(changes,1);self.assertEqual(current[0],((2,2),))

    def test_sustained_finger_cannot_be_reassigned(self):
        previous=((),((2,1),),(),())
        current,_=finger_transition(previous,(((2,1),),((1,3),)),((2,1),))
        self.assertIn((2,1),current[1])

    def test_individual_fingers_remain_available_beside_barre(self):
        geometry=((3,3),(5,1),(6,1));options=unit_candidates(geometry)
        self.assertTrue(any(len(units)==3 for units in options))
        previous=(((5,1),),((6,1),),(),())
        self.assertTrue(any(finger_transition(previous,units,((5,1),(6,1))) is not None for units in options))

    def test_no_instrumental_section_is_exact_noop(self):
        s,v,g=music();s['sections']=[{'kind':'vocal','start_tick':0,'end_tick':3840}]
        a,r=arrange_instrumental_register(s,v,g)
        self.assertEqual(a,g);self.assertFalse(r['applied'])

    def test_melody_role_inside_vocal_section_stays_protected(self):
        s,v,g=music();n=next(n for n in g['notes'] if n['id']=='normal');n['role']='instrumental_melody'
        a,_=arrange_instrumental_register(s,v,g)
        self.assertEqual(n,next(n for n in a['notes'] if n['id']=='normal'))

    def test_names_and_lyrics_do_not_choose_fingering(self):
        s,v,g=music();a,_=arrange_instrumental_register(s,v,g)
        changed=deepcopy(v);changed['title']='任意未见歌曲'
        for char in changed['lyrics']['characters']:char['text']='任'
        other,_=arrange_instrumental_register(s,changed,g)
        self.assertEqual(a['notes'],other['notes'])

    def test_idempotent_upgrade_does_not_lower_twice(self):
        s,v,g=music();a,r=arrange_instrumental_register(s,v,g);b,_=arrange_instrumental_register(s,v,a)
        self.assertEqual(a,b)

    def test_musical_snapshot_tampering_is_rejected(self):
        s,v,g=music();a,_=arrange_instrumental_register(s,v,g)
        a['notes'][0]['start_tick']+=120
        self.assertFalse(validate_instrumental_register(s,v,a)['valid'])

    def test_normal_note_tampering_stays_rejected_with_updated_hash(self):
        s,v,g=music();a,_=arrange_instrumental_register(s,v,g)
        next(n for n in a['notes'] if n['id']=='normal')['velocity']-=1
        a['instrumental_register']['result_notes_sha256']=fingerprint(a['notes'])
        self.assertFalse(validate_instrumental_register(s,v,a)['valid'])

    def test_source_projection_does_not_unlock_normal_notes(self):
        s,v,g=music();a,_=arrange_instrumental_register(s,v,g)
        n=next(n for n in g['notes'] if n['id']=='normal')
        self.assertEqual(projected_source_note(n,a),n)

    def test_strict_replay_requires_bound_source(self):
        s,v,g=music();a,_=arrange_instrumental_register(s,v,g)
        self.assertIn('instrumental_register_missing_bound_source',validate_instrumental_register(s,v,a,replay=True)['errors'])

    def test_serialized_bound_source_replays_and_rejects_changes(self):
        s,v,g=music();a,_=arrange_instrumental_register(s,v,g)
        # 吉他器乐低把位与指型复用：修改，旧系统临时目录在Windows沙箱不可写；固定父目录于项目测试区。
        # with tempfile.TemporaryDirectory() as directory:
        temp_parent=Path(__file__).resolve().parents[1]/'test_outputs'/'instrumental_register_unit_temp'
        temp_parent.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=temp_parent) as directory:
            source=Path(directory)/'source.json'
            source.write_text(json.dumps({'shared_analysis':s,'accepted_vocal_project':v,'arrangements':{'guitar':g}}),encoding='utf-8')
            bind_register_source(a,source,s,v)
            restored=json.loads(json.dumps(a))
            self.assertTrue(validate_instrumental_register(s,v,restored,replay=True)['valid'])
            source.write_text('{}',encoding='utf-8')
            self.assertFalse(validate_instrumental_register(s,v,restored,replay=True)['valid'])

    # 吉他器乐低把位与指型复用：新增实际拍速／拍号变体，不依赖雨天或遇见的小节编号。
    def test_different_meters_and_tempos_keep_source_attacks(self):
        for meter,bpm in (([3,4],72),([4,4],180),([6,8],90)):
            s,v,g=music();bar=int(480*4/meter[1]*meter[0])
            v['timing'].update(meter=meter,steady_tempo_bpm=bpm,
                               knots=[{'seconds':0,'quarter':0},{'seconds':60/bpm,'quarter':1}])
            v['statistics'].update(bar_ticks=bar,total_ticks=bar*3,measure_count=3)
            s['statistics']=deepcopy(v['statistics']);s['timing']=deepcopy(v['timing'])
            a,r=arrange_instrumental_register(s,v,g)
            self.assertEqual([(n['id'],n['start_tick'],n['end_tick']) for n in g['notes']],
                             [(n['id'],n['start_tick'],n['end_tick']) for n in a['notes']])
            self.assertTrue(r['playability']['valid'])

    def test_high_register_can_use_two_octaves_without_folding_each_note(self):
        s,v,g=music()
        for n in g['notes']:
            if n['role']=='instrumental_melody':n['pitch_midi']+=17;n['fret']+=17
        a,r=arrange_instrumental_register(s,v,g)
        self.assertEqual({n['instrumental_register_octave_shift'] for n in a['notes'] if n['role']=='instrumental_melody'},{-24})
        self.assertEqual(r['after']['above_twelve'],0)

    def test_sustained_melody_does_not_split_on_barline(self):
        s,v,g=music();s['sections']=[{'kind':'intro','start_tick':0,'end_tick':3840}]
        g['notes']=[{'id':'first','start_tick':1680,'end_tick':2160,'pitch_midi':72,'role':'instrumental_melody','chord_id':'h0'},
                    {'id':'second','start_tick':1920,'end_tick':2400,'pitch_midi':74,'role':'instrumental_melody','chord_id':'h1'},
                    {'id':'bass','start_tick':1920,'end_tick':2400,'pitch_midi':48,'role':'bass','chord_id':'h1'}]
        phrases=melodic_phrases(s,g['notes'],editable_notes(s,g))
        self.assertEqual(len(phrases),1)

    def test_real_rest_separates_register_motifs(self):
        s,v,g=music(repeat=True)
        phrases=melodic_phrases(s,g['notes'],editable_notes(s,g))
        self.assertEqual([p['start_tick'] for p in phrases],[0,960])


if __name__=='__main__':unittest.main()
