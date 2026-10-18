# 自动乐谱生成器

当前代码版本：2026-10-18第五版，支持4/4右手型选择、多区间配置、实时完整主谱／试听及候选悬停六线谱预览。已有55种分解、合拨和扫弦；未选择时保持原演奏，保存时另建曲谱版本。

在已经恢复环境、歌曲与现有工程的本机，双击项目根目录的`启动右手选择.cmd`，即可打开右手编辑页面。候选示意使用C和弦原节奏，确认后实际歌曲由原和弦和所选设置编配。

2026-10-18目录更正：实际开发目录为`E:\Project\Software\sheet_music_generator`，第五版备份为`history-version/version5-20261018-optional-chords`。旧拼写的开发目录现在只是兼容联接，原工程仍通过它读取来源，请保留；日常在新目录工作。`data/workspace_identity.json`用于保持原配置编号，不是实际文件访问路径。完整检查见[目录改名报告](reports/accompaniment/20261018_workspace_rename/report.md)。

上传和后续更新请阅读[GitHub上传与持续更新教程](history-version/GitHub上传与持续更新教程.md)。代码仓库排除了歌曲、模型环境、成品、缓存及整份本地历史快照；首次克隆不会自带原电脑的九首曲谱和运行环境。整体任务及当前进展见[todo.md](todo.md)、[HANDOFF.md](HANDOFF.md)，音乐保护要求见[MUSIC_REQUIREMENTS.md](MUSIC_REQUIREMENTS.md)。

以下保留历史交付记录，其中的本机绝对路径链接需要对应素材与成果目录；当前开发状态以HANDOFF.md顶部为准。

## 《我不难过》钢琴同步完成（2026-10-15）

当前[简谱与两套伴奏总览](E:/Project/Software/sheet_music_generator/results/accompaniment/我不难过_v3_钢琴同步与局部简化/index.html)：[钢琴谱及原唱试听](E:/Project/Software/sheet_music_generator/results/accompaniment/我不难过_v3_钢琴同步与局部简化/piano/score.html)。沿用认可拍轴／小节／歌词；钢琴仅省略两处有原声证据的生成低音碰撞并整理已有和弦标记。吉他、简谱及原唱目录与v2逐字节相同。1226测试、真实文件／浏览器及音乐范围验收通过，正常入口已更新，旧版本保留。[修改与验收报告](E:/Project/Software/sheet_music_generator/reports/accompaniment/20261015_piano_sync_approved_lyrics/report.md)。下方为历史交付。

## 《我不难过》两处词音局部修订（2026-10-15）

当前[简谱及吉他版](E:/Project/Software/sheet_music_generator/results/accompaniment/我不难过_v2_局部词音与认可吉他编配/index.html)已更新正常入口：[吉他谱与原唱试听](E:/Project/Software/sheet_music_generator/results/accompaniment/我不难过_v2_局部词音与认可吉他编配/guitar/score.html)。第二遍“我”标为承接满尾音的短下滑；末句“我”记轻声入口，后续固定音归向。沿用用户已认可拍轴、小节、906音吉他与8小节复用，未整曲重算。1216测试、实际文件／浏览器及五曲保护通过；旧版本保留，本次不新交付钢琴或认证前轮未采用的新拍轴。[修改和验收报告](E:/Project/Software/sheet_music_generator/reports/accompaniment/20261015_two_wo_local_ownership/report.md)。以下为历史交付记录，当前入口以[曲谱库](E:/Project/Software/sheet_music_generator/results/accompaniment/index.html)及HANDOFF顶部为准。

## 《无限大》简谱与双乐器编配（2026-10-12，已交付）

[总入口](E:/Project/Software/sheet_music_generator/results/accompaniment/无限大_v1_通用双乐器编配/index.html) · [人声简谱](E:/Project/Software/sheet_music_generator/results/accompaniment/无限大_v1_通用双乐器编配/vocal/score.html) · [吉他谱及原唱合播](E:/Project/Software/sheet_music_generator/results/accompaniment/无限大_v1_通用双乐器编配/guitar/score.html) · [钢琴谱及原唱合播](E:/Project/Software/sheet_music_generator/results/accompaniment/无限大_v1_通用双乐器编配/piano/score.html) · [生成与验收](E:/Project/Software/sheet_music_generator/reports/accompaniment/20261012_wu_xian_da_generation/summary.md)。当前程序生成全曲128小节，认可人声479音／374歌词单位与拍轴保持；吉他1102／钢琴1046音，各自提供原歌手合播；78器乐黑点／67低弦填充。实际XML／SMF／PCM、来源重放与Chrome213项通过，生产代码不改。默认自动局部拍轴候选未通过后采用认可人声保护入口，具体过程和待改进的通用入口问题在报告中留档。

## 旧工程功能自动升级与三曲器乐表现统一（2026-10-12，已交付）

[雨天吉他谱与原唱合播](E:/Project/Software/sheet_music_generator/results/accompaniment/雨天_v23_通用工程升级与器乐重音/guitar/score.html) · [遇见吉他谱与原唱合播](E:/Project/Software/sheet_music_generator/results/accompaniment/遇见_v9_通用工程升级与器乐重音/guitar/score.html) · [渴吉他谱与原唱合播](E:/Project/Software/sheet_music_generator/results/accompaniment/渴_v5_通用工程升级与器乐重音/guitar/score.html) · [实施与验收](E:/Project/Software/sheet_music_generator/reports/accompaniment/20261012_project_feature_upgrade/summary.md)。通用能力实际检查／来源绑定最小补齐已接入所有重导入口；雨天73／遇见93／渴40器乐主旋律黑点、主音增强和填充轻奏统一；完整工程幂等，认可旋律／节奏／和弦／人声／钢琴／反复路线保持。963项测试、三曲实际文件和Chrome531项／打印通过。

## 重复乐句折叠与多遍挂词（2026-10-12，已交付）

[雨天吉他反复谱](E:/Project/Software/sheet_music_generator/results/accompaniment/雨天_v22_反复折叠与多遍挂词/guitar/score.html) · [遇见吉他反复谱](E:/Project/Software/sheet_music_generator/results/accompaniment/遇见_v8_反复折叠与多遍挂词/guitar/score.html) · [渴吉他反复谱](E:/Project/Software/sheet_music_generator/results/accompaniment/渴_v4_反复折叠与多遍挂词/guitar/score.html) · [实施验收](E:/Project/Software/sheet_music_generator/reports/accompaniment/20261012_repeat_score_layout/summary.md)。共用实际伴奏的部分折叠，多遍简谱／歌词上下排列；D.S.／To Coda／Fine与明确演奏顺序、各遍试听和高亮已接入。最多四小节一行，原音乐／完整展开谱／原唱合播及钢琴字节保持；937项测试与三曲实际浏览器／打印／字形／路线核验通过。

# 自动乐谱生成器

## 2026-10-12最新交付：器乐填充随主体密度与《渴》v3

用户要求前奏／间奏／尾奏低弦空拍填充跟随同曲正文密度，不固定八分。已完成通用guitar_instrumental_density与instrumental_flow版本2：真实普通右手攻击分组、覆盖时长基本格、相邻稳定唱段／整曲后备、已有旋律／低音攻击预算及原持音恢复；版本1仍可严格重放。新生成默认，旧工程--instrumental-flow-density明确另存，背景筛选／黑点力度继续应用。

当前[渴v3吉他谱／原唱合播](E:/Project/Software/sheet_music_generator/results/accompaniment/渴_v3_器乐填充密度跟随主体/guitar/score.html)；[通用逻辑与验收](E:/Project/Software/sheet_music_generator/reports/accompaniment/20261012_instrumental_density_follow/summary.md)。渴从554四分＋2八分正文攻击自动选五个器乐段四分密度，填充96→15，831→750吉他音；40主旋律逐字段保持，560正文音／原事件、人声／歌词／共享时轴／原唱字节与v2一致，背景0–20.34秒休止保持。原低音／关键和声起音、音高和弦品保留，持音恢复来源后按同音重拨审计，已有钢琴保持。

913项全测（新增17）、遇见v7／雨天v21八分基本密度的真实试算及旧源重放、实际XML／SMF／PCM／SVG、Chrome128项和目视通过。遇见填充111→103、雨天35→23为工作区回归结果，未覆盖其公开旧谱；主旋律／正文／钢琴保持。原渴拍轴6残差／15相位冲突继续待听审。本轮旧文件9021基线审计通过。

下一步依据渴v3试听反馈继续通用音乐质量复核，再按用户安排其他歌曲或指弹独奏，旧谱、原素材和模型来源保留。


## 2026-10-12最新交付：通用背景筛选与《渴》v2

用户要求程序自动筛选杂乱、旋律不清晰的器乐背景，渴前20秒只是实例，不能仅以手填时段处理。已完成通用instrumental_clarity及来源绑定的guitar_instrumental_expression：联合原混音／伴奏／低音、真实攻击规律、候选本频起音及旋律连续性，三态判别并保护自由旋律、长音／尾响；新生成默认，旧工程--instrumental-expression显式另存，人工复核为可选覆写。

当前[渴v2吉他谱／原唱合播](E:/Project/Software/sheet_music_generator/results/accompaniment/渴_v2_前段休止与旋律突出/guitar/score.html)；[实施验收与通用原理](E:/Project/Software/sheet_music_generator/reports/accompaniment/20261012_instrumental_rest_and_focus/summary.md)。正式运行未传人工复核，自动0–20.343204秒背景休止，125背景音移除；40主旋律黑点／力度增强，96低弦填充减弱，831吉他音／196小节／49行。560唱段音及原事件、认可人声583音、344歌词／源拍轴／原唱保持；公开参考580音仅清除3个已获用户同意的背景无歌词候选。已认可钢琴保持。

896测试、遇见v7／雨天v21实际来源回归及无器乐误删、实际XML／SMF／PCM／SVG、Chrome128项检查和目视通过。原源账本不删，表现必须独立重放实际父工程／音源。原普通事件使用source_note_ids而无note_ids时需逐字段保留，不能丢掉右手模板时值；该实文件故障已修复并加反例。旧源拍轴6残差／15冲突仍明确待听审，本轮不强改。下一步依据渴v2试听反馈继续通用质量复核，再按用户安排推进其它曲或指弹独奏。


## 当前跨曲验证：《遇见》两套伴奏与原唱合播

[吉他简谱／六线谱与原唱合播](E:/Project/Software/sheet_music_generator/results/accompaniment/遇见_v1_乐句和弦复用/guitar/score.html) · [钢琴谱与合播](E:/Project/Software/sheet_music_generator/results/accompaniment/遇见_v1_乐句和弦复用/piano/score.html) · [实施与独立验收](E:/Project/Software/sheet_music_generator/reports/accompaniment/20261010_yu_jian_phrase_harmony/summary.md)。29个乐句、18个家族，7组跨句复用；原167段分析留审计，实际127段共同编配。源Ab调，吉他夹1品；原歌手0移调，82小节／21行，正文四小节一行。

本轮通用修复源调恢复、器乐准备顺序、相关攻击／弱证据版本3、完整拍换弦与尾拍共同编配。721项回归及实际谱／MIDI／原唱PCM／两套离线浏览器验收，旧《雨天》v20版本2严格重建保持。自动和声与稀疏源覆盖仍需音乐听审；原谱与原轨不覆盖。

## 既有《雨天》首选：v20相似乐句和弦框架复用

[吉他简谱、六线谱与原唱合播](E:/Project/Software/sheet_music_generator/results/accompaniment/雨天_v20_乐句和弦复用/guitar/score.html) · [钢琴谱与原唱合播](E:/Project/Software/sheet_music_generator/results/accompaniment/雨天_v20_乐句和弦复用/piano/score.html) · [实施验收](E:/Project/Software/sheet_music_generator/reports/accompaniment/20261010_phrase_harmony_v20/summary.md)。按完整音乐乐句联合选择主要和弦／换弦拍位／右手型，保留持续主音、低音及三音／七音支持的必要差异，不依赖曲名、歌词文本或人工和弦表。正式5–8／9–12／25–28由8／11／9段归并到各4段，分别C-Am7-F-C、C-Am7-F-Gsus4、C/G-Am7-F-Gsus4（吉他指型），共同规整八分／十六分分解型。

692项回归及两套实际XML／MIDI／PCM／浏览器通过；已认可人声、物理拍轴、原唱、v19器乐／特色填句及41小节换夹保持。新编配默认启用；旧工程--phrase-harmony明确另存升级，普通编辑保留人工音符。原声学harmony留审计，arranged_harmony共同驱动实际谱与音源。上一轮《遇见》仅规划通过、器乐换把未通过的限制，已由本轮上述通用准备与整曲交付接续；自动证据不代表全曲音乐认证。

## 历史伴奏谱：v19器乐声部与规整节奏

[v19吉他简谱/六线谱与原唱合播](E:/Project/Software/sheet_music_generator/results/accompaniment/雨天_v19_器乐声部与规整节奏/guitar/score.html) · [钢琴谱](E:/Project/Software/sheet_music_generator/results/accompaniment/雨天_v19_器乐声部与规整节奏/piano/score.html) · [实施验收](E:/Project/Software/sheet_music_generator/reports/accompaniment/20261010_instrumental_rhythm_v19/summary.md)。2026-10-10用户要求回到v17的器乐复杂度，主要规整节奏。本轮保留旋律、低音和必要和声：器乐吉他260→246、钢琴263→257，低音54/53全部保留，异音旋律音序保持，只有3次短同音旋律连发归并。最小正常十六分，常规非附点拨弦槽；新器乐实际XML无32分及更小/附点16分，各仅1个附点八分延音片段。认可人声/普通伴奏486与595音、物理拍秒/原唱与和声分析保持。

661项回归（新增21）、实际XML/MIDI/PCM/两套隔离浏览器通过；四小节一行及第41换夹保持，钢琴1033实际字形全部可见。新生成默认完整声部节奏整理；旧工程--regular-instrumental显式另存，旧--simplify-instrumental仍可生成单线策略，普通编辑重导保持音乐。本轮v19输入为完整v17，v18及原v17留作对照。

## 当前十曲集合与v9补强

[打开十曲简谱与MIDI](<E:/Project/Software/sheet_music_generator/results/index.html>)。新六曲Bruce Lee、黑夜中 (Live)、The Moment、极美、无限大、雨天已实际处理，按歌归档简谱HTML/SVG、MIDI、MusicXML和原声复核；原四曲v8的74个交付文件保持。

v9采用连续局部调性识别，支持无长停唱和换歌词的转调；调性不确定时保留演唱候选音高，明确段继续“调外音宁缺毋滥”。208项回归、六曲XML/MIDI/歌词来源/按拍布局和集合1971个链接核验通过，12张谱面PNG已查看。小调仅诊断保护；Bruce Lee末段英文尚未定位，部分转调起点与未挂词声段待听审。

[本轮结果、证据与复核清单](<E:/Project/Software/sheet_music_generator/reports/tonality_v9/summary.md>)。当前集合指针为[current_results.json](<E:/Project/Software/sheet_music_generator/reports/current_results.json>)；[todo.md](<E:/Project/Software/sheet_music_generator/todo.md>)与[progress.md](<E:/Project/Software/sheet_music_generator/progress.md>)记录接续状态。下方保留各阶段历史说明，音乐结果仍为自动草稿，整曲人工听审与外部写谱软件GUI往返未完成。

<!-- 连续转调识别与不确定调性保护：更新当前入口，旧四曲归档说明作为历史注释保留。
## 四曲v8结果归档

最新集合：[打开四曲简谱与MIDI](E:/Project/Software/sheet_music_generator/results/index.html)。`results`内每首歌曲单独一个同名文件夹，包含简谱HTML/SVG、MusicXML、MIDI、复核页和验证记录。遇见/我不难过/渴已用当前v8重新生成，日落大道收录最新版；旧谱保留。

集合入口为`reports/current_results.json`，本轮来源、生成日志与核验记录位于`reports/results_v8`。四曲导出/挂词/调号/布局/本地链接核验通过；渴的小节相位较旧版移一拍（197小节），稳定调外例外及未完成整曲听审详见本轮summary.md。
-->

<!-- 第二首跨歌曲验证：新增当前产物入口；下方各历史阶段仍保留供对照。 -->
<!-- 简谱按拍分组优化：修改当前阅读入口，上一版说明保留作历史记录。
当前歌曲已切换为**孙燕姿《渴》标准歌词版**：[对齐简谱](test_outputs/scores/ke_standard_aligned/score/jianpu.html) · [清单与试听](test_outputs/scores/ke_standard_aligned/score/manual_review.html) · [本轮验证](reports/ke_validation/quality.md)。69行、344歌词单位全挂谱，4个Hu保留；196小节。G大调/4拍/166速度为自动候选，音乐待听审。已认可《遇见》独立指针为[yu_jian.current.json](reports/scores/yu_jian.current.json)。
-->
<!-- 简谱按拍分组优化：新增两首通过通用渲染程序重导出的新版入口。 -->
<!-- 第三首《我不难过》跨歌曲验证：修改当前入口，下列原说明作为历史记录保留。
当前阅读版：[《遇见》按拍分组简谱](test_outputs/scores/yu_jian_beat_grouped/score/jianpu.html) · [《渴》按拍分组简谱](test_outputs/scores/ke_beat_grouped/score/jianpu.html) · [本轮排版核查](reports/beat_grouped/verification.json)。同拍短音下划线按层连接，拍内紧凑、拍间留白；每行仍4小节对齐。两首项目/XML/MIDI/验证数据与旧稿逐字节一致，121项回归通过。《遇见》既有位置的用户认可记录保留，《渴》的音乐听审状态沿用上一版。
-->
<!-- 第三首《我不难过》跨歌曲验证：新增第三首独立自动稿、参考对照与原声试听入口。 -->
<!-- 第四首《日落大道》男声跨歌曲验证：修改当前入口，第三曲说明保留为历史记录。
当前歌曲**孙燕姿《我不难过》**：[按拍分组简谱](test_outputs/scores/wo_bu_nan_guo_beat_grouped/score/jianpu.html) · [8项重点与原声试听](test_outputs/scores/wo_bu_nan_guo_beat_grouped/score/manual_review.html) · [参考简谱差异报告](reports/wo_bu_nan_guo_validation/comparison.md) · [交付核查](reports/wo_bu_nan_guo_validation/verification.json)。完整320.4秒、44行/476单位全挂谱、171小节；Eb大调/4拍/128速度为自动候选，64半速与音乐仍待听审。先冻结独立稿，再核对4页参考中人声简谱的28个代表位置；未从吉他编配导入答案。132项回归通过。

[《遇见》既有阅读版](test_outputs/scores/yu_jian_beat_grouped/score/jianpu.html)与[《渴》既有阅读版](test_outputs/scores/ke_beat_grouped/score/jianpu.html)保留，独立指针与音乐文件未改；《遇见》既有位置的用户认可记录不变。《我不难过》独立指针为[wo_bu_nan_guo.current.json](reports/scores/wo_bu_nan_guo.current.json)，全局当前入口已更新。



-->
<!-- 第四首《日落大道》男声跨歌曲验证：新增男声自动稿、实际转调与已知剩余问题入口。 -->
<!-- 大调约束与强拍先验：修改当前入口，v6说明保留为历史记录。
当前歌曲**梁博《日落大道》**：[按拍分组简谱](test_outputs/scores/ri_luo_da_dao_beat_grouped/score/jianpu.html) · [8项重点与原声试听](test_outputs/scores/ri_luo_da_dao_beat_grouped/score/manual_review.html) · [参考对照与通用修复](reports/ri_luo_da_dao_validation/comparison.md) · [交付核查](reports/ri_luo_da_dao_validation/verification.json)。完整275.435秒、28行/301单位，300可靠挂谱、1个“的”未定位；148小节、409音段。参考选调G、原调B、变调夹4品；输出保留录音B大调并标末段转C，未按打印谱把实际升半音强改回去。153项回归通过，62个代表位置对照不是整曲准确率，128/64拍单位与剩余细部仍需听审。
-->
<!-- 大调约束与强拍先验：新增v7通用规则与实际核查入口。 -->
<!-- 调外音宁缺毋滥：修改当前入口，v7说明保留历史。
当前歌曲**梁博《日落大道》v7**：[按拍分组新版简谱](test_outputs/scores/ri_luo_da_dao_tonal_rhythm_beat_grouped/score/jianpu.html) · [调外候选与原声试听](test_outputs/scores/ri_luo_da_dao_tonal_rhythm_beat_grouped/score/manual_review.html) · [通用规则与验证说明](reports/tonal_rhythm_v1/comparison.md) · [交付核查](reports/tonal_rhythm_v1/verification.json)。第16小节降3纠正为3，“飞”落12小节第一拍；B大调至89小节C大调保留。148小节/407音段，301原单位保留、300挂谱；“的”为用户确认吞字，不造时间/音符。大调先验、稳定调外例外、模糊句首强拍先验及弱起/切分保护已接入通用程序，171项回归通过。6个稳定调外候选与10个证据不足半音有试听入口；整曲准确率尚未听审。v6与旧三曲保留。
-->
<!-- 调外音宁缺毋滥：新增v8严格门槛、滑音连奏与验证入口。 -->
当前歌曲**梁博《日落大道》v8**：[按拍分组新版简谱](test_outputs/scores/ri_luo_da_dao_conservative_major_beat_grouped/score/jianpu.html) · [五处修复原声试听](test_outputs/scores/ri_luo_da_dao_conservative_major_beat_grouped/score/manual_review.html) · [保守规则与实测](reports/chromatic_precision_v1/comparison.md) · [独立核查](reports/chromatic_precision_v1/verification.json)。调外音宁缺毋滥：迷失只留2到3并连奏，金1、40夜2、44宴4、52看3；本首主谱调外事件0，148小节/404音段。飞12首拍、89小节B转C和已确认吞字保持；原409音段、源字/音素时间与旧稿保留。180项回归及XML/MIDI/按拍排版通过；这是一版保守记谱，部分短借用音可能省略，原始候选在复核层。



[《遇见》既有阅读稿](test_outputs/scores/yu_jian_beat_grouped/score/jianpu.html) · [《渴》既有阅读稿](test_outputs/scores/ke_beat_grouped/score/jianpu.html) · [《我不难过》既有阅读稿](test_outputs/scores/wo_bu_nan_guo_beat_grouped/score/jianpu.html)保留，旧文件/分曲指针SHA均不变；新规则的旧曲候选变化单独披露，未覆盖用户认可稿。第四曲分曲指针为[ri_luo_da_dao.current.json](reports/scores/ri_luo_da_dao.current.json)，全局入口reports/current_score.json已更新。

当前正在推进 Windows 本地歌词对齐与真实人声制谱；兼容性基线已完成。产品第一阶段目标为带中文歌词、可以独立写谱软件校正的人声简谱；第二阶段为吉他指弹编配。

## 当前已验证

- 十首 NCM 已还原为原编码 FLAC，全部完整解码通过，源文件转换前后 SHA256 一致。
- 七首歌曲不超过五分钟。《我不难过》《Bruce Lee》《黑夜中 (Live)》保留为压力样本。
- 《遇见》选为首曲；真实兼容片段为歌曲 40–70 秒，详见 reports/sample_manifest.json。
- GPU 张量、FFT、卷积及 Demucs/ROSVOT 短片段与整首推理通过；《遇见》音频到转录数据/MIDI 的本次完整入口墙钟约16.94秒，不含歌词识别对齐、节奏制谱或首次下载。
- 人工 MusicXML 语义与程序化校正版回导通过；它不是音频转谱效果样例，易谱实际往返尚待验证。真实歌曲初步歌词对齐、节奏制谱和校正版回导已跑通；自动音乐准确性与编辑器GUI往返仍需核查。

## 目录

- test_music：用户原始素材，保留原件。
- test_outputs/converted：NCM 还原的原格式音频。
- test_outputs/samples：有明确偏移的模型测试片段。
- test_outputs/probe：转换、音频参数和完整解码日志。
- test_outputs/notation：人工 MusicXML 与项目 JSON 兼容样例。
- tools：可复用验证脚本，新增代码附任务中文注释。
- reports：机器可读结果及中文验证报告。
- .tools、.runtime、.venv-gpu、.cache：项目内便携工具、运行时、依赖和模型缓存。
- progress.md：完整工作日志；todo.md：稳定总体任务与当前上一步/下一步。

## 重复验证

在项目目录用 PowerShell 运行：

```powershell
.\run_validation.ps1 -Stage AudioFirst
.\run_validation.ps1 -Stage AudioAll
.\run_validation.ps1 -Stage Notation
.\run_validation.ps1 -Stage GPU
.\run_models.ps1
.\run_models.ps1 -Full
```

素材检查可重复执行，源与产物SHA256一致的还原缓存复用，并重新完整解码。片段核对真实帧数且同参数可复用；不同参数独立输出。模型入口默认30秒片段，-Full处理整首，每次另存独立报告与输出目录；避免把缓存命中时间当作首次下载或转换耗时。

GPU 与模型依赖使用项目内 .venv-gpu；不调用系统默认 Python 3.13/3.14。下载、模型加载、推理及人工校正分别记录；GPU 模型依次运行。

## 核查依据

- [首曲验证汇总](reports/first_sample.md)
- [项目素材验证报告](reports/audio_validation.md)
- [本机模型环境及依赖锁](reports/environment.md)
- [ROSVOT实测](reports/rosvot_compatibility.md)
- [MusicXML编辑兼容检查](reports/notation_compatibility.md)
- [ncmdump](https://github.com/taurusxin/ncmdump)
- [FFmpeg](https://ffmpeg.org/download.html)
- [PyTorch Blackwell 支持说明](https://pytorch.org/blog/pytorch-2-7/)
- [ROSVOT](https://github.com/RickyL-2000/ROSVOT)
- [Demucs](https://github.com/facebookresearch/demucs)

处理速度、准确率及编辑器兼容性以本机 reports 内实测为准。五分钟歌曲约五分钟处理为优化目标。


## 正确歌词与真实草稿

本轮《遇见》使用用户提供的25行歌词，原文保存为 test_outputs/lyrics/user_supplied/yu_jian.txt。识别原稿、用户文本、逐字候选时间、连续f0和最终记谱层分别保存。不可将ASR文本正确性、内部对齐诊断和MusicXML结构有效性混为同一准确率。

```powershell
.\run_score.ps1 -LyricsFile .\test_outputs\lyrics\user_supplied\yu_jian.txt
# 分句路线：需同源ASR锚点，真实逐句模型推理；保留匹配代价和候选警告。
.\run_score.ps1 -LyricsFile .\test_outputs\lyrics\user_supplied\yu_jian.txt -AlignmentBackend tifa-phrases
# 可选人工覆盖（示例值，需核对音乐）
.\run_score.ps1 -LyricsFile .\test_outputs\lyrics\user_supplied\yu_jian.txt -Tempo 92.285 -Key 'Eb:major' -Meter '4/4'
```

每次在 test_outputs/score_runs/<run_id> 另存 refined、lyrics 和 score，并在 reports/score_runs/<run_id> 保存计时和阶段清单。入口检查整首零偏移模型报告；分句窗口仅以同源ASR/有声段定位，用户歌词仍是权威文本，不按字均分时间。无可靠时间的字保留警告，不强塞入音符。

score/jianpu.html 是全曲静态简谱，preview_first_vocal.png 是首段预览；vocal_draft.musicxml 供独立写谱软件校正，vocal_draft.mid 是自动记谱试听；project.json 保留秒—拍映射、量化误差、歌词冲突和原分析引用。review.html 可在本机浏览器点击试听优先复核候选，音频只引用同源本地人声。页面交互未通过GUI实测，文件/路径/SHA已由生成工具核对。

拍速和调性保留候选与启发式支持；4/4目前为弱证据显式先验。固定网格无法自动识别三连音；量化塌缩短音以待审倚音保留，不自动认定为原唱装饰音。简谱基准八度明确写成如1=Eb3（MIDI51）；导出MIDI/原音频同步需使用project中的score_start_seconds，而不是假设谱面第0秒等于原音频第0秒。

## 乐谱校正版回导

先在独立编辑器另存MusicXML，再使用对应原project回导；输出路径不能覆盖源项目。

```powershell
.\.venv-gpu\Scripts\python.exe -B tools\import_score.py import --musicxml '<校正后的.musicxml>' --project '<原project.json>' --output '<另存的校正版project.json>' --report '<回导报告.json>'
```

校正记谱层与原自动事件/连续f0分离，修订历史与原路径/SHA保留。ID丢失、重排或节奏变化导致身份匹配不确定时报告候选并返回状态码2，需要复核后处理。当前验证范围为单声部、完整小节和整数半音；多声部/微分音拒绝，不是完整MusicXML XSD支持。实际编辑器往返尚未实测；已完成的程序化副本修改/回导只证明当前格式的结构与数据保留。


## 首份用户歌词详细草稿（保留）

详见 [阶段汇总](reports/real_vocal_draft.md) 和 [当前产物指针](reports/current_score.json)。详细稿run为20261005_192901_116，82小节、237字全部挂谱；69个字音警告和14个网格塌缩短音需复核。默认已改为medium识别与真实分句TIFA，显式整曲基线可用-AlignmentBackend tifa。

已有对齐可显式哈希核对后复用（这个速度是缓存CPU导出，不是新GPU推理）：

```powershell
.\run_score.ps1 -LyricsFile .\test_outputs\lyrics\user_supplied\yu_jian.txt -AlignedLyrics .\test_outputs\lyrics\user_phrases_candidate\characters.json
```


## 主旋律简化版

先前简化谱另存为test_outputs/scores/simplified_main/score/jianpu.html；MusicXML、MIDI与首段PNG在同目录。音符段352→255、14个量化倚音→0，保留237字和重要转音，原详细版仍可对比。简化层在现有ticks上处理，不重新识别、对齐或量化。

详见[简化版报告](reports/simplified_vocal_draft.md)及[当前指针](reports/current_score.json)；详细版指针为reports/current_score.detailed.json。规则仍属自动草稿，需试听校正。

```powershell
.\.venv-gpu\Scripts\python.exe -B tools\simplify_melody.py --project test_outputs\score_runs\20261005_192901_116\score\project.json --output test_outputs\scores\simplified_main\project.input.json --report reports\simplify_melody.json
.\.venv-gpu\Scripts\python.exe -B tools\export_simplified_score.py --project test_outputs\scores\simplified_main\project.input.json --output-dir test_outputs\scores\simplified_main\score --report reports\score_simplified_export.json
.\.venv-gpu\Scripts\python.exe -B -m unittest discover -s tests -p test_simplify_melody.py -v
```


## G大调与参考谱对照

按用户参考，人声目标为G大调，器乐间奏短段降B。G调简化稿位于test_outputs/scores/simplified_g_major/score。原素材首句基音与G谱相差约半音，新稿整体降低1半音；不按原误估Eb升4半音，不修改原音频/f0。新稿仍沿用自动节奏和字音，不是参考谱校正版。

[差异报告](reports/g_reference_comparison.md)记录主音误删、字音错配、转音漏检及弱起/量化/尾部拍格问题。尤其零tick不能统一当作装饰音删除；下一阶段需先修字音与量化前的旋律主干。

```powershell
.\.venv-gpu\Scripts\python.exe -B tools\rekey_simplified_score.py --project test_outputs\scores\simplified_main\score\project.json --output-dir test_outputs\scores\simplified_g_major\score --key G:major --semitones -1 --reference-midi 55 --report reports\rekey_g_major.json
.\.venv-gpu\Scripts\python.exe -B -m unittest discover -s tests -p test_rekey_simplified_score.py -v
```


## 量化前音乐解码（当前默认）

`run_score.ps1` 默认 `-NotationProfile musical`，使用 `tools/musical_decode.py`。先核查连续音高与局部YIN，再做完整音段的单调软字音关联和主音/倚音/转音分类；不把歌词边界碎片或零tick当成可删装饰音。低置信长段保留为待核转音，源音频/f0/原模型音符均保留。

默认不移调，人声调性候选与混音候选分开；`-Key` 在新层表示目标调，例如源人声候选Ab→目标G会显式降半音。旧原型入口仍可用 `-NotationProfile legacy`，其Key仅覆盖调号，和新版语义不同。`Subdivision` 保留旧入口兼容，新层使用分层拍格及32分最短主音保护。

```powershell
.\run_score.ps1 -LyricsFile .\test_outputs\lyrics\user_supplied\yu_jian.txt -AlignedLyrics .\test_outputs\lyrics\user_phrases_candidate\characters.json -Key 'G:major'
# 默认保留录音实际音高：省略 -Key。
.\.venv-gpu\Scripts\python.exe -B -m unittest discover -s tests -v
```

<!-- 字音归属修复：修改当前版本说明，原文保留。
最新冻结验证稿为 `test_outputs/score_runs/20261006_002641_294/score`。G稿 jianpu.html / vocal_draft.musicxml / vocal_draft.mid、首段/尾段PNG、可试听的review.html与project.json均已生成；源音高稿另存 `test_outputs/scores/musical_native_final/score`。旧G简化稿和首轮已暂停交付的中间稿保留。
-->
上轮冻结验证稿为 `test_outputs/score_runs/20261006_002641_294/score`，及其源音高稿、旧G简化稿和首轮中间稿均保留；当前版本见下方字音归属修复。

XML的同音tied、不同音slur和grace时间分配分别导出。MIDI回读和XML倚音百分比回算均验证；跨编辑器GUI播放未测试。三连音自动识别、尾声渐慢尚未实现，不把普通弧线伪称三连音。

80项程序回归及独立5类故障复查通过；具体音乐效果见 [最终音乐抽查报告](reports/musical_quality_final.md)。参考谱仅作评估：首32字、已知错例和5个跨段窗口，不能称整曲准确率。主音/转音有改善也有退步，弱起拍位和边界敏感性仍有问题；其他真实歌曲的音乐质量尚未验证。程序测试通过不等于乐谱已准确。

- [程序及扰动检查](reports/musical_program_final_checks.json)
- [独立缺陷终审](reports/musical_decoder_v1_final_audit.json)
- [回归运行记录](reports/musical_regression_final.txt)


## 音素驱动的字音归属（当前默认）

默认musical入口现使用v2联合挂词：TIFA音素按原G2P owner保留，校验裁剪音频SHA与全局时间坐标，旧缓存派生为characters_phonemes.json；所有音段在同一单调路径上共同分配给歌词。音素核音、声母和独立词起音参与，音高转折不直接当作换字；原声学音高分析保持。

每次生成自动检查音素时间±80ms的敏感性。复核页优先显示不确定的当前字、所在句、相邻候选和可定位的人声试听；分数是未校准证据，不能称正确率。多音字的重要音继续保留，不以唯一main标签与参考谱不一致直接判音乐错误。

字音修复时的G稿为 `test_outputs/score_runs/20261006_015056_492/score`，源音高稿为同运行的 `native_score`。237字均接入实际音素，95项回归通过（新增15项）；单句真实GPU新推理已验证。3个跨字声段调整，原首32字、“意”的四音转折及“美”的普通4/5保持；“们”恢复普通有时值2。另有32个时间敏感声段/36条提示仍需原声确认。旧报告和旧谱保持。

[本轮字音复验](reports/word_ownership_v2/quality.md) · [全部回归记录](reports/word_ownership_v2/regression.txt) · [当前产物](reports/current_score.json)

上面的run_score命令无需新增用户参数；音素证据从已核对的真实对齐报告自动接入。默认仍保留源音高，指定`-Key G:major`另存G稿。原参考简谱只用于独立评价，没有注入生成答案。其他歌曲的音乐质量、弱起/渐慢和独立编辑器GUI往返仍待验证。


## 简谱小节对齐与人工复核汇总（2026-10-06）

当前阅读入口为 `test_outputs/scores/aligned_measures_g_major/score/jianpu.html`，每行4小节，小节边界纵向对齐；小节密度决定统一列宽，网页可放大与横向滚动。小节编号避开连奏弧线。此版沿用015056_492的音乐内容，项目/XML/MIDI/验证数据与上版逐字节相同，未重新运行模型。

`manual_review.html` 提供按句汇总和整句/短段试听，小节号直达对应谱面；另存Markdown和JSON。36条字音提示去重为32段，分布22句；58条音高和44条细节候选按句折叠，旧69字窗口提示和50条声学提示保留在证据层。这些类别可能重叠，不作为已确认错误数。

当前曲优先六项评估为首句弱起早1拍、开/待的2→1、两遍我等的人首我音高、尾声渐慢；仅展示用户参考谱与已有评估，不输入生成算法。美的4/5、意的完整四音不因唯一主音标签而判错误。

通用渲染器与默认复核入口均已更新，后续运行run_score.ps1自动采用对齐格式和按句清单；只重排旧项目可使用：

```powershell
.\.venv-gpu\Scripts\python.exe -X utf8 -B tools/format_score.py --score-dir test_outputs/score_runs/20261006_015056_492/score --output-dir test_outputs/scores/aligned_measures_g_major/score --findings reports/aligned_measures/evaluation_findings.json
```

95项回归通过，排版几何/全部提示覆盖/文件哈希/本地链接核查通过；实际查看PNG与隔离浏览器页面和小节跳转。未进行整曲听审和编辑器GUI往返。记录见 [格式核查](reports/aligned_measures/verification.json)；唯一当前入口仍为 [当前产物指针](reports/current_score.json)。


## 第二首与任意本地歌曲入口（2026-10-06）

新增-Song选择本地NCM，完整报告独立保存到reports/runs；控制台给出可直接输入run_score的报告路径。原首曲完整报告不覆盖。

```powershell
# 第二首跨歌曲验证：新增歌曲选择与标准歌词输入示例。
.\run_models.ps1 -Full -Song '孙燕姿 - 渴.ncm'
.\run_score.ps1 -ModelReport 'reports\runs\<新模型运行号>\integrated_pipeline.json' -LyricsFile 'test_music\孙燕姿 - 渴 歌词.txt'
```

可显式-AsrAnchor提供同源识别原始JSON；程序核对源SHA/时间偏移，自动稿缓存还核对全部识别配置。Hu目前为受支持的单音节哼唱记号，其他英文不静默删除。窗口支持多行/多段，合并保护首尾短行并统一匹配副本简繁；真实逐字边界来自TIFA，未均分。仍可提供完整按实际演唱顺序的正确歌词，保留重复段。

默认复核页另列全部无挂词音段；静音过滤仍可能漏掉真实唱词，同音误字未解决，不能把全挂谱与程序测试当音乐准确率。标准版完整实测与局限详见reports/ke_validation/quality.md；111项回归通过，编辑器GUI往返仍待做。下方/上方标注其他运行号的说明均是历史阶段，不是本曲当前阅读入口。

## 简谱按拍分组优化

<!-- 简谱按拍分组优化：新增通用程序规则及可复现入口，不写入歌曲特定音乐答案。 -->
`tools/score_export.py`中的默认渲染器使用小节内tick和拍号分组。4/4按四分拍连接八分、十六分、三十二分各层减时线，拍界断线；短休止参与同拍线条，零时值倚音单独绘线。附点与切分的真实时值、同音延音/不同音连奏弧线、原歌词归属保持不变。长音横线位于相应四分拍。

拍内字形间隙8像素（倚音后6），拍组间最少28；空白分布在拍组两侧，每行4小节、列宽按全曲最密小节统一。节选和完整谱使用同样密度标准。独立重排仍通过`tools/format_score.py`，不重新跑模型：

```powershell
# 简谱按拍分组优化：补全字音段预览复现参数，原命令保留。
# .\.venv-gpu\Scripts\python.exe -X utf8 -B tools/format_score.py --score-dir test_outputs/scores/aligned_measures_g_major/score --output-dir test_outputs/scores/yu_jian_beat_grouped/score --findings reports/aligned_measures/evaluation_findings.json --preview-range coda:73:82
.\.venv-gpu\Scripts\python.exe -X utf8 -B tools/format_score.py --score-dir test_outputs/scores/aligned_measures_g_major/score --output-dir test_outputs/scores/yu_jian_beat_grouped/score --findings reports/aligned_measures/evaluation_findings.json --preview-range word_ownership:37:44 --preview-range coda:73:82
.\.venv-gpu\Scripts\python.exe -X utf8 -B tools/format_score.py --score-dir test_outputs/scores/ke_standard_aligned/score --output-dir test_outputs/scores/ke_beat_grouped/score --findings reports/ke_validation/evaluation_findings.json --preview-range humming:38:47 --preview-range coda:171:196
```

[121项回归记录](reports/beat_grouped/regression.txt) · [独立核查脚本](reports/beat_grouped/verify_layout.py)。82/196小节全部线条层数/连接边界/字形间距/歌词顺序及600个本地引用检查通过；实际查看两首首段、最密、尾声和《渴》Hu段共7张PNG。本轮只验证排版与数据保持，不重新评估音乐准确率；旧阅读稿及当前指针快照保留在各原目录及reports/beat_grouped。


## 中文冻结版本与英文融合验证（2026-10-07）

中文制谱v9代码冻结在 [version1-chinese-sheetmusic](history-version/version1-chinese-sheetmusic/VERSION.md)，287文件逐项SHA通过；已认可的无限大和雨天以及原十曲170个文件均保留。

当前程序可据标准TXT自动选择中文、英文或混合TIFA前端，英文按单词和实际元音音节处理，保留原拼写与各音节主音，同音音节不合并。Bruce Lee七次重复短句通过整组音频对齐补全，Fly287词/330音节通过实际验证。237项回归通过；输出在 [results入口](results/index.html)，原Bruce基线与英文融合版分开。

[本轮说明及复现入口](reports/english_integration/summary.md)。英文验证稿仍待全曲试听；词序、音节、XML/MIDI和排版检查不等于音高/节奏准确率。完整英文自动识别（无标准TXT）、小调/三连音及独立写谱软件GUI往返尚未验收。

## 可编辑五线谱

当前11首首选版本的五线谱入口：`results/staff_index.html`。每首歌曲目录新增：

- `staff_score.musicxml`：未压缩的可编辑五线谱，写谱软件可修改音符、时值、歌词和排版。
- `staff_score.mxl`：与上述MusicXML内容完全一致的压缩交换文件。
- `staff.html` 与 `staff_pages/page_*.svg`：可缩放、分页查看的五线谱；网页本身用于阅读。
- `staff_validation.json`：原简谱与五线谱的音高、节奏、歌词、调号和来源文件核验。

默认真实制谱、legacy制谱和简谱重排入口都会调用通用五线谱导出。不重新运行音高识别或歌词模型；沿用当前旋律。原简谱、原MIDI和中文冻结版本保留。英文按整词排版，普通短音按拍连梁，倚音、延音与连奏区分；调内等音拼写适配五线谱，例如F#大调的第7级写E#，实际音高不变。

已有结果可直接运行：

```powershell
.\.venv-gpu\Scripts\python.exe -B tools\staff_export.py --score-dir 'results\Fly'
.\.venv-gpu\Scripts\python.exe -B tools\export_staff_collection.py --manifest 'results\manifest.json'
```

排版依赖固定在`requirements-staff.txt`。本轮安装Verovio6.3.0进行实际MusicXML/MXL导入和SVG排版，resvg-py0.5.0用于PNG视觉核查；原音频模型依赖没有替换。若通过一个已有pip的Python管理此项目环境，可执行：

```powershell
python -m pip --python .\.venv-gpu\Scripts\python.exe install -r requirements-staff.txt
```

11首MusicXML无修改回导检查通过；两份另存的改音/改词示例只产生预期两项校正。回导原程序已补充分段调号比较，原有转调不会被误报为新的编辑。252项测试通过。真实写谱软件GUI操作尚未实测；这与MusicXML可编辑交换文件及实际排版导入检查分别记录。说明见`reports/staff_export/summary.md`。

格式与工具依据：[MusicXML官方格式](https://www.w3.org/2021/06/musicxml40/)、[MuseScore文件导出](https://handbook.musescore.org/file-management/file-export)、[Verovio输入格式](https://book.verovio.org/toolkit-reference/input-formats.html)、[Verovio Python接口](https://book.verovio.org/installing-or-building-from-sources/python.html)。
