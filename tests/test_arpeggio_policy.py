"""分解和弦优先：已知柱式/分解、弱证据反例及真实音符语义。"""
# 分解和弦优先：新增独立音乐夹具，避免将真实歌曲未确认和弦当测试答案。
import copy
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
import numpy as np
import soundfile as sf
from test_accompaniment import fixture,ROOT
import score_export as score
import accompaniment_analysis as analysis
import accompaniment_arrange as arrange
import accompaniment_export as export
from accompaniment_texture_policy import block_support,performance_kind,onset_pitch_classes


# 分解和弦优先：新增人工明确三音同时起音的C/D自拟片段及两轨交叉证据。
def block_fixture():
    shared,vocal=fixture();shared['instrumental_melody']=[]
    for texture,chord in zip(shared['measure_textures'],shared['harmony']):
        texture['kind']='block';texture['source']='six_piano'
        texture['attacks']=[]
        for offset in (0,480,960,1440):
            pitches=[60+chord['root_pc'],64+chord['root_pc'],67+chord['root_pc']]
            texture['attacks'].append({'tick':texture['start_tick']+offset,
              'seconds':texture['start_seconds']+offset/960,'source':'six_piano','strength':1.,
              'pitches':[{'pitch_midi':p,'weight':1.,'relative_weight':1.,'sustain_weight':1.} for p in pitches]})
    all_attacks=[a for t in shared['measure_textures'] for a in t['attacks']]
    features={name:SimpleNamespace(attacks=copy.deepcopy(all_attacks),rms=np.ones(8),
                                  window=lambda start,end:slice(None)) for name in ('six_piano','accompaniment')}
    return shared,vocal,features


class ArpeggioPolicyTests(unittest.TestCase):
    # 分解和弦优先：新增假设不足时默认分解，不能信任稀疏攻击留下的柱式标签。
    def test_sparse_label_without_audio_support_is_arpeggio(self):
        shared,_,_=block_fixture()
        for label in ('block','strum'):
            shared['measure_textures'][0]['kind']=label
            kind,_=performance_kind(shared['measure_textures'][0],0)
            self.assertEqual(kind,'arpeggio')

    def test_repeated_cross_supported_block_is_preserved(self):
        shared,_,features=block_fixture();texture=shared['measure_textures'][0]
        support=block_support(texture,shared['harmony'],features)
        self.assertTrue(support['allow_block']);self.assertEqual(support['confirmed_attack_count'],4)
        texture['block_support']=support
        self.assertEqual(performance_kind(texture,0)[0],'block')
        self.assertEqual(performance_kind(texture,240)[0],'arpeggio')

    def test_near_silent_instrument_cannot_authorize_blocks(self):
        shared,_,features=block_fixture();features['six_piano'].rms[:]=.00001
        support=block_support(shared['measure_textures'][0],shared['harmony'],features)
        self.assertFalse(support['allow_block']);self.assertFalse(support['source_has_effective_energy'])

    def test_octave_doublings_are_not_three_chord_tones(self):
        shared,_,features=block_fixture()
        for a in shared['measure_textures'][0]['attacks']:
            a['pitches']=[{'pitch_midi':p,'weight':1.,'relative_weight':1.} for p in (60,72,84)]
        self.assertFalse(block_support(shared['measure_textures'][0],shared['harmony'],features)['allow_block'])

    def test_unrelated_cross_source_or_only_one_attack_is_insufficient(self):
        shared,_,features=block_fixture()
        for a in features['accompaniment'].attacks:
            a['pitches']=[{'pitch_midi':p,'weight':1.,'relative_weight':1.} for p in (61,65,68)]
        self.assertFalse(block_support(shared['measure_textures'][0],shared['harmony'],features)['allow_block'])
        shared,_,features=block_fixture();shared['measure_textures'][0]['attacks']=shared['measure_textures'][0]['attacks'][:1]
        self.assertFalse(block_support(shared['measure_textures'][0],shared['harmony'],features)['allow_block'])

    def test_held_tones_without_attack_cannot_authorize_block(self):
        shared,_,features=block_fixture();texture=shared['measure_textures'][0]
        for a in texture['attacks']:
            for p in a['pitches']:p.update(weight=.08,sustain_weight=1.)
        self.assertFalse(block_support(texture,shared['harmony'],features)['allow_block'])

    # 分解和弦优先：新增检查实际攻击而非标签，所有伴奏音不能继续同tick齐奏。
    def test_both_instruments_really_break_up_unconfirmed_chords(self):
        shared,vocal,_=block_fixture();before=copy.deepcopy(shared)
        for arrangement in (arrange.arrange_guitar(shared,vocal,1),arrange.arrange_piano(shared,vocal)):
            harmonic_counts={}
            for n in arrangement['notes']:
                if n['role']=='harmony':harmonic_counts[n['start_tick']]=harmonic_counts.get(n['start_tick'],0)+1
            self.assertLessEqual(max(harmonic_counts.values()),1)
            pcs={n['pitch_midi']%12 for n in arrangement['notes'] if n['start_tick']<1920}
            self.assertTrue({0,4,7}.issubset(pcs))
            self.assertTrue(any(n['onset_origin']=='arranged_subdivision' for n in arrangement['notes']))
            self.assertTrue(arrange.validate_playability(arrangement,analysis.SongClock(vocal))['valid'])
            parsed,check=export.parse_musicxml_notes(export.build_musicxml(shared,vocal,arrangement)[0])
            self.assertTrue(check['valid']);self.assertEqual(len(parsed),len(arrangement['notes']))
        self.assertEqual(shared,before)

    def test_evidenced_column_remains_in_actual_piano_notes(self):
        shared,vocal,features=block_fixture()
        for t in shared['measure_textures']:t['block_support']=block_support(t,shared['harmony'],features)
        piano=arrange.arrange_piano(shared,vocal)
        pcs={n['pitch_midi']%12 for n in piano['notes'] if n['start_tick']==0}
        self.assertEqual(pcs,{0,4,7})
        self.assertGreaterEqual(len([n for n in piano['notes'] if n['start_tick']==0 and n['role']=='harmony']),3)

    def test_melody_and_observed_arpeggio_attacks_are_preserved(self):
        shared,vocal=fixture();before=copy.deepcopy(shared)
        groups=arrange.performance_groups(shared)
        self.assertEqual([g['tick'] for g in groups],[a['tick'] for t in shared['measure_textures'] for a in t['attacks']])
        self.assertTrue(all(g['onset_origin']=='observed' for g in groups))
        for a in (arrange.arrange_guitar(shared,vocal,1),arrange.arrange_piano(shared,vocal)):
            melody=[n for n in a['notes'] if n['role']=='instrumental_melody']
            self.assertTrue(any(n['start_tick']==0 and n['pitch_midi']%12==0 for n in melody))
        self.assertEqual(shared,before)

    # 分解和弦优先：新增真实合成和弦音频检验，多音起音来自音频而非编配器预设。
    def test_known_simultaneous_chord_audio_produces_supported_attacks(self):
        shared,vocal,_=block_fixture()
        folder=ROOT/'test_outputs/accompaniment_runs/tests';folder.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=folder) as temp:
            path=Path(temp);sr=22050;time=np.arange(sr*2)/sr;wave=np.zeros_like(time)
            for start in (.125,.875,1.625):
                mask=(time>=start)&(time<start+.28)
                elapsed=time[mask]-start;envelope=np.minimum(1,elapsed/.018)*np.exp(-elapsed*5)
                wave[mask]+=sum(.12*np.sin(2*np.pi*f*elapsed)*envelope for f in (261.625565,329.627557,391.995436))
            sf.write(path/'known.wav',wave,sr,subtype='FLOAT')
            source={'path':str(path/'known.wav'),'sha256':score.sha256(path/'known.wav')}
            feature=analysis.extract_features(source,path/'features','known')
            attacks=[{**a,'tick':round(a['seconds']*960),'source':'six_piano'} for a in feature.attacks]
            texture={**shared['measure_textures'][0],'attacks':attacks}
            support=block_support(texture,shared['harmony'],{'six_piano':feature,'accompaniment':feature})
            self.assertTrue(support['allow_block'],support)


if __name__=='__main__':unittest.main()
