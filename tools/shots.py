"""把每一個畫面畫成 PNG，用來檢查有沒有炸版。

看畫面這件事沒辦法用斷言代替：「文字有沒有壓到按鈕」「面板有沒有超出畫面」
只有真的畫出來才看得到。這支工具無頭跑遊戲、擺好每一個場景、存成圖片。

    .venv/bin/python tools/shots.py [輸出資料夾]
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import pygame                                          # noqa: E402

from gingerbread import model as m                     # noqa: E402
from gingerbread.app import game as G                  # noqa: E402
from gingerbread.app import scenes as S                # noqa: E402


def fresh(*, profiles: dict | None = None, tmp: Path) -> G.Game:
    """一個乾淨的 Game，存檔寫在暫存資料夾裡。"""
    G.SAVE_PATH = tmp / "save.json"
    G.PROFILES_PATH = tmp / "profiles.json"
    if profiles:
        import json
        G.PROFILES_PATH.write_text(json.dumps(profiles, ensure_ascii=False),
                                   encoding="utf-8")
    return G.Game(seed=7, fullscreen=False)


def run(game: G.Game, frames: int = 6, events=()) -> None:
    for i in range(frames):
        game.stack.frame(1 / 60.0, list(events) if i == 0 else [])


def settle(game: G.Game) -> None:
    """把疊在遊戲畫面上的東西收掉，直到 PlayScene 在最上面。"""
    for _ in range(8):
        if isinstance(game.stack.top, S.PlayScene):
            break
        game.stack.pop()
        run(game, 2)


def shoot(game: G.Game, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pygame.image.save(game.window, str(path))
    print(f"  {path.name}")


def key(code: int, text: str = "") -> pygame.event.Event:
    return pygame.event.Event(pygame.KEYDOWN, key=code, mod=0, unicode=text,
                              scancode=0)


def typed(text: str) -> pygame.event.Event:
    return pygame.event.Event(pygame.TEXTINPUT, text=text)


def deep_save(night: int = 7, stars=(0, 3, 2, 3, 1, 2, 3, 2)) -> dict:
    return {"小白": {"best_night": night, "night_stars": list(stars),
                     "night_tries": [0, 1, 1, 4, 2, 1, 3, 5],
                     "difficulty": "normal", "taught": [], "onboarding": False,
                     "fun": {}, "stamp": 9},
            "阿婷": {"best_night": 2, "night_stars": [0, 3, 1, 0, 0, 0, 0, 0],
                     "night_tries": [0, 1, 2, 0, 0, 0, 0, 0],
                     "difficulty": "easy", "taught": [], "onboarding": True,
                     "fun": {"godmode": True}, "stamp": 4}}


def main(out: Path) -> int:
    tmp = out / "_tmp"
    tmp.mkdir(parents=True, exist_ok=True)

    # ── 存檔畫面（沒有存檔 / 有存檔 / 正在打字）──────────────────
    g = fresh(tmp=tmp)
    run(g, 8)
    shoot(g, out / "01-存檔-空的.png")
    run(g, 4, [typed("小白")])
    shoot(g, out / "02-存檔-打字中.png")
    pygame.quit()

    g = fresh(profiles=deep_save(), tmp=tmp)
    run(g, 8)
    shoot(g, out / "03-存檔-有紀錄.png")

    # ── 主選單 ───────────────────────────────────────────────────
    g.stack.pop()
    g.stack.push(S.build_menu(g.session))
    run(g, 8)
    shoot(g, out / "04-主選單.png")

    # ── 圖鑑、成績單、七夜地圖 ───────────────────────────────────
    for name, factory, frames in (
            ("05-圖鑑", lambda: S.CodexScene(g.session), 8),
            ("06-成績單", lambda: S.LedgerScene(g.session, victory=True), 8),
            ("07-七夜地圖", lambda: S.MapScene(g.session), 200),
            ("14-製作者", lambda: S.CreditsScene(g.session), 8)):
        g.stack.push(factory())
        run(g, frames)
        shoot(g, out / f"{name}.png")
        g.stack.pop()

    # ── 操作導覽、練習場 ─────────────────────────────────────────
    g.stack.push(S.TutorialScene(g.session, m.Mode.CAMPAIGN))
    run(g, 20)
    shoot(g, out / "16-操作導覽.png")
    g.stack.pop()
    g.stack.push(S.PracticeScene(g.session, ("mirror",)))
    run(g, 90)
    shoot(g, out / "17-練習場.png")
    while not isinstance(g.stack.top, S.MenuScene) and len(g.stack.scenes) > 1:
        g.stack.pop()

    # ── 圖鑑的另外兩頁 ───────────────────────────────────────────
    for page, label in ((1, "18-圖鑑-頭目"), (2, "19-圖鑑-技能")):
        codex = S.CodexScene(g.session)
        codex.page = page
        g.stack.push(codex)
        run(g, 8)
        shoot(g, out / f"{label}.png")
        g.stack.pop()

    # ── 白天商店、選技能 ─────────────────────────────────────────
    # 白天一進去會自動疊上劇情卡和地圖，把它們收掉才看得到商店本身。
    g.session.start(m.Mode.CAMPAIGN)
    g.session.cutscenes_played.update(S.CUTSCENES)
    g.session.story_shown = 99
    g.stack.push(S.PlayScene(g.session))
    run(g, 8)
    settle(g)
    shoot(g, out / "08-白天商店.png")
    g.stack.push(S.ChoiceScene(g.session))
    run(g, 8)
    shoot(g, out / "09-選技能.png")
    settle(g)                          # ChoiceScene 可能已經自己收掉了

    # ── 夜晚 ─────────────────────────────────────────────────────
    g.session.state = m.apply_action(g.session.state, "begin_night")
    for _ in range(600):
        g.session.state = m.apply_action(g.session.state, "tick")
    run(g, 4)
    settle(g)
    shoot(g, out / "10-夜晚.png")

    # ── 王之夜 ───────────────────────────────────────────────────
    g.session.act("goto:7")
    g.session.state = m.apply_action(g.session.state, "begin_night")
    for _ in range(900):
        g.session.state = m.apply_action(g.session.state, "tick")
        if g.session.state.phase is not m.Phase.NIGHT:
            break
    run(g, 4)
    settle(g)
    shoot(g, out / "15-王之夜.png")

    # ── 暫停 ─────────────────────────────────────────────────────
    g.stack.push(S.PauseScene(g.session, g))
    run(g, 6)
    shoot(g, out / "11-暫停.png")
    g.stack.pop()

    # ── 天亮評分 ─────────────────────────────────────────────────
    g.session.state.phase = m.Phase.SHOP
    g.stack.push(S.DawnScene(g.session))
    run(g, 30)
    shoot(g, out / "12-天亮評分.png")
    g.stack.pop()

    # ── 死掉 ─────────────────────────────────────────────────────
    g.session.state.phase = m.Phase.LOST
    g.stack.push(S.ResultScene(g.session))
    run(g, 300)
    shoot(g, out / "13-死掉.png")
    pygame.quit()
    return 0


if __name__ == "__main__":
    where = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("/tmp/shots")
    raise SystemExit(main(where))
