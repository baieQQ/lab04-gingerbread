"""Generate placeholder sound effects, so the audio layer can be heard today.

⚠ **These are scaffolding, not the soundtrack.**  They are built from sine
waves and filtered noise by about eighty lines of arithmetic; they exist so the
event wiring can be *heard* and judged — is the swing too loud, does a kill
land at the right moment, is anything firing twice — while the real audio is
still being made.  Replacing any file in ``assets/sfx`` with a real recording of
the same name needs no code change at all.

Written with the standard library only (``wave``, ``array``, ``math``): the
project has no numpy, and adding a build-time dependency to make temporary
files would be a poor trade.

Run:  python tools/make_sfx.py
"""

from __future__ import annotations

import array
import math
import os
import random
import shutil
import subprocess
import wave

RATE = 44100
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(HERE, "assets", "sfx")


def render(duration: float, layers) -> array.array:
    """Sum ``layers`` over ``duration`` seconds and return 16-bit samples.

    Each layer is ``(kind, f0, f1, gain, curve)``: a frequency sweep from f0 to
    f1, scaled by gain, shaped by an amplitude curve over 0..1.
    """
    n = int(RATE * duration)
    buf = array.array("h", bytes(2 * n))
    for kind, f0, f1, gain, curve in layers:
        phase = 0.0
        for i in range(n):
            t = i / n
            freq = f0 + (f1 - f0) * t
            phase += 2 * math.pi * freq / RATE
            if kind == "sine":
                value = math.sin(phase)
            elif kind == "square":
                value = 1.0 if math.sin(phase) >= 0 else -1.0
            elif kind == "saw":
                value = 2.0 * ((phase / (2 * math.pi)) % 1.0) - 1.0
            else:                                   # noise, pitch-tilted
                value = random.uniform(-1.0, 1.0) * (0.4 + 0.6 * (freq / 4000.0))
            sample = buf[i] + int(32767 * 0.42 * gain * curve(t) * value)
            buf[i] = max(-32768, min(32767, sample))
    return buf


# ── amplitude shapes ─────────────────────────────────────────────────
def hit(t):      return (1 - t) ** 3.2                 # a strike: all attack
def soft(t):     return math.sin(math.pi * t) ** 1.4   # a swell
def hold(t):     return min(1.0, t * 14) * (1 - t) ** 0.7
def rise(t):     return t ** 2.0 * (1 - t * 0.2)


#: name -> (seconds, layers).  Deliberately terse: these are throwaway.
RECIPES = {
    "swing":      (0.16, [("noise", 2600, 700, 0.55, hit)]),
    "hit":        (0.16, [("sine", 190, 90, 0.85, hit), ("noise", 1400, 400, 0.35, hit)]),
    "kill":       (0.30, [("sine", 150, 55, 0.90, hit), ("sine", 520, 300, 0.30, hit)]),
    "clang":      (0.22, [("square", 1750, 1600, 0.30, hit), ("square", 2310, 2180, 0.24, hit)]),
    "reflect":    (0.20, [("sine", 2100, 2600, 0.42, hit)]),
    "guard":      (0.10, [("sine", 320, 260, 0.40, hit)]),
    "guard_hit":  (0.14, [("sine", 240, 150, 0.70, hit), ("noise", 900, 300, 0.28, hit)]),
    "dash":       (0.20, [("noise", 500, 2400, 0.42, soft)]),
    "sugar":      (0.26, [("sine", 1880, 1880, 0.34, hit), ("sine", 2820, 2820, 0.20, hit)]),
    "hurt":       (0.26, [("saw", 220, 120, 0.55, hit), ("noise", 700, 200, 0.30, hit)]),
    "down":       (0.55, [("sine", 260, 70, 0.75, hold)]),
    # ── 王的招式 ─────────────────────────────────────────────────
    "fireball":   (0.34, [("noise", 900, 260, 0.50, hit),
                          ("saw", 340, 150, 0.35, hold)]),
    "bounce":     (0.11, [("square", 520, 300, 0.30, hit)]),
    "blaze":      (0.42, [("noise", 620, 180, 0.42, soft)]),
    "fog_in":     (1.10, [("noise", 320, 90, 0.34, soft),
                          ("sine", 130, 62, 0.32, soft)]),
    "fog_clear":  (0.70, [("sine", 220, 620, 0.34, rise),
                          ("noise", 700, 1800, 0.20, rise)]),
    "meteor_call":(0.60, [("sine", 180, 520, 0.36, rise)]),
    "blink":      (0.26, [("sine", 900, 240, 0.34, hit),
                          ("noise", 2200, 500, 0.22, hit)]),
    "pinned":     (0.30, [("sine", 300, 880, 0.34, rise)]),
    "meteor_hit": (0.60, [("sine", 130, 40, 0.95, hit),
                          ("noise", 1900, 300, 0.55, hit)]),
    # A stand-in for a real recorded cry.  Eighty lines of arithmetic cannot
    # make a human sound hurt, and this one does not — it is here so the death
    # beat has *something* with a hard attack on it until the recording lands.
    "scream":     (0.80, [("saw", 700, 150, 0.60, hold),
                          ("saw", 1050, 280, 0.28, hit),
                          ("noise", 2400, 600, 0.30, hit)]),
    "sister_hit": (0.40, [("sine", 300, 180, 0.60, hold), ("sine", 318, 190, 0.55, hold)]),
    "douse":      (0.44, [("noise", 2200, 300, 0.42, hold)]),
    "cast":       (0.36, [("sine", 300, 1500, 0.48, soft), ("sine", 450, 2250, 0.22, soft)]),
    "arrow":      (0.14, [("noise", 3000, 1500, 0.34, hit)]),
    "windup":     (0.60, [("saw", 180, 420, 0.30, rise)]),
    "interrupt":  (0.16, [("square", 900, 300, 0.34, hit)]),
    "burst":      (0.30, [("noise", 1800, 300, 0.50, hit), ("sine", 180, 60, 0.40, hit)]),
    "split":      (0.22, [("sine", 700, 900, 0.34, hit), ("sine", 500, 640, 0.30, soft)]),
    "revive":     (0.42, [("sine", 260, 520, 0.40, soft)]),
    "surface":    (0.34, [("sine", 90, 200, 0.60, soft), ("noise", 600, 200, 0.26, hit)]),
    "burrow":     (0.34, [("sine", 200, 80, 0.55, hold), ("noise", 600, 180, 0.24, hold)]),
    "rock":       (0.26, [("sine", 130, 70, 0.70, hit), ("noise", 900, 250, 0.34, hit)]),
    "surge_tell": (0.40, [("sine", 420, 420, 0.34, hold), ("sine", 315, 315, 0.28, hold)]),
    "surge":      (0.60, [("sine", 150, 60, 0.85, hold), ("noise", 1200, 200, 0.30, hit)]),
    "event":      (0.55, [("sine", 660, 660, 0.30, soft), ("sine", 990, 990, 0.18, soft)]),
    "boss_enter": (1.10, [("sine", 90, 45, 0.90, hold), ("saw", 135, 90, 0.24, hold)]),
    "boss_down":  (1.20, [("sine", 400, 60, 0.75, hold), ("sine", 600, 90, 0.30, hold)]),
    "nightfall":  (1.30, [("sine", 160, 120, 0.45, soft), ("sine", 240, 180, 0.22, soft)]),
    "dawn":       (1.10, [("sine", 392, 392, 0.34, soft), ("sine", 494, 494, 0.26, soft)]),
    "victory":    (1.20, [("sine", 392, 587, 0.42, soft), ("sine", 494, 784, 0.28, soft)]),
    "lost":       (1.30, [("sine", 392, 196, 0.45, hold), ("sine", 466, 233, 0.30, hold)]),
    "buy":        (0.14, [("sine", 1320, 1600, 0.34, hit)]),
}


def write(path: str, samples: array.array) -> None:
    """Write ``samples`` to ``path``, as OGG where that is possible.

    **The web build rejects WAV outright.**  pygbag stops packing with
    "has a common unsupported format" the moment it meets one, and it stops
    *after* writing the archives but *before* writing ``index.html`` — so the
    output folder looks half-plausible and the browser sits on a loading
    screen forever.  That cost an afternoon; it is not allowed to cost another.

    So WAV is only ever an intermediate here.  If ``ffmpeg`` is missing the
    files still get written, because a silent game is better than no game, but
    the warning says exactly what will break.
    """
    raw = path if path.endswith(".wav") else path[: path.rfind(".")] + ".wav"
    with wave.open(raw, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(RATE)
        out.writeframes(samples.tobytes())

    if shutil.which("ffmpeg") is None:
        print(f"[make_sfx] 沒有 ffmpeg，只能留下 {os.path.basename(raw)}；"
              f"網頁版建置會失敗，請手動轉成 .ogg")
        return
    ogg = raw[:-4] + ".ogg"
    result = subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-i", raw,
         "-c:a", "libvorbis", "-q:a", "2", ogg],
        capture_output=True)
    if result.returncode == 0:
        os.remove(raw)


def ambience(seconds: float = 12.0) -> array.array:
    """A slow night bed that loops: two low tones beating against each other.

    Deliberately dull.  A placeholder that tries to be a composition is a
    placeholder nobody replaces.  Whole-cycle frequencies so the loop point is
    silent — a click every twelve seconds is worse than no music.
    """
    n = int(RATE * seconds)
    buf = array.array("h", bytes(2 * n))
    for freq, gain in ((55.0, 0.30), (82.5, 0.16), (110.0, 0.09)):
        cycles = round(freq * seconds)
        f = cycles / seconds
        for i in range(n):
            swell = 0.65 + 0.35 * math.sin(2 * math.pi * i / n * 3)
            value = math.sin(2 * math.pi * f * i / RATE) * gain * swell
            buf[i] = max(-32768, min(32767, buf[i] + int(32767 * value)))
    return buf


if __name__ == "__main__":
    random.seed(7)                      # same placeholders every run
    os.makedirs(OUT, exist_ok=True)
    os.makedirs(os.path.join(HERE, "assets", "music"), exist_ok=True)
    for name, (duration, layers) in sorted(RECIPES.items()):
        write(os.path.join(OUT, f"{name}.wav"), render(duration, layers))
    print(f"寫出 {len(RECIPES)} 個暫用音效 -> {OUT}")
    print("音樂不在這裡產生：assets/music/ 放的是真的曲子，"
          "由 view/audio.py 的 MUSIC 表指定")
