"""Sound, driven by the events the rules already emit.

The rules announce everything they do — ``swing``, ``hit:villager``,
``sister_hit``, ``boss_enter:slime`` — and until now nothing listened.  This
listens.  Nothing here can change an outcome: it reads a list of strings the
model produced and turns them into noise.

**Missing files are normal, not an error.**  Every slot below may be empty
while the audio is still being made, and the game has to stay playable and
silent rather than crash on a filename.  So a lookup that finds nothing is
simply silence, and the one report is a single line at start-up naming what is
missing — enough to work from, not enough to bury the console.

**One sound per event kind per frame.**  Five villagers dying in the same tick
is one death sound, not five stacked into a clipping mess.  Mixer channels are
finite and re-triggering the same short sample five times in 16 ms sounds like
a fault, not like five kills.
"""

from __future__ import annotations

import os
from typing import Final

import pygame

#: Event prefix -> sound name.  Prefixes are matched longest-first, so
#: ``boss_down:`` can differ from ``kill:`` even though both end a life.
#:
#: The left-hand side is the rules' vocabulary and must not be invented here;
#: run ``python -m gingerbread --content`` for the authoritative list.
EVENT_SOUNDS: Final[dict[str, str]] = {
    "swing": "swing",
    "whiff": "swing",
    "hit:": "hit",
    "kill:": "kill",
    "armour:": "clang",
    "reflected:": "reflect",
    "guard": "guard",
    "guarded": "guard_hit",
    # 聖癒's shield reuses the guard's clang on purpose: both are "that did not
    # get through", and teaching the ear one sound for one meaning is worth
    # more than a second sample that means the same thing.
    "warded": "guard_hit",
    "ward_off": "douse",
    "dash": "dash",
    "picked": "sugar",
    "player_hurt": "hurt",
    "player_down": "down",
    "sister_hit": "sister_hit",
    "sister_burned": "sister_hit",
    "reached": "sister_hit",
    "doused": "douse",
    "cast:": "cast",
    "shoot:": "arrow",
    "windup:": "windup",
    "interrupted:": "interrupt",
    "burst": "burst",
    "split:": "split",
    # ── the bosses' own moves ────────────────────────────────────────
    "fireball:": "fireball",
    "bounce": "bounce",
    "blaze": "blaze",
    "fog_in": "fog_in",
    "fog_clear": "fog_clear",
    "fog_cut": "interrupt",
    "blink:": "blink",
    "pinned": "pinned",
    "meteor_call:": "meteor_call",
    "meteor_hit": "meteor_hit",
    "revive": "revive",
    "surface:": "surface",
    "burrow:": "burrow",
    "barricade": "rock",
    "surge_incoming": "surge_tell",
    "surge": "surge",
    "event:": "event",
    "boss_enter:": "boss_enter",
    "boss_down:": "boss_down",
    "nightfall": "nightfall",
    "dawn": "dawn",
    "victory": "victory",
    # The death beat.  A cry, not the old soft two-note fall — the moment the
    # run ends is the one the player remembers, and it was the quietest sound
    # in the game.
    "lost": "scream",
    "bought:": "buy",
    "learned:": "buy",
}

#: Which music track belongs to which situation.  Looked up by the shell.
#:
#: All four point at one file today, which is deliberate: with a single track,
#: naming four of them would only produce silence wherever a file was missing —
#: and the place that would bite hardest is the boss fight, the one moment the
#: game least wants to go quiet.  Because ``music()`` ignores a request for the
#: track already playing, one name across all four states means the music simply
#: runs on through dusk, the shop and the fight without a seam.
#:
#: When there are more tracks, this table is the only thing that changes.
MUSIC: Final[dict[str, str]] = {
    "menu": "gloom",
    "day": "gloom",
    "night": "gloom",
    "boss": "gloom",
}

#: Extensions tried for each name, in order.
_SFX_EXT: Final = (".ogg", ".wav")
_MUSIC_EXT: Final = (".ogg", ".mp3", ".wav")


class Audio:
    """Loads what exists, plays what it is told, never raises."""

    def __init__(self, root: str | None = None, *, quiet: bool = False) -> None:
        self.ok = False
        self.muted = False
        self.sfx_volume = 0.55
        self.music_volume = 0.40
        self._sounds: dict[str, pygame.mixer.Sound] = {}
        self._playing: str | None = None
        self._missing: set[str] = set()

        try:
            # Small buffer: the default 4096 puts about 90 ms between a swing
            # and the sound of it, which is long enough to feel like lag rather
            # than like a hit.
            pygame.mixer.pre_init(44100, -16, 2, 512)
            pygame.mixer.init()
            pygame.mixer.set_num_channels(16)
            self.ok = True
        except pygame.error:
            if not quiet:
                print("[gingerbread] no audio device; running silent")
            return

        self.root = root or _find_assets()
        self._load_all(quiet=quiet)

    # ── loading ──────────────────────────────────────────────────────
    def _load_all(self, *, quiet: bool) -> None:
        wanted = sorted(set(EVENT_SOUNDS.values()))
        for name in wanted:
            path = _first_existing(self.root, "sfx", name, _SFX_EXT)
            if path is None:
                self._missing.add(name)
                continue
            try:
                sound = pygame.mixer.Sound(path)
            except pygame.error:
                self._missing.add(name)
                continue
            sound.set_volume(self.sfx_volume)
            self._sounds[name] = sound

        if self._missing and not quiet:
            print(f"[gingerbread] {len(self._missing)}/{len(wanted)} 音效還沒有檔案："
                  f"{'、'.join(sorted(self._missing))}")

    # ── playing ──────────────────────────────────────────────────────
    def consume(self, events) -> None:
        """Turn one frame's worth of model events into sound."""
        if not self.ok or self.muted or not events:
            return
        fired: set[str] = set()
        for event in events:
            name = self._match(event)
            if name is None or name in fired:
                continue
            fired.add(name)
            sound = self._sounds.get(name)
            if sound is not None:
                sound.play()

    @staticmethod
    def _match(event: str) -> str | None:
        """Longest prefix wins, so ``boss_down:`` beats a bare ``down``."""
        best: str | None = None
        best_len = -1
        for prefix, name in EVENT_SOUNDS.items():
            if len(prefix) > best_len and (
                    event == prefix or event.startswith(prefix)):
                best, best_len = name, len(prefix)
        return best

    def music(self, key: str) -> None:
        """Start the track for a situation, or stop if there is no file.

        Re-requesting the track already playing does nothing.  Restarting the
        same loop on every phase check would stutter the music once a frame.
        """
        if not self.ok:
            return
        name = MUSIC.get(key)
        if name is None or self.muted:
            self.stop_music()
            return
        if self._playing == name:
            return
        path = _first_existing(self.root, "music", name, _MUSIC_EXT)
        if path is None:
            self.stop_music()
            self._playing = name        # remembered so it is not retried daily
            return
        try:
            pygame.mixer.music.load(path)
            pygame.mixer.music.set_volume(self.music_volume)
            pygame.mixer.music.play(-1, fade_ms=600)
            self._playing = name
        except pygame.error:
            self._playing = name

    def stop_music(self) -> None:
        if self.ok and pygame.mixer.music.get_busy():
            pygame.mixer.music.fadeout(400)

    def toggle_mute(self) -> bool:
        self.muted = not self.muted
        if self.muted:
            self.stop_music()
        else:
            self._playing = None        # so the next music() call restarts it
        return self.muted

    def report(self) -> dict[str, object]:
        """What loaded and what did not — for ``--check`` and the pause menu."""
        return {"ok": self.ok, "loaded": sorted(self._sounds),
                "missing": sorted(self._missing)}


# ── file lookup ──────────────────────────────────────────────────────
def _find_assets() -> str:
    """Walk upward for an ``assets`` folder, the way the font loader does."""
    here = os.path.dirname(os.path.abspath(__file__))
    for _ in range(6):
        candidate = os.path.join(here, "assets")
        if os.path.isdir(candidate):
            return candidate
        parent = os.path.dirname(here)
        if parent == here:
            break
        here = parent
    return os.path.join(os.getcwd(), "assets")


def _first_existing(root: str, folder: str, name: str,
                    extensions) -> str | None:
    for ext in extensions:
        path = os.path.join(root, folder, name + ext)
        if os.path.exists(path):
            return path
    return None
