# -*- coding: utf-8 -*-
import json, os, re, html

BASE = r"C:\Users\EDY\Documents\ChatGPT\即梦"
SY = os.path.join(BASE, "_zzdh_sync")
OUT = os.path.join(BASE, "deliverables", "字字动画-提示词样稿")
os.makedirs(OUT, exist_ok=True)

panels = json.load(open(os.path.join(SY, "panels_live.json"), encoding="utf-8"))["panels"]
samples = json.load(open(os.path.join(SY, "dryrun", "samples.json"), encoding="utf-8"))
smap = {s["idx"]: s for s in samples}

def cnum(s):
    d = {"零":0,"一":1,"二":2,"三":3,"四":4,"五":5,"六":6,"七":7,"八":8,"九":9}
    if s.isdigit(): return int(s)
    if s == "十": return 10
    if "十" in s:
        a, b = s.split("十")
        return (d.get(a,1) if a else 1)*10 + (d.get(b,0) if b else 0)
    return d.get(s, 0)

ep_re = re.compile(r"第([一二三四五六七八九十百零\d]+)集")
starts = []
for i, p in enumerate(panels, 1):
    m = ep_re.search(p.get("paperwork") or "")
    if m:
        n = cnum(m.group(1))
        if n and (not starts or n > starts[-1][0]):
            starts.append((n, i))

ep_ranges = []
for j, (n, i) in enumerate(starts):
    end = starts[j+1][1]-1 if j+1 < len(starts) else len(panels)
    ep_ranges.append((n, i, end))

def esc(t): return html.escape(t or "")
def blocks(t): return "".join("<p>"+esc(x)+"</p>" for x in (t or "").split("\n") if x.strip())

# ---- table rows ----
row_html = []
for i in (1,2,3,4,5,6):
    p = panels[i-1]
    s = smap.get(i)
    status = "已生成·只读" if i in (1,3) else ("样稿·待确认" if s else "未写")
    if s: dur = str(s["dur"]) + " 秒"
    elif i == 1: dur = "5 秒"
    elif i == 3: dur = "6 秒"
    else: dur = "-"
    kind = (s or {}).get("kind", "-")
    row_html.append("<tr><td>第%d镜</td><td class='mono'>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>"
                    % (i, esc(p["unique_name"]), status, dur, esc(kind)))

# ---- sample cards ----
cards = []
for s in samples:
    p = panels[s["idx"]-1]
    cards.append("""
<details class="card" open>
  <summary><b>第__IDX__镜</b>　__KIND__　<span class="badge">建议时长 __DUR__ 秒</span><span class="mono">　un=__UN__</span></summary>
  <div class="grid">
    <div class="col">
      <h4>原始文案（不改动）</h4>
      <div class="paper">__PAPER__</div>
      <h4>时长依据</h4>
      <div class="note">__EST__</div>
      <h4>人物 / 场景实体</h4>
      <div class="note">角色：__CHARS__<br>场景：__LOCS__<br>场次：__SCENE__</div>
      <h4>inherit_prompt（继承提示词 · 衔接写入这里）</h4>
      <pre class="inherit">__INHERIT__</pre>
    </div>
    <div class="col">
      <h4>video_prompt（提示词主体 · 将写入分镜）</h4>
      <pre class="vp">__VP__</pre>
    </div>
  </div>
</details>""".replace("__IDX__", str(s["idx"]))
        .replace("__KIND__", esc(s["kind"]))
        .replace("__DUR__", str(s["dur"]))
        .replace("__UN__", esc(s["unique_name"]))
        .replace("__PAPER__", blocks(p.get("paperwork")))
        .replace("__EST__", esc(s["est"]))
        .replace("__CHARS__", esc("、".join(s["chars"])))
        .replace("__LOCS__", esc("、".join(s["locs"])))
        .replace("__SCENE__", esc(s["scene"]))
        .replace("__INHERIT__", esc(s["inherit"]))
        .replace("__VP__", esc(s["video_prompt"])))

# ---- readonly 1 & 3 ----
gen = []
for i in (1, 3):
    p = panels[i-1]
    gen.append("<details class='card readonly'><summary><b>第%d镜</b>　已生成，只读不覆盖<span class='mono'>　un=%s</span></summary>"
               "<div class='paper'>%s</div><pre class='vp'>%s</pre></details>"
               % (i, esc(p["unique_name"]), blocks(p.get("paperwork")), esc(p.get("video_prompt"))))

ep_rows = "".join("<tr><td>第%d集</td><td>%d – %d</td><td>%d</td></tr>" % (n, a, b, b-a+1) for n, a, b in ep_ranges)

# ---- html template (placeholder replace, no % formatting) ----
TPL = """<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<title>字字动画 · 分镜提示词/时长/衔接 样稿（第2、4、6镜）</title>
<style>
:root{--line:#d9d9d9;--bg:#fafafa;--accent:#1a6fb5;--warn:#b45309}
*{box-sizing:border-box}body{font-family:"Microsoft YaHei",system-ui,sans-serif;margin:0;padding:24px;background:var(--bg);color:#222;line-height:1.65}
h1{font-size:20px;margin:0 0 6px}h2{font-size:16px;margin:28px 0 10px;padding-bottom:6px;border-bottom:2px solid var(--line)}
h4{font-size:13px;margin:14px 0 6px;color:#444}
table{border-collapse:collapse;width:100%;background:#fff;font-size:13px}th,td{border:1px solid var(--line);padding:6px 8px;text-align:left}
th{background:#f0f4f8}.mono{font-family:Consolas,monospace;color:#666;font-size:12px}
.badge{background:#e8f2fb;color:var(--accent);border-radius:10px;padding:1px 8px;font-size:12px;margin-left:6px}
.card{background:#fff;border:1px solid var(--line);border-radius:6px;padding:10px 14px;margin:12px 0}
.card.readonly{opacity:.82;border-style:dashed}
summary{cursor:pointer;font-size:14px}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:18px;margin-top:8px}
@media(max-width:1100px){.grid{grid-template-columns:1fr}}
pre{white-space:pre-wrap;word-break:break-word;font-family:Consolas,"Microsoft YaHei",monospace;font-size:12.5px;line-height:1.75;background:#fbfbfb;border:1px solid #eee;border-radius:4px;padding:10px;max-height:520px;overflow:auto}
pre.inherit{background:#f2fbf3;border-color:#cfe9d5}pre.vp{background:#f7fbff;border-color:#d7e6f5}
.paper{font-size:13px;background:#fffdf6;border:1px solid #f0e6cf;border-radius:4px;padding:8px 10px;max-height:180px;overflow:auto}
.paper p{margin:2px 0}.note{font-size:13px;color:#444}
.warn{color:var(--warn);font-weight:600}
.tip{font-size:13px;color:#555;background:#fff;border-left:4px solid var(--accent);padding:8px 12px;border-radius:4px}
ul{font-size:13.5px;margin:6px 0 6px 18px}
</style></head><body>
<h1>字字动画《重回80我有了山神系统》· 提示词 / 时长 / 镜头衔接 样稿</h1>
<div class="tip">本文件是<b>本地样稿</b>，还没有写进作品。当前作品共 <b>426</b> 个分镜，其中<b>第1镜、第3镜已有视频</b>（只读，不覆盖、不重生成）；其余分镜提示词为空。</div>

<h2>一、将要写入的内容一览</h2>
<table><tr><th>镜号</th><th>unique_name</th><th>状态</th><th>建议时长</th><th>示范类型</th></tr>
@ROWS@</table>

<h2>二、三份样稿（左：原稿与衔接；右：将写入的提示词主体）</h2>
@CARDS@

<h2>三、只读参考：已生成的第1、3镜（保持原样）</h2>
@GEN@

<h2>四、时长口径（待你确认）</h2>
<div class="tip">
中文对白按 <b>5 字/秒</b> 估算，内心独白（OS）按 <b>4.5 字/秒</b>，无台词的动作/反应镜头每个预留 <b>1.5 秒</b>，
合计后取整、限制在 <b>4–15 秒</b>（即梦 2.0 分镜时长可选范围）。上面三份样稿按这个口径分别是 <b>第2镜 13 秒、第4镜 13 秒、第6镜 11 秒</b>。
如果觉得偏长，可以改用紧凑口径（对白 6 字/秒、OS 5 字/秒、无台词镜头 1.2 秒），对应 <b>10 / 11 / 8 秒</b>。
</div>

<h2>五、镜头衔接的处理规则（按剪辑关系分三类）</h2>
<ul>
<li><b>换场景 / 时间跳跃</b>（如第2镜结尾进闪回、第4镜闪回结束回当下）：重新交代站位与光线，不继承上一场机位，不抽帧、不上传参考图。</li>
<li><b>普通反打 / 反应镜 / 视点切换</b>（如第6镜）：不抽帧、不上传衔接图，只保持人物相对位置、道具状态与视线关系。</li>
<li><b>同一动作跨镜</b>（如第1镜结尾挑开扣子 → 第2镜手指继续下探）：必要时才看上一镜结束前约0.3秒的一帧；是否把它绑成下一镜参考，属于单独一步，需要你确认后我才做。</li>
</ul>
<div class="tip">衔接文字写入分镜的 <b>inherit_prompt（继承提示词）</b>；软件最终提示词 = 参考提示词（自动取选中的角色/场景）＋ 前缀 ＋ <b>继承提示词</b> ＋ 提示词主体(video_prompt) ＋ 后缀。</div>

<h2>六、覆盖范围与分批计划</h2>
<div class="tip">全片 <b>426 镜 / 共 66 集</b>。建议按集分批写入，每批写完抽样回读校验后再推进；第1、3镜跳过（已有视频）。
如果你只要某几集或某个镜号区间，告诉我区间即可。</div>
<div style="max-height:280px;overflow:auto">
<table><tr><th>集数</th><th>镜号区间</th><th>该集镜数</th></tr>@EP@</table></div>

</body></html>"""

htmlout = (TPL.replace("@ROWS@", "".join(row_html))
              .replace("@CARDS@", "".join(cards))
              .replace("@GEN@", "".join(gen))
              .replace("@EP@", ep_rows))

with open(os.path.join(OUT, "index.html"), "w", encoding="utf-8") as f:
    f.write(htmlout)
print("html:", os.path.join(OUT, "index.html"), len(htmlout))
print("episodes:", len(starts))
