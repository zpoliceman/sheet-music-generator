# 项目交接说明

更新：2026-10-18。本文件只保存当前可用起点；详细历史已归档，旧文中的“当前／下一步”不能覆盖这里。

## 新对话先读这里

主项目是本地自动乐谱生成器：原曲与缓存分析→人声简谱／歌词→同一和声下的吉他、钢琴两套伴奏及原唱合播。当前阶段是伴奏与阅读，完整指弹独奏、独奏五线谱和网站／小程序尚未启动。稳定总体目标见todo.md。

**2026-10-18工作目录和第五版名称更正已检查并修复。** 实际根目录为E:\Project\Software\sheet_music_generator，第五版为version5-20261018-optional-chords。原虚拟环境路径已修正，8766从新目录运行，启动器重复执行复用同一进程。旧名称sheet_musit_generator是指向新目录的Windows目录联接，供不可改写的旧工程绝对路径读取；请保留，日常使用新目录。data/workspace_identity.json保存原曲谱编号种子，应随代码保留，不是文件访问位置。

九曲来源及五套旧配置兼容，1493项最终测试、18项实际浏览器检查及一版隔离完整保存通过。新保存62小节、707音，人声／共享分析／双乐器编配与原四区间版本一致，216.88秒音频采样也一致；8338份results、5份原配置及1457份旧版本文件保持。改名后的第五版40106份文件完整校验通过，冻结内容未改写。[目录改名报告](E:/Project/Software/sheet_music_generator/reports/accompaniment/20261018_workspace_rename/report.md)与[总核对](E:/Project/Software/sheet_music_generator/reports/accompaniment/20261018_workspace_rename/verification.json)列明实际入口；没有重新执行整首模型识别或新增音乐发布。专用隐藏浏览器与8767已关闭，用户8766仍运行。

**2026-10-18旧版本清理、第五版备份和GitHub教程已经完成。** 用户明确授权删除的verision3-20261014-temporary-right、version4-20261016-temporary-right及version1-chinese-sheetmusic已经从实际history-version删除；第二版与20261014_general_music_rejected保留。MUSIC_REQUIREMENTS的R35当前备份指向version5-20261018-optional-chords，旧路径只作历史，不能再以旧保护文字要求用户重复确认已授权清理。

第五版约30.3GiB，保存代码、正式成品、当前编辑目录及所需来源，独立清单覆盖40106份文件；环境、模型缓存和整个试验目录不整份重复复制，恢复范围见备份内BACKUP_README和dependency_notes。首轮检查发现三套静态回溯成品未选入，已补567文件并核验，37页480个本地链接保持。[备份入口](E:/Project/Software/sheet_music_generator/history-version/version5-20261018-optional-chords/BACKUP_INDEX.html)、[本轮报告](E:/Project/Software/sheet_music_generator/reports/accompaniment/20261018_version5_backup/report.md)、[最终核对](E:/Project/Software/sheet_music_generator/reports/accompaniment/20261018_version5_backup/verification.json)记录实际范围。九首当前来源读取及原8338个results文件、5套配置、1457个已存版本保护通过，8766服务保持。

[GitHub上传与持续更新教程](E:/Project/Software/sheet_music_generator/history-version/GitHub上传与持续更新教程.md)有20节，含本机首次上传、日常更新、分支标签、恢复及Desktop路线。38段PowerShell语法与320份约4.8MiB代码的隔离暂存／检出通过；根.gitignore排除本机数据，.gitattributes保持.cmd行尾，README已有入口。实际.git仍无提交、索引和远程，没有替用户上传；后续从原项目目录继续，不在冻结快照中开发。本轮没有新音乐验收或发布。

**2026-10-18右手候选悬停六线谱预览已经完成。** 刷新8766后点击“右手型”，鼠标移到名称上即可在候选右侧查看C和弦原节奏示意，55型全部支持；点击或按Enter才应用，Escape关闭，触屏先点名称再点“应用此手型”。保留原select作为唯一实际选择值，分类／区间／清空同步，主谱、试听和保存仍走原入口。不要把悬停变成选型或向/api/preview发送请求。

新增tools/guitar_pattern_picker.js及css，ranges界面只增加入口／同步，服务只增加静态资源路由。示意使用C指型、原动作、原节奏与真实上下扫箭头；它不是当前歌曲或用户自定时值的完整预编配。55份实际图形读回、66项相关程序、22项隔离浏览器及9项8766浏览器检查通过；8066份曲谱目录文件、5份旧配置及1457份已存版本保持。原8766已经加载新代码并使用原工作目录，详见[悬停预览报告](E:/Project/Software/sheet_music_generator/reports/accompaniment/20261018_pattern_hover_preview/report.md)及[最终核对](E:/Project/Software/sheet_music_generator/reports/accompaniment/20261018_pattern_hover_preview/verification.json)。本轮没有新完整音乐或发布，后续接用户实际阅读／选型反馈。

**2026-10-18页面连接已经恢复，启动器也已调整。** 当天检查到8766没有监听、服务进程不存在，上次错误日志未记录退出原因。现在启动右手选择.cmd通过tools/start_guitar_pattern_preview.py启动独立隐藏进程，健康检查确认本应用就绪后才打开网页；已有服务直接复用，启动窗口关闭后服务继续运行。服务仍从right_hand_editor_session.json找回20261017_right_hand_editor目录；电脑重启后双击同一启动器即可。日志位于test_outputs/accompaniment_runs/right_hand_editor_service，原guitar_pattern_preview.py及音乐逻辑未修改。

本轮29项相关检查和6项实际浏览器检查通过，默认完整谱、旧配置和旧216.88秒音频可以读取／起播；修复前新建摘要所覆盖的8066份曲谱目录文件、5份配置和1457份已保存版本均保持。Windows批处理的UTF-8中文解析问题已实际修正并重测；继续保留该文件的UTF-8代码页与CRLF行尾。完整证据见[恢复报告](E:/Project/Software/sheet_music_generator/reports/accompaniment/20261018_preview_service_restore/report.md)和[最终核对](E:/Project/Software/sheet_music_generator/reports/accompaniment/20261018_preview_service_restore/verification.json)。本轮仅恢复服务，不新增音乐正确性结论。下文是此前已经完成的音乐功能及其有效保护决定。

**当前已经完成扫弦延音简化和右手候选扩充。** 普通扫弦保留跨弦箭头和动作节奏，程序不再逐弦画自然余音弧；只有明确空扫、停拨或较长保持才在六线谱上方集中提示。分解与合拨保留必要的逐弦提示。候选总数为55个，其中22种分解、13种合拨、20种扫弦；新增26型的具体弦序、时值和来源见[中文使用说明](E:/Project/Software/sheet_music_generator/reports/accompaniment/20261017_right_hand_expansion/patterns.md)及[来源核对文件](E:/Project/Software/sheet_music_generator/reports/accompaniment/20261017_right_hand_expansion/reference_review.json)。不要恢复普通扫弦逐弦画线的旧逻辑。

最终程序通过1477项测试、五曲130个新型窗口、26次实际网页选型和16项浏览器检查。程序还确认原29型定义及自拟工程保持，五曲15个旧方案的实际音符、演奏文件和音频采样相同，九首未选工程逐项保持。1497份正常成品及1309份旧配置／版本文件保持，详见[本轮报告](E:/Project/Software/sheet_music_generator/reports/accompaniment/20261017_right_hand_expansion/report.md)、[最终核对](E:/Project/Software/sheet_music_generator/reports/accompaniment/20261017_right_hand_expansion/verification.json)和[40条要求范围](E:/Project/Software/sheet_music_generator/reports/accompaniment/20261017_right_hand_expansion/requirements_acceptance.md)。新验证成品v20261017_221919_b2e4b2包含多远四个区间，完整62小节、707音、216.88秒；音乐仍需用户听审，正常曲谱库没有更新。

本轮涉及的通用函数是guitar_pattern_performance.draw_action_marks／strum_sustain_spans，以及guitar_pattern_selection._shape。前两者把扫弦的自然余音和明确延续分开；_shape的后备搜索现在真正枚举B2需要的另一条低弦，十二品、原低音、和弦性质及按弦条件保持。初次10例和四区间保存的失败记录保留在attempt1文件中，最终同批案例已重跑通过。浏览器清空后的比较只排除default-score-target定位高亮类，实际谱行及图形仍全部核对，不能改成仅检查“默认”标签。

服务继续使用8766和20261017_right_hand_editor目录；旧页面刷新后读取55型和新的画法。旧存档页面不批量改写，载入旧配置再保存会另建版本。AGENTS.md已经写入用户本轮明确更新的中文输出规范，后续回复和报告应说明谁做了什么、实际检查得到什么结果。其它拍号、拍弦／闷音及三连音仍未开放，The Moment继续暂停。

**需要继续保留的扫弦规则：跨弦直箭头。** 用户明确下扫在TAB向上，上扫向下，长度只跨实际扫到的弦。已重新实阅《七里香》《红色高跟鞋》等参考；主谱、局部、新完整及阅读谱共用guitar_strum_notation，扫弦不再叠画柱式x／品数，合拨及实际声音保持。图例／缓存同步，旧页面刷新生效。不要恢复上方Unicode方向符号＋柱式音头的旧画法。

1468项完整测试、13项浏览器、五曲15例完整SVG／前后音符MIDI及PCM一致、九曲未选原样、多远完整另存（62小节728音、216.88秒实际播放）通过；1497正常成品和1074旧配置／版本保持。[最新报告](E:/Project/Software/sheet_music_generator/reports/accompaniment/20261017_strum_arrow_notation/report.md)、[最终证据](E:/Project/Software/sheet_music_generator/reports/accompaniment/20261017_strum_arrow_notation/verification.json)、[40条范围](E:/Project/Software/sheet_music_generator/reports/accompaniment/20261017_strum_arrow_notation/requirements_acceptance.md)。验证成品v20261017_213341_073372，仍needs_review；旧保存HTML冻结，重新载入配置保存才产生新画法版本。纸面／全曲人工听审／真人试弹未代签。

本轮实际修正了复用阅读导出“只统计音头”拦截，完整导出、共同_modern_tab_rows、动作验收及变奏对齐均读实际跨弦箭头／指型；新增6项几何及完整阅读导出测试。失败现场保留attempt1；不要用旧音头计数拒绝合法扫弦，也不能只读data-direction通过。服务仍8766，目录仍20261017_right_hand_editor；本轮专用隐藏测试浏览器收尾关闭，用户浏览器保留。

**仍需保持：选型后同一主谱实时显示当前编配。** 用户反馈“选完没变化”已实测复现：上轮主谱固定为原谱、变化仅在下方局部，分类仅筛选。现初始显示默认完整谱和歌词，选型／时值后眼前主谱直接更新；分类实际选型，先选时值也能生效。试听与错误提示位于主谱旁，原谱可单独打开对照，清空恢复默认。不要恢复上轮固定原谱的主显示设计。

1462项完整测试、15项真实主谱／音频浏览器、五曲实际完整主谱及多远一版完整另存通过，1497正常文件及921旧配置／版本保持。[本轮报告](E:/Project/Software/sheet_music_generator/reports/accompaniment/20261017_right_hand_visible_change/report.md)、[复现](E:/Project/Software/sheet_music_generator/reports/accompaniment/20261017_right_hand_visible_change/reproduction.json)、[收尾](E:/Project/Software/sheet_music_generator/reports/accompaniment/20261017_right_hand_visible_change/verification.json)。完整音乐导出实测为多远一版，五曲为完整主谱SVG＋实际编译／持握及片段音频，不冒充整曲听审。

**当前已完成4/4选型及多区间配置、当前网页内整曲交付。** 29型候选保持；可逐条填写起止小节、独立设置右手型／时值／收音，可命名保存多套并载入。保存后页面内直接显示全部小节与整曲试听，另存版本不覆盖认可谱。[本轮报告](E:/Project/Software/sheet_music_generator/reports/accompaniment/20261017_right_hand_ranges/report.md)、[实际证据及最终测试数](E:/Project/Software/sheet_music_generator/reports/accompaniment/20261017_right_hand_ranges/verification.json)、[40条范围](E:/Project/Software/sheet_music_generator/reports/accompaniment/20261017_right_hand_ranges/requirements_acceptance.md)。15项主浏览器、9项同名配置／保存快照、五曲新范围MIDI／XML／TAB及音频窗口、雨天三版完整成品通过；1497正常文件保持。整曲听审及真人试弹未代签，新音乐仍needs_review。

使用[本机选择页面](http://127.0.0.1:8766/)，旧页面刷新；关闭后双击[启动右手选择.cmd](E:/Project/Software/sheet_music_generator/启动右手选择.cmd)。填区间、点击行编辑、命名保存，下方出现完整曲谱和原唱合播。保留名称再次保存更新本套配置并另建曲谱，改名另存另一套。默认仍不选择。器乐、停顿、短小节、弱起及跨界旧延音保留并明确列出编号；重叠不静默覆盖。其它拍号／拍弦闷音／三连音未开放，The Moment继续暂停。

用户已确认：“空”是不拨／空扫、前音自然延续，另选消音休止。扫弦例4/4第1拍下八分＋空八分，第4拍下八分＋下十六分＋上十六分，第2／3拍按无新起音理解；PPQ480起音0、1440、1680、1800。动作占时与各弦余音分开，不再重复问这两项。

先读AGENTS.md、todo.md、progress.md、MUSIC_REQUIREMENTS.md；协作约束以用户最新提供的实时记录和中文输出要求为准。当前40条音乐要求继续适用。

当前显示实现：Editor.score_links提供初始默认谱；Editor.preview沿原编译器生成实际音乐，新增guitar_pattern_live_score.render_live_score按原阅读分行与真实小节输出全部SVG行，通过score_html返回。前端paintVisibleScore更新原default-score容器中的主谱，showDefault缓存原行用于撤销，pointDefault按当前真实小节定位。局部音频与完整当前谱使用同一编译快照；最新请求序号防串，缓存原子写入。默认源文件不写回。主播放器／visible-status在主谱旁，局部放大在details。新测试test_guitar_pattern_live_score.py直接比较完整可见动作与编译动作，不能只测隐藏局部有变化。

初始化与清空仍默认，来源校验及完整保存硬验收继续；即时试听2–4小节，保存后完整音频／谱页在同页出现。默认8766与上次目录按原启动器接续，正常谱、缓存和全部旧配置／版本保留。

## 当前正常入口及本轮结果

[正常曲谱库](E:/Project/Software/sheet_music_generator/results/accompaniment/index.html)。三首首次发布到正常入口：

|歌曲|正常版本|本次发布范围|
|---|---|---|
| 多远都要在一起 | [多远都要在一起_v1_认可音乐与自动流程确认](E:/Project/Software/sheet_music_generator/results/accompaniment/多远都要在一起_v1_认可音乐与自动流程确认/index.html) | 简谱＋吉他＋钢琴 |
| 勇敢的心 | [勇敢的心_v1_认可音乐与自动流程确认](E:/Project/Software/sheet_music_generator/results/accompaniment/勇敢的心_v1_认可音乐与自动流程确认/index.html) | 简谱＋吉他＋钢琴 |
| 南方姑娘 | [南方姑娘_v1_认可音乐与自动流程确认](E:/Project/Software/sheet_music_generator/results/accompaniment/南方姑娘_v1_认可音乐与自动流程确认/index.html) | 简谱＋吉他＋钢琴 |

只复制上轮严格验证的精确候选，未调用识别、编配、导谱或音频合成；三份project.json及555份非HTML文件与候选逐字节相同。HTML只改确认状态和总览。原六首当前入口、历史链接及三首所有旧隔离稿保留；除正常索引外8062份既有受保护文件不变。

本轮新增通用发布证明v2，明确授权简谱＋吉他＋钢琴；v1仍只支持简谱＋吉他，不能顺带发布钢琴。三项v2逐文件绑定认可成品，重读实际吉他产物、钢琴MIDI与可演奏性。1421项测试、13页27播放器及最终正常索引通过。旧《极美》《渴》的v1范围实际复核通过，钢琴保持原入口。

原工程的needs_review等历史备注逐字节保留，正常副本旁publication.json绑定本轮用户发布授权。用户授权的是发布当前精确成品，不代表新增逐字听审；《勇敢的心》原4个字符、《南方姑娘》尾行2个“啦”等历史备注不抹除，也不自动扩成下一轮改词任务。后续换右手后的新音乐仍先隔离验收，不能继承原发布资格。

[本轮发布与文档整理报告](E:/Project/Software/sheet_music_generator/reports/accompaniment/20261017_three_songs_publication_handoff/report.md)；[本轮用户授权与精确成品绑定](E:/Project/Software/sheet_music_generator/reports/accompaniment/20261017_three_songs_publication_handoff/approval.json)；[精确发布路径及检查记录](E:/Project/Software/sheet_music_generator/reports/accompaniment/20261017_three_songs_publication_handoff/publication.json)。

## 已完成的4/4功能与后续边界

当前4/4已支持29型、统一四分／八分／十六分、逐格时值及多条小节闭区间。原全局／单段计划格式仍兼容；新计划为version:1、ranges:[{id,start_measure,end_measure,choice}]，起止是谱面编号，弱起偏移只转换一次。区间不与旧default／sections混用，重叠明确失败。范围循环锚定指定首小节，跨选区原延音传播保护，末尾动作占时不越过配置边界。

新增tools/guitar_pattern_ranges.py、guitar_pattern_configurations.py、guitar_pattern_ranges_ui.py、guitar_pattern_ranges_editor.js／css及tests/test_guitar_pattern_ranges.py；旧页面／脚本保留，统一编译和服务注释保留旧代码。当前配置及完整另存继续位于test_outputs/accompaniment_runs/20261017_right_hand_editor；configurations按来源ID与SHA绑定，saved每次生成新目录，并附configuration.json。默认8766服务成功启动后把相对目录存入test_outputs/accompaniment_runs/right_hand_editor_session.json，原启动器不传目录时找回该目录；其它测试端口不更改记忆。不要删除既有saved、features、来源缓存或把旧出版资格迁移给新版本。

正常CLI及修订／首次阶段仍用--right-hand-plan，共用统一范围核心；本轮新范围完整导出实际从网页→revise_selection→export_revision执行，其它CLI未逐一重跑整曲。未选原样交付、已选版本不传计划保持音乐的旧证明继续保留。其它历史实现和首阶段完整跨曲证据见20261017_right_hand_selection_implementation报告。

原始旧库诊断在[inspection.json](E:/Project/Software/sheet_music_generator/reports/accompaniment/20261017_right_hand_choice_design/inspection.json)，只描述旧直接调用路线。新显式型使用独立动作编译／实际重建验收，不放宽旧均匀单音规则。扫弦的逻辑拍位、受限发声投影、实际MIDI／音频、SVG可见箭头及XML动作分别核对，复用签名已纳入手势。用户已确认的语义不再询问。

新模块：guitar_pattern_selection.py统一编译；guitar_pattern_performance.py负责方向发声和纯记谱释放视图；revise_guitar_selection.py执行完整另存；guitar_pattern_preview.py服务；guitar_pattern_editor.js／css及guitar_pattern_selection_ui.py页面；guitar_pattern_preservation.py原样交付。细节、实际CLI命令和40条范围见实施报告。

需要保留的实现决定：换夹处只搜索新型的必要局部配音，不截原器乐／延音；受保护旧余音在拍格间结束时只作独立记谱投影，工程和实际声音不改；未选原样交付不迁移原目录发布授权，也不冒充最新音乐规则重新通过。旧显式重排的印刷／极短音守卫保持，不能因本轮新增保留入口放宽。

1. 未显式选择时沿用当前默认和已认可音乐；普通旧工程重导不换型。明确换型才修改指定演唱段伴奏，另存版本。
2. 已有分解／合拨／扫弦、时值、收音和范围选择；全局及单段覆盖已接通，复杂相似段联动后续完善。固定1–6弦和B角色区分；其它拍号待整链验证后开放。
3. 段内保持一种主型，根音在4／5／6弦变化不算换型；相似乐句优先共用相同选择。保留真实休止、过门、弱起、短小节、器乐衔接和跨界延音。
4. 不整曲重识别人声、拍轴、音高、和弦；钢琴及前奏／间奏／尾奏保持。尽量沿用原左手配音，必要的局部配音调整另存并逐音比较，不能以换右手为由重做整首。
5. 扫弦必须表达上下方向、实际发声弦组、空扫／延续与重音；同刻合拨、扫弦及逐弦分解不能混为一谈。扫弦动作细节不能制造谱面32／64分或破坏持续按弦。
6. 自动贴近原曲与用户主动选择改编型须分别说明，不能把用户选择的扫弦说成从原曲识别出来。保持十六分、和弦密度、12品、稳定右手和完整乐句／时长复用检查，不放宽门槛。
7. 先证明“不选则旧版不变”和“明确选型实际生效”，再验证不同分解、扫弦方向、重复段一致、完整播放、实际手指可行；现有正确曲谱和正常入口不自动替换。

## 已有代码：不要从零重写或只把参数挂上

|模块|当前实际作用／下一轮应注意|
|---|---|
|tools/data/guitar_right_hand_patterns.json|已有24种模板，含分解、交替低音、合拨、扫弦／混合及少量3/4、6/8。它是旧库，不代表24种都已通过当前稳定段落链或可被用户选择。|
|tools/guitar_right_hand_patterns.py|旧库加载、选型、弦组映射与D／U等演奏事件；可参考，不能绕过最新保护及验收直接套旧路线。|
|tools/guitar_section_patterns.py|旧默认仍3种简单型；显式新型转assess_selection独立实际重建验收，记忆表显示真实选择。|
|tools/revise_guitar_patterns.py|新增right_hand_plan参数，在旧inherited短路前进入统一显式选型；普通旧默认保留。|
|tools/guitar_pattern_grid.py|旧默认格点／均匀判据保持；显式新型由guitar_pattern_selection单独编译和验收。|
|tools/first_generation_delivery.py|实际首次末阶段及恢复CLI已传递right_hand_plan；多远A14三类完整输出实测通过。|
|tools/generate_accompaniment.py|正常CLI已接--right-hand-plan，显式编辑先于旧保护短路；当前正常工程无任何修改请求时逐文件另存。|
|tools/accompaniment_export.py、guitar_readability_acceptance.py|实际TAB／指型／XML／MIDI／试听及共用硬验收，必须验证选择后的产物。|
|tools/guitar_variable_repeat.py|相似段读法、完整乐句与实际时长；换型后重新核对共用条件，不能直接丢反复，也不能复制失效通过标记。|

库里有6/8模板不等于完整6/8首发流程已经支持。《The Moment》按用户决定先跳过，不能借本轮选型任务擅自恢复生成。

## 当前正常生成与缓存保护

上轮已经把自动选拍、局部分组、覆盖、局部词音及配音保护接到真实首次入口；三首均无旧拍轴答案或单独词音参数实跑通过。南方仅输入新产出的共享分析再次生成也通过。源音高、原和声不整曲重算。

|文件|作用与必须保留的边界|
|---|---|
|first_generation_analysis_bundle.py|共享分析旁analysis_bundle.json自动登记必需词音／认可伴随音来源，缺文件、改文件、整张清单丢失都停止；不按歌名搜历史。旧缓存首次迁移用通用package另存，不能覆盖原分析。|
|first_generation_word_cache.py、first_generation_words.py|旧v1／v2语义不改；新类型分别严格复核旧、新拍轴，再比较完整音乐，重放原音素／PCM；工作目录变化不能被当作词音变化，也不能直接忽略全部SHA。|
|guitar_companion_register.py|只保护同源认可伴随音区。沿来源链取器乐重提取之前的初次快照，不能拿重提取后可能复用的编号硬锁初次请求。旋律整句、弦位及完整持续按弦仍实际求解。|
|source_clock_content.py、first_generation_content.py、first_generation_source.py|拍单位／首拍／活动覆盖分别验证，原曲证据不足就停止，不强行通过。|
|scoped_music_publication.py|当前v1／v2分别验证两项／三项明确发布范围，冻结工程不为发布清除历史备注。|

精确分析包、原始证据、正常CLI命令、输出及代码指纹见 [上轮真实生成清单](E:/Project/Software/sheet_music_generator/reports/accompaniment/20261017_automatic_words_and_companion_register/run_manifest.json)、[通用修复报告](E:/Project/Software/sheet_music_generator/reports/accompaniment/20261017_automatic_words_and_companion_register/report.md)。这些目录及其父工程、原曲、分轨、音高／和弦缓存、源账本均是有效依赖，不是可以删除的临时文件。历史任务的workflow/finalize等脚本可能重写文档，不能盲目重跑。

## 音乐保护重点与回归

- 《极美》《渴》现在是已确认的慢拍二合一及JB1–JB3／KB1局部小节；JB2已确认修正，不重开旧问题。复用按完整乐句、实际时长、回跳后连续演奏和阅读负担，不机械卡8小节。《极美》钢琴未随慢拍简谱／吉他更新，《渴》钢琴仍暂缓，三首新发布不扩大它们的授权范围。
- 《遇见》两遍“号”和第一遍“牌”已修；“右”“看”按用户决定保留。《极美》开头误取泛音已排除，第二遍“我们忘了”及完整“你”长音等已认可词音不能再裁短，尾奏用户确认无问题。
- 《我不难过》第二遍“充满我生活”的“我”接“满”尾音短促下滑；末句“我”轻声带过，稳定音已是“向”。不再问是否唱出，不另猜固定音高；吉他和已同步钢琴继续保护。
- 《黑夜中Live》认可的拍轴、首拍、完整延音、器乐把位和稳定右手保持；低品无解不得删音／缩延音或放宽到20品。原4处字音备注不自动修。
- 吉他0–4品优先，必要5–12，硬上限12（报告区分相对夹位与物理品位）；最短十六分；和弦通常1–2／小节、每拍最多一个。段内主型稳定，真实休止保持。器乐黑点是旋律突出，不是断奏。
- 相似主副歌优先共用和弦／左手／右手；换型需重新验实际共用和长段路线，声音和MIDI始终完整原曲顺序。

新功能默认不变测试以正常9首精确工程为保护基准；重点原曲隔离回归仍包括雨天、遇见、渴、无限大、极美。黑夜中、日落大道、我记得的最新额外基准路径见 [已有九曲来源清单](E:/Project/Software/sheet_music_generator/reports/accompaniment/20261016_first_generation_meter_bridge/protected_reexports.json)，其中《我不难过》最终基准应优先使用正常v3，避免用旧钢琴草稿。旧成果保护、实际新型产物和原曲音乐验证分开报告，不以旧文件未改冒充新编配已通过。

## 环境与记录

工作区E:/Project/Software/sheet_music_generator；PowerShell；Python使用.venv-gpu/Scripts/python.exe，常用-B -X utf8。本机GPU／模型证据见reports/environment.md和对应任务报告，不重新假定模型尚未安装。沙箱unittest临时目录需放工作区TEMP／TMP；本轮完整测试命令及环境在报告workflow.py。

重要冻结备份继续保留：history-version/verision3-20261014-temporary-right（目录拼写沿用户原名）、history-version/version4-20261016-temporary-right，以及早期人声中英版本；不要当当前程序入口或清理对象。2026-10-14被否决的整曲音乐重算保持停用。

后续文档职责：todo保存稳定目标、当前任务与唯一上一步／下一步；progress每轮合并成一条结果／关键决定／待办摘要，细日志链接reports；HANDOFF只更新当前起点，禁止再次前插历轮全文。

## 完整归档与新对话开场

[完整旧日志及标题目录](E:/Project/Software/sheet_music_generator/reports/handoff/20261017_right_hand_choice_handoff/history_index.md)；[本轮整理前四份完整文档](E:/Project/Software/sheet_music_generator/reports/handoff/20261017_right_hand_choice_handoff/original)；[更早完整历史](E:/Project/Software/sheet_music_generator/reports/handoff/20261012_document_cleanup/original)。

可直接在新对话说明：

> 请先读AGENTS.md、todo.md、progress.md、HANDOFF.md和MUSIC_REQUIREMENTS.md。4/4可选右手、多区间命名配置和保存后网页内完整谱／整曲试听已完成，先看20261017_right_hand_ranges报告及实际证据；原曲谱和缓存保持，空位语义已确认。按用户实际听感与使用反馈接续，未选沿用原奏，新改编不自动替换正常入口；其它拍号、拍弦闷音等后续再推进。
