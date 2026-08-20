"""把 ``story/`` 底下的過場動畫接進遊戲的場景堆疊。

那四段動畫是另一位組員寫的，各自是一支能單獨執行的程式：自己的視窗、自己的
主迴圈、自己的 480×270 內部畫布。這個檔案不重寫它們，也不把它們的畫法搬過
來 —— 每一個像素還是他畫的，只是改由遊戲餵時間、餵事件、指定畫到哪裡。

能這樣接是因為他自己已經走到一半了：``day_1.py`` 裡有一個 ``PrologueScene``
類別，``update(dt)`` / ``draw(surface)`` / ``finished`` 三件事都在，而所有
``draw_*`` 函式收的都是傳進去的 surface 而不是螢幕。剩下的只有兩件事 ——
另外三支還把主迴圈綁在模組層，還有它們的畫布尺寸跟遊戲不一樣。

尺寸的處理方式是**不縮排版、只縮成品**：讓那一段動畫畫在它自己那張
``WINDOW_W × WINDOW_H`` 的離屏 surface 上，整張再等比例縮進遊戲畫布置中。
他排好的字幕位置、留白、行高因此一個像素都不會跑掉。
"""

from __future__ import annotations

import importlib
import os
import sys
from typing import Final

import pygame

from ..view import palette as P
from ..view.ui import Scene, SceneStack, UI

#: 過場代號 -> story/ 底下的模組名。
CUTSCENES: Final[dict[str, str]] = {
    "intro": "intro",
    "day_1": "day_1",
    "night_1": "night_1",
    "day_2": "day_2",
}


def _story_root() -> str:
    """``story/`` 的上一層 —— 也就是專案根目錄。"""
    here = os.path.dirname(os.path.abspath(__file__))
    for _ in range(6):
        if os.path.isdir(os.path.join(here, "story")):
            return here
        parent = os.path.dirname(here)
        if parent == here:
            break
        here = parent
    return os.getcwd()


def load(key: str):
    """載入一段過場，回傳它的模組；載不起來就回 ``None``。

    絕不往外丟例外。過場是氣氛，遊戲沒有它照樣能玩 —— 一段動畫壞掉不該讓
    整個攤位當在開場畫面。
    """
    name = CUTSCENES.get(key)
    if name is None:
        return None
    root = _story_root()
    if root not in sys.path:
        sys.path.insert(0, root)
    try:
        return importlib.import_module(f"story.{name}")
    except Exception as exc:                       # noqa: BLE001 - 見上
        print(f"[gingerbread] 過場 {key} 載入失敗，跳過：{exc}")
        return None


class CutsceneScene(Scene):
    """播一段組員做的動畫，播完就把自己彈掉。

    輸入直接轉交給他的 ``handle_event``（滑鼠左鍵推進字幕，這是他訂的規則，
    照舊），另外補一個 Esc 跳過 —— 攤位上後面排隊的人不會想看第四次。
    """

    wants_escape = True

    def __init__(self, app_state, key: str) -> None:
        self.g = app_state
        self.key = key
        self.module = load(key)
        self.inner = None
        self.frame: pygame.Surface | None = None
        if self.module is not None:
            try:
                self.inner = self.module.PrologueScene()
                self.frame = pygame.Surface(
                    (self.module.WINDOW_W, self.module.WINDOW_H))
            except Exception as exc:               # noqa: BLE001
                print(f"[gingerbread] 過場 {key} 起不來，跳過：{exc}")
                self.inner = None

    def update(self, app: SceneStack, ui: UI, dt: float) -> None:
        if self.inner is None or self.frame is None:
            app.pop()
            return

        for event in ui.events:
            if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                app.pop()
                return
            try:
                self.inner.handle_event(event)
            except Exception:                      # noqa: BLE001
                pass

        try:
            self.inner.update(dt)
            self.frame.fill(P.INK[:3])
            self.inner.draw(self.frame)
        except Exception as exc:                   # noqa: BLE001
            print(f"[gingerbread] 過場 {self.key} 播放中出錯，跳過：{exc}")
            app.pop()
            return

        # 等比例縮放置中。整張一起縮，所以他排的字幕位置不會跑掉。
        surface = ui.surface
        sw, sh = surface.get_size()
        fw, fh = self.frame.get_size()
        k = min(sw / fw, sh / fh)
        size = (max(1, int(fw * k)), max(1, int(fh * k)))
        surface.fill(P.INK[:3])
        surface.blit(pygame.transform.smoothscale(self.frame, size),
                     ((sw - size[0]) // 2, (sh - size[1]) // 2))

        ui.text("滑鼠左鍵繼續　·　Esc 跳過",
                (sw // 2, sh - ui.s(16)), "small", P.MUTED, "center")

        if getattr(self.inner, "finished", False):
            app.pop()
