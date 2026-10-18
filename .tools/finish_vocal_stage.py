# 歌词对齐与真实制谱：新增收尾元数据校正、缓存证据与任务书，音乐产物不变。
from pathlib import Path
import json,hashlib
root=Path.cwd()
load=lambda p:json.loads(Path(p).read_text(encoding='utf-8-sig'))
c=load(root/'reports/current_score.json'); correction=load(root/'reports/score_correction.latest.json'); cache=load(root/'reports/lyrics_cache_report_fix.json')
assert cache['passed'] and all(cache['checks'].values())
assert cache['protected_hashes_before']==cache['protected_hashes_after']
for path,digest in cache['protected_hashes_after'].items(): assert hashlib.sha256(Path(path).read_bytes()).hexdigest()==digest
c['timings']['programmatic_correction_import_seconds']=correction['demonstration_wall_seconds']
c['verification']={'final_artifact_checks':str(root/'reports/final_score_checks.json'),'final_score_semantic_tests':str(root/'reports/score_export_tests.final.json'),'cache_first_report_preservation':str(root/'reports/lyrics_cache_report_fix.json')}
(root/'reports/current_score.json').write_text(json.dumps(c,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
p=root/'reports/real_vocal_draft.md';s=p.read_text(encoding='utf-8');s+='''

## 收尾复核与版本记录

最终字间距修复后制谱11项语义回归再次通过，当前源码/测试SHA另存score_export_tests.final.json。分句缓存命中曾有覆写首次计时报告风险，现改为latest文件保存；独立复制夹具在GPU不可见条件下11/11检查通过，原首次报告及真实候选/计划SHA未变。0.181秒属于CPU缓存检查，不是GPU推理提速。实际GPU执行、后续边缘诊断和当前报告保存代码版本分别留有哈希与旧源码快照，31.300秒只绑定实际旧版本推理，未称当前修改后重新推理。
''';p.write_text(s,encoding='utf-8')
p=root/'reports/first_sample.md';s=p.read_text(encoding='utf-8-sig');s+='''

## 后续阶段入口（2026-10-05）

本报告保留首轮兼容性实测口径。后续已完成用户歌词真实分句对齐与首份82小节草稿，当前产物/警告/计时见[真实制谱阶段报告](real_vocal_draft.md)及[current_score.json](current_score.json)。仍未完成音乐人工校正和GUI编辑器往返，不把后续结果回填为首次模型计时。
''';p.write_text(s,encoding='utf-8-sig')
p=root/'todo.md';s=p.read_text(encoding='utf-8-sig')
import re
s=re.sub(r'(?s)(## 当前任务范围\r?\n).*?(?=\r?\n## 持续约束)',lambda m:m[1]+'\n首曲《遇见》的接缝派生、本地ASR/用户歌词覆盖、真实分句对齐与MusicXML/MIDI/简谱/项目JSON/本地复核报告已实现并实跑；用户提供的237字完整挂谱，82小节草稿等待人工音乐校正。当前唯一产物指针为reports/current_score.json，阶段说明为reports/real_vocal_draft.md。实际独立编辑器GUI往返仍未实测。\n',s)
steps='''## 上一步

已完成run20261005_192901_116最终草稿：237字完整挂谱、82小节、全部原数据SHA/连续f0保留；实际PNG与文件链接核查、最终11项制谱回归、15项校正版回导、16项分句证据及11项缓存报告保护检查通过。当前指针/阶段报告/README已更新，测试修订副本与主草稿分离。

## 下一步

先试听复核69个歌词窗口/边缘标记（含牌、害两处尾音）、14个网格塌缩短音及半音候选，建立一段人工音高/歌词/节奏基线；确认约92.285BPM、Eb调性候选、4/4先验与记谱起点。在真实写谱软件完成导入/试听/另存/回导后，扩展其余六首范围内歌曲，再验证三首压力样本。吉他指弹和网页/小程序留在后续阶段。
'''
s=re.sub(r'(?s)## 上一步\r?\n.*\Z',steps,s);p.write_text(s,encoding='utf-8-sig')
print(json.dumps({'current_run':c['run_id'],'cache_preserves_first_report':True,'correction_seconds':c['timings']['programmatic_correction_import_seconds'],'todo_updated':True},ensure_ascii=False))
