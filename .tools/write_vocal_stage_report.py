# 歌词对齐与真实制谱：新增阶段汇总与当前产物指针，所有数值来自已保存真实报告。
from pathlib import Path
from datetime import datetime
import json
root=Path.cwd(); run_id='20261005_192901_116'; folder=root/'test_outputs/score_runs'/run_id; score=folder/'score'; rdir=root/'reports/score_runs'/run_id
load=lambda path:json.loads(Path(path).read_text(encoding='utf-8-sig'))
run=load(rdir/'run.json'); export=load(rdir/'score_export.json'); phrase=load(rdir/'lyrics_alignment.json'); correction=load(root/'reports/score_correction.latest.json')
checks=load(root/'reports/final_score_checks.json')
checks['png_visual_checked']='root viewed actual final preview_first_vocal.png; Chinese/accidentals/octave label/spacing/ties readable'
checks['correction_import_checked']=correction['status']=='corrected_score_imported' and correction['uncertain_event_count']==0
(root/'reports/final_score_checks.json').write_text(json.dumps(checks,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
current={'schema_version':1,'task':'歌词对齐与真实制谱','run_id':run_id,'status':'real_vocal_draft_ready_for_manual_musical_review',
         'audio_seconds':209.76,'lyrics_reference_kind':'user_supplied','lyric_characters':237,'mapped_characters':237,'warning_characters':69,
         'measure_count':82,'quarter_beats':328,'refined_pitched_notes':333,'notation_events':563,'tempo_bpm_candidate':export['tempo_bpm'],
         'key_candidate':export['key']['label'],'meter':'4/4','meter_status':'weak_evidence_explicit_prior_requires_confirmation',
         'musical_accuracy_verified':False,'external_editor_roundtrip':'not_tested','review_playback_gui_tested':False,
         'timings':{'scope':'分别实测，不合并称为全链benchmark；缓存导出不是新GPU推理',
                    'real_phrase_alignment_first_wall_seconds':phrase['wall_seconds'],'cached_score_pipeline_wall_seconds':run['wall_seconds'],
                    'programmatic_correction_import_seconds':correction.get('wall_seconds',None)},
         'artifacts':{'musicxml':str(score/'vocal_draft.musicxml'),'jianpu':str(score/'jianpu.html'),'svg':str(score/'jianpu.svg'),
                      'midi':str(score/'vocal_draft.mid'),'project':str(score/'project.json'),'review':str(score/'review.html'),
                      'preview':str(score/'preview_first_vocal.png'),'lyrics':str(root/'test_outputs/lyrics/user_supplied/yu_jian.txt'),
                      'alignment':str(folder/'lyrics/characters.json'),'run_report':str(rdir/'run.json'),
                      'correction_test_report':str(root/'reports/score_correction.latest.json'),'summary':str(root/'reports/real_vocal_draft.md')},
         'limitations':['69个字有窗口/锚点或尾音边缘复核标记，包括2字crop右缘可能截尾',
                        '14个网格塌缩短音以待审倚音保留，固定十六分网格不自动识别三连音',
                        '调性/拍号/半拍倍拍存在候选歧义；未建立人工音高/节奏质量基线',
                        'GUI编辑器/HTML播放交互未实测；Windows控制运行内核因deny-read ACLs退出']}
(root/'reports/current_score.json').write_text(json.dumps(current,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
text=f'''# 首份真实带歌词人声乐谱草稿

已用用户提供的25行《遇见》歌词生成82小节可编辑草稿；237个有效歌词字从用户输入、逐字候选、项目到MusicXML完整同序。当前产物运行：{run_id}；它是待人工音乐校正的草稿，全部挂谱不是准确率100%。当前指针：current_score.json。

## 可打开的产物

- [全曲简谱](../test_outputs/score_runs/{run_id}/score/jianpu.html)、[首段PNG](../test_outputs/score_runs/{run_id}/score/preview_first_vocal.png)、[全曲SVG](../test_outputs/score_runs/{run_id}/score/jianpu.svg)。
- [可编辑MusicXML](../test_outputs/score_runs/{run_id}/score/vocal_draft.musicxml)、[自动记谱MIDI](../test_outputs/score_runs/{run_id}/score/vocal_draft.mid)、[独立项目JSON](../test_outputs/score_runs/{run_id}/score/project.json)。
- [本地片段试听复核](../test_outputs/score_runs/{run_id}/score/review.html)：50个优先音符候选、69个逐字警告；点击后播放同源本地人声，GUI播放未实测，链接目标/SHA已核对。

## 已完成和关键决策

原模型334个非休止音符派生为333个，仅合并一个有重叠上下文支持的跨段同音续音；另修复60/120秒异音重叠。原始音符、连续f0、上下文数组、源音频不覆盖。43个低音高支持、15个半音差异候选与宽音高运动保留；各类可重叠，不能相加当错误数。

自动Whisper turbo/medium均实跑。medium首尾幻觉较少但仍有错字，最终没有把自动稿当正确歌词。用户25行原文（包括“总有一天”）保存为UTF-8，空格/标点/重复段落不被网页或记忆替换；实际对齐仅过滤记谱不发音字符，原文保留。

整曲TIFA首句候选落在17秒前奏，169/237字有可用候选、167挂谱；包装音素owner与0.01秒帧尺度核查无误。一次分句对照将25行组成22个真实模型预测窗口：ASR仅定位音频窗，漏识别4行主歌使用116.514–137.305秒真实旋律多句窗，未按字或行均分时间。结果237字均有候选并挂谱，首句24.96–29.08秒恢复至真实旋律附近；仍未经人工听感确认。原全曲坏稿/两种ASR/原phone/TextGrid/诊断独立保留。

新版82个完整4/4小节，共157440ticks（480ticks/四分拍），328四分拍。约92.285 BPM、Eb大调为候选，4/4仅弱证据显式先验。简谱基准注明1=Eb3（MIDI51）；音符/歌词跨小节延音、附点、减时线、矢量升降号及最小字间距已视觉核查。记谱起点比源曲早约1.0797秒，MIDI末尾含整小节补齐；同步需读取project中的score_start_seconds。

## 实测计时口径

| 步骤 | 实测 | 范围 |
|---|---:|---|
| 先前分离+音符链 | 16.939秒 | 独立完整模型入口，不含歌词/制谱/下载 |
| 用户歌词整曲TIFA基线 | 8.512秒 | 模型对齐，但首句错位 |
| 22窗真实分句TIFA | {phrase['wall_seconds']:.3f}秒 | 加载/裁剪/G2P/推理/诊断导出，权重已缓存 |
| 最终统一缓存制谱 | {run['wall_seconds']:.3f}秒 | 严格哈希核对后复用上述对齐，CPU接缝/文本/制谱/复核导出 |
| 程序化校正版回导 | 0.456秒 | 一处音高/一处歌词测试修改后的回导，不含GPU |

这些是独立运行实测，未相加冒充一次从NCM到校正乐谱的全链benchmark；首次环境/模型下载与人工校正分开。分句allocated峰243466240字节约0.227GiB，不是驱动总显存。最终量化边界绝对误差中位47.5ms、95分位78.3ms、最大91.7ms，相对模型/对齐边界而非人工真值。

## 检查与当前界限

接缝12项、制谱11项、校正版回导15项CPU回归通过；分句16项源/文本/窗口/边界/预测证据审计通过。最终独立回读563个记谱事件、82小节、237字顺序、324个tempo事件、MIDI终点均与project一致。非零tempo offset的sound=yes已验证，所有源SHA不变。原数据和完整f0保留，真实MusicXML副本改一处音高和一处歌词再回导为独立校正层，0身份歧义。测试改动不是对歌曲的真正音乐修正，不能替代主草稿。

69个字有窗口/锚点/尾音边缘警告，其中字序181“牌”和203“害”接触crop右缘，可能截尾，未强行延长。14个网格塌缩音以待审倚音保留，不认定为原唱装饰音；固定十六分网格暂不自动检测三连音。continuous f0本身不是独立人工音高标准。

实际易谱/MuseScoreGUI导入/校正/回导未测：computer-use支持入口三次（含重置）因Windows sandbox apply deny-read ACLs退出，未绕过前台控制流程。HTML试听交互也未GUI实测。内部语义核查为单声部、完整小节/整数半音子集，不是完整MusicXML XSD兼容性承诺。

## 下一步

先试听复核69个字、两处尾音和14个短音，建立一段人工音高/歌词/节奏对照；确认拍速/拍号/调性和记谱起点。在真实独立编辑器完成往返和校正版回导后，再扩展另外六首范围内歌曲，之后处理三首压力样本。吉他指弹和网页/小程序仍属后续阶段。
'''
(root/'reports/real_vocal_draft.md').write_text(text,encoding='utf-8')
readme=root/'README.md'; s=readme.read_text(encoding='utf-8-sig'); s+='''

## 当前可查看的首份用户歌词草稿

详见 [阶段汇总](reports/real_vocal_draft.md) 和 [当前产物指针](reports/current_score.json)。当前run为20261005_192901_116，82小节、237字全部挂谱；69个字音警告和14个网格塌缩短音需复核。默认已改为medium识别与真实分句TIFA，显式整曲基线可用-AlignmentBackend tifa。

已有对齐可显式哈希核对后复用（这个速度是缓存CPU导出，不是新GPU推理）：

```powershell
.\\run_score.ps1 -LyricsFile .\\test_outputs\\lyrics\\user_supplied\\yu_jian.txt -AlignedLyrics .\\test_outputs\\lyrics\\user_phrases_candidate\\characters.json
```
'''; readme.write_text(s,encoding='utf-8-sig')
print(json.dumps({'current_score':str(root/'reports/current_score.json'),'summary':str(root/'reports/real_vocal_draft.md'),'run_id':run_id},ensure_ascii=False))
