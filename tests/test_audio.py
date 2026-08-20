"""音效表指到的檔案都要在，該有聲音的事件都要有聲音。

音效缺檔是安靜的：``Audio`` 載不到就跳過，遊戲照跑，只是那一下沒有聲音 ——
而「沒有聲音」跟「這個技能沒有效果」在手感上是同一件事。
"""

from __future__ import annotations

import ast
from pathlib import Path

from gingerbread.view.audio import EVENT_SOUNDS, MUSIC

ROOT = Path(__file__).resolve().parent.parent

#: 刻意不出聲的事件：介面與流程的記帳，不是玩家做了什麼。
SILENT = {
    "boss_say:", "chose:", "day_over", "elite:", "event_over:", "exposed:",
    "map:", "offer", "pack:", "prepare:", "slot:", "turn:", "charge:",
    "zapped",                      # 電死的那一下由 kill: 負責
}


def _emitted() -> set[str]:
    found: set[str] = set()
    for path in (ROOT / "src" / "gingerbread" / "model").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "emit" and node.args):
                continue
            first = node.args[0]
            if isinstance(first, ast.Constant):
                found.add(first.value)
            elif isinstance(first, ast.JoinedStr):
                found.add("".join(
                    part.value if isinstance(part, ast.Constant) else ""
                    for part in first.values))
    return found


def test_every_mapped_sound_has_a_file():
    folder = ROOT / "assets" / "sfx"
    missing = sorted(name for name in set(EVENT_SOUNDS.values())
                     if not (folder / f"{name}.ogg").exists())
    assert not missing, f"音效表指到不存在的檔案：{missing}"


def test_every_music_track_has_a_file():
    folder = ROOT / "assets" / "music"
    missing = sorted(name for name in set(MUSIC.values())
                     if name and not (folder / f"{name}.ogg").exists())
    assert not missing, f"音樂表指到不存在的檔案：{missing}"


def test_every_event_the_player_can_cause_makes_a_sound():
    keys = set(EVENT_SOUNDS)
    quiet = []
    for event in sorted(_emitted()):
        if any(event.startswith(k) or k.startswith(event) for k in keys):
            continue
        if any(event.startswith(s) for s in SILENT):
            continue
        quiet.append(event)
    assert not quiet, (
        f"這些事件沒有聲音：{quiet}\n"
        "要嘛在 EVENT_SOUNDS 補一條，要嘛加進這支測試的 SILENT。")
