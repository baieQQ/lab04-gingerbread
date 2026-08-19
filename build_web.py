"""Build the browser version with pygbag.

The web runtime has no system fonts and no src/ layout, so this script
assembles a flat folder that pygbag can compile to WebAssembly:

    web/
      main.py            async entry point
      gingerbread/       a copy of the package
      assets/            the subset CJK font

Run:  python build_web.py          then open build/web/index.html
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent
WEB = ROOT / "web"

MAIN = '''"""Browser entry point (pygbag compiles this to WebAssembly).

Everything is wrapped so a failure is *visible*.  Under WebAssembly an
uncaught exception goes nowhere the developer can see: the loading banner
simply stays up forever, and the browser console shows only the runtime's own
chatter.  Writing the traceback into the document turns a silent hang into a
message that can be read and fixed.
"""

import asyncio
import os
import sys
import traceback

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")


def _show(text):
    try:
        import platform
        platform.window.document.title = text[:120]
        el = platform.window.document.createElement("pre")
        el.id = "boot-error"
        el.style.cssText = ("position:fixed;left:0;top:0;z-index:99999;"
                            "background:#111;color:#f66;font:12px monospace;"
                            "padding:12px;white-space:pre-wrap;max-width:100%")
        el.textContent = text
        platform.window.document.body.appendChild(el)
    except Exception:
        print(text, file=sys.stderr)


def _mark(step):
    """Leave a breadcrumb in the tab title, so a hang says where it hung."""
    try:
        import platform
        platform.window.document.title = "boot: " + step
    except Exception:
        pass


async def main() -> None:
    # Everything is inside the coroutine because pygbag's ``asyncio.run``
    # schedules and returns immediately — a try/except around *it* catches
    # nothing, which is why the first attempt at this reported no error at all.
    try:
        _mark("import")
        # **Not fullscreen.**  ``set_mode((0, 0), FULLSCREEN)`` means "the whole
        # desktop" on a desktop; under WebAssembly there is no desktop.
        from gingerbread.app.game import Game

        _mark("construct")
        game = Game(seed=42, fullscreen=False)
        _mark("run")
        await game.run()
    except BaseException:
        _show(traceback.format_exc())
        raise


asyncio.run(main())
'''


def stage() -> None:
    if WEB.exists():
        shutil.rmtree(WEB)
    WEB.mkdir()
    shutil.copytree(ROOT / "src" / "gingerbread", WEB / "gingerbread",
                    ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copytree(ROOT / "assets", WEB / "assets")
    (WEB / "main.py").write_text(MAIN, encoding="utf-8")
    print(f"staged -> {WEB}")


def build() -> int:
    stage()
    cmd = [sys.executable, "-m", "pygbag", "--build", "--ume_block", "0",
           "--title", "糖果屋之後", str(WEB)]
    print("running:", " ".join(cmd))
    return subprocess.call(cmd)


def publish() -> None:
    """Copy the finished build to ``web-dist``, which is what Vercel serves.

    ``web/`` is ignored by git — it is a scratch area pygbag rewrites on every
    run — so the deployable copy lives somewhere the repository can keep.  A
    static folder with no build step is deliberate: Vercel would otherwise need
    Python *and* pygbag on its builders to produce something this machine has
    already produced.
    """
    out = ROOT / "web-dist"
    if out.exists():
        shutil.rmtree(out)
    out.mkdir()
    for item in (ROOT / "web" / "build" / "web").iterdir():
        if item.is_file():
            shutil.copy2(item, out / item.name)
    print(f"published -> {out}")


if __name__ == "__main__":
    code = build()
    if code == 0:
        publish()
    raise SystemExit(code)
