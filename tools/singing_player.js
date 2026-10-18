// 结构稳定伴奏与人声合播：新增共用AudioContext的双轨播放器，离线文件不依赖fetch。
(() => {
  const panel = document.getElementById('singing-player');
  if (!panel || !window.accompanimentSingingData) return;
  const data = window.accompanimentSingingData;
  const seek = document.getElementById('singing-seek');
  const status = document.getElementById('singing-status');
  const time = document.getElementById('singing-time');
  const voiceVolume = document.getElementById('singing-voice');
  const accompanimentVolume = document.getElementById('singing-accompaniment');
  let ctx, voiceGain, accompanimentGain, buffers, loading, sources = [];
  let position = 0, startedAt = 0, playing = false, request = 0;
  seek.max = String(data.duration);
  const stamp = seconds => `${Math.floor(seconds / 60)}:${String(Math.floor(seconds % 60)).padStart(2, '0')}`;
  // 结构稳定伴奏与人声合播：播放预约尚未开始时不出现负时间。
  // 原代码：const current = () => playing ? Math.min(data.duration, position + ctx.currentTime - startedAt) : position;
  const current = () => playing ? Math.min(data.duration, position + Math.max(0, ctx.currentTime - startedAt)) : position;
  const update = () => {
    const value = current(); seek.value = String(value);
    time.textContent = `${stamp(value)} / ${stamp(data.duration)}`;
    panel.dataset.playing = String(playing);
  };
  const stopSources = () => {
    sources.forEach(source => { source.onended = null; try { source.stop(); } catch (_) {} source.disconnect(); });
    sources = [];
  };
  const pause = () => { request++; position = current(); playing = false; stopSources(); update(); };
  const decode = (encoded) => {
    const raw = atob(encoded); const bytes = new Uint8Array(raw.length);
    for (let i = 0; i < raw.length; i++) bytes[i] = raw.charCodeAt(i);
    return ctx.decodeAudioData(bytes.buffer);
  };
  const ensure = async () => {
    if (!ctx) {
      const Audio = window.AudioContext || window.webkitAudioContext;
      if (!Audio) throw new Error('当前浏览器不支持独立音量控制，请使用下方合播音频。');
      ctx = new Audio(); const master = ctx.createGain(); master.gain.value = data.masterGain;
      const limiter = ctx.createDynamicsCompressor(); limiter.threshold.value = -1; limiter.knee.value = 3; limiter.ratio.value = 20;
      voiceGain = ctx.createGain(); accompanimentGain = ctx.createGain();
      voiceGain.connect(master); accompanimentGain.connect(master); master.connect(limiter); limiter.connect(ctx.destination);
      loading = Promise.all([decode(window.accompanimentVocalBuffer), decode(data.accompaniment)]).then(values => {
        buffers = values;
        const error = Math.max(...values.map(buffer => Math.abs(buffer.duration - data.duration)));
        if (error > .002) throw new Error('音频解码时长不匹配，请使用下方合播音频。');
        window.singingPlayback.diagnostics = { sampleRate: ctx.sampleRate, durations: values.map(b => b.duration), durationError: error };
        panel.dataset.ready = 'true';
      });
    }
    await ctx.resume(); await loading;
    voiceGain.gain.value = Number(voiceVolume.value); accompanimentGain.gain.value = Number(accompanimentVolume.value);
  };
  const playFrom = async (seconds) => {
    pause(); position = Math.max(0, Math.min(data.duration - .001, Number(seconds))); update();
    const ticket = ++request; status.textContent = '正在准备合播…';
    try {
      await ensure(); if (ticket !== request) return;
      document.querySelectorAll('audio').forEach(audio => audio.pause());
      const when = ctx.currentTime + .06; startedAt = when; playing = true;
      sources = buffers.map((buffer, index) => {
        const source = ctx.createBufferSource(); source.buffer = buffer;
        source.connect(index === 0 ? voiceGain : accompanimentGain); source.start(when, position); return source;
      });
      window.singingPlayback.lastStart = { contextTime: when, offset: position, tracks: sources.length };
      sources[1].onended = () => { if (playing) { position = data.duration; playing = false; stopSources(); update(); } };
      status.textContent = '人声与伴奏同步播放'; update();
    } catch (error) { playing = false; stopSources(); status.textContent = error.message; panel.dataset.error = error.message; update(); }
  };
  document.getElementById('singing-play').addEventListener('click', () => playFrom(position >= data.duration - .01 ? 0 : current()));
  document.getElementById('singing-pause').addEventListener('click', pause);
  seek.addEventListener('change', () => { const value = Number(seek.value); if (playing) playFrom(value); else { position = value; update(); } });
  // 结构稳定伴奏与人声合播：修改，实时手动音量直接设置固有值，避免暂停状态的自动化读回滞后。
  // voiceVolume.addEventListener('input', () => { if (voiceGain) voiceGain.gain.setValueAtTime(Number(voiceVolume.value), ctx.currentTime); });
  // accompanimentVolume.addEventListener('input', () => { if (accompanimentGain) accompanimentGain.gain.setValueAtTime(Number(accompanimentVolume.value), ctx.currentTime); });
  voiceVolume.addEventListener('input', () => { if (voiceGain) voiceGain.gain.value = Number(voiceVolume.value); });
  accompanimentVolume.addEventListener('input', () => { if (accompanimentGain) accompanimentGain.gain.value = Number(accompanimentVolume.value); });
  document.querySelectorAll('button[data-singing-second]').forEach(button => button.addEventListener('click', () => playFrom(Number(button.dataset.singingSecond))));
  document.querySelectorAll('audio').forEach(audio => audio.addEventListener('play', () => { pause(); document.querySelectorAll('audio').forEach(other => { if (audio !== other) other.pause(); }); }));
  window.singingPlayback = { playFrom, pause, position: current, diagnostics: null,
    gains: () => ({ voice: voiceGain?.gain.value ?? Number(voiceVolume.value), accompaniment: accompanimentGain?.gain.value ?? Number(accompanimentVolume.value) }) };
  const animate = () => { if (playing) update(); requestAnimationFrame(animate); }; update(); animate();
})();
