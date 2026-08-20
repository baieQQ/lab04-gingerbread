"""把 AI 生出來的圖，對齊成遊戲裡那四隻小怪的方塊像素風。

生圖工具（ChatGPT、Midjourney 之類）就算你在指令裡寫死「大方塊、純色、不要
抗鋸齒」，交出來的還是會有柔邊、有漸層、有幾百個顏色。這支程式做三件事：

1. **去背** —— 把四個角落的顏色當成背景色，連通區域填成透明。
2. **對齊網格** —— 依照指定的格數重新取樣，每一格只留一個顏色（取眾數，不是
   平均；平均會在邊界produce出灰灰的中間色，正是像素風最忌諱的東西）。
3. **壓色票** —— 把每一格吸到最接近的一個調色盤顏色上。預設的調色盤就是從
   現有四隻小怪身上量出來的那八個顏色，所以新圖跟舊圖天生同一國。

用法::

    python tools/fit_sprite.py ~/Downloads/slime.png assets/images/monster/slime.png
    python tools/fit_sprite.py in.png out.png --blocks 12x13
    python tools/fit_sprite.py in.png out.png --free      # 不壓色票，只對齊網格

``--free`` 給那些顏色本來就該跳出色票的圖用（例如女巫的洋紅、法師的紫）。
它還是會對齊網格、還是會去背，只是保留原本的顏色。

需要 Pillow：``.venv/bin/pip install pillow``
"""

from __future__ import annotations

import argparse
import os
from collections import Counter

try:
    from PIL import Image
except ImportError:                                   # pragma: no cover
    raise SystemExit("需要 Pillow：.venv/bin/pip install pillow")

#: 從 assets/images/monster/*.png 量出來的共用色票。
PALETTE = [
    (0x45, 0x2D, 0x2B), (0x23, 0x18, 0x15), (0xFF, 0xF8, 0xE6),
    (0xE2, 0xA1, 0x29), (0xE0, 0x44, 0x1C), (0x8D, 0x5E, 0x34),
    (0x7B, 0x6A, 0x56), (0xFF, 0xCC, 0x33), (0xE7, 0x27, 0x1E),
    (0x86, 0xC1, 0x23), (0x00, 0x66, 0x32), (0x51, 0x9F, 0x8F),
    (0xC9, 0xCA, 0xCA), (0xDC, 0xE8, 0xA6),
]

#: 一格輸出成幾像素，跟現有的四隻對齊。
BLOCK = 60


def _strip_background(im: Image.Image, tolerance: int = 46) -> Image.Image:
    """把四角顏色當背景，從邊緣往內洪水填充成透明。

    只從邊緣蔓延，不是全圖比色 —— 不然角色身上剛好跟背景同色的區塊會被挖掉，
    白襯衫在白底上會變成一個洞。
    """
    im = im.convert("RGBA")
    w, h = im.size
    px = im.load()
    corners = [px[0, 0], px[w - 1, 0], px[0, h - 1], px[w - 1, h - 1]]
    bg = Counter(c[:3] for c in corners).most_common(1)[0][0]

    seen = bytearray(w * h)
    stack = [(x, 0) for x in range(w)] + [(x, h - 1) for x in range(w)]
    stack += [(0, y) for y in range(h)] + [(w - 1, y) for y in range(h)]
    while stack:
        x, y = stack.pop()
        if not (0 <= x < w and 0 <= y < h) or seen[y * w + x]:
            continue
        r, g, b, a = px[x, y]
        if a == 0:
            seen[y * w + x] = 1
            continue
        if abs(r - bg[0]) + abs(g - bg[1]) + abs(b - bg[2]) > tolerance * 3:
            continue
        seen[y * w + x] = 1
        px[x, y] = (r, g, b, 0)
        stack += [(x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)]
    return im


def _nearest(colour, palette):
    r, g, b = colour
    return min(palette, key=lambda c: (c[0] - r) ** 2
               + (c[1] - g) ** 2 + (c[2] - b) ** 2)


def _blockify(im: Image.Image, cols: int, rows: int, snap: bool) -> Image.Image:
    """每一格取眾數顏色，畫成一張 cols×rows 的小圖。"""
    w, h = im.size
    px = im.load()
    small = Image.new("RGBA", (cols, rows), (0, 0, 0, 0))
    out = small.load()
    for cy in range(rows):
        for cx in range(cols):
            x0, x1 = cx * w // cols, (cx + 1) * w // cols
            y0, y1 = cy * h // rows, (cy + 1) * h // rows
            tally: Counter = Counter()
            solid = 0
            total = 0
            for y in range(y0, y1):
                for x in range(x0, x1):
                    r, g, b, a = px[x, y]
                    total += 1
                    if a < 128:
                        continue
                    solid += 1
                    # 先粗量化再數眾數，否則幾百個相近色各算各的，眾數等於雜訊。
                    tally[(r // 24 * 24, g // 24 * 24, b // 24 * 24)] += 1
            # 一格要超過四成是實心才留著，不然柔邊會長出一圈毛。
            if not tally or solid * 5 < total * 2:
                continue
            colour = tally.most_common(1)[0][0]
            if snap:
                colour = _nearest(colour, PALETTE)
            out[cx, cy] = (*colour, 255)
    return small


def main() -> None:
    ap = argparse.ArgumentParser(description="把 AI 圖對齊成遊戲的方塊像素風")
    ap.add_argument("source")
    ap.add_argument("target")
    ap.add_argument("--blocks", default="12x13",
                    help="幾格寬x幾格高，預設 12x13（王）；主角建議 8x10")
    ap.add_argument("--block-px", type=int, default=BLOCK,
                    help="一格輸出幾像素，預設 60，跟現有小怪一致")
    ap.add_argument("--free", action="store_true",
                    help="不壓色票，保留原色（女巫、法師這種）")
    ap.add_argument("--keep-bg", action="store_true", help="不要去背")
    args = ap.parse_args()

    cols, rows = (int(n) for n in args.blocks.lower().split("x"))
    im = Image.open(args.source)
    if not args.keep_bg:
        im = _strip_background(im)
    small = _blockify(im, cols, rows, snap=not args.free)
    big = small.resize((cols * args.block_px, rows * args.block_px),
                       Image.NEAREST)

    os.makedirs(os.path.dirname(os.path.abspath(args.target)), exist_ok=True)
    big.save(args.target)
    used = len({p for p in small.getdata() if p[3]})
    print(f"寫出 {args.target}　{big.size[0]}×{big.size[1]}"
          f"　{cols}×{rows} 格　{used} 個顏色")


if __name__ == "__main__":
    main()
