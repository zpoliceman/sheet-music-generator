# 和弦弹唱与伴奏编配

<!-- 自动拍层级与首拍盲测：新增只诊断的通用入口及明确边界，下面历史入口保持。 -->
## 原声快慢拍与首拍自动候选比较（2026-10-16）

新诊断可显式使用 `tools/diagnose_source_timing.py --project <工程绝对路径> --work <全新隔离目录> --auto-select --model-cache <原混音模型元数据绝对路径> --features-from <来源绑定声学缓存绝对路径>`；多个缓存目录可重复传入。`--work` 仍必须在本项目 `test_outputs/accompaniment_runs` 中。旧工程默认重放行为保持，不能与 `--use-source-review` 同时启用。

也可先用 `tools/select_source_meter.py prepare --binding <原声绑定JSON绝对路径> --work <全新隔离目录> --model-cache <元数据绝对路径> --features-from <缓存绝对路径>` 打包匿名原声，再用 `choose --evidence <raw_evidence.json绝对路径> --output <新预测JSON绝对路径>` 独立选择。仅复用原始节拍激活、来源绑定声学特征及原鼓／原唱的能量攻击；缺少声学缓存会停止，不启动音高或和弦重识别。

结果分别给出 `notation_level`、`bar_first_beat`、全曲分段竞争证据及未决窗口。`selected` 只表示候选选择达到当前门槛，`full_clock_music_accepted`、`downstream_timing_revision_allowed`、`normal_publication_allowed` 仍为假；不能拿它覆盖旧拍轴或发布正常谱。证据不够时给 `needs_review`，最高分提案不能被当成已选择答案。已有来源绑定的人工确认由原复核路线保留，不能为了重新盲测再次向用户询问相同材料。

本轮首次九曲遮蔽测试出现两项与认可参考冲突，已完整保留失败。追加的v2安全回归为两项自动匹配、七项未决；《我记得》能独立选慢四拍，《日落大道》仍拒判。v2成绩是揭盲后的回归，不是全新盲测准确率。详见[报告](E:/Project/Software/sheet_music_generator/reports/accompaniment/20261016_blind_meter_selection/report.md)。

<!-- 吉他编配规则与统一验收修复：新增已认可工程的窄范围修订入口，历史说明保留。 -->
## 在已认可音乐上修订吉他编配

本轮实际成果：[我不难过吉他谱与原唱试听](E:/Project/Software/sheet_music_generator/test_outputs/accompaniment_runs/20261015_guitar_readability_contract_fix/我不难过/readability_v3/guitar/score.html)、[通用修复与五曲回归报告](E:/Project/Software/sheet_music_generator/reports/accompaniment/20261015_guitar_readability_contract_fix/report.md)。三项吉他规则及实际导出通过；歌词归属等整曲未决保持，正常入口没有替换。

先读 [MUSIC_REQUIREMENTS.md](E:/Project/Software/sheet_music_generator/MUSIC_REQUIREMENTS.md)。使用 `run_accompaniment.ps1` 的 `-EditedProject`、`-ReadableGuitar` 和 `-Output`，或 Python 主入口的 `--edited-project`、`--readable-guitar`、`--output`。输出必须是 `test_outputs/accompaniment_runs` 内尚未使用的独立目录；可用 `-ReadabilityFeatureCache`／`--readability-feature-cache` 指向来源SHA绑定的特征缓存。

这条路线固定已有拍轴、小节、人声、原共享和声分析、钢琴及器乐音高弦品，只整理吉他实际换和弦、右手音值和有原音支持的共同乐句。它不运行整曲音高或和弦识别。新修订工程后续从主入口重导会自动沿用此路线；旧工程首次使用需明确指定上述参数，不会偷偷重编已认可旧谱。不能与整曲重排或重建拍轴同时请求。

生成、时间修订导出、纯反复排版及正常入口发布均核对实际吉他规则和实际文件；本条修订路线还须通过独立原低音检查。旧完成标记、过期策略或只有预检结果都不能替代当前验收。一次反复至少共用8小节，默认至多一条主D.S.；有真实差异的遍次分别保留。原曲顺序的XML、MIDI与全长试听不随页面折叠而缩短。

吉他规则通过与整曲音乐验收分开记录。歌词或原曲匹配仍未决的候选保持 `needs_review`，不更新正常谱库入口。相关实现：[修订入口](E:/Project/Software/sheet_music_generator/tools/revise_guitar_readability.py)、[共同验收](E:/Project/Software/sheet_music_generator/tools/guitar_readability_acceptance.py)、[独立原低音验收](E:/Project/Software/sheet_music_generator/tools/guitar_source_bass_acceptance.py)。

<!-- 回退后吉他规则保留核查：最新接续 -->

2026-10-14最新状态：上版程序的12品及长段反复代码均保留；此前回退入口偏旧，已另存雨天v24、遇见v10、渴v6、无限大v4的“认可音乐低把位长段阅读”版本并设为当前。雨天／渴完整展开，遇见一次12小节普通反复，无限大一次8小节D.S.；极美仍v3。四谱低品策略均v2，最高不超过12；无限大原有52个5–12品音保持。原认可人声／拍轴／普通唱段／钢琴保持；仅采用此前验证的低品成果及显示重导，未恢复失败源音乐v4，175个生产代码文件未改。

[当前谱库](E:/Project/Software/sheet_music_generator/results/accompaniment/index.html)；[本轮核验报告](E:/Project/Software/sheet_music_generator/reports/accompaniment/20261014_retained_guitar_rules_check/report.md)。我不难过v1原问题仍未解决；旧版本、原素材、此前低品候选及绑定缓存保持。下方回退时的旧入口清单属于上一阶段，当前以本段为准。

<!-- 最新接续结束 -->

<!-- 音乐回归失败排查与上版恢复：当前接续 -->

2026-10-14：用户否决上一轮通用音乐重生成，已恢复修改前程序；六份失败新版停用归档。当前继续使用雨天v23、遇见v9、渴v5、无限大v3、极美v3；我不难过回到v1，原有拍轴／歌词问题仍未解决。

[当前谱库](E:/Project/Software/sheet_music_generator/results/accompaniment/index.html)；[原因与回退报告](E:/Project/Software/sheet_music_generator/reports/accompaniment/20261014_music_regression_rollback/report.md)；[失败归档](E:/Project/Software/sheet_music_generator/history-version/20261014_general_music_rejected/index.html)。上一轮1108测试／文件检查通过不代表音乐正确，不得从被否决v4继续生成或声称已通过整曲音乐验收。两处我字听辨事实仍保存；全部原曲及旧绑定缓存保留。

<!-- 当前接续结束 -->

<!-- 我不难过通用双乐器制谱：新增最新成果与通用可靠性修复，历史版本说明保留。 -->
## 最新制谱：《我不难过》

[总入口](E:/Project/Software/sheet_music_generator/results/accompaniment/我不难过_v1_通用双乐器编配/index.html) · [吉他谱与原唱合播](E:/Project/Software/sheet_music_generator/results/accompaniment/我不难过_v1_通用双乐器编配/guitar/score.html) · [钢琴谱与原唱合播](E:/Project/Software/sheet_music_generator/results/accompaniment/我不难过_v1_通用双乐器编配/piano/score.html) · [独立简谱](E:/Project/Software/sheet_music_generator/results/accompaniment/我不难过_v1_通用双乐器编配/vocal/score.html) · [报告](E:/Project/Software/sheet_music_generator/reports/accompaniment/20261013_wo_bu_nan_guo_first_generation/report.md)。476字、171小节；吉他夹3品、最高相对7品，本曲按长段门槛完整展开。1089测试／231浏览器检查和五曲旧来源回放通过，旧成果保留。字音287“我”保留来源挂词，等待试听复核。

默认新曲的源派生v3按完整原门槛选择可验证拍轴备选；相邻字音修正不能搬空某字唯一的计量挂词音，冲突显式保存。钢琴共同和声重配接入固定器乐音保护下的新内声／新低音同音级八度搜索；吉他器乐乐句规划与复核使用同一最终和声。历史v1／v2及旧起音缓存政策保持，无解继续停止；本轮没有歌曲专用修补。

<!-- 原声覆盖与选音归属通用修复：新增默认源质量和旧工程明确升级说明，历史说明保留。 -->
## 原声覆盖、字音归属及用户认可段落

默认新编配先检查未记谱的真实人声和相邻字的音段归属，再生成和声与伴奏。原人声／伴奏独立复核拒绝弱串音；局部拨弦和真实持续音不能被全曲强攻击门限吞掉。器乐源旋律在八度规划之前筛二至八次泛音；独立高音保留，局部强低音切换依据优先于相似乐句复用。旧版本普通重导保持，明确`--rebuild-source-meter`／`-RebuildSourceMeter`会升级旧v1质量检查。

用户已认可的段落可用`--approved-section-review`／`-ApprovedSectionReview`保留。JSON需有version=1、source_project、source_project_sha256和approved_sections（start_tick／end_tick）；同源、同拍轴、同乐器及夹位才允许合并。完整持续音、原音高、力度和弦品保持，新旧来源和最终实际演奏均核验；不能借保留层任意改音或伪换来源账本。

本轮实例及验收见[极美v2修复报告](E:/Project/Software/sheet_music_generator/reports/accompaniment/20261013_source_coverage_fix/report.md)。


<!-- 极美通用双乐器制谱：新增最新交付及通用双手内声规划说明，历史交付保留。 -->
## 最新制谱：《极美》

[独立人声简谱](E:/Project/Software/sheet_music_generator/results/accompaniment/极美_v1_通用双乐器编配/vocal/score.html) · [吉他谱与原唱合播](E:/Project/Software/sheet_music_generator/results/accompaniment/极美_v1_通用双乐器编配/guitar/score.html) · [钢琴谱与原唱合播](E:/Project/Software/sheet_music_generator/results/accompaniment/极美_v1_通用双乐器编配/piano/score.html) · [验收报告](E:/Project/Software/sheet_music_generator/reports/accompaniment/20261013_ji_mei_first_generation/summary.md)。原Eb调，134小节；吉他夹3品，器乐最高6品。1028项完整测试通过，原版本保留。

钢琴原逐和弦配音无法通过换位时，通用程序联合搜索双手内声的同音级八度，保护固定低音、器乐旋律、持续按键、起止和96半音／秒限制；可完成旧输入保持原配音，无解仍停止。

<!-- 器乐合理分句与十二品硬限制：新增当前规划与旧工程升级说明，历史资料保留。 -->
## 吉他器乐：合理乐句降八度与12品硬限制

新编配按有音乐依据的乐句统一选择原八度、降一或降两八度，优先0–4品，必要时使用5–12品。同一八度无法覆盖一长段旋律时，只在已释放、有音区交接或节拍／和声依据的边界重分动机；每个新增动机至少两拍，内部音程保持，并限制交接处的异常大跳。旋律、低音、关键和声、持续音和换位联合检查；找不到12品内可演奏方案即停止，不自动放宽到20品。

已有工程普通重导保留历史音乐；明确低品升级从绑定的真实原音输入恢复，重新规划、填充和导出试听，防止重复降八度或重复加重音。 不同目录深度另存时，保留页面的本地链接重新定位；XML、MIDI、音频及原版本保持。Python入口使用 `--low-position-instrumental`；Windows入口使用 `-LowPositionInstrumental`。输出与分析缓存应使用新目录，例如：

```powershell
.\run_accompaniment.ps1 -EditedProject "E:\Project\Software\sheet_music_generator\results\accompaniment\无限大_v2_原曲拍轴与歌词拍位通用修复\project.json" -LowPositionInstrumental -Output "E:\Project\Software\sheet_music_generator\results\accompaniment\新低品候选" -AnalysisDir "E:\Project\Software\sheet_music_generator\test_outputs\accompaniment_runs\新低品任务"
```

<!-- 默认入口原曲节拍强制复核：新增当前入口说明，以下旧阶段资料保留作历史参考。 -->
## 当前默认入口：先复核原曲节拍

新曲和旧工程重导都先核对原声及拍轴来源。没有可重放的原轨校正依据时，程序自动重建拍轴、歌词拍位和两套伴奏；不需要用户记住额外纠拍开关。已校正的工程严格重放后保留已有音乐。拍轴有歧义、源文件改变或校正失败时停止，不能退回错误旧轴继续交付；纯反复排版也不能绕过。

Windows脚本支持原人声／分轨输入，以及现有伴奏工程输入。旧工程另存示例：

```powershell
.\run_accompaniment.ps1 -EditedProject "E:\Project\Software\sheet_music_generator\results\accompaniment\无限大_v2_原曲拍轴与歌词拍位通用修复\project.json" -Output "E:\Project\Software\sheet_music_generator\results\accompaniment\另存候选" -AnalysisDir "E:\Project\Software\sheet_music_generator\test_outputs\accompaniment_runs\新任务" -ExportVocal
```

`-ExportVocal`同时输出独立简谱。`-RebuildSourceMeter`用于明确要求重新估计已有校正；未经校正的输入默认已经自动处理。输出目录须另存，原版本和来源缓存保留。这里的旧工程兼容检查不代表所有新歌曲从原始录音开始的自动识别都已验证。详细接续资料以[HANDOFF.md](E:/Project/Software/sheet_music_generator/HANDOFF.md)为准，以下为历史阶段记录。

## 当前跨曲交付：《遇见》

[吉他简谱／六线谱与原唱合播](E:/Project/Software/sheet_music_generator/results/accompaniment/遇见_v1_乐句和弦复用/guitar/score.html) · [钢琴谱与原唱合播](E:/Project/Software/sheet_music_generator/results/accompaniment/遇见_v1_乐句和弦复用/piano/score.html) · [工程与全部下载](E:/Project/Software/sheet_music_generator/results/accompaniment/遇见_v1_乐句和弦复用/index.html) · [实施验收](E:/Project/Software/sheet_music_generator/reports/accompaniment/20261010_yu_jian_phrase_harmony/summary.md)。原Ab调，吉他夹1品、G指型；原歌手音高／原时间保持。82小节，21行，正文四小节一行；吉他655／钢琴646音。29句归18个家族，其中7组复用，原167段分析留审计，实际127段共同编配。

通用新增源调准备、器乐前置准备、版本3源攻击身份／弱证据校准及正拍／尾拍共同编配，721项回归；独立实际XML／MIDI／PCM／来源重建及两套浏览器已核验。原《雨天》v20仍为该曲首选，严格保留版本2重建；原《遇见》G稿、原轨和旧成果只读。

新生成默认版本3；旧工程普通重导保持音乐和旧策略，明确拍轴升级或和声升级另存。自动音乐质量及源覆盖不足仍需听审，完整范围、源证据与复现命令见上方报告。以下v17及更早概述是历史记录。

## v17历史说明

当前首选《雨天》v17：通用局部多字时序校准、倚音实际播放坐标及弱有效音区质量筛选已实现。42“怯/你/都/了/解”源音段入口最大差约23毫秒，字内主音最大约60毫秒；认可人声谱面与完整原唱保持。615项回归、原PCM/实际MIDI/合播/隔离浏览器及四个实际其它工程软件复用检查完成。42和弦候选、其它演唱/记谱分歧及稀疏段继续保留听审。

- [v17吉他谱与原歌手合播](E:/Project/Software/sheet_music_generator/results/accompaniment/雨天_v17_局部时序与弱证据校准/guitar/score.html)
- [v17钢琴谱与合播](E:/Project/Software/sheet_music_generator/results/accompaniment/雨天_v17_局部时序与弱证据校准/piano/score.html)、[人声谱/正式MIDI](E:/Project/Software/sheet_music_generator/results/accompaniment/雨天_v17_局部时序与弱证据校准/vocal/score.html)、[全部下载](E:/Project/Software/sheet_music_generator/results/accompaniment/雨天_v17_局部时序与弱证据校准/index.html)
- [v17通用实现、跨歌实测及复核范围](E:/Project/Software/sheet_music_generator/reports/accompaniment/20261010_local_performance_v17/summary.md)

新生成默认使用版本2；历史工程通过`--performance-beat-clock`明确升级另存，普通编辑保留原策略，v16版本1严格源重建继续可用。独立半小节发现未解决残差时拒绝发布，未知覆盖明确复核；原唱和旧成果保留。下文为历史阶段。

<!-- 局部时序与弱证据通用修复：保留v16历史概述，当前入口移到上方v17。
当前首选《雨天》v16：修正连续唱段的物理拍秒，保留认可人声谱面与完整原唱，同步重算共有和声、吉他/钢琴伴奏及合播。38–39指定原钢琴拍点差约20毫秒以内，“你能体谅我有雨天”8字源音段差约58毫秒以内。588项回归与实际XML/MIDI/PCM/Chrome核验通过；4小节一行及41换夹保持。第39“我的眼眶泪太满”有原唱迟入或记谱差异待试听，历史其它听审项继续保留。

- [v16吉他谱与原歌手合播](E:/Project/Software/sheet_music_generator/results/accompaniment/雨天_v16_连续唱段拍轴与原唱同步/guitar/score.html)
- [v16钢琴谱与合播](E:/Project/Software/sheet_music_generator/results/accompaniment/雨天_v16_连续唱段拍轴与原唱同步/piano/score.html)、[人声谱/正式MIDI](E:/Project/Software/sheet_music_generator/results/accompaniment/雨天_v16_连续唱段拍轴与原唱同步/vocal/score.html)、[全部下载](E:/Project/Software/sheet_music_generator/results/accompaniment/雨天_v16_连续唱段拍轴与原唱同步/index.html)
- [v16通用逻辑、实测改善及复核范围](E:/Project/Software/sheet_music_generator/reports/accompaniment/20261010_performance_clock_v16/summary.md)

新生成默认启用演奏拍秒层；历史工程使用 `--performance-beat-clock` 明确升级另存，普通编辑重导保持音乐。源时序或相位矛盾未解决时停止发布，独立分析目录保存诊断。v15及以前成果与严格历史派生策略保留。下文v15等概述属于历史阶段。
-->

[保留v16历史入口](E:/Project/Software/sheet_music_generator/results/accompaniment/雨天_v16_连续唱段拍轴与原唱同步/index.html)、[v16历史验收](E:/Project/Software/sheet_music_generator/reports/accompaniment/20261010_performance_clock_v16/summary.md)。

<!-- 规整分解节奏与延音显示：更新当前说明，旧v8概述保留。
复用已认可人声工程，结合原混音、完整伴奏、低音及可获得的乐器分轨，生成共享和声分析，再分别编配吉他和钢琴。当前《雨天》118小节v8为声部对齐与节奏图例版，保持v7全部音乐：76个正常演唱小节采用稳定的环绕/稀疏分解，保留休止、和弦性质音、跨小节延音与器乐段。v8统一记谱拍点中心，保留装饰间距并分开15处倚音/主音；原曲听审和实际演奏复核继续待验收。
-->
<!-- 结构稳定伴奏与人声合播：更新当前概述，旧v9说明保留。
复用已认可人声工程，结合原混音、完整伴奏、低音及可获得的乐器分轨，生成共享和声分析，再分别编配吉他和钢琴。当前《雨天》118小节v9优先规整分解：83个含普通演唱伴奏的小节采用成组八分或四分拍格，普通分解无附点和孤立八分；器乐段269个音符逐字段保持。右手拨弦节奏与各弦延响分开，跨小节延音可见；同时起音严格对齐，和弦图对应实际拨弦或必须保持的按指。原曲听审和实际演奏复核继续待验收。
-->
<!-- 小节划分与拍速层级纠错：更新当前概述，旧v10说明保留。
复用已认可人声工程，联合原混音、完整伴奏及可用分轨生成共享和声分析，再分别编配吉他和钢琴。当前《雨天》118小节v10按原轨证据与真实歌词乐句稳定选型，加入规整十六分/混合候选；原歌手人声与两套伴奏分别同步试听、独立调音量。第83小节起夹1→2品，实际音高保持；两套谱每行4小节，共30行、尾行2小节。人声、共享分析、钢琴音乐及269个器乐保护音保持，音乐听审和真实试弹仍待复核。
-->
<!-- 强拍相位与伴奏同步纠错：更新当前概述，旧v11说明保留。
当前《雨天》v11已修正小节划分：4/4、四分拍58.5 BPM，每小节约4.10秒，全曲59小节；吉他与钢琴均4小节一行，共15行，尾行57–59。原117 BPM是检测脉冲的倍速层级，此曲按八分脉冲解释。已同步重新记谱人声、和声、两套伴奏与节奏连线，第42小节换夹1→2品；原实际音高、拨弦节奏及人声同步保持，两个伴奏WAV和两个合播WAV与v10 SHA一致。455项回归及独立标准导出、Chrome实际播放/谱面验证通过。
-->
<!-- 乐句节奏与音值分组：更新当前概述，旧v12说明保留。
当前《雨天》v12进一步修复真正拍点及伴奏循环：四分拍仍为58.5 BPM，以原低音和用户首句16拍校准小节首拍，从原人声音段重新量化整曲；换和弦/休止后从分解型低音重启，钢琴和弦入口也落在拍点。59个正式小节加独立弱起预备，共16行，正文每行4小节；首句第5–8、末行57–59、第42小节换夹1→2品。独立人声简谱/XML/MIDI与两套伴奏及原歌手合播使用同一新时钟。483项回归、实际XML/MIDI/TAB/合播与实时Chrome验证通过；首句逐拍符合用户基准，整曲音乐质量仍需逐段听审。
-->
<!-- 局部拍轴与原唱同步纠错：保留v13概述为历史，其合播验收范围在后续审计中已澄清。
当前《雨天》v13已接入通用乐句联合节奏推断与拍号层级音值/休止/延音/横梁：不再用绝对元音先验和单向游标推后音符。实际XML中用户两句5–12小节32拍全部通过，“没”续段十六分与“有”附点八分合计一拍，“别的借口”四个十六分在同一拍，“口”跨小节延续。508项回归、两套XML/MIDI/TAB、392处同时音0px对齐及真实Chrome原歌手合播通过。原426音段音高/身份/秒时间、原录音及v1–v12保留；后续24个小节只有独立自动证据，不能代替整曲逐字听审。正文每行四小节及第42小节换夹保持。
-->
<!-- 通用段落强拍与乐句节奏修复：保留v14历史说明。
当前《雨天》v14修复局部原曲拍轴与歌词句首/边界：原唱录音保持，伴奏MIDI及合播跟随原曲局部速度；前两句32拍、参考13–14八拍和20字首全部通过，原13–14连续攻击的0.65–0.88秒偏差缩至0–46毫秒。531项回归、两套正式谱/音源及真实Chrome合播通过，420处同刻中心0px；426源音段及15倚音保持。58正式小节加弱起、每行4小节，末行57–58，第42小节换夹保持。后续3个短字边界及稀疏尾奏仍需原曲复核，不能外推整曲逐字准确率。试听使用正式页面合播/WAV/MIDI；附带渲染器原生MIDI对局部速度有兼容限制。
-->
当前《雨天》v15按通用音乐结构纠正段落强拍和句内节奏：相似旋律允许歌词、装饰和调性不同；多个乐句共同校验过门拍数；规整八分、十六分、真实改唱与3:2三连音共同竞争。第20末拍“越”、间奏后25起及高潮重点字首修正，两套和声/伴奏及合播重算；原唱、426源音段及15倚音保持。566项回归、40个已认可拍位、45个重点参考字首、实际XML/MIDI与Chrome双轨播放通过，397处同刻中心0px。58正式小节加弱起，每行4小节，第41小节换夹。另有四首中英文真实工程通过软件复用和源保持检查；过门特殊拍数、3处旧字界差异及稀疏尾奏继续留待原曲听审，不能外推全曲人工准确率。

## 首曲入口

- [当前v15吉他与原歌手合播](E:/Project/Software/sheet_music_generator/results/accompaniment/雨天_v15_段落强拍与音乐复用/guitar/score.html)
- [当前v15钢琴与合播](E:/Project/Software/sheet_music_generator/results/accompaniment/雨天_v15_段落强拍与音乐复用/piano/score.html)、[独立人声](E:/Project/Software/sheet_music_generator/results/accompaniment/雨天_v15_段落强拍与音乐复用/vocal/score.html)、[两套下载入口](E:/Project/Software/sheet_music_generator/results/accompaniment/雨天_v15_段落强拍与音乐复用/index.html)
- [v15通用修复、实际文件核验及音乐复核范围](E:/Project/Software/sheet_music_generator/reports/accompaniment/20261010_structure_rhythm_v15/summary.md)
- [保留v14入口](E:/Project/Software/sheet_music_generator/results/accompaniment/雨天_v14_局部拍轴与原唱同步/index.html)、[历史报告](E:/Project/Software/sheet_music_generator/reports/accompaniment/20261009_local_clock_v14/summary.md)

<!-- 规整分解节奏与延音显示：更新默认入口，旧v8链接保留。
- [两套伴奏谱](results/accompaniment/雨天_v8_声部对齐与节奏图例/index.html)
- [吉他人声简谱、歌词及具体六线谱](results/accompaniment/雨天_v8_声部对齐与节奏图例/guitar/score.html)：标准调弦、固定夹一品；常规C/Am采用完整开放图；器乐区匹配常用手型时附图，否则省略和弦名/图、使用数字TAB，空弦为0。有图处继续沿用左手写x、临时改变才写数字；简谱主音/休止/长音横线与TAB同刻中心对齐，下方节奏八分一线、十六分两线。
- [节奏符号与拍数详细图例](results/accompaniment/雨天_v8_声部对齐与节奏图例/guitar/rhythm_guide.html)：单竖线、左右短钩、相连横线、附点、空心长音及持续线。
- [声部对齐交付与独立核验](reports/accompaniment/20261008_alignment_v8/summary.md)
- [常用分解/合拨/扫弦的读谱参考](results/accompaniment/雨天_v8_声部对齐与节奏图例/guitar/right_hand.html)及[调研报告](reports/accompaniment/20261008_right_hand_patterns/research.md)
- [钢琴人声简谱参考与双手大谱表](results/accompaniment/雨天_v8_声部对齐与节奏图例/piano/score.html)：按实际Db转D发声，踏板与按键持续分开；完整编配及正式XML/MIDI/WAV与v7相同。
- [原曲/分轨及逐小节复核](results/accompaniment/雨天_v8_声部对齐与节奏图例/review.html)
-->
<!-- 结构稳定伴奏与人声合播：更新默认入口，旧v9链接保留。
- [两套伴奏谱](results/accompaniment/雨天_v9_规整分解与延音/index.html)
- [吉他人声简谱、歌词及具体六线谱](results/accompaniment/雨天_v9_规整分解与延音/guitar/score.html)：常用指型优先、器乐数字独奏、有图x与临时数字规则保持；普通伴奏八分成组，低音延响看沿弦细线，括号品数表示上一小节的音继续响、无需重拨。
- [节奏符号与拍数详细图例](results/accompaniment/雨天_v9_规整分解与延音/guitar/rhythm_guide.html)
- [规整节奏、延音及13–14小节修正报告](reports/accompaniment/20261008_regular_v9/summary.md)
- [常用分解/合拨/扫弦的读谱参考](results/accompaniment/雨天_v9_规整分解与延音/guitar/right_hand.html)及[调研报告](reports/accompaniment/20261008_right_hand_patterns/research.md)
- [钢琴人声简谱参考与双手大谱表](results/accompaniment/雨天_v9_规整分解与延音/piano/score.html)：完整编配及正式XML/MIDI/WAV与v8相同。
- [原曲/分轨及逐小节复核](results/accompaniment/雨天_v9_规整分解与延音/review.html)
-->
<!-- 小节划分与拍速层级纠错：更新首曲入口，旧v10链接保留。
- [两套伴奏谱v10](results/accompaniment/雨天_v10_稳定编配与人声合播/index.html)
- [吉他简谱、歌词、指型与六线谱](results/accompaniment/雨天_v10_稳定编配与人声合播/guitar/score.html)：4小节一行，夹位从第83小节改为2品；稳定主型，90–94小节采用八分/十六分混合。
- [钢琴人声简谱参考与双手大谱表](results/accompaniment/雨天_v10_稳定编配与人声合播/piano/score.html)：4小节一行，原编配及XML/MIDI/伴奏WAV保持。
- [吉他人声合播WAV](results/accompaniment/雨天_v10_稳定编配与人声合播/guitar/singing_preview.wav)、[钢琴人声合播WAV](results/accompaniment/雨天_v10_稳定编配与人声合播/piano/singing_preview.wav)：页面有播放/暂停、定位和独立音量，调到0可静音；每行可从对应小节开始合播。
- [本轮验证与编配说明](reports/accompaniment/20261009_stable_v10/summary.md)、[节奏图例](results/accompaniment/雨天_v10_稳定编配与人声合播/guitar/rhythm_guide.html)、[24种右手型参考](results/accompaniment/雨天_v10_稳定编配与人声合播/guitar/right_hand.html)
- [原曲/分轨及逐小节复核](results/accompaniment/雨天_v10_稳定编配与人声合播/review.html)
-->
- [保留v13吉他、钢琴与独立人声入口](E:/Project/Software/sheet_music_generator/results/accompaniment/雨天_v13_乐句节奏与音值分组/index.html)
- [v13吉他简谱与六线谱](E:/Project/Software/sheet_music_generator/results/accompaniment/雨天_v13_乐句节奏与音值分组/guitar/score.html)
- [v13人声简谱/XML/MIDI](E:/Project/Software/sheet_music_generator/results/accompaniment/雨天_v13_乐句节奏与音值分组/vocal/score.html)
- [本次修复与独立验收](E:/Project/Software/sheet_music_generator/reports/accompaniment/20261009_phrase_rhythm_v13/summary.md)
- [两套伴奏谱及独立人声v12](results/accompaniment/雨天_v12_强拍与伴奏同步/index.html)
- [吉他简谱、歌词、指型与六线谱](results/accompaniment/雨天_v12_强拍与伴奏同步/guitar/score.html)：首句5–8小节，分解低音与拍点同步，59个正式小节加弱起预备。
- [独立人声节拍校正版](results/accompaniment/雨天_v12_强拍与伴奏同步/vocal/score.html)：可下载人声MusicXML及MIDI。
- [钢琴简谱参考与双手大谱表](results/accompaniment/雨天_v12_强拍与伴奏同步/piano/score.html)：和弦低音入口采用共同正拍。
- [吉他原歌手合播WAV](results/accompaniment/雨天_v12_强拍与伴奏同步/guitar/singing_preview.wav)、[钢琴原歌手合播WAV](results/accompaniment/雨天_v12_强拍与伴奏同步/piano/singing_preview.wav)：新谱时钟同步，页面支持独立音量及小节定位。
- [本轮纠错原因与验收报告](reports/accompaniment/20261009_beat_phase_v12/summary.md)、[原曲/分轨复核](results/accompaniment/雨天_v12_强拍与伴奏同步/review.html)、[节奏图例](results/accompaniment/雨天_v12_强拍与伴奏同步/guitar/rhythm_guide.html)
- [保留小节长度纠正版v11](results/accompaniment/雨天_v11_小节划分纠正/index.html)、[其报告](reports/accompaniment/20261009_bar_grid_v11/summary.md)及[和声/歌词历史审计](reports/accompaniment/20261009_bar_grid_v11/harmony_bar_audit.json)
- [保留稳定编配/人声合播版v10](results/accompaniment/雨天_v10_稳定编配与人声合播/index.html)及[其历史报告](reports/accompaniment/20261009_stable_v10/summary.md)
- [保留规整分解与延音版v9](results/accompaniment/雨天_v9_规整分解与延音/index.html)及[其验证报告](reports/accompaniment/20261008_regular_v9/summary.md)
- [保留声部对齐版v8](results/accompaniment/雨天_v8_声部对齐与节奏图例/index.html)及[原交付报告](reports/accompaniment/20261008_alignment_v8/summary.md)
- [保留常用右手伴奏型版v7](results/accompaniment/雨天_v7_常用右手伴奏型/index.html)
- [右手伴奏型交付与独立核验](reports/accompaniment/20261008_right_hand_patterns/summary.md)
- [保留常用指型与独奏版v6](results/accompaniment/雨天_v6_常用指型与独奏/index.html)
- [常用指型、独奏与持续时序验证](reports/accompaniment/20261008_rain_common_grips_v6/summary.md)及[检索来源/筛选方法](reports/accompaniment/20261008_rain_common_grips_v6/research.md)
- [保留空弦x版v5](results/accompaniment/雨天_v5_空弦X/index.html)及[空弦规则验证](reports/accompaniment/20261007_rain_open_string_x_v5/summary.md)
- [保留同拍节奏线版v4](results/accompaniment/雨天_v4_同拍节奏线/index.html)及[节奏验证记录](reports/accompaniment/20261007_rain_rhythm_beams_v4/summary.md)
- [保留指型/x版v3](results/accompaniment/雨天_v3_指型X六线谱/index.html)及[指型验证记录](reports/accompaniment/20261007_rain_chord_diagrams_v3/summary.md)
- [保留分解优先版v2](results/accompaniment/雨天_v2_分解优先/index.html)及[分解编配前后对比](reports/accompaniment/20261007_rain_arpeggio_v2/summary.md)
- [保留第一版](results/accompaniment/雨天_v1/index.html)及[和声参考谱差异](reports/accompaniment/20261007_rain_v1/summary.md)

每套有独立MIDI、简化音色WAV、MusicXML/MXL。共享分析在shared_analysis.json，可编辑工程在project.json。人声简谱/歌词参考行使用当前校正版；两套伴奏XML/MXL承载伴奏声部，吉他只有六线谱，独立人声XML/MIDI在vocal目录。试听音色用于核对音高、时值及编配，不能代表原录音乐器质感。

吉他HTML/SVG中的x表示沿用当前图的左手指型拨响该弦，包含空弦：黑点与横按共同决定基础按位，无按点且无横按覆盖时该弦的x即空弦。只有相对图示指型需临时松开/增加按指才写具体品数；有图时0表示需松开原按指弹空弦，无图数字段的0直接表示空弦。同音异弦仍按该根弦的实际按位判断。图中○为空弦、×为通常不拨，实际拨弦以TAB为准；×不代表一定被左手按住，横按跨过的弦则算已按。品数以变调夹为0品。正文四小节一行，密集行保留字号并可横向滚动，纯器乐行只含TAB及需要的指型，演唱行保留人声参考；MusicXML/MXL使用规范数字弦品，MIDI/WAV按实际编配发声。

常用候选库位于tools/data/guitar_common_grips.json，共303个经音高/转位/覆盖校验的按法：39基础开放、86开放扩展、178横按备选，逐项保留来源和优先级。资料包括Fender/JustinGuitar教学谱与指型、MIT许可的chords-db；许可证随库保存。普通弹唱先试完整常用手型；器乐区按实际同弦同品匹配、持续时长与临时按指增减判断，匹配不足或持握时序不满足时写数字，后台和声不删除。

右手库位于tools/data/guitar_right_hand_patterns.json，24个类型/规范示例（原19种+新增5种规整十六分/混合示例）覆盖上行、环绕、交替低音、Travis、合拨、稀疏分解和扫弦；逐项区分教学正文可核对节奏与本项目示例，不声称歌曲频率排名。新编配按短乐句的原攻击密度/音序选常用分解型，休止、换和弦低音及性质音优先；扫弦候选须有原曲支持，合拨不视为扫弦。v7选择56个环绕型小节、20个稀疏型小节，边界混合小节、器乐继承延音和特征填句保护；第99至100小节根音延音保持原结束时间。全曲851吉他音，540模板音，377项回归及独立XML/MIDI/TAB/完整图式/模板语义通过；1726旧文件SHA保持，人声/共享分析/钢琴和311个保留区实际音符不变。

本曲v6为673个x、206个其它品数、65个0，实际空弦415个保持；139个指型事件、189张可见图，器乐段有39个纯数字区。5处C及4处常规Am采用完整开放指型，第3小节Gadd9改为无图数字独奏，保留0/10/12。为满足真实持续音的换把时序，10个音同音换弦，第102小节一个旋律音及第103小节一个低音各提前约0.128秒释音，联合换弦使第103小节旋律延音保持；全部音高、起音、力度、音符来源和攻击事件保持。人声、共享分析及钢琴保持。逐音变化保存在工程exact_pitch_refingering与本轮v5_comparison.json中。361项回归及独立读回通过，1579个既有文件SHA保持，v1–v5保留。

<!-- 规整分解节奏与延音显示：更新拨弦与持续关系，旧v4说明保留。
TAB下方的粗横线按拍分组，4/4每拍为四分音符；八分一条、十六分两条，混合时值只对相应短音加第二条。孤立级别用短横钩，附点在符干旁，真实休止间隙和拍/小节边界断开。同刻多弦共用符干，以最短新起音显示攻击节奏，较长持续仍由弦上的细横线表示；复合持续的起始记谱值与延音分开。v4与v3的音符/攻击、指型/音符可见位置以及两套XML/MIDI/WAV一致。
-->
TAB下方的粗横线按拍分组，4/4每拍为四分音符；八分一条、十六分两条，混合时值只对相应短音加第二条，同刻多弦共用符干。v9普通模板按右手拨弦拍格绘制，低音响一拍仍可与半拍后的高音组成两个八分；各弦持续看细线。独奏/特色节奏保留原时值和必要附点、短钩。跨小节用括号品数和续段细线提示旧音继续响，括号不表示新拨弦，也不增加符干。

v8没有重编音乐。四分符干1拍、八分短钩半拍、十六分双钩四分之一拍；短钩左右朝向等义，↓/↑才表示扫弦方向。附点增加本身时值的一半，四分加点1.5拍、八分加点0.75拍。人声主音、休止和长音横线与TAB使用共同记谱拍点；小号倚音按惯例在主音左前方，不额外占拍。389项回归与整曲实际SVG回读通过，566个人声字形（含15倚音）、230处同时声部中心检查偏差0，274处歌词中心及真实小节线通过；两套实际音符/攻击、认可人声/共享分析、XML/MIDI/WAV与v7一致，1874旧文件SHA保持。

v9修正普通伴奏的实际起音相位，含79个完整演唱小节及4个混合边界的小节片段，61个环绕/22个稀疏型范围。519个普通拨弦组为444个八分、75个四分，0普通附点、0孤立八分；全曲805吉他音，其中536个本轮模板音、269个器乐段保留音。剩余18处附点全部在前奏/间奏/尾奏，未新增普通例外。409项回归、正式及独立标准谱/试听/持握/可见几何核验通过；306处同刻声部中心偏差0px，29处跨小节延音可见。2024旧文件SHA保持，人声/共享分析/钢琴不变。截图13–14小节问题来自生成逻辑，无需更换浏览器：13首拍为三弦空弦延音，原Gsus4重复图已移除，14分解从第一拍开始。当前默认规整升级适用于4/4，其它拍号保留既有流程。

## v12强拍、人声量化与伴奏同步

v11解决了小节长度，却仍沿用旧首拍相位、人声起音先验；部分声母比实际元音起唱提前，旧量化会吸附到错误拍位。v12将拍速层级、四分拍秒相位、小节首拍、字界/延音及右手循环分别校验。用户首句第一拍为17.061568秒，距原低音攻击17.043447秒约18毫秒，小于一个声学分析帧。从原音段秒时间重新量化，不改原录音速度或音高。

换和弦时，旧模板曾将当前槽位换成低音但继续原槽位计数。新版明确保存每个循环起点，换和弦及休止后从低音重新开始；普通型保留规整十六分、混合及稀疏候选，按原轨证据选择。真实延音和特殊器乐/休止仍独立处理。源SHA、拍号与四分速度匹配才读取复核；未知歌不套本曲首句，显式beat_origin优先。原人声426音段的音高/身份与15倚音保留，源TXT与音素只读，只有派生歌词按用户和参考谱将“剩”纠正为“想”。

首句16拍已经从实际导出XML独立读回，426个MIDI播放音段也逐起止精确核对；两声部348处同刻中心偏差0px。新拍轴已用于整曲，但其余字界、细节旋律及和声仍需听审。钢琴渲染器试听PPQ120的舍入最多约4.27毫秒，正式MIDI为精确PPQ480，验收区分两种分辨率。

从v11升级另存的复现命令：

~~~powershell
& '.\.venv-gpu\Scripts\python.exe' -X utf8 'tools/generate_accompaniment.py' `
  --edited-project 'results/accompaniment/雨天_v11_小节划分纠正/project.json' `
  --analysis-dir 'test_outputs/accompaniment_runs/20261007_rain_v1' `
  --correct-beat-phase `
  --output 'results/accompaniment/雨天_v12_reproduce'
~~~

## v11小节划分与拍层级（历史）

beat_track输出的是检测脉冲，规律性高不能证明它等于四分拍。程序新增半速/原速/倍速候选，按源音频SHA读取经过人工/参考谱核对的层级；未知音源仍保留歧义，不因某个BPM或一小节一个和弦假设直接减半。显式四分拍tempo覆盖优先于复核记录。自动选择速度不再写成用户的tempo覆盖；谱头和复核页显示实际记谱速度。

认可的人声源工程保持原文件；新版accepted_vocal_project附grid_correction，是可从原工程确定性重建的时间派生，音高、歌词、倚音及发声秒不变。严格重导仍拒绝任意改写人声。和声段183个保留原音高/名称/秒边界，逐小节织体用完整秒域缓存重新归组；删除14次起音截断，完整4/4十六分有16次。旧普通拨弦按新的拍单位显示，通常八分变十六分、四分变八分，少数旧混合细节变32分；本次不重编已有音乐。

原8小节换夹门槛按正确小节计数，58.5 BPM时约32.82秒；雨天D段为第42–59小节、约73.85秒，仍满足。新行较密时保留字号并横向滚动。小节中途调号变化的渲染仍不支持，重记谱遇到此情况会明确拒绝，避免把新调提前显示到小节首；本曲的转调位于第42小节首。

默认重导同源旧工程会自动使用已确认的2倍小节时长；其它曲可用--bar-length-factor 2明确选择，.5用于相反方向，1用于保留原划分。已经纠正的工程普通重导幂等，禁止再次叠加缩放。复现另存如下：

~~~powershell
& '.\.venv-gpu\Scripts\python.exe' -X utf8 'tools/generate_accompaniment.py' `
  --edited-project 'results/accompaniment/雨天_v10_稳定编配与人声合播/project.json' `
  --analysis-dir 'test_outputs/accompaniment_runs/20261007_rain_v1' `
  --output 'results/accompaniment/雨天_v11_reproduce'
~~~

## v10选型与试听（历史拍单位，v11按新拍层级解释）

从完整多轨起音缓存读取细分、重音、原音序和能量证据，不使用旧谱攻击密度作为原曲投票；同源分轨按相关组分配权重。按歌词句与主音音程轮廓识别乐句/重复，不机械每4小节换型。现有38个乐句、5个可复用重复组；明显原节奏变化保留理由，连续演唱的主型共8次变化。2处短sus/add沿稳定基本小和弦显示，必要装饰仍在实际音符和数字TAB中，七音/斜线低音与真正进行保留。

本曲83个普通范围使用42个上行八分、20个环绕八分、16个四分、5个混合型；558次攻击包含462八分、56四分和40十六分。没有强行加入整小节十六分，候选仍可对真实十六分素材选择。声音持续和右手拍格分开；器乐段所需附点/短钩保留。两套页面共用真实人声，但伴奏分开；OGG用于离线控制，WAV用于下载和精确样本读回，标准MIDI仍只保存音符事件。

持续新调至少8小节且旋律/和声共同支持时换夹，短离调保留实音而不换夹；用户指定滑动夹，当前不设操作空档门槛。夹位、相对品数、常用图式、x/数字、持续音、XML与实际音高一起重算。《雨天》83–118小节为D段，夹2保持到结尾，没有回调标记。普通编辑重导保持音乐；新工程默认接入v10流程，旧工程使用下列显式升级参数。

434项回归及独立导出验证通过；2174份旧文件SHA、认可人声/共同分析/完整钢琴工程、钢琴XML/MIDI/WAV保持；269个器乐保护音的音乐字段保持，物理指位允许为新夹位重新规划。341处同时音中心偏差0px，15处倚音、20处跨小节续音保留。Chrome实际双轨解码、静音、播放/暂停、定位与原试听互斥通过。自动来源与可演奏模型不能代替整曲听审、真人试弹；外部写谱软件GUI往返仍待验证。

## 新曲与缓存复现

项目PowerShell中使用通用入口，参数选择歌曲，代码无歌曲专用和弦表：

~~~powershell
.\run_accompaniment.ps1 `
  -VocalProject 'results/雨天/project.json' `
  -DemucsReport 'reports/runs/20261007_001525_687/demucs.json' `
  -Output 'results/accompaniment/雨天_new' `
  -AnalysisDir 'test_outputs/accompaniment_runs/雨天_new' `
  -Capo 1 -SixSources `
  -Reference @('test_music/孙燕姿 - 雨天/孙燕姿 - 雨天 吉他谱1.jpg',
               'test_music/孙燕姿 - 雨天/孙燕姿 - 雨天 吉他谱2.jpg')
~~~

省略SixSources时使用已有四源分离和完整伴奏；省略Capo时搜索固定夹位。六源分离为实验性辅助，原混音、完整伴奏及other始终保留参与分析。参考图片只绑定到复核页，不输入和弦识别器。

两套编配默认分解优先。柱式例外要求反复出现的多和弦音起音及有效多轨交叉支持，不能仅因攻击稀疏就弹整组和弦。原音轨分类保留在复核层，实际编配另列；从未确认齐奏改出的八分细分明确标记为演奏选择。原曲清楚支持的柱式可以保留，最终音乐匹配仍需听审。

复用首曲已有和声分析，补核柱式起音支持后按当前分解优先规则重编配与导出：

~~~powershell
& '.\.venv-gpu\Scripts\python.exe' -X utf8 'tools/generate_accompaniment.py' `
  --shared-analysis 'test_outputs/accompaniment_runs/20261007_rain_v1/shared_analysis.json' `
  --analysis-dir 'test_outputs/accompaniment_runs/20261007_rain_v1' `
  --capo 1 --output 'results/accompaniment/雨天_reproduce'
~~~

特征缓存按源SHA和算法版本绑定；重新提取声学特征使用新曲入口。输出仅允许results/accompaniment或test_outputs/accompaniment_runs下独立子目录。

## 编辑重导

<!-- 通用段落强拍与乐句节奏修复：新增通用结构升级复现命令；源、缓存、旧结果保留。 -->
将既有局部拍轴工程另存为段落强拍与音乐复用版：

~~~powershell
& '.\.venv-gpu\Scripts\python.exe' -B -X utf8 'tools/generate_accompaniment.py' `
  --edited-project 'results/accompaniment/雨天_v14_局部拍轴与原唱同步/project.json' `
  --structural-rhythm `
  --analysis-dir 'test_outputs/accompaniment_runs/structure_reproduce' `
  --output 'results/accompaniment/雨天_structure_reproduce'
~~~

新编配/`--rearrange`默认启用该策略；普通历史编辑重导保持原音乐和策略。`--structural-rhythm`明确升级旧工程；已升级工程再次重导幂等。源人声身份、音高、字音归属、原秒时间与音轨SHA由严格派生校验保护，不允许任意改写人声通过。

<!-- 规整分解节奏与延音显示：新增旧工程明确升级复现，输出到新目录以保护旧版。 -->
<!-- 结构稳定伴奏与人声合播：新增明确升级与复现命令，旧版另存不覆盖。 -->
将v9升级为结构稳定、分段夹位及原人声合播：

~~~powershell
& '.\.venv-gpu\Scripts\python.exe' -X utf8 'tools/generate_accompaniment.py' `
  --edited-project 'results/accompaniment/雨天_v9_规整分解与延音/project.json' `
  --structured-accompaniment `
  --analysis-dir 'test_outputs/accompaniment_runs/雨天_v10_reproduce' `
  --output 'results/accompaniment/雨天_v10_reproduce'
~~~

将既有v8另存为规整分解与延音显示版：

~~~powershell
& '.\.venv-gpu\Scripts\python.exe' -X utf8 'tools/generate_accompaniment.py' `
  --edited-project 'results/accompaniment/雨天_v8_声部对齐与节奏图例/project.json' `
  --regular-right-hand --output 'results/accompaniment/雨天_regular_reproduce'
~~~

将既有v6普通演唱伴奏另存为常用右手型：

~~~powershell
& '.\.venv-gpu\Scripts\python.exe' -X utf8 'tools/generate_accompaniment.py' `
  --edited-project 'results/accompaniment/雨天_v6_常用指型与独奏/project.json' `
  --common-right-hand --output 'results/accompaniment/雨天_right_hand_reproduce'
~~~

<!-- 规整分解节奏与延音显示：更新显式升级参数，旧说明保留。
普通--edited-project重导不自动替换已编辑音序；显式--common-right-hand或新编配/--rearrange才接入选型。谱内的新增起音标为编配选择，原观察与源音编号保留，不把模板当成识别出的原曲逐音真值。
-->
普通--edited-project重导不自动替换已编辑音序；显式--structured-accompaniment或新编配/--rearrange接入结构稳定与合播流程；--regular-right-hand、--common-right-hand保留旧策略兼容。已升级工程再次重导保持手工音序。谱内新增起音标为编配选择，原观察与源音编号保留；自动分轨相位和响音持续估计不足以证明原曲完全匹配，不据此批准普通附点/孤立八分例外。

先复制project.json到独立位置，再修改arrangements中音符的pitch_midi、start_tick、end_tick等。吉他同时保持string、fret、当时capo_segments夹位与实际音高一致，手位和持续音仍需通过验证；钢琴手位自动按修改后的音符重新规划。吉他fingering_diagrams、notation_regions、grip_hand_positions、grip_fingerings、tab_display和rhythm_display为派生数据，重导按实际音符重新生成，不需手工同步旧图或横线。持续时序冲突优先同音换弦，旧策略局部仍无解时可最小释音，结构版保护音不允许静默释音；修正记录在exact_pitch_refingering及adjustments，源输入不覆盖。

~~~powershell
& '.\.venv-gpu\Scripts\python.exe' -X utf8 'tools/generate_accompaniment.py' `
  --edited-project 'test_outputs/accompaniment_runs/my_edit/project.json' `
  --output 'results/accompaniment/雨天_edited'
~~~

修改shared_analysis.harmony后加--rearrange以重新生成两套伴奏；该模式替换工程内已有伴奏音符编辑。无此参数不根据新和弦标签重新配音，吉他仍会执行上述持续时序修正与指型选择。

认可人声快照与源音轨指纹不可静默替换；编辑输入不得位于输出目录，必须另存。已实测JSON编辑、重导与XML/MIDI读回；外部写谱软件GUI编辑往返尚未验证。

## 首版约束与边界

检查持续按音、同弦/同键冲突、同时覆盖、攻击/结束边界换位路径、调弦/变调夹实际音高和谱面边界；完整图式连同持续音一起核查，不能在旧按音尚未结束时提前越出可覆盖手位。吉他最多4左手指、跨度5品、规划换把≤24品/秒；钢琴每手同时跨度≤12半音、最多5键、规划手位速度≤96半音/秒。开放弦、横按、踏板和顺序换位分别处理。这些是可计算约束；指法建议和换位模型尚未经真人演奏认证。

当前183个和弦/低音段、144个器乐旋律候选均为自动估计。柱式、分解、扫弦及尾奏衰减需听审；无法可靠识别的扫弦方向明确记为编配选择。多声部超出单人容量时，按特色器乐旋律、主要低音/节奏、决定和弦性质的音排序，省略重复与次要内声，取舍保存在工程中。

复核原曲的链接依赖本工作区源文件；谱面、MIDI、WAV和工程为本地产物。既有认可人声、旧结果与冻结快照保持不变。
