"""錄一段遊戲畫面，存成 mp4 和 gif。

介紹網站上放靜態截圖，說不出這款遊戲在玩什麼 —— 提燈照亮的那一圈跟著人走、
怪從黑暗裡冒出來、技能炸開的那一下，都是動態才看得出來的東西。

無頭跑、逐幀存檔、再交給 ffmpeg 合成。所以錄出來的畫面跟真的玩一樣，只是不
需要有人坐在那裡玩。

    .venv/bin/python tools/record.py [輸出資料夾]
"""

from __future__ import annotations

import math
import os
import shutil
import subprocess
import sys
from pathlib import Path

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import pygame                                          # noqa: E402

from gingerbread import model as m                     # noqa: E402
from gingerbread.app import game as G                  # noqa: E402
from gingerbread.app import scenes as S                # noqa: E402

FPS = 30                                # 每兩幀存一張，網頁上夠順了


def showman(state: m.State) -> str:
    """一個「打起來好看」的機器人。

    它不是最強的打法，是最像玩家的打法：追最近的那一隻、走到打得到的距離就
    揮燈、技能一好就放。真人不會這樣一直揮，但錄十二秒的畫面需要每一秒都有
    事情發生。
    """
    live = [x for x in list(state.monsters) + list(state.bosses) if x.active]
    if not live:
        return "tick"
    p = state.player
    target = min(live, key=lambda x: math.hypot(x.x - p.x, x.y - p.y))
    parts = []
    if target.x > p.x + 8:
        parts.append("right")
    elif target.x < p.x - 8:
        parts.append("left")
    if target.y > p.y + 8:
        parts.append("down")
    elif target.y < p.y - 8:
        parts.append("up")
    if math.hypot(target.x - p.x, target.y - p.y) < 74:
        parts.append("swing")
    return "move:" + "+".join(sorted(parts)) if parts else "swing"


def stage(night: int, skills: tuple[str, str], tmp: Path) -> G.Game:
    G.SAVE_PATH = tmp / "save.json"
    G.PROFILES_PATH = tmp / "profiles.json"
    game = G.Game(seed=9, fullscreen=False)
    session = game.session
    session.set_onboarding(False)
    session.cutscenes_played.update(S.CUTSCENES)
    session.story_shown = 99
    # 不開無敵：HUD 會把作弊開關寫在畫面上（那是刻意的），而介紹網站上放一
    # 段角落寫著「無敵模式」的影片，等於在說這遊戲要開外掛才打得動。
    meta = m.Meta(night=night)
    meta.skills = list(skills)
    meta.slots = list(skills)
    # 錄影用的裝備：走到那一夜的人身上會有的升級。
    meta.upgrades = {"forge": 2, "swing_rate": 4, "reach": 3, "shade": 3,
                     "life": 4}
    session.state = m.new_game(seed=9, meta=meta)
    session.state = m.apply_action(session.state, "begin_night")
    game.stack.pop()
    game.stack.push(S.PlayScene(session))
    for _ in range(4):
        game.stack.frame(1 / 60.0, [])
    return game


def film(game: G.Game, seconds: float, out: Path, *, cast_every: float = 3.0,
         bot=showman) -> int:
    out.mkdir(parents=True, exist_ok=True)
    frames = 0
    since = 0.0
    for step in range(int(seconds * 60)):
        session = game.session
        since += m.FIXED_DT
        if since >= cast_every:
            since = 0.0
            for key in session.state.meta.slots:
                if key and session.state.cooldowns.get(key, 0) <= 0:
                    session.state = m.apply_action(session.state, f"cast:{key}")
                    break
        if session.state.phase is m.Phase.NIGHT:
            session.state = m.apply_action(session.state, bot(session.state))
        game.stack.frame(1 / 60.0, [])
        session.drain()
        if step % 2 == 0:
            pygame.image.save(game.window, str(out / f"{frames:05d}.png"))
            frames += 1
    return frames


def encode(folder: Path, name: str, out: Path) -> None:
    if not shutil.which("ffmpeg"):
        print("  (沒有 ffmpeg，只留下逐幀圖片)")
        return
    out.mkdir(parents=True, exist_ok=True)
    mp4 = out / f"{name}.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(FPS),
         "-i", str(folder / "%05d.png"),
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "22",
         "-movflags", "+faststart", str(mp4)], check=True)
    gif = out / f"{name}.gif"
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", str(mp4),
         "-vf", "fps=12,scale=540:-1:flags=lanczos,split[a][b];"
                "[a]palettegen[p];[b][p]paletteuse",
         str(gif)], check=True)
    print(f"  {mp4.name}  {mp4.stat().st_size // 1024} KB"
          f"　·　{gif.name}  {gif.stat().st_size // 1024} KB")


CLIPS = (
    # (檔名, 第幾夜, 帶哪兩個技能, 錄幾秒)
    ("夜晚", 1, ("bolt", "thunderclap"), 14.0),
    ("弓箭手之夜", 3, ("holy", "blessing"), 14.0),
    ("女巫之夜", 7, ("riptide", "windrun"), 16.0),
)


def main(out: Path) -> int:
    tmp = out / "_frames"
    for name, night, skills, seconds in CLIPS:
        print(f"錄 {name}（第 {night} 夜）")
        folder = tmp / name
        shutil.rmtree(folder, ignore_errors=True)
        game = stage(night, skills, tmp)
        film(game, seconds, folder)
        pygame.quit()
        encode(folder, name, out)
    shutil.rmtree(tmp, ignore_errors=True)
    return 0


if __name__ == "__main__":
    where = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("site/media")
    raise SystemExit(main(where))
