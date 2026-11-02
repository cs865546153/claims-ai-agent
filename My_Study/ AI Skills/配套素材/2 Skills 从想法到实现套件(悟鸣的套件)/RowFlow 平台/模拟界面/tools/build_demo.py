#!/usr/bin/env python3
"""Embed authoritative docs, example data, interpreter and UI in one offline HTML."""
from pathlib import Path
import json
import re

ROOT = Path(__file__).resolve().parents[1]
summaries = {
 '00': '阅读导航、使用路径与规范边界', '01': '脚本入口、参数与 Groovy 子集',
 '02': 'HTTP / RPC 接入、扫描与查询、响应路径', '03': '只读 Map、空值与金额转换',
 '04': '筛选、映射、展开、排序与截取', '05': '多源关联、逐行查询、分组与统计',
 '06': '时限、重试、降级与错误码', '07': '核心概念、执行阶段与一致性',
 '08': '授权、凭据、幂等与性能优化', '09': '常见问题、导入与排障建议',
 '10': '订单与用户数据、接口契约与验收结果', '11': '6 个完整脚本及预期输出',
 '12': 'AI 提示词、生成任务与边界测试', '14': '界面操作、导入导出与课堂讲解',
 '15': '导入格式、注释、样例与解释器边界', '16': '库存补货新场景与 AI 提示词',
}
docs = []
for file in [ROOT / 'README.md'] + sorted(ROOT.glob('[0-1][0-9]-*.md')):
    doc_id = '00' if file.name == 'README.md' else file.name[:2]
    if doc_id not in summaries:
        continue
    text = file.read_text()
    title = text.splitlines()[0].removeprefix('# ').replace('语法手册：', '').replace('平台知识：', '')
    if doc_id == '00':
        title = '文档导航与框架约定'
    category = 'syntax' if '01' <= doc_id <= '06' or doc_id == '15' else 'platform' if '07' <= doc_id <= '09' else 'examples'
    docs.append(dict(id=doc_id, file=file.name, title=title, category=category, summary=summaries[doc_id], text=text))
faq = [dict(question=q, answer=a.strip()) for q, a in re.findall(
    r'^## FAQ-\d+：([^\n]+)\n+(.*?)(?=^## FAQ-|\Z)',
    (ROOT / '09-平台知识-常见问题与排障.md').read_text(), re.M | re.S)]
fixtures = [json.loads(s) for s in re.findall(r'^```json\n(.*?)^```\s*$', (ROOT / '10-示例数据与服务契约.md').read_text(), re.M | re.S)]
scripts = [s.strip() + '\n' for s in re.findall(r'^```groovy\n(.*?)^```\s*$', (ROOT / '11-完整脚本示例.md').read_text(), re.M | re.S)]
assert len(scripts) == 6
payload = dict(orders=fixtures[0], users=fixtures[1], docs=docs, faq=faq,
               scripts=dict(city=scripts[2], http=scripts[1], lookup=scripts[3]),
               importExample=(ROOT / 'examples/inventory_replenishment.groovy').read_text())
html_file = ROOT / 'rowflow-demo.html'
html = html_file.read_text()
encoded = json.dumps(payload, ensure_ascii=False, separators=(',', ':')).replace('<', '\\u003c').replace('\u2028', '\\u2028').replace('\u2029', '\\u2029')
html, count = re.subn(r'(<script id="platform-data" type="application/json">).*?(</script>)', lambda m: m[1] + encoded + m[2], html, flags=re.S)
assert count == 1
for script_id, file in [('rowflow-engine', 'lib/rowflow-engine.js'), ('rowflow-app', 'lib/rowflow-app.js'), ('rowflow-import-ui', 'lib/rowflow-import-ui.js')]:
    code = (ROOT / file).read_text()
    assert '</script' not in code.lower(), file
    tag = f'<script id="{script_id}">\n{code}</script>'
    pattern = rf'<script id="{script_id}">.*?</script>'
    if re.search(pattern, html, re.S):
        html = re.sub(pattern, lambda _: tag, html, count=1, flags=re.S)
    elif script_id == 'rowflow-engine':
        html = html.replace('<script id="rowflow-app">', tag + '\n<script id="rowflow-app">', 1)
    else:
        html = html.replace('</body>', tag + '\n</body>', 1)
style = '<style id="rowflow-import-style">\n' + (ROOT / 'lib/rowflow-import.css').read_text() + '</style>'
if '<style id="rowflow-import-style">' in html:
    html = re.sub(r'<style id="rowflow-import-style">.*?</style>', lambda _: style, html, count=1, flags=re.S)
else:
    html = html.replace('</head>', style + '\n</head>', 1)
html_file.write_text(html)
print(f'Built {html_file.name}: {len(docs)} documents, {len(faq)} FAQ; {html_file.stat().st_size:,} bytes; no external runtime dependencies.')
