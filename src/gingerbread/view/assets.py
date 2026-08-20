"""Asset discovery, loading and caching — with a working game when nothing exists.

The art and audio for this game are being produced separately and will arrive a
few files at a time over weeks.  So the rule here is absolute:

    **A missing asset is never an error.**  Every lookup may return ``None``,
    and every caller must be able to draw or play something reasonable without
    it.  The game must be fully playable with an empty ``assets/`` directory.

That is what lets art land incrementally: drop a correctly-named file in, and it
appears in the game with no code change.

Naming
------
Files are addressed by their path under the media directory, without the
extension, with separators turned into dots::

    assets/images/monster/villager_awake.png  ->  "monster.villager_awake"
    assets/sounds/sfx/hit.wav                 ->  "sfx.hit"

so a partner adding a new monster's art only has to match the key the content
table already declares.
"""

from __future__ import annotations

import os
from typing import Final, Iterable

import pygame

#: Tried in order for each key; the first that exists wins.
IMAGE_SUFFIXES: Final = (".png", ".webp", ".jpg", ".jpeg")
SOUND_SUFFIXES: Final = (".wav", ".ogg")
MUSIC_SUFFIXES: Final = (".ogg", ".mp3", ".wav")


def _search_roots(explicit: str | None) -> list[str]:
    """Directories that might contain ``assets/``; see ``fonts._search_roots``."""
    if explicit:
        return [explicit]
    roots = [os.getcwd()]
    here = os.path.dirname(os.path.abspath(__file__))
    for _ in range(6):
        roots.append(here)
        parent = os.path.dirname(here)
        if parent == here:
            break
        here = parent
    return roots


def _display_ready() -> bool:
    """Return True when ``convert``/``convert_alpha`` are safe to call.

    Both raise if no display mode has been set.  The headless determinism check
    and the tests load assets with no window at all, so conversion has to be
    skipped there rather than crashing.
    """
    return bool(pygame.display.get_init() and pygame.display.get_surface())


class AssetLibrary:
    """Lazily loads and caches media, and remembers what was missing.

    The missing-key log is the point of this class as much as the cache is: it
    turns "the game looks unfinished" into an exact, ordered shopping list —
    see :meth:`missing_report`.
    """

    def __init__(self, root: str | None = None, *, quiet: bool = False) -> None:
        self.base = self._find_base(root)
        self.quiet = quiet
        self._images: dict[str, pygame.Surface | None] = {}
        self._sounds: dict[str, pygame.mixer.Sound | None] = {}
        self._missing: set[str] = set()
        self._found: set[str] = set()

    # ── discovery ────────────────────────────────────────────────────
    @staticmethod
    def _find_base(root: str | None) -> str | None:
        """Return the first directory that actually holds an ``assets`` folder."""
        for candidate in _search_roots(root):
            path = os.path.join(candidate, "assets")
            if os.path.isdir(path):
                return path
        return None

    def _resolve(self, kind: str, key: str, suffixes: Iterable[str]) -> str | None:
        if self.base is None:
            return None
        relative = key.replace(".", os.sep)
        for suffix in suffixes:
            path = os.path.join(self.base, kind, relative + suffix)
            if os.path.isfile(path):
                return path
        return None

    # ── images ───────────────────────────────────────────────────────
    def image(self, key: str) -> pygame.Surface | None:
        """Return the image for ``key``, or ``None`` when it does not exist.

        The surface is converted once on load: an unconverted surface is
        re-formatted on *every* blit, which is the single most common cause of
        a pygame game running at half speed for no visible reason.
        """
        if key in self._images:
            return self._images[key]

        path = self._resolve("images", key, IMAGE_SUFFIXES)
        surface: pygame.Surface | None = None
        if path is not None:
            try:
                loaded = pygame.image.load(path)
                surface = loaded.convert_alpha() if _display_ready() else loaded
            except pygame.error as exc:               # corrupt or unreadable file
                if not self.quiet:
                    print(f"[assets] could not load {path}: {exc}")
                surface = None

        self._images[key] = surface
        (self._found if surface is not None else self._missing).add(f"images/{key}")
        return surface

    def scaled(self, key: str, size: tuple[int, int]) -> pygame.Surface | None:
        """Return the image pre-scaled to ``size``, cached at that size.

        Scaling every frame is wasteful and, with ``smoothscale``, expensive.
        Cached under a size-qualified key so several sizes can coexist.
        """
        cache_key = f"{key}@{size[0]}x{size[1]}"
        if cache_key in self._images:
            return self._images[cache_key]
        source = self.image(key)
        result = pygame.transform.smoothscale(source, size) if source else None
        self._images[cache_key] = result
        return result

    #: Source-to-target ratio past which ``fitted`` averages instead of
    #: sampling.  Eight is comfortably above the coarse art (9 blocks into a
    #: 40 px monster is ~13, but each block is a flat colour so sampling is
    #: exact) and below the fine art, which is where sampling starts to lose
    #: whole features.
    SMOOTH_ABOVE = 8.0

    def fitted(self, key: str, span: int) -> pygame.Surface | None:
        """Return the image scaled to fit a ``span``-wide box, aspect intact.

        ``scaled`` takes an explicit size, and every caller in the renderer was
        passing a square one — so a sprite drawn 540×600 (which four of the
        first five are) was squashed by a tenth of its height on every frame.
        Art arrives at whatever shape the artist drew it, and the game should
        not silently reshape it; it should decide how *tall* to make it and let
        the width follow.

        Which filter to use depends on how far the art has to come down.

        ``scale`` (nearest) keeps hard square edges, which is right for art
        already drawn on a coarse grid — the first four monsters are 9×10
        blocks, and smoothing those turns a deliberate style into mush.

        ``smoothscale`` is right for anything drawn finely enough that nearest
        would be *sampling* rather than *scaling*.  The boss art is roughly
        1200 px of detailed pixel work landing in a 95 px box: picking one
        source pixel out of every thirteen throws away nine tenths of the
        drawing and what survives shimmers as the boss walks.  Averaging keeps
        the shape.

        Measured rather than assumed — both were rendered at real game size and
        compared side by side, and at these ratios the difference is the
        difference between a hooded archer and a grey smudge.
        """
        source = self.image(key)
        if source is None:
            return None
        w, h = source.get_size()
        if not w or not h:
            return None
        height = span
        width = max(1, int(round(w * height / h)))
        cache_key = f"{key}#fit{width}x{height}"
        hit = self._images.get(cache_key)
        if hit is None:
            fine = h > height * self.SMOOTH_ABOVE
            resize = (pygame.transform.smoothscale if fine
                      else pygame.transform.scale)
            hit = self._images[cache_key] = resize(source, (width, height))
        return hit

    # ── audio ────────────────────────────────────────────────────────
    def sound(self, key: str) -> pygame.mixer.Sound | None:
        """Return a sound effect, or ``None`` if absent or the mixer is off."""
        if key in self._sounds:
            return self._sounds[key]

        result: pygame.mixer.Sound | None = None
        if pygame.mixer.get_init():
            path = self._resolve("sounds", key, SOUND_SUFFIXES)
            if path is not None:
                try:
                    result = pygame.mixer.Sound(path)
                except pygame.error as exc:
                    if not self.quiet:
                        print(f"[assets] could not load {path}: {exc}")

        self._sounds[key] = result
        (self._found if result is not None else self._missing).add(f"sounds/{key}")
        return result

    def music_path(self, key: str) -> str | None:
        """Return a path for ``pygame.mixer.music.load``, or ``None``.

        Music is streamed rather than decoded into memory, so it is addressed by
        path instead of being cached as a Sound object.
        """
        path = self._resolve("music", key, MUSIC_SUFFIXES)
        (self._found if path else self._missing).add(f"music/{key}")
        return path

    # ── reporting ────────────────────────────────────────────────────
    def missing_report(self) -> list[str]:
        """Return every key that was asked for and did not exist, sorted.

        Run the game, then print this: it is the exact list of art and audio
        still to be produced, in the game's own vocabulary.
        """
        return sorted(self._missing)

    def found_report(self) -> list[str]:
        return sorted(self._found)

    def summary(self) -> str:
        base = self.base or "(no assets directory found)"
        return (f"assets: {len(self._found)} present, {len(self._missing)} missing, "
                f"root={base}")
