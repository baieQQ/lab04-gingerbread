"""把介紹網站生出來 —— 文案直接從遊戲的資料表讀。

網站上寫「褪影射手有 52 滴血」這種話，只要是手打的，遲早就會跟遊戲對不上。
所以這一頁跟圖鑑走同一條規矩：每一個數字、每一句技能說明，都是從 model 的
內容表讀出來的。改了平衡，重跑這支工具，網站就跟著對。

    .venv/bin/python tools/build_site.py

輸出在 site/：index.html 加一個 media/ 資料夾。用瀏覽器直接打開就能看。
"""

from __future__ import annotations

import html
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

from gingerbread.model import constants as C            # noqa: E402
from gingerbread.model.content import (BEATS, BOSSES,   # noqa: E402
                                       MONSTERS, SPELLS)
from gingerbread.model.content.elements import ELEMENTS  # noqa: E402
from gingerbread.model.content.monsters import COUNTERS  # noqa: E402
from gingerbread.model.content.stages import STAGES     # noqa: E402

SITE = ROOT / "site"
MEDIA = SITE / "media"
ART = MEDIA / "art"

MAKERS = (("不分系", "曾哲瀚"), ("工科所", "陳彥婷"), ("工科所", "陳昱安"))

CLIPS = (("夜晚", "第一夜", "提燈照到的地方才看得見。看不見的東西還是在走。"),
         ("弓箭手之夜", "第三夜　褪影射手",
          "遠處那道光是它在拉弓。走過去打斷它，或是替葛蕾特擋下那一箭。"),
         ("女巫之夜", "第七夜　糖果屋女巫",
          "前面六夜的每一種招式，她全部都有。"))

SHOTS = (("04-主選單.png", "主選單"),
         ("07-七夜地圖.png", "七夜地圖"),
         ("08-白天商店.png", "白天：用糖霜換活下去的本錢"),
         ("05-圖鑑.png", "圖鑑：每一隻怪都寫得出剋星"),
         ("12-天亮評分.png", "天亮：這一夜打得怎麼樣"),
         ("06-成績單.png", "七夜之後的成績單"))


def e(text: str) -> str:
    return html.escape(str(text))


#: 網站只用得到主視覺那一張背景，其餘六張地板圖是遊戲裡的東西。
USED_TITLES = ("menu",)


def copy_art() -> None:
    """把要用的圖轉成 webp 搬過來。

    直接複製原始 PNG 的話，光是圖就 14 MB —— 而其中七 MB 是六張網站根本沒
    引用的背景。立繪用 lossless：那是像素畫，壓壞了就看得出來。
    """
    from PIL import Image

    ART.mkdir(parents=True, exist_ok=True)
    for folder, lossless in (("title", False), ("monster", True),
                             ("icon", True), ("char", True)):
        src = ROOT / "assets" / "images" / folder
        if not src.is_dir():
            continue
        dst = ART / folder
        dst.mkdir(parents=True, exist_ok=True)
        for png in src.glob("*.png"):
            if folder == "title" and png.stem not in USED_TITLES:
                continue
            out = dst / f"{png.stem}.webp"
            image = Image.open(png).convert("RGBA")
            # 立繪的原檔是 1200 見方，網頁上只畫到 72 像素高。等比縮到 320
            # 之後看起來一模一樣，檔案小十倍 —— 而 image-rendering:pixelated
            # 需要的是「別被瀏覽器平滑掉」，不是「原檔要很大」。
            limit = 320 if folder != "title" else 1600
            if max(image.size) > limit:
                scale = limit / max(image.size)
                image = image.resize(
                    (max(1, round(image.width * scale)),
                     max(1, round(image.height * scale))), Image.LANCZOS)
            if lossless:
                image.save(out, lossless=True, method=6)
            else:
                image.save(out, quality=82, method=6)


def draw_missing_monsters() -> None:
    """沒有像素圖的怪，用遊戲自己的畫法畫出來。

    圖鑑裡那幾隻本來就是程式畫的 —— 網站上放一顆空圓圈，等於承認「這幾隻我
    們沒做完」，但實際上遊戲裡它們長得好好的。同一段程式畫兩次，網站和圖鑑
    就不會有兩套長相。
    """
    import pygame

    from gingerbread.view import figures as F
    from gingerbread.view import palette as P
    from gingerbread.view.board import _BUILD

    pygame.init()
    pygame.display.set_mode((64, 64))
    folder = ART / "monster"
    folder.mkdir(parents=True, exist_ok=True)
    for spec in MONSTERS.values():
        out = folder / f"{spec.key}.webp"
        if out.exists() or (folder / f"{spec.key}.png").exists():
            continue
        size = 96
        surface = pygame.Surface((size, size), pygame.SRCALPHA)
        F.humanoid(surface, size // 2, size // 2 + 8, 30,
                   getattr(spec, "colour", P.BLOOD),
                   build=_BUILD.get(getattr(spec, "silhouette", "villager"),
                                    "adult"),
                   phase=0.35, moving=False, squash=0.0, facing=(0.0, 1.0))
        pygame.image.save(surface, str(out.with_suffix(".png")))
    pygame.quit()
    from PIL import Image

    for png in list(folder.glob("*.png")):
        Image.open(png).save(png.with_suffix(".webp"), lossless=True, method=6)
        png.unlink()


def shrink_shots() -> None:
    """只留網站用得到的那幾張，而且換成 webp。

    截圖是 900x648 的 PNG，一張半 MB；十五張放進 repo 是七 MB 的無用重量。
    """
    from PIL import Image

    folder = MEDIA / "shots"
    keep = {name for name, _caption in SHOTS}
    for png in list(folder.glob("*.png")):
        if png.name in keep:
            Image.open(png).save(png.with_suffix(".webp"), quality=82,
                                 method=6)
        png.unlink()


def make_shots() -> None:
    """跑一次 shots.py，把截圖放進 media/shots。"""
    sys.argv = ["shots", str(MEDIA / "shots")]
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "shots", ROOT / "tools" / "shots.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.main(MEDIA / "shots")
    shutil.rmtree(MEDIA / "shots" / "_tmp", ignore_errors=True)


# ── 區塊 ─────────────────────────────────────────────────────────────
def hero() -> str:
    return f"""
<header class="hero">
  <img class="hero-art" src="media/art/title/menu.webp" alt="">
  <div class="hero-text">
    <p class="kicker">成功大學　Python 課程專題</p>
    <h1>糖果屋之後</h1>
    <p class="tagline">這一次，換他來保護妹妹。</p>
    <p class="lede">
      兄妹倆從女巫的屋子回來了，帶著一整袋糖。<br>
      村子餓了一整個冬天，而現在他們手上有東西。<br>
      七個夜晚之後，來敲門的已經不是人了。
    </p>
    <div class="pills">
      <span>七個夜晚</span><span>六隻頭目</span>
      <span>{len(SPELLS)} 個技能</span><span>{len(MONSTERS)} 種怪物</span>
    </div>
  </div>
</header>"""


def loop() -> str:
    cards = (("白天", "村子還是村子",
              "用昨晚撿到的糖霜換裝備、學技能，決定今晚帶哪兩個上場。"
              "一天只有這麼多資源，選了這個就沒有那個。"),
             ("夜晚", "提燈照到的地方才看得見",
              f"守住葛蕾特 {C.NIGHT_SECONDS:.0f} 秒。她不會跑、不會躲，"
              "被碰到就掉血 —— 而她的血，天亮也不會自己補回來。"),
             ("天亮", "這一夜打得怎麼樣",
              "六項評分、一個等第、一到三顆星。"
              "打得不好可以重來，重來的成績只會往上不會往下。"))
    items = "".join(f"""
      <article class="card">
        <p class="card-tag">{e(tag)}</p>
        <h3>{e(head)}</h3>
        <p>{e(body)}</p>
      </article>""" for tag, head, body in cards)
    return f"""
<section id="loop">
  <h2>一天，一夜，再一天</h2>
  <div class="grid three">{items}</div>
</section>"""


def films() -> str:
    items = "".join(f"""
      <figure class="clip">
        <video src="media/{e(name)}.mp4" autoplay loop muted playsinline></video>
        <figcaption><strong>{e(head)}</strong>{e(note)}</figcaption>
      </figure>""" for name, head, note in CLIPS)
    return f"""
<section id="play">
  <h2>玩起來是這樣</h2>
  <p class="sub">下面三段都是遊戲實際跑出來的畫面，沒有剪接。</p>
  <div class="grid three clips">{items}</div>
</section>"""


def nights() -> str:
    rows = []
    for night in range(1, C.CAMPAIGN_NIGHTS + 1):
        stage = STAGES[night]
        beat = BEATS.get(night)
        boss = BOSSES.get(stage.boss) if stage.boss else None
        art = (f'<img src="media/art/monster/{boss.key}.webp" alt="">'
               if boss else
               '<img src="media/art/char/hansel.webp" alt="">')
        weak = (ELEMENTS.get(boss.weakness or "", {}).get("name", "沒有單一解答")
                if boss else "—")
        title = boss.name if boss else "沒有頭目"
        line = beat.body.split("\n")[0] if beat else stage.tagline
        rows.append(f"""
      <article class="night">
        <div class="night-art">{art}</div>
        <div class="night-body">
          <p class="card-tag">第 {night} 夜　{e(beat.heading if beat else '')}</p>
          <h3>{e(title)}</h3>
          <p>{e(line)}</p>
          <p class="stat">{'血 %d　弱點 %s' % (boss.hp, weak) if boss else e(stage.tagline)}</p>
        </div>
      </article>""")
    return f"""
<section id="nights">
  <h2>七個夜晚</h2>
  <p class="sub">每一夜換一張地圖、換一批怪；從第二夜起，每一夜有一隻頭目。</p>
  <div class="grid nights-grid">{"".join(rows)}</div>
</section>"""


def skills() -> str:
    items = []
    for spec in SPELLS.values():
        element = ELEMENTS.get(spec.element, {}).get("name", "")
        length = f"持續 {spec.duration:.0f} 秒" if spec.duration else "瞬間"
        items.append(f"""
      <article class="skill">
        <img src="media/art/icon/{e(spec.key)}.webp" alt="">
        <div>
          <h3>{e(spec.name)}<span class="tier">{spec.tier} 階</span></h3>
          <p class="stat">{e(element)}　冷卻 {spec.cooldown:.0f} 秒　{e(length)}</p>
          <p>{e(spec.description)}</p>
        </div>
      </article>""")
    return f"""
<section id="skills">
  <h2>八個技能，四種元素</h2>
  <p class="sub">雷破甲、光揭穿、風開路、水滅火。
     帶錯元素打得動，帶對元素打得快 —— 而有一隻頭目，不帶水就真的碰不到它。</p>
  <div class="grid two">{"".join(items)}</div>
</section>"""


def bestiary() -> str:
    items = []
    for spec in MONSTERS.values():
        beat = COUNTERS.get(spec.key)
        art = ART / "monster" / f"{spec.key}.webp"
        picture = (f'<img src="media/art/monster/{e(spec.key)}.webp" alt="">'
                   if art.exists() else '<span class="no-art"></span>')
        items.append(f"""
      <article class="beast">
        {picture}
        <h4>{e(spec.name)}</h4>
        <p class="stat">血 {spec.hp}　速 {spec.speed:.0f}</p>
        {f'<p class="counter">剋星：{e(beat)}</p>' if beat else ''}
      </article>""")
    return f"""
<section id="beasts">
  <h2>來敲門的是誰</h2>
  <p class="sub">{len(MONSTERS)} 種怪，每一種都有一個「這樣做就對了」的答案。
     遊戲裡的圖鑑會直接告訴你那個答案 —— 難的從來不是知道，是做到。</p>
  <div class="grid beasts-grid">{"".join(items)}</div>
</section>"""


def gallery() -> str:
    items = "".join(f"""
      <figure>
        <img src="media/shots/{e(name).replace(".png", ".webp")}" alt="{e(caption)}" loading="lazy">
        <figcaption>{e(caption)}</figcaption>
      </figure>""" for name, caption in SHOTS
                    if (MEDIA / "shots"
                        / name.replace(".png", ".webp")).exists())
    return f"""
<section id="shots">
  <h2>畫面</h2>
  <div class="grid two shots">{items}</div>
</section>"""


def controls() -> str:
    keys = (("WASD／方向鍵", "走"), ("J／空白", "揮燈"), ("K", "防禦"),
            ("Shift", "衝刺"), ("L", "一階技能"), ("；", "二階技能"),
            ("Esc", "暫停"), ("F11", "全螢幕"))
    items = "".join(f"<div><kbd>{e(k)}</kbd><span>{e(v)}</span></div>"
                    for k, v in keys)
    return f"""
<section id="how">
  <h2>怎麼玩</h2>
  <div class="keys">{items}</div>
  <div class="run">
    <p>需要 Python 3.11 以上。</p>
    <pre><code>python3.11 -m venv .venv
.venv/bin/python -m pip install -e ".[test,display]"
.venv/bin/python -m gingerbread</code></pre>
  </div>
</section>"""


def credits() -> str:
    rows = "".join(f"""
      <div class="maker"><span>{e(dept)}</span><strong>{e(who)}</strong></div>"""
                   for dept, who in MAKERS)
    return f"""
<section id="credits">
  <h2>製作者</h2>
  <div class="makers">{rows}</div>
  <p class="closing">兩個人在森林裡，一個提著燈。</p>
</section>"""


CSS = """
*, *::before, *::after { box-sizing: border-box; }
:root {
  --void:#06050b; --ink:#0d0b15; --panel:#15121f; --panel-hi:#1e1a2c;
  --line:#241e36; --bone:#f0e5cd; --dim:#b8a98b; --muted:#6a6383;
  --ember:#f2a93b; --ember-dark:#a86b1f; --blood:#c03a2e; --arcane:#8e6bd6;
  --sugar:#d68a54;
}
html { scroll-behavior:smooth; }
body {
  margin:0; background:var(--void); color:var(--bone);
  font-family:"PingFang TC","Hiragino Sans GB","Microsoft JhengHei",
              "Noto Sans TC",system-ui,sans-serif;
  line-height:1.75; -webkit-font-smoothing:antialiased;
}
img, video { max-width:100%; display:block; }
img[src*="/monster/"], img[src*="/char/"], img[src*="/icon/"] {
  image-rendering:pixelated;
}
section { max-width:1080px; margin:0 auto; padding:5rem 1.5rem; }
h1,h2,h3,h4 { line-height:1.3; margin:0 0 .6rem; font-weight:600; }
h2 { font-size:clamp(1.5rem,3.4vw,2.1rem); color:var(--ember);
     letter-spacing:.04em; }
h2::after { content:""; display:block; width:3rem; height:2px;
            background:var(--ember-dark); margin-top:.9rem; }
p { margin:0 0 .8rem; }
.sub { color:var(--dim); max-width:60ch; margin-bottom:2.4rem; }
.stat { color:var(--muted); font-size:.86rem; letter-spacing:.03em; }
.card-tag { color:var(--arcane); font-size:.8rem; letter-spacing:.14em;
            margin-bottom:.3rem; }

/* hero */
.hero { position:relative; min-height:min(88vh,760px); display:flex;
        align-items:flex-end; overflow:hidden; }
.hero-art { position:absolute; inset:0; width:100%; height:100%;
            object-fit:cover; opacity:.5; }
.hero::after { content:""; position:absolute; inset:0;
  background:linear-gradient(180deg,rgba(6,5,11,.55) 0%,
             rgba(6,5,11,.2) 35%,var(--void) 100%); }
.hero-text { position:relative; z-index:1; max-width:1080px; width:100%;
             margin:0 auto; padding:0 1.5rem 5rem; }
.kicker { color:var(--muted); letter-spacing:.2em; font-size:.78rem; }
.hero h1 { font-size:clamp(2.6rem,8vw,5rem); color:var(--ember);
           letter-spacing:.1em; margin:.2rem 0 .4rem;
           text-shadow:0 0 40px rgba(242,169,59,.28); }
.tagline { font-size:clamp(1rem,2.4vw,1.3rem); color:var(--bone);
           letter-spacing:.06em; }
.lede { color:var(--dim); margin-top:1.4rem; }
.pills { display:flex; flex-wrap:wrap; gap:.5rem; margin-top:1.8rem; }
.pills span { border:1px solid var(--line); background:rgba(21,18,31,.8);
  padding:.34rem .9rem; border-radius:999px; font-size:.82rem;
  color:var(--dim); }

/* grids */
.grid { display:grid; gap:1.2rem; }
.two { grid-template-columns:repeat(auto-fit,minmax(320px,1fr)); }
.three { grid-template-columns:repeat(auto-fit,minmax(260px,1fr)); }
.nights-grid { grid-template-columns:repeat(auto-fit,minmax(300px,1fr)); }
.beasts-grid { grid-template-columns:repeat(auto-fill,minmax(140px,1fr)); }

.card, .night, .skill, .beast, .clip figcaption {
  background:var(--panel); border:1px solid var(--line); border-radius:10px;
}
.card { padding:1.6rem 1.4rem; }
.card h3 { color:var(--bone); }
.card p:last-child { color:var(--dim); margin:0; }

/* clips */
.clips figure { margin:0; }
.clip video { border:1px solid var(--line); border-radius:10px 10px 0 0;
              background:#000; }
.clip figcaption { border-top:0; border-radius:0 0 10px 10px;
  padding:1rem 1.1rem; color:var(--dim); font-size:.88rem; }
.clip figcaption strong { display:block; color:var(--bone);
  font-weight:600; margin-bottom:.25rem; }

/* nights */
.night { display:flex; gap:1rem; padding:1.2rem; align-items:flex-start; }
.night-art { flex:0 0 84px; height:84px; display:flex; align-items:center;
  justify-content:center; background:var(--ink); border-radius:8px;
  border:1px solid var(--line); }
.night-art img { max-height:72px; width:auto; }
.night-body h3 { color:var(--ember); font-size:1.05rem; }
.night-body p { margin:0 0 .4rem; color:var(--dim); font-size:.9rem; }

/* skills */
.skill { display:flex; gap:1rem; padding:1.2rem; align-items:flex-start; }
.skill img { flex:0 0 54px; width:54px; border-radius:8px;
  background:var(--ink); border:1px solid var(--line); padding:4px; }
.skill h3 { color:var(--bone); font-size:1rem; display:flex; gap:.6rem;
  align-items:baseline; }
.tier { font-size:.72rem; color:var(--arcane); border:1px solid var(--line);
  border-radius:4px; padding:.05rem .45rem; }
.skill p:last-child { margin:.45rem 0 0; color:var(--dim); font-size:.88rem; }

/* beasts */
.beast { padding:1rem .8rem; text-align:center; }
.beast img, .beast .no-art { height:56px; width:auto; margin:0 auto .6rem; }
.beast .no-art { display:block; width:34px; border-radius:50%;
  background:var(--panel-hi); border:1px solid var(--line); }
.beast h4 { font-size:.92rem; margin-bottom:.2rem; }
.counter { color:var(--sugar); font-size:.76rem; margin:.35rem 0 0; }

/* shots */
.shots figure { margin:0; }
.shots img { border:1px solid var(--line); border-radius:10px; }
.shots figcaption { color:var(--muted); font-size:.82rem; padding-top:.6rem; }

/* how */
.keys { display:grid; gap:.7rem;
  grid-template-columns:repeat(auto-fit,minmax(180px,1fr)); margin-bottom:2rem; }
.keys div { display:flex; gap:.8rem; align-items:center; }
kbd { background:var(--panel-hi); border:1px solid var(--line);
  border-bottom-width:2px; border-radius:6px; padding:.2rem .6rem;
  font-family:ui-monospace,Menlo,monospace; font-size:.8rem; color:var(--bone);
  min-width:5.2rem; text-align:center; }
.keys span { color:var(--dim); font-size:.9rem; }
.run pre { background:var(--ink); border:1px solid var(--line);
  border-radius:10px; padding:1.1rem 1.3rem; overflow-x:auto; }
.run code { font-family:ui-monospace,Menlo,monospace; font-size:.85rem;
  color:var(--dim); }
.run p { color:var(--muted); font-size:.86rem; }

/* credits */
#credits { text-align:center; padding-bottom:7rem; }
#credits h2::after { margin-left:auto; margin-right:auto; }
.makers { display:flex; flex-wrap:wrap; gap:1rem; justify-content:center;
  margin:2.4rem 0 2rem; }
.maker { background:var(--panel); border:1px solid var(--line);
  border-radius:10px; padding:1.1rem 2rem; min-width:190px; }
.maker span { display:block; color:var(--muted); font-size:.76rem;
  letter-spacing:.14em; margin-bottom:.3rem; }
.maker strong { font-size:1.15rem; font-weight:600; letter-spacing:.08em; }
.closing { color:var(--muted); font-size:.9rem; }

@media (max-width:600px) {
  section { padding:3.5rem 1.2rem; }
  .hero-text { padding-bottom:3rem; }
}
"""


def build() -> int:
    SITE.mkdir(parents=True, exist_ok=True)
    copy_art()
    if not (MEDIA / "shots" / "04-主選單.webp").exists():
        make_shots()
        shrink_shots()
    draw_missing_monsters()
    body = "".join([hero(), loop(), films(), nights(), skills(),
                    bestiary(), gallery(), controls(), credits()])
    page = f"""<!doctype html>
<html lang="zh-Hant">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>糖果屋之後 · After the Gingerbread House</title>
<meta name="description" content="七個夜晚，一盞提燈，一個必須被守住的人。">
<style>{CSS}</style>
</head>
<body>
{body}
</body>
</html>
"""
    out = SITE / "index.html"
    out.write_text(page, encoding="utf-8")
    print(f"寫好了：{out.relative_to(ROOT)}  ({len(page) // 1024} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(build())
