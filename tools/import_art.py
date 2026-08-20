"""把生好的角色圖收進 assets/，裁到剛好、命名正確。

生圖工具每次留的邊界寬度都不一樣 —— 同一組指令，有的角色佔滿畫布、有的四周
空一大圈。渲染器是照「高度」把圖縮到場上的，所以邊界不一致 = 同樣設定的兩隻
王在場上一大一小。這支程式把圖裁到實際有顏色的範圍，讓每一張的「滿版」意義
相同。

用法::

    python tools/import_art.py ~/Downloads/圖.png monster.slime
    python tools/import_art.py ~/Downloads/圖.png char.hansel

第二個參數就是遊戲裡的資源鍵，會自動翻成 assets/images/<資料夾>/<名字>.png。

不做去背 —— 現在的生圖工具交出來就是透明底。真的需要去背的話用
``tools/fit_sprite.py``，它有洪水填充。

需要 Pillow。
"""

from __future__ import annotations

import argparse
import os

try:
    from PIL import Image
except ImportError:                                   # pragma: no cover
    raise SystemExit("需要 Pillow：.venv/bin/pip install pillow")

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IMAGES = os.path.join(HERE, "assets", "images")

#: 裁完之後，四周各留幾個百分比的空白。
#: 完全貼齊邊緣的圖在場上看起來會「卡」在地板裡，留一點點餘裕比較像站著。
MARGIN = 0.02


def _trim(im: Image.Image, threshold: int = 12) -> Image.Image:
    """裁到真正有顏色的範圍。

    用 alpha 門檻而不是 ``getbbox()``：生圖常常在角色外圍留一圈 alpha 只有
    三四的霧狀雜訊，``getbbox()`` 會把那圈也算進去，等於沒裁到。
    """
    alpha = im.getchannel("A").point(lambda a: 255 if a >= threshold else 0)
    box = alpha.getbbox()
    if box is None:
        return im
    im = im.crop(box)
    pad_x = max(1, int(im.width * MARGIN))
    pad_y = max(1, int(im.height * MARGIN))
    out = Image.new("RGBA", (im.width + pad_x * 2, im.height + pad_y * 2),
                    (0, 0, 0, 0))
    out.alpha_composite(im, (pad_x, pad_y))
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="把角色圖收進 assets/")
    ap.add_argument("source")
    ap.add_argument("key", help="資源鍵，例如 monster.slime 或 char.gretel")
    ap.add_argument("--no-trim", action="store_true", help="不要裁邊")
    args = ap.parse_args()

    if "." not in args.key:
        raise SystemExit("資源鍵要像 monster.slime 這樣，中間有一個點")
    folder, name = args.key.split(".", 1)

    im = Image.open(args.source).convert("RGBA")
    before = im.size
    if not args.no_trim:
        im = _trim(im)

    target = os.path.join(IMAGES, folder, f"{name}.png")
    os.makedirs(os.path.dirname(target), exist_ok=True)
    im.save(target)
    rel = os.path.relpath(target, HERE)
    print(f"{args.key:22} {before[0]}×{before[1]} → {im.size[0]}×{im.size[1]}"
          f"　{rel}")


if __name__ == "__main__":
    main()
