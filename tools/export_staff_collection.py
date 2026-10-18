"""十一首可编辑五线谱：根据成果清单的首选版本批量生成和登记五线谱。"""
# 十一首可编辑五线谱：新增通用集合入口，不包含歌曲名称或固定小节答案。
from __future__ import annotations
import argparse
import copy
from datetime import datetime, timezone
import html
from pathlib import Path
import sys
from urllib.parse import quote
import score_export as score
import staff_export as staff

# 十一首可编辑五线谱：新增集中选择首选版本，保留同曲旧版本，避免重复生成12份冒充11首。
def preferred_rows(manifest):
    rows = {row['id']: row for row in manifest['songs']}
    ids = list(manifest.get('preferred_song_versions', {}).values()) or list(rows)
    if len(set(ids)) != len(ids) or any(identity not in rows for identity in ids):
        raise ValueError('首选歌曲版本存在重复或缺失。')
    return [rows[identity] for identity in ids]

# 十一首可编辑五线谱：新增11首统一五线谱入口，每首都有真实可编辑文件及对应简谱/MIDI。
def collection_html(rows, results_dir):
    body = []
    for row in rows:
        folder = Path(row['folder']).resolve()
        relative = folder.relative_to(results_dir).as_posix()
        link = lambda name: quote(relative + '/' + name, safe='/')
        keys = ' → '.join(str(x[1]).replace(':major', '大调').replace(':minor','小调') for x in row.get('key_segments', []))
        body.append(f'<tr><th scope="row">{html.escape(row["title"])}</th><td>{html.escape(keys)}</td><td>{row["measures"]}</td>'
                    f'<td>{row["staff_export"]["page_count"]}</td><td><a href="{link("staff.html")}">打开五线谱</a></td>'
                    f'<td><a href="{link("staff_score.musicxml")}" download>MusicXML</a> · <a href="{link("staff_score.mxl")}" download>MXL</a></td>'
                    f'<td><a href="{link("jianpu.html")}">简谱</a> · <a href="{link("vocal_draft.mid")}">MIDI</a></td></tr>')
    return '''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>可编辑人声五线谱</title><style>body{margin:0;background:#eef2f6;color:#18314b;font-family:"Microsoft YaHei",sans-serif;line-height:1.7}main{max-width:1320px;margin:30px auto;padding:28px;background:white;border-radius:10px}h1{font-size:27px;margin-top:0}a{color:#205a98}table{width:100%;border-collapse:collapse}th,td{padding:13px 12px;border-bottom:1px solid #dce4ec;text-align:left;white-space:nowrap}thead{background:#f2f6fa}tbody th{font-weight:500}.scroll{overflow:auto}p{color:#52677b}@media(max-width:700px){main{margin:12px;padding:18px}}</style></head><body><main><h1>COUNT首歌曲的可编辑人声五线谱</h1><p>音高、节奏、歌词和转调沿用当前简谱。选择“打开五线谱”阅读；下载MusicXML或MXL后，用写谱软件打开即可修改音符、时值、歌词和排版。</p><p><a href="index.html">返回全部成果</a></p><div class="scroll"><table><thead><tr><th>歌曲</th><th>调号</th><th>小节</th><th>页数</th><th>五线谱</th><th>编辑文件</th><th>对照试听</th></tr></thead><tbody>ROWS</tbody></table></div></main></body></html>'''.replace('COUNT', str(len(rows))).replace('ROWS', '\n'.join(body))

# 十一首可编辑五线谱：新增批量导出后才更新当前清单，原音乐文件按哈希完整保护。
def export_collection(manifest_path, report_dir):
    manifest_path = Path(manifest_path).resolve(); results_dir = manifest_path.parent
    report_dir = Path(report_dir).resolve(); report_dir.mkdir(parents=True, exist_ok=True)
    manifest = score.read_json(manifest_path)
    before = copy.deepcopy(manifest)
    preserved = {}
    for row in manifest['songs']:
        for name, facts in row.get('files', {}).items():
            path = Path(row['folder'])/name
            # 十一首可编辑五线谱：新增再次运行只保护来源及旧简谱，允许更新本工具所属五线谱排版。
            if name.startswith('staff_') or name == 'staff.html':
                continue
            actual = score.sha256(path)
            if actual != facts['sha256']:
                raise ValueError('集合来源文件与清单不一致：' + str(path))
            preserved[str(path)] = actual
    selected = preferred_rows(manifest)
    reports = []
    for row in selected:
        folder = Path(row['folder']).resolve()
        if not folder.is_relative_to(results_dir):
            raise ValueError('首选版本输出目录必须位于成果集合内。')
        result = staff.export_staff_score(folder)
        row['staff_export'] = {'version': staff.VERSION, 'page_count': result['page_count'],
                               'music_semantics_preserved': True, 'verification': str(folder/'staff_validation.json'),
                               'editable_formats': ['MusicXML','MXL'], 'renderer': result['renderer']['version']}
        row.setdefault('artifacts', {}).update({'staff': str(folder/'staff.html'),
                    'staff_musicxml': str(folder/'staff_score.musicxml'), 'staff_mxl': str(folder/'staff_score.mxl')})
        files = [folder/name for name in ('staff.html','staff_score.musicxml','staff_score.mxl','staff_validation.json')]
        files += [folder/'staff_pages'/f'page_{number:03d}.svg' for number in range(1,result['page_count']+1)]
        for path in files:
            row['files'][path.relative_to(folder).as_posix()] = {'sha256': score.sha256(path), 'bytes': path.stat().st_size}
        reports.append({'song_id': row['id'], 'title': row['title'], 'result': result})
        print(row['title'] + '：' + str(result['page_count']) + '页，音乐语义保持', flush=True)
    for path, digest in preserved.items():
        if score.sha256(path) != digest:
            raise ValueError('批量五线谱改变了已交付音乐：' + path)
    entry = results_dir/'staff_index.html'
    entry.write_text(collection_html(selected, results_dir), encoding='utf-8')
    manifest['staff_collection'] = {'task': '十一首可编辑五线谱', 'version': staff.VERSION,
                                  'song_count': len(selected), 'preferred_versions': [r['id'] for r in selected],
                                  'entry': str(entry), 'created_utc': datetime.now(timezone.utc).isoformat(),
                                  'verification': str(report_dir/'collection.json')}
    index = results_dir/'index.html'
    if index.exists():
        original = index.read_text(encoding='utf-8-sig')
        if 'id="staff-collection-nav"' not in original:
            # 十一首可编辑五线谱：新增入口链接，原HTML整页先留存，历史注释不删除。
            (report_dir/'index_before.html').write_text(original, encoding='utf-8')
            head, separator, tail = original.rpartition('<body><main>')
            if not separator:
                raise ValueError('成果入口缺少主体，不能盲目插入链接。')
            nav = '<!-- 十一首可编辑五线谱：新增首选11曲五线谱入口。 --><p id="staff-collection-nav"><a href="staff_index.html">打开十一首可编辑五线谱（MusicXML / MXL）</a></p>'
            index.write_text(head+separator+nav+tail, encoding='utf-8')
    score.save_json(report_dir/'manifest_before.json', before)
    score.save_json(manifest_path, manifest)
    score.save_json(score.ROOT/'reports/current_results.json', manifest)
    score.save_json(report_dir/'delivery_manifest.json', manifest)
    report = {'task': '十一首可编辑五线谱', 'status': 'passed', 'song_count': len(selected),
              'source_files_preserved': len(preserved), 'source_fingerprints': preserved,
              'entry': str(entry), 'songs': reports,
              'external_editor_gui_roundtrip': 'not_tested', 'audio_model_rerun': False}
    score.save_json(report_dir/'collection.json', report)
    return report

# 十一首可编辑五线谱：新增可重复运行命令。
def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest',type=Path,default=score.ROOT/'results/manifest.json')
    parser.add_argument('--report-dir',type=Path,default=score.ROOT/'reports/staff_export')
    args=parser.parse_args()
    report=export_collection(args.manifest,args.report_dir)
    print('完成：'+str(report['song_count'])+'首；入口：'+report['entry'])

if __name__=='__main__':
    main()
