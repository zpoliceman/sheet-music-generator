"""结构稳定伴奏与人声合播：真实人声共同时钟试听与离线浏览器播放器。"""
# 结构稳定伴奏与人声合播：新增源人声重采样/起点补偿，仅写新交付目录。
from pathlib import Path
from workspace_location import local_path
import base64
import hashlib
import json
import math
import numpy as np
import soundfile as sf
from scipy.signal import resample_poly
from accompaniment_analysis import SongClock
from score_export import sha256, save_json


# 结构稳定伴奏与人声合播：新增分块OGG写入，避免Windows libsndfile长数组编码栈溢出。
def write_ogg(path,samples,sample_rate):
    with sf.SoundFile(path,mode='w',samplerate=sample_rate,channels=samples.shape[1],format='OGG',subtype='VORBIS') as stream:
        for begin in range(0,len(samples),16384):stream.write(samples[begin:begin+16384])


def align_samples(samples, source_rate, target_rate, offset_seconds, frames):
    samples=np.asarray(samples,dtype=np.float32)
    if samples.ndim==1:samples=samples[:,None]
    divisor=math.gcd(int(source_rate),int(target_rate))
    if source_rate!=target_rate:samples=resample_poly(samples,target_rate//divisor,source_rate//divisor,axis=0).astype(np.float32)
    offset=round(offset_seconds*target_rate); output=np.zeros((frames,samples.shape[1]),dtype=np.float32)
    source_start=max(0,-offset);dest_start=max(0,offset)
    length=max(0,min(len(samples)-source_start,frames-dest_start))
    if length:output[dest_start:dest_start+length]=samples[source_start:source_start+length]
    return output, {'offset_samples':offset,'source_crop_samples':source_start,
                    'destination_pad_samples':dest_start,'copied_samples':length}


# 结构稳定伴奏与人声合播：新增一次准备共享真实人声，不重复分离、不改原文件。
def prepare_vocals(output,shared,vocal):
    output=Path(output);folder=output/'audio';folder.mkdir(exist_ok=True)
    source=shared['input_binding']['sources']['vocals']
    if sha256(source['path'])!=source['sha256']:raise ValueError('合播人声来源指纹已改变')
    shift=int(vocal['notation'].get('transpose_semitones',0))
    samples,sr=sf.read(local_path(source['path']),always_2d=True,dtype='float32')
    # 结构稳定伴奏与人声合播：新增显式目标调支持；原人声只读，转换试听另存。
    if shift:
        import librosa
        samples=np.stack([librosa.effects.pitch_shift(samples[:,c],sr=sr,n_steps=shift) for c in range(samples.shape[1])],axis=1)
    # 原曲拍轴与歌词拍位通用修复：修改，旧按正首拍裁掉原声起点保留；新源层的两套音频使用完整原声共同起点。
    # clock=SongClock(vocal);origin=clock.seconds(0);duration=clock.seconds(clock.total_ticks)-origin
    clock=SongClock(vocal);origin=clock.audio_origin_seconds;duration=clock.seconds(clock.total_ticks)-origin
    frames=math.ceil(duration*sr);offset=float(source.get('offset_seconds',0))-origin
    aligned,placement=align_samples(samples,sr,sr,offset,frames)
    peak=float(np.abs(aligned).max(initial=0));voice_scale=min(1.,.97/max(1e-9,peak));aligned*=voice_scale
    sf.write(folder/'vocals_aligned.wav',aligned,sr,subtype='PCM_16')
    # 结构稳定伴奏与人声合播：修改，原整数组编码保留；使用固定小块写入长歌曲。
    # sf.write(folder/'vocals_aligned.ogg',aligned,sr,format='OGG',subtype='VORBIS')
    write_ogg(folder/'vocals_aligned.ogg',aligned,sr)
    decoded,dsr=sf.read(folder/'vocals_aligned.ogg',always_2d=True,dtype='float32')
    if dsr!=sr or len(decoded)!=frames:raise ValueError('人声编码改变了合播时钟长度')
    encoded=base64.b64encode((folder/'vocals_aligned.ogg').read_bytes()).decode('ascii')
    (folder/'vocal_buffer.js').write_text('// 结构稳定伴奏与人声合播：离线人声数据，使用共同时钟解码。\nwindow.accompanimentVocalBuffer='+json.dumps(encoded)+';\n',encoding='utf-8')
    meta={'source_path':source['path'],'source_sha256':source['sha256'],'sample_rate':sr,
          'channels':aligned.shape[1],'frames':frames,'duration_seconds':frames/sr,
          'origin_song_seconds':origin,'source_offset_seconds':source.get('offset_seconds',0),
          'placement_seconds':offset,'voice_scale':voice_scale,'transpose_semitones':shift,
          'placement':placement,'encoded_frames':len(decoded),
          'vocal_kind':'original_separated_singer_audio',
          'alignment_error_seconds':abs(placement['offset_samples']/sr-offset)}
    # 原曲拍轴与歌词拍位通用修复：新增仅新正首拍层的谱／音频起点区别，旧交付元数据字节保持原格式。
    if origin!=clock.seconds(0):
        meta['score_start_song_seconds']=clock.seconds(0)
        meta['original_source_frames_preserved']=placement['copied_samples']==len(samples) and placement['source_crop_samples']==0
    save_json(folder/'vocal_alignment.json',meta)
    return aligned,meta


# 结构稳定伴奏与人声合播：新增分别合成两套合播音频，WAV作精确验证、OGG作离线控制。
def write_singing_preview(folder,preview_path,voice,voice_meta):
    folder=Path(folder);sr=voice_meta['sample_rate'];frames=len(voice)
    accompaniment,asr=sf.read(preview_path,always_2d=True,dtype='float32')
    accompaniment,_=align_samples(accompaniment,asr,sr,0,frames)
    if accompaniment.shape[1]==1 and voice.shape[1]>1:accompaniment=np.repeat(accompaniment,voice.shape[1],axis=1)
    vg,ag=.8,.35;mix=voice*vg+accompaniment*ag
    peak=float(np.abs(mix).max(initial=0));master=min(1.,.95/max(1e-9,peak));mix*=master
    if not np.isfinite(mix).all():raise ValueError('合播存在非有限样本')
    sf.write(folder/'singing_preview.wav',mix,sr,subtype='PCM_16')
    # 结构稳定伴奏与人声合播：修改，原整数组编码保留；两轨用相同分块编码路径。
    # sf.write(folder/'accompaniment_preview.ogg',accompaniment,sr,format='OGG',subtype='VORBIS')
    write_ogg(folder/'accompaniment_preview.ogg',accompaniment,sr)
    decoded,dsr=sf.read(folder/'accompaniment_preview.ogg',always_2d=True,dtype='float32')
    if dsr!=sr or len(decoded)!=frames:raise ValueError('伴奏编码改变了合播时钟长度')
    encoded=base64.b64encode((folder/'accompaniment_preview.ogg').read_bytes()).decode('ascii')
    meta={'sample_rate':sr,'channels':mix.shape[1],'frames':frames,'duration_seconds':frames/sr,
          'origin_song_seconds':voice_meta['origin_song_seconds'],'voice_gain':vg,'accompaniment_gain':ag,
          'master_gain':master,'peak':float(np.abs(mix).max(initial=0)),
          'voice_kind':'original_separated_singer_audio','clock':'one_audio_context',
          'encoded_frames':len(decoded),'source_sha256':voice_meta['source_sha256']}
    code=(Path(__file__).parent/'singing_player.js').read_text(encoding='utf-8')
    payload={'accompaniment':encoded,'duration':frames/sr,'sampleRate':sr,'frames':frames,
             'voiceGain':vg,'accompanimentGain':ag,'masterGain':master}
    (folder/'singing_player.js').write_text('// 结构稳定伴奏与人声合播：本乐器离线同步试听数据。\nwindow.accompanimentSingingData='+json.dumps(payload,separators=(',',':'))+';\n'+code,encoding='utf-8')
    save_json(folder/'singing_preview.json',meta)
    return meta


# 结构稳定伴奏与人声合播：新增常规浏览器无需网络的控制面板，产品页面不展示编码实现。
def singing_player_html():
    return '''<div class="singing-player" id="singing-player"><label><b>原歌手人声＋本谱伴奏</b></label>
<div class="singing-actions"><button id="singing-play" type="button">播放合播</button><button id="singing-pause" type="button">暂停</button><span id="singing-time">0:00 / 0:00</span></div>
<label>播放位置 <input id="singing-seek" type="range" min="0" step="0.01" value="0" aria-label="合播播放位置"></label>
<div class="singing-gains"><label>人声音量 <input id="singing-voice" type="range" min="0" max="1.2" step="0.01" value="0.8" aria-label="人声音量"></label><label>伴奏音量 <input id="singing-accompaniment" type="range" min="0" max="1.2" step="0.01" value="0.35" aria-label="伴奏音量"></label></div>
<p class="muted" id="singing-status" role="status">可独立调整人声与伴奏音量，调至0可静音。</p>
<details><summary>合播音频与下载</summary><audio id="singing-file" controls preload="metadata" src="singing_preview.wav"></audio><a href="singing_preview.wav" download>下载人声合播</a></details></div>
<script defer src="../audio/vocal_buffer.js"></script><script defer src="singing_player.js"></script>'''


# 结构稳定伴奏与人声合播：新增音频读回验证，核对实际样本而非仅按钮存在。
def validate_singing_preview(folder,shared,vocal):
    folder=Path(folder);meta=json.loads((folder/'singing_preview.json').read_text(encoding='utf-8'))
    vm=json.loads((folder.parent/'audio/vocal_alignment.json').read_text(encoding='utf-8'))
    voice,sr=sf.read(folder.parent/'audio/vocals_aligned.wav',always_2d=True,dtype='float32')
    preview,psr=sf.read(folder/'preview.wav',always_2d=True,dtype='float32')
    acc,_=align_samples(preview,psr,sr,0,len(voice))
    if acc.shape[1]==1 and voice.shape[1]>1:acc=np.repeat(acc,voice.shape[1],axis=1)
    actual,msr=sf.read(folder/'singing_preview.wav',always_2d=True,dtype='float32')
    expected=(voice*meta['voice_gain']+acc*meta['accompaniment_gain'])*meta['master_gain']
    error=float(np.max(np.abs(actual-expected))) if actual.shape==expected.shape else float('inf')
    errors=[];clock=SongClock(vocal)
    if msr!=sr or len(actual)!=vm['frames']:errors.append('combined_rate_or_frames_mismatch')
    if error>2.1/32768:errors.append('combined_samples_differ_from_voice_and_accompaniment')
    # 原曲拍轴与歌词拍位通用修复：修改，旧偏移式保留；验证实际原唱全帧使用共同音频起点。
    # desired=float(shared['input_binding']['sources']['vocals'].get('offset_seconds',0))-clock.seconds(0)
    desired=float(shared['input_binding']['sources']['vocals'].get('offset_seconds',0))-clock.audio_origin_seconds
    if abs(vm['placement']['offset_samples']/sr-desired)>.5/sr+1e-10:errors.append('voice_source_time_offset_wrong')
    if vm['source_sha256']!=shared['input_binding']['sources']['vocals']['sha256']:errors.append('wrong_original_singer_source')
    # 结构稳定伴奏与人声合播：新增从原人声重新构造样本验证，不能仅信偏移元数据。
    source = shared['input_binding']['sources']['vocals']
    if sha256(source['path']) != source['sha256']: errors.append('original_voice_source_changed')
    original,osr=sf.read(local_path(source['path']),always_2d=True,dtype='float32')
    shift=int(vocal['notation'].get('transpose_semitones',0))
    if shift:
        import librosa
        original=np.stack([librosa.effects.pitch_shift(original[:,c],sr=osr,n_steps=shift) for c in range(original.shape[1])],axis=1)
    expected_voice,_=align_samples(original,osr,sr,desired,len(voice))
    expected_voice*=vm['voice_scale']
    source_error=float(np.max(np.abs(expected_voice-voice))) if expected_voice.shape==voice.shape else float('inf')
    if source_error>1.1/32768:errors.append('aligned_voice_samples_differ_from_original_source')
    if not np.isfinite(actual).all() or not np.any(np.abs(actual)>.0001):errors.append('combined_audio_invalid_or_silent')
    if float(np.abs(actual).max(initial=0))>=.999:errors.append('combined_audio_clipped')
    return {'valid':not errors,'errors':errors,'frames':len(actual),'sample_rate':msr,
            'maximum_mix_sample_error':error,'voice_placement_seconds':vm['placement']['offset_samples']/sr,
            # 结构稳定伴奏与人声合播：修改，原末字段注释保留；记录实际人声样本误差。
            # 'source_sha256':vm['source_sha256']}
            'source_sha256':vm['source_sha256'],'maximum_original_voice_sample_error':source_error}
