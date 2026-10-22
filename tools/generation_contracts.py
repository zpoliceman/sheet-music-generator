"""Validate the data passed between fresh-generation stages, without certifying music accuracy."""
from pathlib import Path
import hashlib
import json
import math

class GenerationConflict(ValueError):
    def __init__(self, stage, message, **details):
        self.report={'valid':False,'stage':stage,'message':message,'details':details}
        super().__init__('制谱步骤衔接失败（'+stage+'）：'+message)

def require(condition, stage, message, **details):
    if not condition:raise GenerationConflict(stage,message,**details)

def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))

def digest(path, check_cancel=lambda:None):
    value=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):
            check_cancel();value.update(block)
    return value.hexdigest()

def finite(value):
    return isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value)

def source_matches(record, path, stage, check_cancel=lambda:None):
    path=Path(path).resolve()
    require(Path(record.get('path','')).resolve()==path,stage,'当前结果引用了另一份音源。',expected=str(path),observed=record.get('path'))
    require(path.is_file(),stage,'被引用的人声音源不存在。',path=str(path))
    require(record.get('sha256')==digest(path,check_cancel),stage,'当前结果中的音源摘要与实际文件不同。',path=str(path))
    require(finite(record.get('duration_seconds')) and record['duration_seconds']>0,stage,'音源时长无效。')
    return record['duration_seconds']

def check_separation(report_path, mixed, check_cancel=lambda:None):
    import soundfile as sf
    stage='分轨→旋律识别';report=read(report_path)
    result=report.get('checks',{}).get('demucs_short_inference',{})
    require(Path(result.get('input','')).resolve()==Path(mixed).resolve(),stage,'分轨报告引用的混音不属于本任务。')
    duration=sf.info(mixed).duration;outputs=result.get('outputs',{})
    require('vocals' in outputs and len(outputs)>=4,stage,'人声或伴奏分轨未完整生成。',roles=list(outputs))
    for role,path in outputs.items():
        check_cancel();require(Path(path).is_file(),stage,'分轨文件缺失。',role=role,path=str(path))
        info=sf.info(path)
        require(info.frames>0 and abs(info.duration-duration)<=.06,stage,'分轨时长与原音不一致，不能继续对齐。',role=role,expected_seconds=duration,actual_seconds=info.duration)
    return {'valid':True,'stage':stage,'duration_seconds':duration,'roles':list(outputs),'musical_accuracy_verified':False}

def check_analysis(path, vocal_audio, check_cancel=lambda:None):
    stage='旋律识别→歌词对齐';analysis=read(path);duration=source_matches(analysis.get('source',{}),vocal_audio,stage,check_cancel)
    notes=analysis.get('notes',[]);pitched=[n for n in notes if not n.get('is_rest')]
    require(bool(pitched),stage,'没有识别到可用于制谱的演唱音符。')
    identities=set()
    for note in notes:
        check_cancel();begin=note.get('start_seconds');end=note.get('end_seconds')
        require(finite(begin) and finite(end) and -.06<=begin<end<=duration+.06,stage,'旋律音符的源时间无效或超出音源。',note_id=note.get('id'),start=begin,end=end,duration=duration)
        require(note.get('id') and note['id'] not in identities,stage,'旋律音符编号缺失或重复。',note_id=note.get('id'));identities.add(note['id'])
        require(finite(note.get('pitch_midi')) and 0<=note['pitch_midi']<=127,stage,'旋律音高不在有效范围内。',note_id=note['id'])
    return {'valid':True,'stage':stage,'notes':len(notes),'pitched_notes':len(pitched),'source_sha256':analysis['source']['sha256'],'musical_accuracy_verified':False}

def check_lyrics(path, analysis_path, anchor=None, check_cancel=lambda:None):
    stage='歌词对齐→简谱';data=read(path);analysis=read(analysis_path)
    require(data.get('source')==analysis.get('source'),stage,'歌词与旋律来自不同的人声音源或时间轴。')
    if anchor is not None:
        require(read(anchor).get('source')==analysis.get('source'),stage,'定位演唱句子的识别结果与旋律来源不一致。')
    characters=data.get('characters')
    if characters is None:
        require(bool(data.get('text','').strip()),stage,'歌词正文为空。')
        return {'valid':True,'stage':stage,'reference_only':True,'musical_accuracy_verified':False}
    require(bool(characters),stage,'对齐结果没有歌词单位。')
    identities=set();timed=0;duration=analysis['source']['duration_seconds']
    for char in characters:
        check_cancel();identity=char.get('index');require(isinstance(identity,int) and identity not in identities,stage,'歌词单位编号缺失或重复。',character_index=identity);identities.add(identity)
        begin=char.get('start_seconds');end=char.get('end_seconds')
        if begin is None and end is None:continue
        require(finite(begin) and finite(end) and -.06<=begin<=end<=duration+.06,stage,'歌词单位的源时间无效或超出人声音源。',character_index=identity,start=begin,end=end,duration=duration)
        timed+=1
    require(timed>0,stage,'歌词尚无可用的对齐时间，不能生成有歌词的简谱。')
    return {'valid':True,'stage':stage,'characters':len(characters),'characters_with_time':timed,'unresolved_characters':len(characters)-timed,'musical_accuracy_verified':False}

def check_vocal(project, stage='简谱→共享和声', check_cancel=lambda:None):
    timing=project.get('timing',{});stats=project.get('statistics',{});total=stats.get('total_ticks');bar=stats.get('bar_ticks')
    require(finite(total) and total>0 and finite(bar) and bar>0,stage,'简谱缺少有效曲长或小节长度。')
    knots=timing.get('knots',[])
    require(len(knots)>=2,stage,'简谱没有完整的秒数与拍数换算表。')
    for point in knots:
        require(finite(point.get('quarter')) and finite(point.get('seconds')),stage,'拍轴含无效数值。')
    require(all(a['quarter']<b['quarter'] and a['seconds']<b['seconds'] for a,b in zip(knots,knots[1:])),stage,'拍轴出现重复或倒序，不能继续换算时间。')
    notes=project.get('quantized_notes',[]);require(bool(notes),stage,'简谱没有已记谱音符。');identities=set()
    for note in notes:
        check_cancel();identity=note.get('id');begin=note.get('start_tick');end=note.get('end_tick')
        require(identity and identity not in identities,stage,'简谱音符编号缺失或重复。',note_id=identity);identities.add(identity)
        require(finite(begin) and finite(end) and 0<=begin<=end<=total and (note.get('grace') or begin<end),stage,'简谱音符边界超出曲长或时值无效。',note_id=identity,start=begin,end=end,total=total)
        require(finite(note.get('pitch_midi')) and 0<=note['pitch_midi']<=127,stage,'简谱音高无效。',note_id=identity)
    return {'valid':True,'stage':stage,'notes':len(notes),'total_ticks':total,'musical_accuracy_verified':False}

def check_melody(path, analysis_path, lyrics_path, mixed, check_cancel=lambda:None):
    stage='简谱→共享和声';project=read(path)
    report=check_vocal(project,stage,check_cancel)
    for key,value in (('notes',analysis_path),('lyrics',lyrics_path),('mix_audio',mixed)):
        value=Path(value).resolve();inputs=project.get('inputs',{})
        require(Path(inputs.get(key+'_path','')).resolve()==value,stage,'简谱引用了本任务之外的输入。',input_kind=key,expected=str(value),observed=inputs.get(key+'_path'))
        require(inputs.get(key+'_sha256')==digest(value,check_cancel),stage,'简谱输入摘要与当前文件不一致。',input_kind=key)
    require(project['inputs'].get('transcription_source')==read(analysis_path).get('source'),stage,'简谱与旋律识别的人声来源不一致。')
    return report


def check_shared(shared,vocal,stage='共享和声→吉他编配',check_cancel=lambda:None):
    require(shared.get('timing')==vocal.get('timing'),stage,'共享和声与当前简谱使用不同拍轴，必须先重新投影再编配。')
    for key in ('bar_ticks','total_ticks','measure_count'):
        require(shared.get('statistics',{}).get(key)==vocal.get('statistics',{}).get(key),stage,'共享和声与简谱的小节或曲长记录不同。',field=key,shared=shared.get('statistics',{}).get(key),vocal=vocal.get('statistics',{}).get(key))
    total=vocal['statistics']['total_ticks'];previous=0;identities=set();harmony=shared.get('harmony',[])
    require(bool(harmony),stage,'共享和声为空。')
    for chord in harmony:
        check_cancel();begin=chord.get('start_tick');end=chord.get('end_tick')
        require(finite(begin) and finite(end) and 0<=begin<end<=total,stage,'和弦边界无效或超出当前曲长。',chord_id=chord.get('id'),start=begin,end=end,total=total)
        require(begin>=previous,stage,'共享和弦的时间区间重叠或倒序。',chord_id=chord.get('id'));previous=end
        require(chord.get('id') and chord['id'] not in identities,stage,'共享和弦编号缺失或重复。',chord_id=chord.get('id'));identities.add(chord['id'])
    return {'valid':True,'stage':stage,'harmony_segments':len(harmony),'total_ticks':total,'musical_accuracy_verified':False}

def check_vocal_midi(path, vocal, check_cancel=lambda:None):
    """Read actual vocal MIDI notes, independent of the XML export report."""
    import mido
    midi=mido.MidiFile(path);observed=[];tempos=[];errors=[]
    for track in midi.tracks:
        tick=0;active={}
        for message in track:
            check_cancel();tick+=message.time
            if message.type=='set_tempo':tempos.append((tick,message.tempo))
            if message.type=='note_on' and message.velocity:
                active.setdefault((message.channel,message.note),[]).append(tick)
            elif message.type=='note_off' or message.type=='note_on' and not message.velocity:
                key=(message.channel,message.note)
                if not active.get(key):errors.append('unmatched_vocal_note_off')
                else:observed.append((active[key].pop(0),tick,message.note))
        if any(active.values()):errors.append('unreleased_vocal_note')
    expected=[]
    for note in vocal['quantized_notes']:
        begin=note.get('playback_start_tick',note['start_tick']);end=note.get('playback_end_tick',note['end_tick'])
        if end==begin:
            begin,end=max(0,begin-24),begin
            if end==begin:end+=24
        expected.append((begin,end,note['pitch_midi']))
    if midi.ticks_per_beat!=480:errors.append('vocal_midi_tick_unit_mismatch')
    if sorted(observed)!=sorted(expected):errors.append('vocal_midi_pitch_or_playback_interval_mismatch')
    expected_tempos=[(event['tick'],min(0xFFFFFF,max(1,round(60000000/event['bpm'])))) for event in vocal['tempo_events']]
    if sorted(tempos)!=sorted(expected_tempos):errors.append('vocal_midi_tempo_mismatch')
    return {'valid':not errors,'errors':errors,'note_count':len(observed),
            'exact_pitches_playback_intervals_and_tempo':not errors,'musical_accuracy_verified':False}


def check_delivery(path, check_cancel=lambda:None):
    stage='完整曲谱→预览与导出';path=Path(path);project=read(path/'project.json')
    manifest=read(path/'manifest.json')
    variable=manifest.get('exporter')=='variable_measure_timeline'
    validation=read(path/('export_validation.json' if variable else 'validation.json'))
    check_vocal(project['accepted_vocal_project'],stage,check_cancel)
    check_shared(project['shared_analysis'],project['accepted_vocal_project'],stage,check_cancel)
    if variable:
        require(validation.get('valid') is True and validation.get('status')=='actual_artifacts_passed',stage,'实际小节导出未通过成品检查。',status=validation.get('status'))
        checks=validation.get('checks',{})
        for kind in ('vocal','guitar'):
            require(checks.get(kind,{}).get('valid') is True,stage,'实际小节导出缺少完整简谱或吉他检查。',instrument=kind)
        require(checks['guitar'].get('midi',{}).get('valid') is True,stage,'实际小节导出的吉他MIDI未通过检查。')
        vocal_midi=check_vocal_midi(path/'vocal/score.mid',project['accepted_vocal_project'],check_cancel)
        require(vocal_midi['valid'],stage,'实际简谱MIDI与演唱音符或速度不同。',check=vocal_midi)
        for key in ('repeat','readability_acceptance'):
            require(checks['guitar'].get(key,{}).get('valid') is True,stage,'实际小节吉他谱缺少通过的检查。',check=key)
        midi='guitar/score.mid'
    else:
        require(validation.get('status')=='structural_and_playability_checks_passed',stage,'生成程序未通过结构与可弹性检查。',status=validation.get('status'))
        instrument=validation.get('instruments',{}).get('guitar',{})
        for key in ('xml','midi','playability','tab'):
            require(instrument.get(key,{}).get('valid') is True,stage,'实际吉他产物缺少通过的检查。',check=key)
        for key in ('guitar_repeat_layout','guitar_readability_acceptance','vocal_delivery'):
            require(validation.get(key,{}).get('valid') is True,stage,'实际完整谱缺少通过的检查。',check=key)
        midi='guitar/accompaniment.mid'
    for name in ('index.html','guitar/score.html','guitar/score_full.html','guitar/score.musicxml',midi,'guitar/preview.wav','guitar/singing_preview.wav','guitar/repeat_plan.json','vocal/score.html'):
        target=path/name;require(target.is_file() and target.stat().st_size>0,stage,'完整草稿缺少实际文件。',file=name)
    from draft_music_review import verify_draft
    verify_draft(project,path/'project.json')
    require(bool(manifest.get('files')),stage,'成品清单为空，不能报告完整生成。')
    for item in manifest.get('files',[]):
        check_cancel();target=(path/item['path']).resolve()
        require(target.is_relative_to(path.resolve()) and target.is_file(),stage,'成品清单指向目录外或缺失文件。',file=item['path'])
        require(digest(target,check_cancel)==item['sha256'],stage,'成品文件与清单摘要不同。',file=item['path'])
    return {'valid':True,'stage':stage,'guitar_notes':len(project['arrangements']['guitar']['notes']),'manifest_files':len(manifest.get('files',[])),'status':'complete_review_draft','exporter':'variable_measure_timeline' if variable else 'regular_measures','musical_accuracy_verified':False}
