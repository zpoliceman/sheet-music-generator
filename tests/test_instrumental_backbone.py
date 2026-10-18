"""器乐主旋律简化与规整节奏：独立声部/静音/移调/持续按音与实际XML反例。"""
# 器乐主旋律简化与规整节奏：新增合成音乐证据，不以雨天的音符/小节表作为程序真值。
from copy import deepcopy
from pathlib import Path
import sys
import unittest
import numpy as np
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'tools'))
from test_accompaniment import fixture
from accompaniment_analysis import Features, LOW_MIDI, HIGH_MIDI, SongClock
from accompaniment_arrange import arrange_guitar, arrange_piano
from accompaniment_export import build_musicxml
from instrumental_backbone import build_plan, apply_plan, continuous_path, rearticulations, sample_evidence, guitar_locations


# 器乐主旋律简化与规整节奏：新增独立持续主线和密集内声部，支持音量缩放/整曲移调/段落比较。
def synthetic(shift=0, gain=1., phrase_change=False, attacks=()):
    times = np.arange(0, 4.01, .01)
    energy = np.zeros((HIGH_MIDI-LOW_MIDI+1, len(times)))
    for i, t in enumerate(times):
        main = (74 if phrase_change and t >= 2 else 72) + shift
        inner = (64 if int(t/.125)%2 else 67) + shift
        energy[main-LOW_MIDI, i] = .9*gain
        energy[inner-LOW_MIDI, i] = 1.2*gain
    return Features(times, energy, np.ones(len(times))*.2*gain, np.zeros(len(times)), list(attacks), {'sha256':'a'*64})


def source_project(shift=0, phrase_change=False):
    shared, vocal = fixture()
    shared['instrumental_melody'] = [{'id':f'raw_{i}', 'start_tick':i*120, 'duration_ticks':120,
                                     'pitch_midi':((74 if phrase_change and i>=16 else 72) if i%3 == 0 else (64 if i%2 else 67))+shift}
                                    for i in range(32)]
    return shared, vocal


class BackboneEvidenceTests(unittest.TestCase):
    # 器乐主旋律简化与规整节奏：新增持续上声部不能被更响、更密的内声部取代。
    def test_held_main_over_busy_inner_arpeggio(self):
        shared, vocal = source_project()
        plan = build_plan(shared, vocal, {'other': synthetic()})
        self.assertEqual([n['pitch_midi'] for n in plan['notes']], [72])
        self.assertEqual((plan['notes'][0]['start_tick'], plan['notes'][0]['end_tick']), (0, 3840))

    def test_phrase_pitch_change_survives(self):
        shared, vocal = source_project(phrase_change=True)
        plan = build_plan(shared, vocal, {'other': synthetic(phrase_change=True)})
        self.assertEqual([n['pitch_midi'] for n in plan['notes']], [72, 74])
        self.assertLessEqual(abs(plan['notes'][1]['start_tick']-1920), 240)

    def test_transposition_is_generic(self):
        a, v = source_project(); b, w = source_project(shift=3)
        b['title'] = '另一首歌'; w['title'] = '无关标题'
        p = build_plan(a, v, {'other': synthetic()})['notes']
        q = build_plan(b, w, {'other': synthetic(shift=3)})['notes']
        self.assertEqual([(n['start_tick'], n['end_tick'], n['pitch_midi']+3) for n in p],
                         [(n['start_tick'], n['end_tick'], n['pitch_midi']) for n in q])

    def test_gain_does_not_change_notes(self):
        shared, vocal = source_project()
        p = build_plan(shared, vocal, {'other': synthetic()})['notes']
        for gain in (.01, .2, 7.):
            q = build_plan(shared, vocal, {'other': synthetic(gain=gain)})['notes']
            self.assertEqual([(n['start_tick'], n['end_tick'], n['pitch_midi']) for n in p],
                             [(n['start_tick'], n['end_tick'], n['pitch_midi']) for n in q])

    def test_silent_stem_does_not_cancel_live_mix(self):
        a = synthetic(); silent = synthetic(gain=0)
        x, _ = sample_evidence({'other': a}, (1, 1.2), 60, 80)
        y, names = sample_evidence({'six_piano': silent, 'other': a}, (1, 1.2), 60, 80)
        np.testing.assert_allclose(x, y); self.assertEqual(names, ['other'])

    def test_silence_produces_rests_not_fictitious_notes(self):
        shared, vocal = source_project()
        p = build_plan(shared, vocal, {'other': synthetic(gain=0)})
        self.assertEqual(p['notes'], [])

    def test_missing_sources_stop_false_success(self):
        shared, vocal = source_project()
        with self.assertRaisesRegex(ValueError, '音频证据'):
            build_plan(shared, vocal, {})

    def test_only_complete_mix_is_sufficient(self):
        shared, vocal = source_project()
        p = build_plan(shared, vocal, {'accompaniment': synthetic()})
        self.assertEqual(p['notes'][0]['pitch_midi'], 72)

    def test_short_inner_ornament_is_not_another_main_note(self):
        rows = np.zeros((16, 3)); rows[:, 1] = .8
        rows[7, 1] = .65; rows[7, 2] = 1
        self.assertEqual(continuous_path(rows, np.array([67,72,74])), [72]*16)

    def test_real_short_melodic_change_can_survive(self):
        rows = np.zeros((8, 2)); rows[:4, 0] = 1; rows[4:, 1] = 1
        self.assertEqual(continuous_path(rows, np.array([72,74])), [72]*4+[74]*4)

    def test_other_pitch_attack_does_not_break_held_note(self):
        f = synthetic(attacks=[{'seconds':1.,'strength':1.}, {'seconds':2.,'strength':1.}])
        _, vocal = source_project()
        self.assertEqual(rearticulations({'other': f}, SongClock(vocal), 0, 3840, 72), [])

    def test_true_main_rearticulation_is_retained(self):
        f = synthetic(attacks=[{'seconds':1.,'strength':1.}, {'seconds':2.,'strength':1.}])
        for t in (1., 2.):
            f.activations[72-LOW_MIDI, (f.times>=t-.2)&(f.times<t)] = .01
        _, vocal = source_project()
        self.assertEqual(rearticulations({'other': f}, SongClock(vocal), 0, 3840, 72), [960,1920])

    # 器乐主旋律简化与规整节奏：新增非零轨偏移的起音/音高同时校验，避免其它歌曲同音重弹错用采样窗。
    def test_offset_rearticulation_uses_local_pitch_window(self):
        f = synthetic(attacks=[{'seconds':1.,'strength':1.}, {'seconds':2.,'strength':1.}])
        f.source['offset_seconds'] = .5
        for t in (1.,2.):
            f.activations[72-LOW_MIDI,(f.times>=t-.2)&(f.times<t)] = .01
        _,vocal = source_project()
        self.assertEqual(rearticulations({'other':f},SongClock(vocal),0,3840,72),[1440,2400])

    def test_raw_analysis_and_vocal_are_read_only(self):
        shared, vocal = source_project(); a, b = deepcopy(shared), deepcopy(vocal)
        build_plan(shared, vocal, {'other': synthetic()})
        self.assertEqual(shared, a); self.assertEqual(vocal, b)

    def test_compound_meter_and_nonzero_origin(self):
        shared, vocal = source_project()
        vocal['notation']['meter'] = {'beats':6,'beat_type':8}
        vocal['statistics']['bar_ticks'] = 1440
        vocal['timing']['score_start_quarter'] = -1
        shared['sections'] = [{'kind':'interlude','start_seconds':0,'end_seconds':3,'start_tick':480,'end_tick':3360}]
        shared['instrumental_melody'] = []
        plan = build_plan(shared, vocal, {'other': synthetic()})
        self.assertTrue(plan['notes'])
        self.assertTrue(all(480<=n['start_tick']<n['end_tick']<=3360 and n['start_tick']%120==n['end_tick']%120==0 for n in plan['notes']))

    def test_binding_offset_applies_to_spectral_and_energy_windows(self):
        f = synthetic(); f.source['offset_seconds'] = .5
        a, _ = sample_evidence({'other': f}, (.5,.8), 60, 80)
        f.source['offset_seconds'] = 0
        b, _ = sample_evidence({'other': f}, (0,.3), 60, 80)
        np.testing.assert_allclose(a,b)


class BackboneArrangementTests(unittest.TestCase):
    # 器乐主旋律简化与规整节奏：新增混合小节实际区间、演唱逐字段保护和导出XML真节奏检查。
    def make(self):
        shared, vocal = fixture()
        arrangements = {'guitar':arrange_guitar(shared,vocal,0), 'piano':arrange_piano(shared,vocal)}
        shared['sections'] = [{'kind':'intro','start_seconds':0,'end_seconds':1,'start_tick':0,'end_tick':960},
                              {'kind':'vocal','start_seconds':1,'end_seconds':3,'start_tick':960,'end_tick':2880},
                              {'kind':'outro','start_seconds':3,'end_seconds':4,'start_tick':2880,'end_tick':3840}]
        # 器乐主旋律简化与规整节奏：新增完整节段标签供实际XML导出，不修改导出器来适应缺失夹具。
        for section in shared['sections']:
            section['label'] = section['kind']
        plan = build_plan(shared,vocal,{'other':synthetic()})
        return shared,vocal,arrangements,plan

    def test_real_section_boundary_preserves_singing_notes(self):
        shared,vocal,arrangements,plan = self.make()
        original = deepcopy(arrangements); source = deepcopy(shared); voice = deepcopy(vocal)
        new, result, validation = apply_plan(shared,vocal,arrangements,plan)
        for name, a in result.items():
            protected = {n['id']:n for n in original[name]['notes'] if 960<=n['start_tick']<2880}
            self.assertEqual(protected,{n['id']:n for n in a['notes'] if 960<=n['start_tick']<2880})
            self.assertTrue(validation['instruments'][name]['playability']['valid'])
        self.assertEqual(shared,source); self.assertEqual(vocal,voice); self.assertEqual(arrangements,original)
        self.assertEqual(new['harmony'],shared['harmony'])

    def test_both_instruments_follow_one_actual_line(self):
        shared,vocal,arrangements,plan = self.make()
        _,result,_ = apply_plan(shared,vocal,arrangements,plan)
        for a in result.values():
            melody = [n for n in a['notes'] if n.get('backbone_id')]
            self.assertEqual([(n['start_tick'],n['end_tick'],n['pitch_midi']%12) for n in melody],
                             [(n['start_tick'],n['end_tick'],n['pitch_midi']%12) for n in plan['notes']])

    def test_actual_xml_has_no_32nds_or_dotted_16ths_in_new_line(self):
        shared,vocal,arrangements,plan = self.make()
        _,result,_ = apply_plan(shared,vocal,arrangements,plan)
        for a in result.values():
            # 器乐主旋律简化与规整节奏：修改，旧忽略片段映射的接收保留；按导出器真实返回结构读XML。
            # tree = build_musicxml(shared,vocal,a)
            tree, fragments = build_musicxml(shared,vocal,a)
            ids = {n['id'] for n in a['notes'] if n.get('backbone_id')}
            found = [n for n in tree.findall('.//note') if any(n.get('id','').startswith(i) for i in ids)]
            self.assertTrue(found)
            self.assertFalse(any(n.findtext('type') in ('32nd','64th') or
                                 (n.findtext('type')=='16th' and n.find('dot') is not None) for n in found))

    def test_real_capo_pitch_and_fixed_vocal_fingering(self):
        shared,vocal,arrangements,plan = self.make()
        # 器乐主旋律简化与规整节奏：新增具有合法变调夹指型调号的合成源调；旧模块不支持A#大调拼法。
        from score_export import key_definition
        for segment in vocal['notation']['key_segments']:
            segment['key'] = key_definition('Db:major')
        arrangement = arrange_guitar(shared,vocal,2); arrangements['guitar'] = arrangement
        _,result,_ = apply_plan(shared,vocal,arrangements,plan)
        for n in result['guitar']['notes']:
            from accompaniment_arrange import TUNING
            self.assertEqual(n['pitch_midi'],TUNING[n['string']]+2+n['fret'])

    # 器乐主旋律简化与规整节奏：新增旧保护账本迁移反例，保留历史证据且不能解除普通段音乐检查。
    def test_only_authorized_instrumental_protection_is_superseded(self):
        shared,vocal,arrangements,plan = self.make()
        g = arrangements['guitar']
        g['regular_rhythm'] = {'version':1,'changed_measures':[],'preserved_notes':deepcopy(g['notes']),
                               'preserved_note_ids':[n['id'] for n in g['notes']],'exceptions':[]}
        _,result,_ = apply_plan(shared,vocal,arrangements,plan)
        from guitar_regular_rhythm import validate_regular_rhythm
        ledger = result['guitar']['regular_rhythm']
        self.assertTrue(ledger['superseded_instrumental_notes'])
        self.assertTrue(all(960<=n['start_tick']<2880 for n in ledger['preserved_notes']))
        self.assertTrue(validate_regular_rhythm(shared,result['guitar'])['valid'])
        kept = next(n for n in result['guitar']['notes'] if n['id']==ledger['preserved_notes'][0]['id'])
        kept['pitch_midi'] += 1
        self.assertFalse(validate_regular_rhythm(shared,result['guitar'])['valid'])

    # 器乐主旋律简化与规整节奏：新增踏板成对语义检查；删除器乐踩下后不能留下孤立释放或悬挂演唱踏板。
    def test_pedal_keeps_vocal_release_without_orphan_instrumental_stops(self):
        shared,vocal,arrangements,plan = self.make()
        arrangements['piano']['pedal'] = [{'tick':t,'value':v} for t,v in
            ((0,127),(480,0),(960,127),(2880,0),(2880,127),(3840,0))]
        _,result,_ = apply_plan(shared,vocal,arrangements,plan)
        self.assertEqual(result['piano']['pedal'],[{'tick':960,'value':127},{'tick':2880,'value':0}])

    # 器乐主旋律简化与规整节奏：新增纯旋律不能因单音匹配产生一副虚构和弦图，演唱仍保留图式。
    def test_new_monophonic_line_uses_solo_tab_without_forced_grips(self):
        shared,vocal,arrangements,plan = self.make()
        _,result,_ = apply_plan(shared,vocal,arrangements,plan)
        from guitar_grip_policy import prepare_common_diagrams
        g = result['guitar']; charts = prepare_common_diagrams(shared,g,vocal)
        instrumental = [r for r in g['notation_regions'] if r['section'] in ('intro','outro')]
        self.assertTrue(all(r['mode']=='solo_tab' for r in instrumental))
        self.assertTrue(charts)
        self.assertTrue(all(960<=d['start_tick']<2880 for d in charts))

    # 器乐主旋律简化与规整节奏：新增实际字形引用输出检查；HTML中的use必须采用可识别的标准前缀。
    def test_inline_piano_glyph_links_keep_html_recognized_namespace(self):
        from accompaniment_export import normalize_harmony_svg
        svg = '<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink"><defs><g id="head"><path d="M0 0L5 0L3 3Z"/></g></defs><g class="notehead"><use xlink:href="#head"/></g></svg>'
        normalized,_ = normalize_harmony_svg(svg,{})
        self.assertIn('xlink:href="#head"',normalized)
        self.assertNotIn('ns1:href',normalized)

    # 器乐主旋律简化与规整节奏：修改，旧开放弦跳跃本可演奏的反例注释保留；改为真实持续同弦碰撞。
    # def test_unsafe_large_leap_cannot_be_hidden_as_playable(self):
    #     _,vocal = fixture()
    #     notes = [{'id':str(i),'pitch_midi':p,'start_tick':i*2,'end_tick':i*2+1,'backbone_id':str(i)}
    #              for i,p in enumerate((40,96,40,96))]
    def test_unplayable_held_vocal_string_cannot_be_overwritten(self):
        _,vocal = fixture()
        notes = [{'id':'fixed','pitch_midi':65,'string':1,'fret':1,'start_tick':0,'end_tick':960},
                 {'id':'new','pitch_midi':96,'backbone_id':'new','start_tick':240,'end_tick':480}]
        with self.assertRaises(ValueError):
            guitar_locations(notes, {'capo_fret':0}, vocal)


if __name__ == '__main__':
    unittest.main()
