# 歌词对齐与真实制谱：新增真实草稿与校正版使用说明；文档状态仅描述已核查能力。
from pathlib import Path
p = Path('README.md')
s = p.read_text(encoding='utf-8-sig')
s = s.replace('当前正在推进 Windows 本地兼容性与样曲验证。', '当前正在推进 Windows 本地歌词对齐与真实人声制谱；兼容性基线已完成。')
s = s.replace('真实歌曲歌词、节奏制谱、接缝音乐质量仍待完成。', '真实歌曲初步歌词对齐、节奏制谱和校正版回导已跑通；自动音乐准确性与编辑器GUI往返仍需核查。')
s += '''

## 正确歌词与真实草稿

本轮《遇见》使用用户提供的25行歌词，原文保存为 test_outputs/lyrics/user_supplied/yu_jian.txt。识别原稿、用户文本、逐字候选时间、连续f0和最终记谱层分别保存。不可将ASR文本正确性、内部对齐诊断和MusicXML结构有效性混为同一准确率。

```powershell
.\\run_score.ps1 -LyricsFile .\\test_outputs\\lyrics\\user_supplied\\yu_jian.txt
# 分句路线：需同源ASR锚点，真实逐句模型推理；保留匹配代价和候选警告。
.\\run_score.ps1 -LyricsFile .\\test_outputs\\lyrics\\user_supplied\\yu_jian.txt -AlignmentBackend tifa-phrases
# 可选人工覆盖（示例值，需核对音乐）
.\\run_score.ps1 -LyricsFile .\\test_outputs\\lyrics\\user_supplied\\yu_jian.txt -Tempo 92.285 -Key 'Eb:major' -Meter '4/4'
```

每次在 test_outputs/score_runs/<run_id> 另存 refined、lyrics 和 score，并在 reports/score_runs/<run_id> 保存计时和阶段清单。入口检查整首零偏移模型报告；分句窗口仅以同源ASR/有声段定位，用户歌词仍是权威文本，不按字均分时间。无可靠时间的字保留警告，不强塞入音符。

score/jianpu.html 是全曲静态简谱，preview_first_vocal.png 是首段预览；vocal_draft.musicxml 供独立写谱软件校正，vocal_draft.mid 是自动记谱试听；project.json 保留秒—拍映射、量化误差、歌词冲突和原分析引用。review.html 可在本机浏览器点击试听优先复核候选，音频只引用同源本地人声。页面交互未通过GUI实测，文件/路径/SHA已由生成工具核对。

拍速和调性保留候选与启发式支持；4/4目前为弱证据显式先验。固定网格无法自动识别三连音；量化塌缩短音以待审倚音保留，不自动认定为原唱装饰音。简谱基准八度明确写成如1=Eb3（MIDI51）；导出MIDI/原音频同步需使用project中的score_start_seconds，而不是假设谱面第0秒等于原音频第0秒。

## 乐谱校正版回导

先在独立编辑器另存MusicXML，再使用对应原project回导；输出路径不能覆盖源项目。

```powershell
.\\.venv-gpu\\Scripts\\python.exe -B tools\\import_score.py import --musicxml '<校正后的.musicxml>' --project '<原project.json>' --output '<另存的校正版project.json>' --report '<回导报告.json>'
```

校正记谱层与原自动事件/连续f0分离，修订历史与原路径/SHA保留。ID丢失、重排或节奏变化导致身份匹配不确定时报告候选并返回状态码2，需要复核后处理。当前验证范围为单声部、完整小节和整数半音；多声部/微分音拒绝，不是完整MusicXML XSD支持。实际编辑器往返尚未实测；已完成的程序化副本修改/回导只证明当前格式的结构与数据保留。
'''
p.write_text(s, encoding='utf-8-sig')
print('README updated with draft and correction workflows')
