"""測試不准碰到真的存檔。

``Session`` 把紀錄寫在家目錄的兩個 JSON 裡，而按鈕全掃那支測試會把每一顆按
鈕都點過一遍 —— 包含「新的存檔」和「真的刪」。沒有這一層，跑一次測試就會在
玩家的存檔清單裡多出幾個名字，或是少掉一個。
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")


@pytest.fixture(autouse=True)
def _sandbox_saves(tmp_path, monkeypatch):
    from gingerbread.app import game

    monkeypatch.setattr(game, "SAVE_PATH", tmp_path / "save.json")
    monkeypatch.setattr(game, "PROFILES_PATH", tmp_path / "profiles.json")
    yield
