"""通用段落强拍与乐句节奏修复：新增跨歌曲通用正负、移调、改唱与真实导出回归。"""
from collections import Counter
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import json,sys,unittest
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'tools'))
from melodic_structure import align_motifs,infer_form,phase_vote,source_sections
from phrase_rhythm_structure import (solve_words,word_models,short_groups,tuplet_candidates,
                                    adapted_reference,allocate)
from structure_beat_clock import bridge_clock,infer_structural_clock,POLICY as CLOCK_POLICY
from rhythm_notation import split_rhythm_tuplets,validate_grouping,xml_beams
from phrase_rhythm import quantize_phrase
from score_export import TempoMap,build_musicxml,write_midi,read_json
from accompaniment_rebar import validate_vocal_snapshot


# 通用段落强拍与乐句节奏修复：新增任意文字/源音序夹具，手工拍位只存在测试断言。
def fixture(onsets,ends=None,pitches=None,lines=None,turn_indices=()):
    # 通用段落强拍与乐句节奏修复：修改夹具，真实空档不能被默认前字的延音填满。
    # ends=ends or [b for b in onsets[1:]]+[onsets[-1]+.8]
    ends=ends or [min(a+.5,b) for a,b in zip(onsets,onsets[1:])]+[onsets[-1]+.8]
    pitches=pitches or [60+i%7 for i in range(len(onsets))]
    notes=[];chars=[]
    for i,(a,b,p) in enumerate(zip(onsets,ends,pitches)):
        ch={'index':i,'text':chr(0x4e20+i),'line_index':lines[i] if lines else 0,
            'start_seconds':a,'end_seconds':b,'phrase_job_id':0,'phonemes':[]}
        chars.append(ch)
        parts=[(a,b,p)] if i not in turn_indices else [(a,(a+b)/2,p+1),((a+b)/2,b,p)]
        for j,(x,y,k) in enumerate(parts):
            notes.append({'id':f'u{i}_{j}','source_note_id':f'raw{i}_{j}','pitch_midi':k,'start_seconds':x,
                          'end_seconds':y,'lyric_index':i,'line_index':ch['line_index'],
                          'role':'main' if j==len(parts)-1 else 'turn','grace':False})
    duration=max(ends)+2
    mapping=TempoMap([{'seconds':0.,'quarter':0.},{'seconds':duration,'quarter':duration}])
    timing={'meter':[4,4],'score_start_quarter':0.,'steady_tempo_bpm':60,'knots':deepcopy(mapping.knots) if hasattr(mapping,'knots') else [{'seconds':0.,'quarter':0.},{'seconds':duration,'quarter':duration}]}
    return notes,chars,mapping,timing,duration


def motif(pitches,offset=0.,scale=1.):
    return [{'pitch':p,'onset_seconds':offset+i*.5*scale} for i,p in enumerate(pitches)]


class MusicalMatchingTests(unittest.TestCase):
    def test_transposed_different_words_match(self):
        a=motif([60,62,65,64,67,65,62,60]);b=motif([61,63,66,65,68,66,63,61],20,1.08)
        for i,w in enumerate(a):w['text']='甲'+str(i)
        for i,w in enumerate(b):w['text']='other'+str(i)
        result=align_motifs(a,b)
        self.assertEqual(result['transpose'],1);self.assertEqual(result['pitch_support'],1)
        self.assertAlmostEqual(result['duration_ratio'],1.08)

    def test_one_added_musical_unit_supported(self):
        a=motif([60,62,65,64,67,65,62,60]);b=motif([60,62,65,64,67,67,65,62,60],20)
        self.assertIsNotNone(align_motifs(a,b))

    def test_same_words_unrelated_melody_rejected(self):
        a=motif([60,62,65,64,67,65,62,60]);b=motif([60,70,58,75,55,72,60,77],20)
        for w in a+b:w['text']='same'
        self.assertIsNone(align_motifs(a,b))

    def test_constant_pitch_not_a_structural_witness(self):
        self.assertIsNone(align_motifs(motif([60]*8),motif([61]*8,20)))

    def test_unrelated_rapid_timing_rejected(self):
        a=motif([60,62,65,64,67,65,62,60]);b=deepcopy(a)
        for w,t in zip(b,[0,.05,1.7,1.75,3.4,3.45,5.1,5.15]):w['onset_seconds']=t
        self.assertIsNone(align_motifs(a,b))

    def test_circular_two_beat_vote_not_cancelled(self):
        vote=phase_vote([1.9,-1.9,2.1,-2.1],4)
        self.assertEqual(vote['phase'],2);self.assertEqual(vote['support'],1)

    def test_breath_does_not_create_a_form_section(self):
        units=[{'index':i,'voiced_q':q,'end_q':q+.5,'start_seconds':q,'end_seconds':q+.5} for i,q in enumerate([0,1,2,6.6])]
        self.assertEqual(len(source_sections(units,4)),2)

    def form_fixture(self,extra=False,sparse=False):
        onsets=[i*.5 for i in range(16)]+[20+i*.5 for i in range(16)]
        lines=[0]*8+[1]*8+[2]*8+[3]*8
        pitch=[60,62,65,64,67,65,62,60,64,67,69,65,62,64,67,65]*2
        if sparse:pitch[24:]=[50,70,55,75,52,73,57,77]
        if extra:
            onsets += [37+i*.5 for i in range(16)];lines += [4]*8+[5]*8;pitch += pitch[:16]
        return fixture(onsets,pitches=pitch,lines=lines)

    def test_supported_one_beat_phase_general(self):
        # 通用段落强拍与乐句节奏修复：移除未使用的原型变量，夹具功能保持。
        # n,c,m,t,d=self.form_fixture();on=[n['start_seconds'] for n in n]
        n,c,m,t,d=self.form_fixture()
        for note in n[16:]:note['start_seconds']+=1;note['end_seconds']+=1
        for ch in c[16:]:ch['start_seconds']+=1;ch['end_seconds']+=1
        form=infer_form(n,c,m,t,4)
        self.assertEqual(form['sections'][1]['phase_delta_quarters'],1)
        self.assertFalse(form['text_used_for_matching'])

    def test_single_witness_cannot_rephase_section(self):
        n,c,m,t,d=self.form_fixture(sparse=True)
        for note in n[16:]:note['start_seconds']+=2;note['end_seconds']+=2
        for ch in c[16:]:ch['start_seconds']+=2;ch['end_seconds']+=2
        self.assertEqual(infer_form(n,c,m,t,4)['sections'][1]['phase_delta_quarters'],0)

    def test_multiple_gaps_keep_cumulative_phase(self):
        n,c,m,t,d=self.form_fixture(extra=True)
        for note in n[16:32]:note['start_seconds']+=2;note['end_seconds']+=2
        for ch in c[16:32]:ch['start_seconds']+=2;ch['end_seconds']+=2
        form=infer_form(n,c,m,t,4)
        self.assertEqual([s['phase_delta_quarters'] for s in form['sections']],[0,2,1])

    def test_compound_meter_phase_uses_big_beats(self):
        n,c,m,t,d=self.form_fixture();t['meter']=[6,8]
        form=infer_form(n,c,m,t,3)
        self.assertTrue(all(s['phase_delta_quarters']%1.5==0 for s in form['sections']))

    def test_unmatched_later_section_inherits_known_phase(self):
        n,c,m,t,d=self.form_fixture(extra=True)
        for note in n[16:32]:note['start_seconds']+=2;note['end_seconds']+=2
        for ch in c[16:32]:ch['start_seconds']+=2;ch['end_seconds']+=2
        for i,note in enumerate(n[32:]):note['pitch_midi']=50+i*3
        form=infer_form(n,c,m,t,4)
        self.assertEqual(form['sections'][2]['phase_delta_quarters'],2)
        self.assertEqual(form['sections'][2]['witness_count'],0)


class GapPathTests(unittest.TestCase):
    def test_fixed_count_survives_stronger_offbeats(self):
        nodes=[{'seconds':i*.5,'strength':2. if i%2 else 1.,'tracks':['guitar']} for i in range(1,16)]
        path=bridge_clock(nodes,0,8,8,1)
        self.assertEqual(len(path['beats']),9);self.assertEqual(path['beats'][-1]['seconds'],8)
        self.assertEqual([b['step'] for b in path['beats']],list(range(9)))

    def test_special_gap_not_rounded_to_full_bars(self):
        self.assertEqual(bridge_clock([],0,6,6,1)['count'],6)

    def test_impossible_extension_falls_back(self):
        self.assertIsNone(bridge_clock([],0,16,2,1))

    def test_missing_attacks_still_monotonic(self):
        path=bridge_clock([{'seconds':3,'strength':1.,'tracks':['bass']}],0,8,8,1)
        self.assertTrue(all(a['seconds']<b['seconds'] for a,b in zip(path['beats'],path['beats'][1:])))

    def test_nonintegral_big_beat_phase_keeps_original_clock(self):
        n,c,m,t,d=fixture([0,.5,1,1.5,8,8.5,9,9.5]);t['meter']=[7,8];t['beat_groups']=[2,2,3]
        form={'sections':[{'section':0,'end_seconds':2,'phase_delta_quarters':0},
                          {'section':1,'start_seconds':8,'end_seconds':10,'phase_delta_quarters':1.5}],
              'matches':[],'units':[],'lines':[]}
        vocal={'timing':t,'quantized_notes':n,'lyrics':{'characters':c}}
        with patch('structure_beat_clock.infer_form',return_value=form),patch('structure_beat_clock.structural_candidates') as candidates:
            knots,audit=infer_structural_clock(vocal,{'sources':{}},ROOT/'test_outputs')
        self.assertEqual(knots,t['knots']);candidates.assert_not_called()
        self.assertEqual(audit['transitions'][0]['status'],'unresolved_nonintegral_big_beat_phase_keep_original')

    def test_subbeat_phrase_variant_does_not_rephase_full_section(self):
        n,c,m,t,d=fixture([0,.5,1,1.5,8,8.5,9,9.5])
        form={'sections':[{'section':0,'end_seconds':2,'phase_delta_quarters':0},
                          {'section':1,'start_seconds':8,'end_seconds':10,'phase_delta_quarters':.5}],
              'matches':[],'units':[],'lines':[]}
        vocal={'timing':t,'quantized_notes':n,'lyrics':{'characters':c}}
        with patch('structure_beat_clock.infer_form',return_value=form):knots,audit=infer_structural_clock(vocal,{'sources':{}},ROOT/'test_outputs')
        self.assertEqual(knots,t['knots']);self.assertEqual(audit['transitions'],[])


class StructureRhythmTests(unittest.TestCase):
    def test_four_short_words_with_pitch_turns_are_not_disqualified(self):
        n,c,m,t,d=fixture([1.08,1.40,1.72,2.02],ends=[1.4,1.72,2.02,2.9],turn_indices=(0,2))
        self.assertEqual(short_groups(word_models(n,c,m,t),1)[0]['kind'],'four_sixteenths')
        out,a=solve_words(n,c,m,t,d)
        heads=[min(x['start_tick'] for x in out if x['lyric_index']==i) for i in range(4)]
        self.assertEqual(heads,[480,600,720,840]);self.assertEqual(len(out),len(n))

    def test_true_mixed_pickup_preserved(self):
        n,c,m,t,d=fixture([.76,1.02,1.50,1.78],ends=[1.02,1.50,1.78,2.5])
        out,a=solve_words(n,c,m,t,d)
        self.assertEqual([x['start_tick'] for x in out],[360,480,720,840])

    def test_three_sixteenths_not_a_tuplet(self):
        n,c,m,t,d=fixture([1.,1.25,1.5],ends=[1.25,1.5,2.5])
        self.assertEqual(tuplet_candidates(word_models(n,c,m,t),1),[])

    def test_tuplet_with_melisma_keeps_source_identity(self):
        n,c,m,t,d=fixture([1.10,1.43,1.76],ends=[1.43,1.76,2.5],turn_indices=(0,2))
        t['structural_rhythm']={'version':1}
        ev,out,stats=quantize_phrase(n,c,m,t,d)
        self.assertEqual(stats['phrase_rhythm']['tuplet_groups'][0]['start_tick'],480)
        self.assertEqual(sum(e['duration_ticks'] for e in ev if e.get('tuplet')),480)
        fields=('id','pitch_midi','role','start_seconds','end_seconds','lyric_index')
        self.assertEqual([tuple(x[k] for k in fields) for x in n],[tuple(x[k] for k in fields) for x in out])
        self.assertTrue(any(e.get('tuplet_stop') for e in ev));self.assertTrue(stats['rhythm_grouping']['valid'])

    def test_cadence_variation_budget_is_source_based(self):
        n,c,m,t,d=fixture([0,.5,1,1.5],ends=[.5,1,1.5,2.5],turn_indices=(0,))
        left=word_models(n,c,m,t);right=deepcopy(left)
        right[0]['notes']=right[0]['notes'][-1:];right[0]['observed_span']=.28
        path=[(i*240,(i+1)*240,(240,)) for i in range(4)]
        pairs=[((0,i),(1,i)) for i in range(4)]
        ref,changes=adapted_reference(left,right,path,pairs)
        self.assertEqual(ref[1],120);self.assertEqual(changes[0]['variant_ticks'],120)

    def test_equal_pieces_do_not_shorten_reference(self):
        n,c,m,t,d=fixture([0,.5,1,1.5]);ws=word_models(n,c,m,t)
        ref,changes=adapted_reference(ws,ws,[(i*240,(i+1)*240,(240,)) for i in range(4)],[((0,i),(1,i)) for i in range(4)])
        self.assertEqual(changes,[]);self.assertEqual(ref[3],720)

    def test_tuplet_grid_is_not_enabled_outside_window(self):
        self.assertFalse(allocate((.3,),0,160,())[1])
        self.assertTrue(allocate((.3,),0,160,((0,480),))[1])


class TupletNotationTests(unittest.TestCase):
    def group(self,a=0):return {'id':'t','start_tick':a,'end_tick':a+480,'actual_notes':3,'normal_notes':2}

    def test_effective_duration_and_nominal_eighth(self):
        piece=split_rhythm_tuplets(0,160,tuplets=[self.group()])[0]
        self.assertEqual((piece['duration_ticks'],piece['type']),(160,'eighth'))

    def test_tie_exits_tuplet_to_normal_eighth(self):
        parts=split_rhythm_tuplets(320,720,tuplets=[self.group()])
        self.assertEqual([(p['duration_ticks'],p['type'],bool(p.get('tuplet'))) for p in parts],[(160,'eighth',True),(240,'eighth',False)])

    def test_invalid_cross_beat_tuplet_rejected(self):
        with self.assertRaises(ValueError):split_rhythm_tuplets(0,480,tuplets=[self.group(120)])

    def test_overlapping_tuplets_rejected(self):
        with self.assertRaises(ValueError):split_rhythm_tuplets(0,480,tuplets=[self.group(),self.group()])

    def test_missing_tuplet_fragment_is_invalid(self):
        ev=[dict(split_rhythm_tuplets(0,160,tuplets=[self.group()])[0],id='e',pitch_midi=60)]
        self.assertFalse(validate_grouping(ev,[4,4])['valid'])

    def test_tuplet_beams_use_same_big_beat(self):
        ev=[dict(split_rhythm_tuplets(i*160,(i+1)*160,tuplets=[self.group()])[0],id=str(i),pitch_midi=60) for i in range(3)]
        self.assertEqual([xml_beams(ev,[4,4])[str(i)][0][1] for i in range(3)],['begin','continue','end'])

    def test_actual_xml_ratio_and_midi_intervals(self):
        import mido
        n,c,m,t,d=fixture([1.1,1.43,1.76],ends=[1.43,1.76,2.5]);t['structural_rhythm']={'version':1}
        ev,out,stats=quantize_phrase(n,c,m,t,d)
        p=read_json(ROOT/'results/雨天/project.json')
        p.update(events=ev,quantized_notes=out,statistics=stats,timing=t,tempo_events=[{'tick':0,'bpm':60}])
        p['notation']['key_segments']=[]
        xml=build_musicxml(p);trip=xml.findall('.//time-modification')
        self.assertTrue(trip);self.assertTrue(all(x.findtext('actual-notes')=='3' and x.findtext('normal-notes')=='2' for x in trip))
        self.assertEqual(len(xml.findall('.//tuplet[@type="start"]')),1)
        with TemporaryDirectory(dir=ROOT/'test_outputs') as folder:
            path=Path(folder)/'tuplet.mid';write_midi(path,p)
            tick=0;heads=[]
            for msg in mido.merge_tracks(mido.MidiFile(path).tracks):
                tick+=msg.time
                if msg.type=='note_on' and msg.velocity:heads.append(tick)
            self.assertEqual(heads[:3],[480,640,800])


class CompatibilityTests(unittest.TestCase):
    def test_old_delivery_still_strictly_reconstructs(self):
        p=read_json(ROOT/'results/accompaniment/雨天_v14_局部拍轴与原唱同步/project.json')
        self.assertTrue(validate_vocal_snapshot(p['accepted_vocal_project'],p['shared_analysis']['input_binding']))

    def test_changed_old_source_note_cannot_pass_snapshot(self):
        p=read_json(ROOT/'results/accompaniment/雨天_v14_局部拍轴与原唱同步/project.json')
        p['accepted_vocal_project']['quantized_notes'][0]['pitch_midi']+=1
        self.assertFalse(validate_vocal_snapshot(p['accepted_vocal_project'],p['shared_analysis']['input_binding']))

    def test_guitar_uses_shared_different_text_motif(self):
        from guitar_structure_patterns import structure_phrases
        n,c,m,t,d=fixture([.5,1,1.5,2,4.5,5,5.5,6],lines=[0]*4+[1]*4)
        for note in n:note.update(start_tick=round(note['start_seconds']*480),end_tick=round(note['end_seconds']*480))
        vocal={'lyrics':{'characters':c},'quantized_notes':n}
        shared={'statistics':{'bar_ticks':1920},'sections':[{'kind':'vocal','start_tick':0,'end_tick':3840}],
                'melodic_motif_matches':[{'reference_line':0,'target_line':1}]}
        phrases,_=structure_phrases(shared,vocal,[1,2])
        self.assertNotEqual(phrases[0]['text'],phrases[1]['text'])
        self.assertEqual(phrases[0]['repeat_group'],phrases[1]['repeat_group'])
        self.assertEqual(phrases[1]['repeat_source'],'shared_source_melody_alignment')


if __name__=='__main__':unittest.main()
