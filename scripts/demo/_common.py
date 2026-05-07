"""Shared helpers for the demo Playwright scripts.

Each scene file imports from here for:
  - launch_browser(): a configured Chromium with sane recording defaults
  - paced_type(): keyboard-event-based typing with realistic per-char delay
  - wait_for_streaming_done(): block until a streamed chat answer finishes
    (detected by the Send/Stop button reverting back to Send)
  - scene_marker(): prints a banner to terminal + a brief pause so a viewer
    watching the screen recording sees a clean transition between scenes
  - pause(): wait with a console note (so the demo operator knows what's happening)

Headed (visible) Chromium by default. The browser window opens on the same
machine that runs uv — i.e. yours, since the backend + frontend live there
— so anything the script does is visible to your screen recorder.
"""
from __future__ import annotations

import os
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from playwright.sync_api import (
    Browser,
    BrowserContext,
    Page,
    Playwright,
    sync_playwright,
)


BASE_URL = os.environ.get("DEMO_BASE_URL", "http://localhost:5173")
USER_ID = os.environ.get("DEMO_USER_ID", "admin")
VIEWPORT = {"width": 1440, "height": 900}

# Per-character typing delay in ms. 80 ms = ~12 cps, slightly faster than
# average human typing — looks natural on video without being slow.
TYPE_DELAY_MS = 80


# ─── Terminal pretty-print ───────────────────────────────────────────────


GREEN = "\033[32m"
CYAN = "\033[36m"
YELLOW = "\033[33m"
DIM = "\033[2m"
RESET = "\033[0m"


def banner(line: str) -> None:
    print(f"\n{CYAN}{'─' * 70}{RESET}")
    print(f"{CYAN}  {line}{RESET}")
    print(f"{CYAN}{'─' * 70}{RESET}\n", flush=True)


def step(text: str) -> None:
    print(f"  {GREEN}→{RESET} {text}", flush=True)


def note(text: str) -> None:
    print(f"  {DIM}{text}{RESET}", flush=True)


def warn(text: str) -> None:
    print(f"  {YELLOW}![{RESET} {text}", flush=True)


# ─── Browser lifecycle ───────────────────────────────────────────────────


def _detect_screen_size() -> tuple[int, int]:
    """Return (width, height) of the primary monitor. Tries Windows
    ctypes first (most accurate), then tkinter, then a 1920x1080 default."""
    try:
        import ctypes
        user32 = ctypes.windll.user32
        user32.SetProcessDPIAware()
        return user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)
    except Exception:
        pass
    try:
        import tkinter
        root = tkinter.Tk()
        root.withdraw()
        w, h = root.winfo_screenwidth(), root.winfo_screenheight()
        root.destroy()
        return w, h
    except Exception:
        pass
    return 1920, 1080


DEBUG_PORT = 9222


def _is_chrome_responding(port: int = DEBUG_PORT, timeout: float = 1.0) -> bool:
    """Probe the CDP debug endpoint without raising."""
    import urllib.request
    try:
        with urllib.request.urlopen(f"http://localhost:{port}/json/version", timeout=timeout):
            return True
    except Exception:
        return False


def _autostart_chrome(timeout_s: float = 15.0) -> bool:
    """Spawn launch_chrome.py as a detached process and poll until the
    debug port responds. Returns True if Chrome came up in time."""
    import subprocess
    launcher = Path(__file__).parent / "launch_chrome.py"
    note(f"Chrome not on :{DEBUG_PORT} — auto-starting via {launcher.name}")
    # Detach so this script doesn't block on Chrome's lifetime.
    creation_flags = 0
    if sys.platform == "win32":
        # DETACHED_PROCESS = 0x00000008
        creation_flags = 0x00000008
    subprocess.Popen(
        [sys.executable, str(launcher)],
        creationflags=creation_flags,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if _is_chrome_responding():
            note(f"Chrome ready on :{DEBUG_PORT}")
            # Give the page a moment to load localhost:5173 before we connect.
            time.sleep(2)
            return True
        time.sleep(0.5)
    return False


@contextmanager
def connect_to_chrome(*, autostart: bool = True) -> Iterator[tuple[Browser, BrowserContext, Page]]:
    """Connect to a Chrome instance on the CDP debug port.

    If `autostart=True` (default) and no Chrome is responding on the port,
    spawn `launch_chrome.py` ourselves and wait for it to come up. The
    Chrome process stays open after the scene finishes — subsequent scenes
    just reconnect to it. The user closes the window when they're done.

    This is the path that works reliably on Windows. Playwright's bundled
    Chromium has DPI/window-bounds quirks that the user's real Chrome
    doesn't.
    """
    if not _is_chrome_responding():
        if autostart:
            if not _autostart_chrome():
                print(
                    f"\n  {YELLOW}Failed to auto-start Chrome on :{DEBUG_PORT}.{RESET}\n"
                    f"  Try manually:    uv run python scripts/demo/launch_chrome.py\n",
                    flush=True,
                )
                raise SystemExit(1)
        else:
            print(
                f"\n  {YELLOW}No Chrome on :{DEBUG_PORT}.{RESET}\n"
                f"  Run:    uv run python scripts/demo/launch_chrome.py\n",
                flush=True,
            )
            raise SystemExit(1)

    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(f"http://localhost:{DEBUG_PORT}")
        context = browser.contexts[0] if browser.contexts else browser.new_context()
        page = context.pages[0] if context.pages else context.new_page()
        page.bring_to_front()
        try:
            yield browser, context, page
        finally:
            # Don't close — user owns the Chrome instance, may run more scenes.
            pass


@contextmanager
def launch_browser(*, headless: bool = False, slow_mo: int = 0, fullscreen: bool = True) -> Iterator[tuple[Browser, BrowserContext, Page]]:
    """Yield (browser, context, page). Always set up to look good on video.

    Approach (Windows-tested):
      1. Detect actual screen size via ctypes/tkinter.
      2. Launch Chromium with --window-size=W,H + --window-position=0,0
         so the window fills the screen on creation. This is the only
         reliable way — `--start-maximized` and `--start-fullscreen` are
         silently ignored when Playwright sets its own window bounds.
      3. Then send Browser.setWindowBounds via CDP to enter fullscreen
         (F11 mode). If that errors, fall back to maximized.

    User can press F11 to exit fullscreen at any time during the demo.
    """
    # Detect physical screen size (DPI-aware) and logical screen size
    # (NOT DPI-aware — call BEFORE SetProcessDPIAware). Their ratio is
    # the actual display scaling factor as Chromium will see it.
    logical_w = 1920
    try:
        import ctypes
        # GetSystemMetrics WITHOUT DPI-awareness returns logical pixels.
        # Use SystemParametersInfo or fall back to running in a fresh
        # subprocess if needed. Simplest: spawn a quick tkinter probe.
        import subprocess, sys as _sys
        result = subprocess.run(
            [_sys.executable, "-c", "import tkinter; r=tkinter.Tk(); print(r.winfo_screenwidth())"],
            capture_output=True, text=True, timeout=5,
        )
        logical_w = int(result.stdout.strip()) if result.stdout.strip() else 1920
    except Exception:
        pass

    sw, sh = _detect_screen_size()  # physical, post-DPI-aware

    scale = round(sw / logical_w, 2) if logical_w > 0 else 1.0
    if scale < 1.0 or scale > 3.0:
        scale = 1.0  # sanity clamp

    args = [
        f"--window-size={sw},{sh}",
        "--window-position=0,0",
        "--high-dpi-support=1",
        # Force Chromium to render the canvas at the OS scale, so a 1280
        # logical-pixel layout fills a 1920 physical-pixel window. Without
        # this, the page paints at 1280 in a 1920 canvas → black on right.
        f"--force-device-scale-factor={scale}",
    ]
    if fullscreen:
        args += ["--start-fullscreen", "--start-maximized"]

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless, slow_mo=slow_mo, args=args)
        # NOTE: do NOT pass device_scale_factor — letting it default lets
        # Chromium read the OS DPI setting and render at the right scale.
        # Forcing it to 1.0 caused the page to render at logical pixels
        # (e.g. 1280 wide) inside a physical-pixel window (1920 wide) =
        # blank space on the right.
        context = browser.new_context(
            viewport=None,
            extra_http_headers={"X-User-Id": USER_ID},
        )
        page = context.new_page()

        # Log what we attempted so we can see in the terminal.
        note(f"detected screen: {sw}x{sh}; scale={scale}; launched with --window-size + --force-device-scale-factor")

        if fullscreen:
            try:
                cdp = context.new_cdp_session(page)
                window = cdp.send("Browser.getWindowForTarget")
                window_id = window["windowId"]

                # Print pre-state to diagnose.
                pre = cdp.send("Browser.getWindowBounds", {"windowId": window_id})
                note(f"CDP pre-state: {pre.get('bounds')}")

                # setWindowBounds: must transition through "normal" before
                # changing state.
                cdp.send("Browser.setWindowBounds", {
                    "windowId": window_id,
                    "bounds": {"windowState": "normal"},
                })
                cdp.send("Browser.setWindowBounds", {
                    "windowId": window_id,
                    "bounds": {"windowState": "fullscreen"},
                })

                # Print post-state.
                post = cdp.send("Browser.getWindowBounds", {"windowId": window_id})
                note(f"CDP post-state: {post.get('bounds')}")

                # Diagnostic: what size does Playwright think the page is?
                vp = page.evaluate("() => ({w: window.innerWidth, h: window.innerHeight, sw: screen.width, sh: screen.height})")
                note(f"page innerWidth/Height: {vp['w']}x{vp['h']}; screen: {vp['sw']}x{vp['sh']}")

                # If still not full, try plain F11 keypress as a final fallback.
                if vp["w"] < vp["sw"] - 50 or vp["h"] < vp["sh"] - 200:
                    warn("window still smaller than screen — pressing F11 as fallback")
                    page.keyboard.press("F11")
                    import time as _t; _t.sleep(0.5)
                    vp2 = page.evaluate("() => ({w: window.innerWidth, h: window.innerHeight})")
                    note(f"post-F11 innerWidth/Height: {vp2['w']}x{vp2['h']}")

            except Exception as e:
                warn(f"CDP fullscreen failed: {e}")
                try:
                    cdp.send("Browser.setWindowBounds", {
                        "windowId": window_id,
                        "bounds": {"windowState": "maximized"},
                    })
                    note("CDP: fell back to maximized")
                except Exception as e2:
                    warn(f"CDP maximized also failed: {e2}")
        # Pipe browser console errors to our terminal — useful when scenes
        # behave weirdly and we want to see if the frontend logged something.
        page.on("pageerror", lambda exc: warn(f"[browser pageerror] {exc}"))
        page.on("console", lambda msg: (
            warn(f"[browser console.error] {msg.text}") if msg.type == "error" else None
        ))
        try:
            yield browser, context, page
        finally:
            context.close()
            browser.close()


# ─── Scene structure ─────────────────────────────────────────────────────


def scene_marker(scene_id: str, title: str, secs: float = 1.5) -> None:
    """Print a scene banner + pause briefly so the screen-recorder sees a
    clean break between scenes (visible in the post-edited video as a moment
    of calm before the next action)."""
    banner(f"{scene_id}  ·  {title}")
    time.sleep(secs)


def pause(secs: float, why: str = "") -> None:
    """Wait `secs` seconds. Prints a note so the operator knows why we're idle."""
    if why:
        note(f"pause {secs:.1f}s — {why}")
    time.sleep(secs)


# ─── Page-level interactions ─────────────────────────────────────────────


def goto(page: Page, path: str = "/", wait_until: str = "networkidle") -> None:
    """Navigate within the app. Default waits for networkidle so the demo
    starts with no inflight requests confusing the viewer."""
    url = f"{BASE_URL}{path}"
    step(f"goto {url}")
    page.goto(url, wait_until=wait_until)


def force_fullscreen_keypress(page: Page) -> None:
    """Press F11 in the page to force fullscreen mode at the OS level.

    Use this AFTER the first goto() — F11 needs the page focused. CDP
    Browser.setWindowBounds is unreliable on Windows; F11 always works.
    Call this once at the start of your demo flow.
    """
    step("pressing F11 to enter fullscreen")
    page.keyboard.press("F11")
    # Brief settle so the transition completes.
    import time as _t; _t.sleep(0.6)


def paced_type(page: Page, locator_text: str, *, delay_ms: int = TYPE_DELAY_MS, by: str = "placeholder") -> None:
    """DEPRECATED helper signature kept for clarity in scene files.

    Prefer locator.type(text, delay=...) directly — Playwright handles the
    paced typing for you. This wrapper exists so scenes can be one-liners
    that read like English: paced_type(page, '查询关键词')."""
    raise NotImplementedError("use locator.type(text, delay=delay_ms) directly")


def type_into(locator, text: str, *, delay_ms: int = TYPE_DELAY_MS) -> None:
    """Type `text` into `locator` with paced delay. Locator must be focused
    or focusable. Clicks first to ensure focus."""
    step(f'type: "{text}"')
    locator.click()
    locator.type(text, delay=delay_ms)


# ─── Streaming detection ─────────────────────────────────────────────────


def wait_for_streaming_done(page: Page, timeout_s: float = 90.0) -> None:
    """Block until the chat answer finishes streaming.

    Detection: while a stream is active, the input bar shows a 'Stop' button
    (red, with a square icon) instead of the normal 'Send' button. When the
    stream completes (or the user clicks stop), it reverts to Send. We watch
    for the Stop button to disappear.
    """
    step("waiting for streamed answer to complete…")

    deadline = time.time() + timeout_s
    # 1) Wait for the Stop button to actually appear (i.e., generation
    # has started). Some queries are very fast; the Stop button may flash
    # and be gone before we check, so this is best-effort with a short wait.
    try:
        page.get_by_role("button", name=lambda n: bool(n and "stop" in n.lower())).wait_for(
            state="visible", timeout=5_000,
        )
    except Exception:
        # Already done before we looked — fine.
        return

    # 2) Wait for it to disappear.
    while time.time() < deadline:
        stop_btn = page.get_by_role("button", name=lambda n: bool(n and "stop" in n.lower()))
        if stop_btn.count() == 0 or not stop_btn.first.is_visible():
            return
        time.sleep(0.25)
    warn(f"streaming did not finish within {timeout_s}s — moving on")


def wait_for_first_token(page: Page, timeout_s: float = 30.0) -> None:
    """Block until the first chunk of streamed text is visible — useful for
    pacing the next narrated line (you don't want to read the wow line
    while the chat is still loading)."""
    step("waiting for first token…")
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        # Heuristic: the assistant message bubble has at least 5 chars.
        # We look for any element matching role=article (typical message
        # container) — frontend uses role="region" wrappers; fall back to
        # text-presence.
        try:
            page.wait_for_function(
                """() => {
                    const msgs = document.querySelectorAll('[data-role="ai-message"], .ai-message, [role="article"]');
                    for (const m of msgs) {
                        if (m.innerText && m.innerText.trim().length >= 5) return true;
                    }
                    return false;
                }""",
                timeout=1_500,
            )
            return
        except Exception:
            pass
        time.sleep(0.2)
    warn("no first-token signal observed — moving on regardless")


# ─── Standalone scene wrapper ────────────────────────────────────────────


def run_standalone(scene_func, *, mode: str = "connect") -> None:
    """Boilerplate so each scene file can be run directly:

        if __name__ == "__main__":
            run_standalone(run)

    mode="connect" (default): connect to the Chrome instance the user
        launched via `scripts/demo/launch_chrome.py`. The right path on
        Windows — uses the user's real Chrome, which handles DPI correctly.
    mode="launch": launch a fresh Playwright Chromium. Has known DPI
        issues on Windows; kept for non-Windows or quick iteration.
    """
    if mode == "connect":
        ctx = connect_to_chrome()
    elif mode == "launch":
        ctx = launch_browser(headless=False)
    else:
        raise ValueError(f"unknown mode: {mode!r}")

    with ctx as (browser, context, page):
        try:
            scene_func(page)
        except Exception:
            warn("scene raised — leaving browser open for inspection")
            time.sleep(30)
            raise
        else:
            note("scene complete — Chrome left open for next scene")
            time.sleep(2)
