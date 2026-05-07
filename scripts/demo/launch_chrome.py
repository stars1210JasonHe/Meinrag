"""Launch a dedicated Chrome instance for the demo.

Run this ONCE before running any demo scene. It opens a fresh Chrome
window with:
  - --remote-debugging-port=9222     so Playwright can connect
  - --user-data-dir=<scratch>        so it doesn't clash with your
                                      everyday Chrome (Chrome refuses
                                      remote-debugging on the default
                                      profile)
  - --start-maximized                so the window fills the screen

Once it's open, press F11 to enter fullscreen if you want.
Then run a demo scene (it will connect to this Chrome instead of
launching its own).

    python scripts/demo/launch_chrome.py

To close the demo Chrome cleanly afterwards: just close the window.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

DEBUG_PORT = 9222
DEMO_USER_DATA_DIR = Path(tempfile.gettempdir()) / "meinrag-demo-chrome"


def find_chrome() -> str | None:
    """Try a few standard Chrome install paths on Windows."""
    candidates = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expanduser(r"~\AppData\Local\Google\Chrome\Application\chrome.exe"),
    ]
    for path in candidates:
        if Path(path).exists():
            return path
    # Fall back to PATH
    on_path = shutil.which("chrome.exe") or shutil.which("chrome")
    return on_path


def main() -> int:
    chrome = find_chrome()
    if not chrome:
        print(
            "Could not find chrome.exe. Edit launch_chrome.py and add your "
            "Chrome install path to find_chrome()."
        )
        return 1

    DEMO_USER_DATA_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Launching Chrome: {chrome}")
    print(f"  User data dir: {DEMO_USER_DATA_DIR}")
    print(f"  Debug port:    {DEBUG_PORT}")
    print()
    print("Once Chrome opens:")
    print("  1. (Optional) press F11 to enter fullscreen")
    print("  2. Leave this Chrome window open — run scenes from another terminal")
    print("  3. Close the Chrome window when done")
    print()

    args = [
        chrome,
        f"--remote-debugging-port={DEBUG_PORT}",
        f"--user-data-dir={DEMO_USER_DATA_DIR}",
        "--start-maximized",
        "--no-first-run",
        "--no-default-browser-check",
        "http://localhost:5173",
    ]

    try:
        # Launch Chrome detached so this script returns once it spawns.
        proc = subprocess.Popen(args)
        print(f"Chrome started (PID {proc.pid}). Waiting for it to close…")
        proc.wait()
        print("Chrome closed.")
    except KeyboardInterrupt:
        print("\nLauncher interrupted.")
        return 130

    return 0


if __name__ == "__main__":
    sys.exit(main())
