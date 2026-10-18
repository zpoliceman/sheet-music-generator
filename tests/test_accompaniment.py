"""和弦弹唱与伴奏编配：已知音乐、演奏反例与真实导出回读。"""
# 和弦弹唱与伴奏编配：新增独立合成夹具，不把真实歌曲的未确认候选当测试真值。
import copy
from pathlib import Path
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile
import numpy as np
import soundfile as sf
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'tools'))
from test_score_export import project_from,note,char
import score_export as score
import accompaniment_analysis as analysis
import accompaniment_arrange as arrange
import accompaniment_export as export
from accompaniment_sources import bind_inputs
from generate_accompaniment import validate_output_path


# 和弦弹唱与伴奏编配：新增两个调的自拟乐句，明确速度、声部、节奏与器乐优先级。
def fixture():
    chars=[char(0,'春',.2,.5),char(1,'风',.5,.8)]
    vocal=project_from([note('v1',.2,.5,64),note('v2',.5,.8,67)],chars,4)
    vocal['timing'].update({'knots':[{'seconds':0,'quarter':0},{'seconds':.5,'quarter':1}],'steady_tempo_bpm':120})
    vocal['audio_analysis']={'tempo':{'bpm':120}};vocal['overrides']={'tempo':120}
    vocal['lyrics']={'characters':chars,'reference_kind':'user_supplied'}
    vocal['notation']['source_key']=score.key_definition('C:major')
    vocal['notation']['key_segments']=[{'start_tick':0,'start_measure':1,'start_seconds':0,'key':score.key_definition('C:major'),'jianpu_reference_midi':60},
                                       {'start_tick':1920,'start_measure':2,'start_seconds':2,'key':score.key_definition('D:major'),'jianpu_reference_midi':62}]
    harmony=[];textures=[]
    for i,root in enumerate((0,2)):
        begin=i*1920;key=score.key_definition(('C' if not i else 'D')+':major')
        harmony.append({'id':'h'+str(i),'name':'C' if not i else 'D','root_pc':root,'quality':'','bass_pc':root,
                        'pitch_classes':[(root+p)%12 for p in (0,4,7)],'key':key,'requires_review':False,
                        'start_tick':begin,'end_tick':begin+1920,'start_seconds':i*2,'end_seconds':i*2+2})
        attacks=[]
        for j,pitch in enumerate((60+root,64+root,67+root,72+root,67+root,64+root,67+root,72+root)):
            attacks.append({'tick':begin+j*240,'seconds':i*2+j*.25,'strength':1.,'source':'other',
                            'pitches':[{'pitch_midi':pitch,'relative_weight':1.,'weight':1.}]})
        textures.append({'measure':i+1,'start_tick':begin,'end_tick':begin+1920,'start_seconds':i*2,'end_seconds':i*2+2,
                         'section':'intro','kind':'arpeggio','source':'other','attacks':attacks})
    shared={'statistics':vocal['statistics'],'harmony':harmony,'measure_textures':textures,
            'sections':[{'kind':'intro','label':'前奏','start_seconds':0,'end_seconds':4,'start_tick':0,'end_tick':3840}],
            'instrumental_melody':[{'id':'melody_a','start_tick':0,'start_seconds':0,'duration_ticks':240,'pitch_midi':72,
                                   'support':1.,'source':'other','section':'intro','role':'instrumental_melody'}],
            'input_binding':{'vocal_project_sha256':'a'*64,'sources':{'mix':{'path':'synthetic.wav'}},'references':[]}}
    return shared,vocal


class HarmonyTests(unittest.TestCase):
    # 和弦弹唱与伴奏编配：新增明确三和弦及斜杠低音，旋律不是根音。
    def test_third_in_voice_is_not_chord_root(self):
        chord=np.zeros(12);chord[[0,4,7]]=[.42,.33,.25]
        bass=np.zeros(12);bass[0]=1;voice=np.zeros(12);voice[4]=1
        winner=analysis.score_chord_candidates(chord,bass,voice,score.key_definition('C:major'),1)[0]
        self.assertEqual((winner['root_pc'],winner['quality']),(0,''))

    def test_inversion_does_not_force_bass_as_root(self):
        chord=np.zeros(12);chord[[0,4,7]]=[.35,.35,.30]
        bass=np.zeros(12);bass[4]=1
        winner=analysis.score_chord_candidates(chord,bass,chord,score.key_definition('C:major'),1)[0]
        self.assertEqual((winner['root_pc'],winner['quality']),(0,''))
        self.assertEqual(analysis.chord_name(0,'',4,score.key_definition('C:major')),'C/E')

    def test_sus2_and_add9_have_different_third_support(self):
        bass=np.zeros(12);bass[0]=1
        sus=np.zeros(12);sus[[0,2,7]]=[.4,.35,.25]
        add=np.zeros(12);add[[0,2,4,7]]=.25
        a=analysis.score_chord_candidates(sus,bass,sus,score.key_definition('C:major'),1)[0]
        b=analysis.score_chord_candidates(add,bass,add,score.key_definition('C:major'),1)[0]
        self.assertEqual(a['quality'],'sus2');self.assertEqual(b['quality'],'add9')

    def test_weak_seventh_does_not_overfit_simple_chord(self):
        chord=np.zeros(12);chord[[0,4,7,11]]=[.39,.31,.27,.03]
        bass=np.zeros(12);bass[0]=1
        winner=analysis.score_chord_candidates(chord,bass,chord,score.key_definition('C:major'),1)[0]
        self.assertEqual(winner['quality'],'')

    def test_modulation_clock_inherits_existing_notation(self):
        shared,vocal=fixture();clock=analysis.SongClock(vocal)
        self.assertEqual(clock.key(1919)['tonic'],'C');self.assertEqual(clock.key(1920)['tonic'],'D')
        self.assertAlmostEqual(clock.seconds(1920),2);self.assertAlmostEqual(clock.tick(1.75),1680)

    def test_original_and_notated_voice_evidence_are_separate(self):
        _,vocal=fixture();vocal['quantized_notes'][0]['source_pitch_midi']=63
        a=analysis.vocal_chroma(vocal,.2,.5);b=analysis.vocal_chroma(vocal,.2,.5,True)
        self.assertEqual(int(np.argmax(a)),4);self.assertEqual(int(np.argmax(b)),3)

    def test_synthetic_audio_harmony_and_cache_fingerprint(self):
        folder=ROOT/'test_outputs/accompaniment_runs/tests';folder.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=folder) as temp:
            p=Path(temp);sr=22050;t=np.arange(sr*2)/sr
            wave=sum(.12*np.sin(2*np.pi*f*t) for f in (261.625565,329.627557,391.995436))
            sf.write(p/'known.wav',wave,sr,subtype='FLOAT')
            source={'path':str(p/'known.wav'),'sha256':score.sha256(p/'known.wav')}
            f=analysis.extract_features(source,p/'cache','known');chroma=f.chroma(.3,1.7,48,84)
            self.assertGreater(float(chroma[[0,4,7]].sum()),.70)
            bass=np.zeros(12);bass[0]=1
            chosen=analysis.score_chord_candidates(chroma,bass,np.zeros(12),score.key_definition('C:major'),1)[0]
            self.assertEqual((chosen['root_pc'],chosen['quality']),(0,''))
            sf.write(p/'known.wav',np.zeros(sr*2),sr,subtype='FLOAT')
            with self.assertRaises(ValueError):analysis.extract_features(source,p/'cache','known')


class PlayabilityTests(unittest.TestCase):
    # 和弦弹唱与伴奏编配：新增跨度、横按、同时持续与换把的明确不可演奏反例。
    def test_open_strings_do_not_enlarge_fretted_span(self):
        self.assertEqual(arrange.grip_info({6:0,5:8,4:10})['span'],2)
        self.assertIsNone(arrange.grip_info({6:3,1:9}))

    def test_six_note_barre_chord_uses_four_fingers(self):
        grip=arrange.grip_info({6:1,5:3,4:3,3:2,2:1,1:1})
        self.assertEqual(grip['finger_count'],4);self.assertIsNotNone(grip['barre'])

    def test_piano_simultaneous_limit_is_twelve_semitones(self):
        _,vocal=fixture();clock=analysis.SongClock(vocal)
        piano={'instrument':'piano','notes':[{'id':'a','pitch_midi':60,'start_tick':0,'end_tick':960,'hand':'right'},
                                            {'id':'b','pitch_midi':72,'start_tick':240,'end_tick':720,'hand':'right'}]}
        self.assertTrue(arrange.validate_playability(piano,clock)['valid'])
        piano['notes'][1]['pitch_midi']=73
        self.assertFalse(arrange.validate_playability(piano,clock)['valid'])

    def test_sequential_arpeggio_can_move_beyond_octave(self):
        _,vocal=fixture();piano={'instrument':'piano','notes':[{'id':'a','pitch_midi':60,'start_tick':0,'end_tick':240,'hand':'right'},
                                                                  {'id':'b','pitch_midi':84,'start_tick':240,'end_tick':480,'hand':'right'}]}
        self.assertTrue(arrange.validate_playability(piano,analysis.SongClock(vocal))['valid'])

    def test_same_string_collision_is_rejected(self):
        _,vocal=fixture();g={'instrument':'guitar','configuration':{'capo_fret':1,'maximum_fret':20},
                           'notes':[{'id':'a','pitch_midi':65,'string':1,'fret':0,'start_tick':0,'end_tick':960},
                                    {'id':'b','pitch_midi':68,'string':1,'fret':3,'start_tick':480,'end_tick':720}]}
        self.assertFalse(arrange.validate_playability(g,analysis.SongClock(vocal))['valid'])

    def test_real_capo_sound_is_not_shape_pitch(self):
        candidates=arrange.shape_candidates(1,'',1,1)
        self.assertTrue(any(49 in c['pitches'].values() for c in candidates))
        for c in candidates:
            for string,pitch in c['pitches'].items():self.assertEqual(pitch,arrange.TUNING[int(string)]+1+c['frets'][string])

    def test_both_arrangements_preserve_vocal_and_solo_priority(self):
        shared,vocal=fixture();before=copy.deepcopy(vocal)
        guitar=arrange.arrange_guitar(shared,vocal,1);piano=arrange.arrange_piano(shared,vocal)
        self.assertEqual(before,vocal)
        for a in (guitar,piano):
            self.assertTrue(arrange.validate_playability(a,analysis.SongClock(vocal))['valid'])
            leads=[n for n in a['notes'] if n['role']=='instrumental_melody']
            self.assertTrue(leads);self.assertEqual(leads[0]['pitch_midi']%12,0)

    def test_position_speed_corruption_is_detected(self):
        shared,vocal=fixture();g=arrange.arrange_guitar(shared,vocal,1)
        g['hand_positions'][1]['position']=20
        check=arrange.validate_playability(g,analysis.SongClock(vocal))
        self.assertFalse(check['valid']);self.assertTrue(any('position' in x for x in check['errors']))

    # 和弦弹唱与伴奏编配：新增钢琴快到无法换位的反例，不能因每次只有一个音就放行。
    def test_piano_rapid_four_octave_jump_rejected(self):
        _,vocal=fixture()
        notes=[{'id':'a','pitch_midi':36,'start_tick':0,'end_tick':120,'hand':'right'},
               {'id':'b','pitch_midi':96,'start_tick':120,'end_tick':240,'hand':'right'}]
        with self.assertRaises(ValueError):arrange.piano_hand_positions(notes,analysis.SongClock(vocal))


class InputBindingTests(unittest.TestCase):
    # 和弦弹唱与伴奏编配：新增同长不同录音、非零偏移和截断分轨的来源反例。
    def setup_files(self,path):
        sr=22050;t=np.arange(sr)/sr;wave=.1*np.sin(2*np.pi*220*t)
        for name in ('mix','vocals','bass','other','drums','accompaniment'):
            sf.write(path/(name+'.wav'),wave,sr,subtype='FLOAT')
        p={'inputs':{'mix_audio_path':str(path/'mix.wav'),'mix_audio_sha256':score.sha256(path/'mix.wav'),
                     'transcription_source':{'sha256':score.sha256(path/'vocals.wav'),'offset_seconds':0}}}
        r={'checks':{'demucs_short_inference':{'input':str(path/'mix.wav'),
                      'outputs':{n:str(path/(n+'.wav')) for n in ('vocals','bass','other','drums','accompaniment')}}}}
        score.save_json(path/'project.json',p);score.save_json(path/'demucs.json',r)
        return p,r

    def test_matching_source_is_bound_and_not_claimed_independent(self):
        folder=ROOT/'test_outputs/accompaniment_runs/tests';folder.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=folder) as temp:
            path=Path(temp);self.setup_files(path);binding=bind_inputs(path/'project.json',path/'demucs.json')
            self.assertFalse(binding['independent_instruments_proven']);self.assertEqual(binding['duration_seconds'],1.)

    def test_same_length_different_recording_rejected(self):
        folder=ROOT/'test_outputs/accompaniment_runs/tests';folder.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=folder) as temp:
            path=Path(temp);p,r=self.setup_files(path);sf.write(path/'different.wav',np.zeros(22050),22050,subtype='FLOAT')
            r['checks']['demucs_short_inference']['input']=str(path/'different.wav');score.save_json(path/'demucs.json',r)
            with self.assertRaises(ValueError):bind_inputs(path/'project.json',path/'demucs.json')

    def test_nonzero_offset_and_truncated_stem_rejected(self):
        folder=ROOT/'test_outputs/accompaniment_runs/tests';folder.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=folder) as temp:
            path=Path(temp);p,r=self.setup_files(path);p['inputs']['transcription_source']['offset_seconds']=.5;score.save_json(path/'project.json',p)
            with self.assertRaises(ValueError):bind_inputs(path/'project.json',path/'demucs.json')
            p['inputs']['transcription_source']['offset_seconds']=0;score.save_json(path/'project.json',p)
            sf.write(path/'bass.wav',np.zeros(11025),22050,subtype='FLOAT')
            with self.assertRaises(ValueError):bind_inputs(path/'project.json',path/'demucs.json')


class ExportTests(unittest.TestCase):
    # 和弦弹唱与伴奏编配：新增双手不等长音/跨小节延音的已知真值，而不从导出器计算预期。
    def piano(self):
        return {'instrument':'piano','configuration':{},'pedal':[],
                'notes':[{'id':'upper','pitch_midi':72,'start_tick':120,'end_tick':2400,'hand':'right','finger':5,'velocity':80},
                         {'id':'inner','pitch_midi':64,'start_tick':480,'end_tick':960,'hand':'right','finger':1,'velocity':70},
                         {'id':'low','pitch_midi':48,'start_tick':0,'end_tick':1920,'hand':'left','finger':5,'velocity':70}]}

    def test_polyphonic_xml_exact_ties_and_backup(self):
        shared,vocal=fixture();root,_=export.build_musicxml(shared,vocal,self.piano())
        parsed,check=export.parse_musicxml_notes(root)
        self.assertTrue(check['valid'],check['errors']);self.assertEqual(check['measure_lengths'],[1920,1920])
        self.assertEqual({k:(n['start_tick'],n['end_tick'],n['pitch_midi']) for k,n in parsed.items()},
                         {'upper':(120,2400,72),'inner':(480,960,64),'low':(0,1920,48)})
        self.assertEqual(root.findtext('part/measure/attributes/staves'),'2')

    def test_tie_pitch_corruption_is_rejected(self):
        shared,vocal=fixture();root,_=export.build_musicxml(shared,vocal,self.piano())
        n=next(x for x in root.findall('part/measure/note') if x.get('id','').startswith('upper_'))
        n.find('pitch/octave').text='6'
        parsed,check=export.parse_musicxml_notes(root);self.assertFalse(check['valid'])

    def test_tab_xml_only_has_six_line_staff(self):
        shared,vocal=fixture();g=arrange.arrange_guitar(shared,vocal,1);root,_=export.build_musicxml(shared,vocal,g)
        self.assertEqual(root.findtext('part/measure/attributes/clef/sign'),'TAB')
        self.assertEqual(root.findtext('part/measure/attributes/staff-details/staff-lines'),'6')
        self.assertEqual(root.findtext('part/measure/attributes/staff-details/capo'),'1')
        self.assertEqual(len(root.findall('part')),1)
        parsed,check=export.parse_musicxml_notes(root)
        self.assertEqual(len(parsed),len(g['notes']));self.assertTrue(check['valid'])

    def test_visible_tab_tampering_changes_sound(self):
        shared,vocal=fixture();g=arrange.arrange_guitar(shared,vocal,1)
        rows=[{'guitar':export.guitar_row(shared,vocal,g,1,2)}]
        self.assertTrue(export.validate_tab(rows,g)['valid'])
        root=ET.fromstring(rows[0]['guitar']);ns='{http://www.w3.org/2000/svg}'
        group=next(x for x in root.iter(ns+'g') if x.get('data-string'));group.find(ns+'text').text='20'
        rows[0]['guitar']=ET.tostring(root,encoding='unicode');self.assertFalse(export.validate_tab(rows,g)['valid'])

    def test_midi_unison_strings_have_independent_releases(self):
        _,vocal=fixture();g={'instrument':'guitar','pedal':[],'notes':[
            {'id':'a','pitch_midi':64,'start_tick':0,'end_tick':480,'string':1,'fret':0,'velocity':80},
            {'id':'b','pitch_midi':64,'start_tick':0,'end_tick':960,'string':2,'fret':5,'velocity':80}]}
        folder=ROOT/'test_outputs/accompaniment_runs/tests';folder.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=folder) as temp:
            path=Path(temp)/'unison.mid';export.write_midi(path,g,vocal)
            self.assertTrue(export.validate_midi(path,g,vocal)['valid'])

    def test_actual_synthesis_has_known_pitch_and_duration(self):
        _,vocal=fixture();p={'instrument':'piano','pedal':[],'notes':[{'pitch_midi':60,'start_tick':0,'end_tick':480,'velocity':80}]}
        folder=ROOT/'test_outputs/accompaniment_runs/tests';folder.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=folder) as temp:
            path=Path(temp)/'c4.wav';report=export.synthesize(path,p,vocal)
            wave,sr=sf.read(path);self.assertEqual(len(wave),4*sr);self.assertTrue(np.isfinite(wave).all())
            block=wave[round(.04*sr):round(.44*sr)];spectrum=np.abs(np.fft.rfft(block*np.hanning(len(block))))
            freq=np.fft.rfftfreq(len(block),1/sr)[int(np.argmax(spectrum))]
            self.assertAlmostEqual(freq,261.625565,delta=3)

    def test_mxl_is_exact_editable_xml(self):
        shared,vocal=fixture();root,_=export.build_musicxml(shared,vocal,self.piano());data=ET.tostring(root,encoding='utf-8')
        folder=ROOT/'test_outputs/accompaniment_runs/tests';folder.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=folder) as temp:
            path=Path(temp)/'score.mxl';export.write_mxl(path,data)
            with zipfile.ZipFile(path) as z:self.assertEqual(z.read('score.musicxml'),data);self.assertIsNone(z.testzip())

    def test_output_cannot_overwrite_voice_or_snapshot(self):
        for path in (ROOT/'results/雨天',ROOT/'history-version/version1-chinese-sheetmusic',ROOT/'.codex',ROOT/'test_music'):
            with self.assertRaises(ValueError):validate_output_path(path)
        self.assertEqual(validate_output_path(ROOT/'results/accompaniment/new'),ROOT/'results/accompaniment/new')


if __name__=='__main__':unittest.main(verbosity=2)
