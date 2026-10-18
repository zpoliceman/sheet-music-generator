# 歌词对齐与真实制谱：依据一次实测改进选择默认路线，原参数与缓存行注释保留。
from pathlib import Path
p=Path('run_score.ps1')
s=p.read_text(encoding='utf-8-sig')
old="    [ValidateSet('turbo', 'medium')][string]$AsrModel = 'turbo',"
new="    # 歌词对齐与真实制谱：原turbo默认注释保留，修改为首尾幻觉较少的medium基线（仍需校正）。\n    # "+old.strip()+"\n    [ValidateSet('turbo', 'medium')][string]$AsrModel = 'medium',"
assert old in s
s=s.replace(old,new)
old="    [ValidateSet('tifa', 'tifa-phrases', 'asr-baseline')][string]$AlignmentBackend = 'tifa',"
new="    # 歌词对齐与真实制谱：原整曲默认注释保留，修改为实测改善首句且覆盖全文的分句模型路线。\n    # "+old.strip()+"\n    [ValidateSet('tifa', 'tifa-phrases', 'asr-baseline')][string]$AlignmentBackend = 'tifa-phrases',"
assert old in s
s=s.replace(old,new)
old="    $cacheCandidate = Join-Path $projectRoot 'test_outputs\\lyrics\\first_song\\asr_raw.json'"
new="    # 歌词对齐与真实制谱：原缓存固定路径注释保留，按显式型号选择既有基线。\n    # "+old.strip()+"\n    if ($AsrModel -eq 'medium') { $cacheCandidate = Join-Path $projectRoot 'test_outputs\\lyrics\\medium_candidate\\asr_raw.json' }\n    else { $cacheCandidate = Join-Path $projectRoot 'test_outputs\\lyrics\\first_song\\asr_raw.json' }"
assert old in s
s=s.replace(old,new)
old="        if ($aligned.source.sha256 -ne $lyricReference.source.sha256 -or $aligned.cache_key.text_sha256 -ne $expectedTextSha -or $aligned.reference_kind -ne $lyricReference.reference_kind) {"
new="        # 歌词对齐与真实制谱：原缓存匹配条件注释保留，新增偏移/时长，防止相同字节错用不同时间坐标。\n        # "+old.strip()+"\n        if ($aligned.source.sha256 -ne $lyricReference.source.sha256 -or $aligned.cache_key.text_sha256 -ne $expectedTextSha -or $aligned.reference_kind -ne $lyricReference.reference_kind -or $aligned.source.offset_seconds -ne $lyricReference.source.offset_seconds -or $aligned.source.duration_seconds -ne $lyricReference.source.duration_seconds) {"
assert old in s
s=s.replace(old,new)
anchor="        $run.alignment_reused = $true"
s=s.replace(anchor,"        # 歌词对齐与真实制谱：新增实际缓存后端状态记录，不把缓存命中说成本次新GPU推理。\n        $run.alignment_backend_requested = $AlignmentBackend\n"+anchor)
p.write_text(s,encoding='utf-8-sig')
print('default medium + genuine phrase alignment selected from measured evidence')
