# 歌词对齐与真实制谱：新增用户歌词文案与独立对齐报告快照，修改行保留注释。
from pathlib import Path
p = Path('tools/review_bundle.py')
s = p.read_text(encoding='utf-8-sig')
anchor = '    replacements = {"ALIGNMENT":'
assert anchor in s
s = s.replace(anchor, '    # 歌词对齐与真实制谱：新增用户提供歌词的准确来源文案，字音时间仍保留待核查状态。\n    if lyrics.get("reference_kind") == "user_supplied":\n        document = document.replace("歌词尚未人工校正", "歌词由用户提供，字音时间尚待核查")\n' + anchor)
p.write_text(s, encoding='utf-8-sig')
p = Path('run_score.ps1')
s = p.read_text(encoding='utf-8-sig')
old = "    Save-ScoreRun '歌词参考文本生成完成（自动结果尚未人工校正）' '完成TIFA对齐并核对对齐状态、逐字时间和旋律关系。'"
new = "    # 歌词对齐与真实制谱：原固定自动歌词日志注释保留，修改为区分用户文本与ASR来源。\n    # " + old.strip() + "\n    $lyricReference = Get-Content -LiteralPath (Join-Path $lyricsDir 'lyrics_reference.json') -Raw -Encoding UTF8 | ConvertFrom-Json\n    Save-ScoreRun ('歌词参考文本生成完成，来源：' + $lyricReference.reference_kind) '完成TIFA对齐并核对对齐状态、逐字时间和旋律关系。'"
assert old in s
s = s.replace(old, new)
anchor = "    $charactersPath = Join-Path $lyricsDir 'characters.json'"
s = s.replace(anchor, "    # 歌词对齐与真实制谱：新增本次TIFA计时与诊断报告快照，避免后续运行覆盖本次证据。\n    Copy-Item -LiteralPath (Join-Path $projectRoot 'reports\\lyrics_alignment.json') -Destination (Join-Path $reportDir 'lyrics_alignment.json')\n" + anchor)
p.write_text(s, encoding='utf-8-sig')
print('user reference wording and alignment report snapshot added')
