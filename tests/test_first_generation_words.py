"""首拍与首尾局部补证：局部词音范围、证据有效性与完整原音保护。"""
# 首拍与首尾局部补证：新增不运行模型的真实音素／PCM来源夹具，检验音乐保护及拒绝伪证。
from copy import deepcopy
import sys
from pathlib import Path
import tempfile
import unittest
import numpy as np
import soundfile as sf
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from first_generation_words import POLICY,base_fingerprint,apply_words,local_jobs,validate_words
from phoneme_evidence import character_phonemes
from score_export import save_json,sha256
from test_score_export import project_from,note,char


def fixture(folder):
    # 首拍与首尾局部补证：新增两个实际核音处于同一个原长音的材料，修词不能删掉或截断原音。
    folder=Path(folder);audio=folder/'voice.wav';sf.write(audio,np.zeros(4*4000),4000,subtype='FLOAT')
    voice=project_from([note('long',1.,2.),note('protected',2.5,3.,64)],seconds=4)
    chars=[{**char(0,'天',None,None),'line_index':0},{**char(1,'空',1.5,2.),'line_index':0},
           {**char(2,'远',2.5,3.),'line_index':1}]
    voice['lyrics']={'characters':chars};voice['quantized_notes'][1]['lyric_index']=2
    voice['timing'].update(knots=[{'quarter':0.,'seconds':0.},{'quarter':1.,'seconds':.5}],steady_tempo_bpm=120.,
        measure_timeline=[{'number':1,'start_tick':0,'end_tick':1920,'meter':[4,4]},
                          {'number':2,'start_tick':1920,'end_tick':3840,'meter':[4,4]}])
    voice['first_source_meter_correction']={'version':2,'decision_path':'old-copy.json','decision_sha256':'unchanged-content'}
    source={'path':str(audio),'sha256':sha256(audio),'offset_seconds':0.,'duration_seconds':4.,'sample_rate':4000,'channels':1}
    states=[{'word_owner':1,'text':'天','start_seconds':1.,'end_seconds':1.5,'phoneme':'zh/ian'},
            {'word_owner':2,'text':'空','start_seconds':1.5,'end_seconds':2.,'phoneme':'zh/ong'}]
    values=[]
    for i,c in enumerate(chars[:2]):
        values.append({**c,'start_seconds':states[i]['start_seconds'],'end_seconds':states[i]['end_seconds'],
            'phonemes':character_phonemes([states[i]],0.),'phoneme_source':{'word_owner':i+1,'timestep_seconds':.01}})
    raw=folder/'raw.json';save_json(raw,{'source':source,'results':[{'texts':['天','空'],'phoneme_states':states}]})
    characters=folder/'characters.json';save_json(characters,values)
    artifact={'version':2,'policy':deepcopy(POLICY),'base_voice_sha256':base_fingerprint(voice),'vocals_sha256':source['sha256'],
        'dependencies':[{'path':str(p),'sha256':sha256(p)} for p in (audio,raw,characters)],
        'jobs':[{'line_indices':[0],'unanchored_terminal_lines':[],'start_seconds':.5,'end_seconds':2.2,
                 'characters_path':str(characters),'raw_alignment_path':str(raw),'crop':source}]}
    return voice,artifact,{'sources':{'vocals':{'path':str(audio),'sha256':source['sha256']}}}


class FirstWordsTests(unittest.TestCase):
    def test_fresh_entry_consumes_requested_words_before_initial_harmony(self):
        # 首拍与首尾局部补证：新增真实首次分支的顺序测试，局部字音不能只在旧工程分支或导出后消费。
        from types import SimpleNamespace
        from unittest.mock import patch
        from test_first_generation_meter import source_case
        from generate_accompaniment import generate
        root=Path(__file__).resolve().parents[1]/'test_outputs/accompaniment_runs/tests';root.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=root) as folder:
            folder=Path(folder);_,_,evidence,_,binding=source_case(folder);words=folder/'words.json';save_json(words,{})
            args=SimpleNamespace(edited_project=None,rearrange=False,output=folder/'new',report=None,binding=folder/'binding.json',
                analysis_dir=folder/'analysis',shared_analysis=None,six_sources=False,capo=None,source_meter_evidence=evidence,first_source_words=words)
            class ReachedCorrectHarmony(Exception):pass
            def consume(voice,actual_binding,path):
                self.assertIn('first_source_meter_correction',voice);self.assertEqual(path,words)
                return {**voice,'first_source_word_correction':{'artifact_sha256':sha256(words)}}
            def analyze(actual_binding,voice,*args,**kwargs):
                self.assertEqual(voice['first_source_word_correction']['artifact_sha256'],sha256(words))
                raise ReachedCorrectHarmony()
            with patch('generate_accompaniment.validate_source_pitch_project',return_value=True), \
                 patch('first_generation_words.use_words',side_effect=consume) as called, \
                 patch('source_meter_entry.require_calibrated_source',return_value={'status':'test_verified'}), \
                 patch('generate_accompaniment.analyze',side_effect=analyze):
                with self.assertRaises(ReachedCorrectHarmony):generate(args)
                self.assertEqual(called.call_count,1)

    def test_existing_score_entry_cannot_silently_ignore_first_word_argument(self):
        # 首拍与首尾局部补证：新增在读取旧曲谱前拦住错误入口组合，保持旧音乐保护。
        from types import SimpleNamespace
        from generate_accompaniment import generate
        with self.assertRaisesRegex(ValueError,'全新输入'):
            generate(SimpleNamespace(edited_project='does-not-exist.json',first_source_words='local.json'))

    def test_local_same_pitch_syllables_keep_full_sound_and_other_notes(self):
        with tempfile.TemporaryDirectory() as folder:
            voice,artifact,binding=fixture(folder);before=deepcopy(voice);out=apply_words(voice,artifact,binding)
            self.assertEqual(voice,before);self.assertEqual(out['timing'],before['timing'])
            parts=[n for n in out['quantized_notes'] if n['id']!='protected']
            self.assertEqual([(n['start_seconds'],n['end_seconds'],n['pitch_midi']) for n in parts],[(1.,1.5,60),(1.5,2.,60)])
            self.assertEqual(out['quantized_notes'][-1],before['quantized_notes'][-1])
            self.assertEqual([n['lyric_index'] for n in parts],[0,1])

    def test_changed_clock_or_pitch_cannot_use_existing_words(self):
        with tempfile.TemporaryDirectory() as folder:
            voice,artifact,binding=fixture(folder)
            for kind in ('pitch','clock'):
                bad=deepcopy(voice)
                if kind=='pitch':bad['quantized_notes'][0]['pitch_midi']+=1
                else:bad['timing']['knots'][1]['seconds']+=.1
                with self.assertRaisesRegex(ValueError,'基准'):apply_words(bad,artifact,binding)

    def test_identical_clock_certificate_copy_is_allowed_but_new_content_is_not(self):
        with tempfile.TemporaryDirectory() as folder:
            voice,artifact,binding=fixture(folder);copy=deepcopy(voice)
            copy['first_source_meter_correction']['decision_path']='new-copy.json'
            self.assertEqual(base_fingerprint(copy),base_fingerprint(voice))
            self.assertEqual(apply_words(copy,artifact,binding)['timing'],voice['timing'])
            copy['first_source_meter_correction']['decision_sha256']='different-content'
            with self.assertRaisesRegex(ValueError,'基准'):apply_words(copy,artifact,binding)

    def test_changed_raw_phonemes_or_crop_cannot_be_hidden_by_rehashing_characters(self):
        with tempfile.TemporaryDirectory() as folder:
            voice,artifact,binding=fixture(folder)
            path=Path(artifact['jobs'][0]['characters_path']);values=__import__('json').loads(path.read_text(encoding='utf8'))
            values[0]['phonemes'][0]['end_seconds']=1.4;save_json(path,values)
            next(r for r in artifact['dependencies'] if r['path']==str(path))['sha256']=sha256(path)
            with self.assertRaisesRegex(ValueError,'音素'):validate_words(artifact,binding)

    def test_changed_word_identity_cannot_reuse_same_raw_phonemes(self):
        # 首拍与首尾局部补证：新增防止同音素冒充别字，即使重新计算缓存摘要也须拒绝。
        with tempfile.TemporaryDirectory() as folder:
            voice,artifact,binding=fixture(folder);path=Path(artifact['jobs'][0]['characters_path'])
            values=__import__('json').loads(path.read_text(encoding='utf8'));values[0]['text']='海';save_json(path,values)
            next(r for r in artifact['dependencies'] if r['path']==str(path))['sha256']=sha256(path)
            with self.assertRaisesRegex(ValueError,'owner'):validate_words(artifact,binding)

    def test_missing_tail_anchor_does_not_expand_known_text_into_instrumental_outro(self):
        voice={'lyrics':{'characters':[{'index':0,'line_index':0},{'index':1,'line_index':1}]},
               'lyric_mapping':{'unmapped_character_indices':[0]},'timing':{'steady_tempo_bpm':60.}}
        plan={'jobs':[{'job_id':1,'line_indices':[0,1],'matches':[{'line':0,'lines':[0],'segments':[0]}],
                       'start_seconds':10.,'end_seconds':80.}]}
        jobs=local_jobs(voice,plan,{'result':{'segments':[{'start':10.,'end':14.}]}},
                        {'lines':['天','啦'],'source':{'duration_seconds':100.}})
        self.assertEqual(jobs[0]['end_seconds'],15.);self.assertEqual(jobs[0]['unanchored_terminal_lines'],[1])


if __name__=='__main__':unittest.main()
