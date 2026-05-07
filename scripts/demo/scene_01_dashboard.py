"""Scene 1 — Dashboard overview + smart search demo.

Wow moment: type a Chinese-tech-style query that doesn't appear in any
filename, and watch the system find the right doc by content.

Standalone: python scripts/demo/scene_01_dashboard.py
Chained:    from scene_01_dashboard import run; run(page)
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _common import (
    goto, scene_marker, step, note, pause,
    type_into, run_standalone, force_fullscreen_keypress,
)


# Query chosen so that none of these tokens appear in `attention_is_all_you_need.pdf`,
# proving the result comes from semantic content matching, not ILIKE on filename.
DEMO_QUERY = "注意力机制 transformer 架构"
EXPECTED_TOP_HIT_FRAGMENT = "attention"


def run(page) -> None:
    scene_marker("Scene 1", "Dashboard + 智能检索 (~60s)")

    # 1. Land on the dashboard.
    # In connect mode, Chrome is already at localhost:5173. We still goto
    # to ensure a clean state (e.g. clear any prior search filter from a
    # previous scene run).
    goto(page, "/")
    pause(1.5, "let sunburst render and tooltip layer settle")

    # 2. Hover over the sunburst centre/inner ring briefly so a viewer sees
    #    the tooltip system is live. We don't depend on the exact wedge
    #    text — just hover the SVG centre.
    step("hover over sunburst centre to surface the tooltip system")
    try:
        sunburst_svg = page.locator("svg").first
        box = sunburst_svg.bounding_box()
        if box:
            cx = box["x"] + box["width"] * 0.5
            cy = box["y"] + box["height"] * 0.5
            page.mouse.move(cx, cy, steps=20)
            pause(2.0, "tooltip dwell")
            # Drift outward to a wedge — proves the layout is interactive.
            page.mouse.move(cx + 80, cy - 40, steps=15)
            pause(2.0, "wedge dwell — show the per-doc tooltip")
        else:
            note("sunburst svg has no bounding box — skipping hover")
    except Exception as e:
        note(f"sunburst hover skipped: {e}")

    # 3. Find the search input by placeholder. Click + slow-type the demo
    #    query so the viewer can read it land character-by-character.
    step('click into the search bar and type the cross-language demo query')
    search_input = page.get_by_placeholder(
        "Search by title, collection, or keyword…",
    ).first
    search_input.click()
    pause(0.8, "let the input get focus")
    type_into(search_input, DEMO_QUERY)
    pause(1.5, "debounced search (300 ms) + server round-trip")

    # 4. Confirm the right doc surfaced. We don't fail the scene if not —
    #    we just print a warning so the operator can see whether the demo
    #    landed before the next scene starts.
    step("verify the expected doc appeared")
    try:
        # Doc rows render the filename inside a <span> inside DocRow. Use
        # locator with text-substring (case-insensitive).
        match = page.locator(f"text=/{EXPECTED_TOP_HIT_FRAGMENT}/i").first
        if match.count() > 0:
            note(f"✓ saw a result containing '{EXPECTED_TOP_HIT_FRAGMENT}'")
        else:
            note(f"⚠ expected '{EXPECTED_TOP_HIT_FRAGMENT}' not visible — "
                 "check the search backend before recording")
    except Exception as e:
        note(f"verification skipped: {e}")

    pause(3.0, "let the viewer see the surfaced result")


if __name__ == "__main__":
    run_standalone(run)
