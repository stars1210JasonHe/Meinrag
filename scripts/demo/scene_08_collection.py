"""Scene 8 — Multi-select + save as collection.

Wow moment: hover-reveal checkboxes, pick a few docs, save the curated
subset by name, then the action bar shows the count + "Ask" entry point.

Standalone: python scripts/demo/scene_08_collection.py
"""
from __future__ import annotations

import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _common import (
    goto, scene_marker, step, note, pause,
    type_into, run_standalone,
)


def run(page) -> None:
    scene_marker("Scene 8", "多选 + 合集 (~30s)")

    goto(page, "/")
    pause(2.0, "settle")

    step("hover doc rows to reveal the per-row checkbox")
    # DocRow checkbox shows on hover. We pick the first 2-3 doc cards
    # and click their checkbox-buttons.
    rows = page.locator("[data-doc-row], .doc-row, [role='row']")
    n_clicked = 0
    for i in range(min(3, rows.count())):
        try:
            row = rows.nth(i)
            row.scroll_into_view_if_needed()
            row.hover()
            pause(0.4, "checkbox reveal")
            # The checkbox is a <button aria-pressed=...> inside the row.
            checkbox = row.locator("button[aria-pressed]").first
            if checkbox.count() > 0:
                checkbox.click()
                n_clicked += 1
                pause(0.5, f"select doc {i + 1}")
        except Exception as e:
            note(f"row {i + 1}: {e}")

    if n_clicked == 0:
        note("no doc rows selected — selectors may not match. Narrator: "
             "'pick 2-3 docs by clicking their checkbox' (manual)")
        pause(4.0, "manual selection window")

    pause(1.5, "show selection count in action bar")

    step("click 'Save as collection' / '保存合集' in the action bar")
    save_btn = page.get_by_role(
        "button",
        name=re.compile(r"save as collection|保存合集|save collection", re.IGNORECASE),
    ).first
    if save_btn.count() > 0:
        save_btn.click()
        pause(1.5, "modal opens")

        step("type a collection name")
        name_input = page.get_by_placeholder(re.compile(r"name|名称", re.IGNORECASE)).first
        if name_input.count() > 0:
            ts = int(time.time()) % 10_000
            name_input.click()
            name_input.type(f"demo-set-{ts}", delay=80)
            pause(1.0, "show the typed name")

            step("submit / 保存")
            confirm_btn = page.get_by_role(
                "button",
                name=re.compile(r"^(save|保存|create|新建).*", re.IGNORECASE),
            ).first
            if confirm_btn.count() > 0:
                confirm_btn.click()
                pause(2.0, "see the success toast + collection appear in sidebar")
    else:
        note("save button not found — narrator: 'click Save as collection in the action bar'")
        pause(3.0, "manual click window")

    pause(2.0, "scene close")


if __name__ == "__main__":
    run_standalone(run)
