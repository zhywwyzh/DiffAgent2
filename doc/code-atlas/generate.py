#!/usr/bin/env python3
"""仅生成离线源码阅读页面；不导入、执行或验收被说明系统。"""
from __future__ import annotations

import hashlib
import html
import json
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
escape = html.escape


def redact(text):
    """保留行数，遮盖机器身份、网络地址与凭据形态。"""
    text = re.sub(r"/(?:home|Users)/[^\s/\"'<>]+", "/<本地主目录>", text)
    text = re.sub(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", "<网络地址>", text)
    text = re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "<邮箱已省略>", text)
    text = re.sub(r"(?i)(https?://)[^\s/@]+:[^\s/@]+@", r"\1<凭据已省略>@", text)
    text = re.sub(r"\b(?:gh[pousr]_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]+|sk-[A-Za-z0-9_-]{20,})", "<凭据已省略>", text)
    text = re.sub(r"(?i)((?:password|api_key|secret|access_token)\s*[=:]\s*)[\"'][^\"']+[\"']", r'\1"<字面值已省略>"', text)
    return text


def rich(text):
    text = escape(text)
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
    return re.sub(r"\[([^\]]+)\]\(#([a-z0-9-]+)\)", r'<a href="#\2">\1</a>', text)


def navigation_group(title, links, number, opened=False):
    return (f'<details class="nav-group"{" open" if opened else ""}>'
            f'<summary><span class="nav-group-number">{number}</span>{escape(title)}'
            f'<span class="nav-count">{len(links)}</span></summary>'
            '<div class="nav-children">' + ''.join(links) + '</div></details>')


def homepage(data):
    figure = (HERE / 'figures/runtime-overview.svg').read_text(encoding='utf-8').replace('href="../index.html#', 'href="#')
    groups = data['navigation']
    paths = ''.join(
        f'<a class="route-card" href="#group-{g["id"]}"><span class="route-number">{i:02}</span>'
        f'<strong>{escape(g["title"])}</strong><p>{escape(g["description"])}</p>'
        f'<span class="route-meta">{len(g["sections"])} 个章节 <span aria-hidden="true">↗</span></span></a>'
        for i, g in enumerate(groups, 1))
    tasks = [
        ('01', 'journey', '基础飞行', '从一次向前平移开始', '意图 → RPC → 执行 → 结果'),
        ('02', 'vla', 'VLA 目标导航', '找到目标，再接地与执行', '观测 → 有界重扫 → 航点'),
        ('03', 'tracking', 'Tracking 持续跟随', '从目标播种进入连续跟踪', '目标种子 → 持续观测与规划'),
    ]
    task_cards = ''.join(
        f'<a class="task-card" href="#{target}"><span class="task-index">任务 / {number}</span>'
        f'<strong>{escape(title)} <span aria-hidden="true">↗</span></strong>'
        f'<p>{escape(desc)}</p><small>{escape(chain)}</small></a>'
        for number, target, title, desc, chain in tasks)
    return f'''<section class="hero" id="atlas-home" aria-labelledby="atlas-title">
<div class="hero-heading"><div><div class="eyebrow">DIFFAGENT2 / 新版源码运行图谱</div>
<h1 id="atlas-title">看见系统全貌，<br>沿源码走完一次执行。</h1></div>
<div class="hero-intro"><p>从站端的一句指令，到机端的运动与反馈。按任务进入，按职责展开，每个关键环节都能回到源码。</p>
<div class="hero-actions"><a class="primary" href="#reading-paths">选择阅读路线 ↓</a><a href="#overview">查看系统总览 ↗</a></div></div></div>
<figure class="hero-figure"><div class="hero-figure-scroll" tabindex="0" role="region" aria-label="系统头图，可横向滚动">{figure}</div>
<figcaption><span class="figure-key"><i></i>指令下行 <i class="return-key"></i>观测与结果回传</span><span>逻辑职责概览 · 点击模块进入章节</span></figcaption></figure>
<div class="hero-meta"><span><b>{len(data['sections']):02}</b> 个源码章节</span><span><b>{len(data['sources'])}</b> 组源码摘录</span><span>工作区快照 · 离线可读</span></div>
</section><section class="home-section" aria-labelledby="task-routes-title"><div class="home-section-heading"><div><div class="eyebrow">从一个具体任务开始</div><h2 id="task-routes-title">你想理解哪一次执行？</h2></div><a href="#skills">查看工具分工 ↗</a></div><div class="task-cards">{task_cards}</div></section>
<section class="home-section" id="reading-paths" aria-labelledby="reading-paths-title"><div class="home-section-heading"><div><div class="eyebrow">六条阅读路线</div><h2 id="reading-paths-title">把系统拆开，逐层读懂。</h2></div><span>侧栏分组与正文顺序一致</span></div><div class="route-grid">{paths}</div></section>'''


def shell(title, body, nav, stamp, source=False):
    css_version = hashlib.sha256((HERE / 'atlas.css').read_bytes()).hexdigest()[:16]
    js_version = hashlib.sha256((HERE / 'atlas.js').read_bytes()).hexdigest()[:16]
    return f'''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="description" content="基于当前工作区源码的 DiffAgent2 新版运行图谱：启动、站端、RPC、技能、规划、仿真与反馈。">
<title>{escape(title)} · DiffAgent2 新版</title><link rel="stylesheet" href="atlas.css?v={css_version}"><script defer src="atlas.js?v={js_version}"></script></head>
<body><a class="skip" href="#main">跳到正文</a><div class="reading-progress" aria-hidden="true"></div>
<header class="topbar"><a class="brand" href="index.html">D2<span>源码运行图谱</span></a><div class="toplinks"><a href="index.html#overview">运行总览</a><a href="index.html#source-index">证据索引</a><a href="sources.html">源码摘录</a><button id="print" type="button">打印 / PDF</button><button id="menu" type="button" aria-expanded="false" aria-controls="sidebar">目录</button></div></header>
<aside id="sidebar"><div class="sidebar-label">{'源码证据' if source else '阅读路线'}</div><label class="search-label" for="search">搜索{'路径或代码' if source else '章节、工具或话题'}</label><input id="search" type="search" placeholder="搜索内容…  /" autocomplete="off"><div id="search-status" aria-live="polite"></div><nav aria-label="章节目录">{nav}</nav><div class="sidebar-note">工作区源码静态解读<br>未运行测试或验收<br>生成于 {escape(stamp)}</div></aside>
<main id="main">{body}<footer>DiffAgent2 新版 · 本地源码阅读产物 · 不代表运行验收结果。<a href="#main">回到顶部 ↑</a></footer></main><button id="top" type="button" aria-label="回到顶部">↑</button></body></html>'''


def diagram(data, identity):
    nodes = data['nodes']
    width = 960
    height = (max(n['row'] for n in nodes) + 1) * 126 + 30
    by_id = {n['id']: n for n in nodes}
    out = [f'<figure class="diagram"><figcaption>{escape(data["title"])}<span>点击节点跳转章节或对应源码 · 横向滚动查看完整图</span></figcaption>',
           f'<div class="diagram-scroll" tabindex="0" role="region" aria-label="{escape(data["title"])}"><svg viewBox="0 0 {width} {height}" role="img" aria-labelledby="{identity}-title {identity}-desc"><title id="{identity}-title">{escape(data["title"])}</title><desc id="{identity}-desc">{escape(data.get("description", "运行流程，详见下方文字链路。"))}</desc><defs><marker id="{identity}-arrow" markerWidth="8" markerHeight="8" refX="7" refY="3.5" orient="auto"><path d="M0,0 L7,3.5 L0,7" fill="currentColor"/></marker></defs>']
    for edge in data['edges']:
        a, b = by_id[edge[0]], by_id[edge[1]]
        ax, ay = 20 + a['col'] * 320, 18 + a['row'] * 126
        bx, by = 20 + b['col'] * 320, 18 + b['row'] * 126
        if a['row'] == b['row']:
            if b['col'] > a['col']:
                x1, x2 = ax + 268, bx
            else:
                x1, x2 = ax, bx + 268
            y1 = y2 = ay + 40
            path = f'M{x1},{y1} L{x2},{y2}'
            tx, ty = (x1+x2)/2, y1-9
        else:
            x1, x2 = ax+134, bx+134
            y1, y2 = (ay+80, by) if by > ay else (ay, by+80)
            mid = (y1+y2)/2
            path = f'M{x1},{y1} L{x1},{mid} L{x2},{mid} L{x2},{y2}'
            tx, ty = (x1+x2)/2+8, mid-5
        label = edge[2] if len(edge)>2 else ''
        if len(edge) > 3:
            route = edge[3]
            path = ' '.join(f'{"M" if i == 0 else "L"}{x},{y}' for i, (x, y) in enumerate(route['points']))
            tx, ty = route['label_pos']
        out.append(f'<path class="edge" d="{path}" marker-end="url(#{identity}-arrow)"/>')
        if label:
            label_width = sum(11 if unicodedata.east_asian_width(c) in ('W', 'F') else 6 for c in label) + 10
            out.append(f'<rect class="edge-label-bg" fill="#fff" x="{tx-label_width/2}" y="{ty-12}" width="{label_width}" height="17" rx="3"/><text class="edge-label" x="{tx}" y="{ty}" text-anchor="middle">{escape(label)}</text>')
    for n in nodes:
        x, y = 20+n['col']*320, 18+n['row']*126
        href = n.get('href', '#' + n['target'])
        out.append(f'<a href="{escape(href)}" aria-label="跳转：{escape(n["label"])}"><rect class="node {escape(n.get("tone", ""))}" x="{x}" y="{y}" width="268" height="80" rx="9"/><text class="node-title" x="{x+16}" y="{y+31}">{escape(n["label"])}</text><text class="node-detail" x="{x+16}" y="{y+57}">{escape(n.get("detail", ""))}</text></a>')
    out.append('</svg></div>')
    out.append('<details class="text-flow"><summary>展开流程文字版</summary><ul>')
    for e in data['edges']:
        a,b=by_id[e[0]],by_id[e[1]]
        ahref, bhref = a.get('href', '#' + a['target']), b.get('href', '#' + b['target'])
        out.append(f'<li><a href="{escape(ahref)}">{escape(a["label"])}</a> → {escape(e[2] if len(e)>2 else "")} → <a href="{escape(bhref)}">{escape(b["label"])}</a></li>')
    out.append('</ul></details></figure>')
    return ''.join(out)


def main():
    data = json.loads((HERE / 'content.json').read_text())
    stamp = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
    sources = {}
    for key, ref in data['sources'].items():
        path = (ROOT / ref['path']).resolve()
        if not path.is_relative_to(ROOT) or any(p in ('test','tests','.git','.local.env') for p in Path(ref['path']).parts):
            raise ValueError('证据路径须位于仓库代码内：' + ref['path'])
        raw = path.read_bytes()
        lines = raw.decode('utf-8').splitlines()
        start = ref.get('line', 1)
        if 'find' in ref:
            found = [i+1 for i, line in enumerate(lines) if ref['find'] in line]
            if not found:
                raise ValueError('源码定位符已变化，需要重新阅读：' + key)
            start = found[ref.get('occurrence', 0)]
        end = min(len(lines), start + ref.get('count', 35) - 1)
        sources[key] = {**ref, 'start':start, 'end':end, 'hash':hashlib.sha256(raw).hexdigest(),
                        'lines':[(i+1,redact(lines[i])) for i in range(start-1,end)]}

    def citations(keys):
        if not keys: return ''
        return '<div class="citations"><span>源码依据</span>' + ''.join(
            f'<a href="sources.html#{k}-L{sources[k]["start"]}">{escape(sources[k]["label"])} <small>L{sources[k]["start"]}–{sources[k]["end"]} ↗</small></a>' for k in keys) + '</div>'

    sections_by_id = {s['id']: s for s in data['sections']}
    groups_by_section = {key: group for group in data['navigation'] for key in group['sections']}
    nav = '<a class="nav-home" href="#atlas-home"><span>⌂</span>阅读首页</a>'
    for number, group in enumerate(data['navigation'], 1):
        links = [f'<a href="#{key}" title="{escape(sections_by_id[key]["title"])}">{escape(sections_by_id[key]["nav_title"])}</a>' for key in group['sections']]
        if group['id'] == 'reference':
            links.append('<a href="#source-index">源码证据索引</a>')
        nav += navigation_group(group['title'], links, f'{number:02}', opened=number <= 2)
    body = [homepage(data)]
    backlinks = {k:[] for k in sources}
    for i,s in enumerate(data['sections'],1):
        group = groups_by_section[s['id']]
        if s['id'] == group['sections'][0]:
            number = data['navigation'].index(group) + 1
            body.append(f'<header class="group-divider" id="group-{group["id"]}" data-section-ids="{escape(" ".join(group["sections"]))}"><span class="group-divider-number">{number:02}</span><div><div class="eyebrow">阅读分组</div><h2>{escape(group["title"])}</h2><p>{escape(group["description"])}</p></div><a href="#reading-paths">全部路线 ↑</a></header>')
        body.append(f'<section class="chapter" id="{s["id"]}" data-searchable><div class="section-kicker">{i:02} / {escape(s["group"])}</div><h2>{escape(s["title"])}<a class="anchor" href="#{s["id"]}" aria-label="本章节链接">#</a></h2><p class="section-lead">{rich(s["lead"])}</p>')
        for j,b in enumerate(s['blocks']):
            kind=b['type']
            if kind=='p': body.append('<p>'+rich(b['text'])+'</p>')
            elif kind=='h3': body.append('<h3>'+rich(b['text'])+'</h3>')
            elif kind in ('ul','ol'):
                body.append(f'<{kind}>'+''.join('<li>'+rich(t)+'</li>' for t in b['items'])+f'</{kind}>')
            elif kind=='callout': body.append(f'<aside class="callout"><strong>{escape(b["title"])}</strong><p>{rich(b["text"])}</p></aside>')
            elif kind=='table':
                body.append('<div class="table-wrap" tabindex="0"><table><caption>'+escape(b['title'])+'</caption><thead><tr>'+''.join('<th scope="col">'+escape(c)+'</th>' for c in b['headers'])+'</tr></thead><tbody>')
                body.extend('<tr>'+''.join('<td>'+rich(c)+'</td>' for c in row)+'</tr>' for row in b['rows'])
                body.append('</tbody></table></div>')
            elif kind=='code': body.append('<figure class="code-sample"><figcaption>'+escape(b['title'])+'</figcaption><pre><code>'+escape(b['text'])+'</code></pre></figure>')
            elif kind=='diagram': body.append(diagram(b, s['id']+'-'+str(j)))
            else: raise ValueError('未知内容块：'+kind)
            refs=b.get('refs',[])
            body.append(citations(refs))
            for key in refs:
                if s['id'] not in backlinks[key]: backlinks[key].append(s['id'])
        related=s.get('related',[])
        if related:
            names={t['id']:t['title'] for t in data['sections']}
            body.append('<div class="related"><span>接着阅读</span>'+''.join(f'<a href="#{k}">{escape(names[k])} →</a>' for k in related)+'</div>')
        body.append('</section>')
    body.append('<section class="chapter" id="source-index" data-searchable><div class="section-kicker">附录 / 可追溯阅读</div><h2>源码证据索引</h2><p>以下摘录来自生成时的工作区内容。行号由生成器按定位符读取；SHA-256 标识完整文件字节。摘录保留原行号，机器身份、地址及凭据形态被遮盖。只读快照不会随运行代码自动变化。</p><div class="source-catalog">')
    body.extend(f'<a href="sources.html#{k}"><strong>{escape(r["label"])}</strong><code>{escape(r["path"])}</code><span>L{r["start"]}–{r["end"]} · SHA-256 {r["hash"][:12]}</span></a>' for k,r in sources.items())
    body.append('</div><h3>如何维护这份图谱</h3><p>解释内容在 <code>content.json</code>，生成器为 <code>generate.py</code>。在仓库根执行 <code>python3 doc/code-atlas/generate.py</code> 只重建静态页面，不启动被说明系统。修改源码后须先重新阅读并修订说明，再生成；摘要更新并不证明文字仍然正确。</p></section>')
    (HERE/'index.html').write_text(shell('完整运行图谱',''.join(body),nav,stamp),encoding='utf-8')
    source_groups = {}
    for k, r in sources.items():
        module = r['path'].split('/')[0]
        title = {'station_projects':'站端 · L4', 'drone_projects':'机端 · L3', 'simulation_projects':'仿真与控制 · L2', 'deployment':'工作区部署'}.get(module, '仓库入口与部署')
        source_groups.setdefault(title, []).append(f'<a href="#{k}">{escape(r["label"])}</a>')
    source_nav = ''.join(navigation_group(title, links, f'{i:02}', opened=i == 1) for i, (title, links) in enumerate(source_groups.items(), 1))
    out=['<div class="source-hero"><div class="eyebrow">证据阅读器 / 工作区快照</div><h1>源码摘录</h1><p>摘录仅用于解释与定位，不是可执行副本。原代码中的注释仅供上下文参考；运行说明以函数体、注册与实际接线为据。</p><a href="index.html">← 返回完整运行图谱</a></div>']
    names={s['id']:s['title'] for s in data['sections']}
    for key,r in sources.items():
        out.append(f'<section class="source-section" id="{key}" data-searchable><h2>{escape(r["label"])}</h2><p class="source-path">{escape(r["path"])}</p><div class="source-meta">L{r["start"]}–{r["end"]} · SHA-256 <code>{r["hash"]}</code></div><div class="related"><span>说明此处代码的章节</span>'+''.join(f'<a href="index.html#{s}">{escape(names[s])} →</a>' for s in backlinks[key])+'</div><pre class="source-code"><code>')
        for number,line in r['lines']:
            out.append(f'<span class="source-line" id="{key}-L{number}"><a class="line-number" href="#{key}-L{number}" aria-label="第 {number} 行">{number}</a><span>{escape(line)}</span></span>')
        out.append('</code></pre></section>')
    (HERE/'sources.html').write_text(shell('源码证据',''.join(out),source_nav,stamp,True),encoding='utf-8')
    print(f'已生成离线阅读页面：{len(data["sections"])} 个章节，{len(sources)} 组源码摘录。未运行测试或验收。')


if __name__ == '__main__':
    main()
