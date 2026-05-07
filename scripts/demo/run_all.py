"""Run every demo scene end-to-end against the connected Chrome.

Auto-launches Chrome via launch_chrome.py if needed (so this is the
single command you run on demo day after pressing F11).

    uv run python scripts/demo/run_all.py

To skip a scene: set its env var to 1, e.g.
    SKIP_SCENE_2=1 uv run python scripts/demo/run_all.py

Scene 6 (graph + Open chunk) is gated by SKIP_SCENE_6 — recommended
to skip if you're recording it manually:
    SKIP_SCENE_6=1 uv run python scripts/demo/run_all.py
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _common import (
    connect_to_chrome, banner, note, pause, GREEN, CYAN, YELLOW, RESET,
)

# Import each scene's run() function.
from scene_01_dashboard import run as scene_01
from scene_02_upload import run as scene_02
from scene_03_single_doc import run as scene_03
from scene_04_cross_lang import run as scene_04
from scene_05_refusal import run as scene_05
from scene_06_graph import run as scene_06
from scene_07_mindmap import run as scene_07
from scene_08_collection import run as scene_08


# (env_var_name, run_fn) — set env=1 to skip.
SCENES: list[tuple[str, callable]] = [
    ("SKIP_SCENE_1", scene_01),
    ("SKIP_SCENE_2", scene_02),
    ("SKIP_SCENE_3", scene_03),
    ("SKIP_SCENE_4", scene_04),
    ("SKIP_SCENE_5", scene_05),
    ("SKIP_SCENE_6", scene_06),
    ("SKIP_SCENE_7", scene_07),
    ("SKIP_SCENE_8", scene_08),
]


def main() -> int:
    print(f"\n{CYAN}═══ MEINRAG demo orchestrator ═══{RESET}\n")
    print("Connecting to Chrome (auto-launches if needed)…\n")

    with connect_to_chrome() as (browser, context, page):
        # Give the operator 3 seconds to position OBS / hit record.
        for i in range(3, 0, -1):
            print(f"  {YELLOW}Recording starts in {i}…{RESET}", flush=True)
            time.sleep(1)
        print(f"  {GREEN}GO{RESET}\n", flush=True)

        for env_var, scene_fn in SCENES:
            if os.environ.get(env_var) == "1":
                note(f"{env_var} set — skipping {scene_fn.__module__}")
                continue
            try:
                scene_fn(page)
            except Exception as e:
                print(f"\n  {YELLOW}scene {scene_fn.__module__} raised: {e}{RESET}")
                print(f"  {YELLOW}continuing to next scene...{RESET}\n")
            # Brief settle pause between scenes.
            time.sleep(1.5)

    banner("DEMO COMPLETE")
    print(f"  {GREEN}✓{RESET} all scenes executed (or skipped per env)\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
