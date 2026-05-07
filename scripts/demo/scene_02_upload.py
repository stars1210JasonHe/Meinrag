"""Scene 2 — Upload (description-only, no actual file submission).

Wow moment is conceptual: "drag a PDF in, the system auto-classifies it
and it lands in the right sunburst wedge." We don't actually submit a
file — that would pollute the corpus and the demo can't recover from it
mid-recording. Instead we hover over the Upload button to keep the
viewer's eye on it while the narrator describes what would happen.

Standalone: python scripts/demo/scene_02_upload.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _common import goto, scene_marker, step, note, pause, run_standalone


def run(page) -> None:
    scene_marker("Scene 2", "Upload (描述为主, 不实际上传) (~30s)")

    # Make sure we're on the dashboard so the upload control is visible.
    if "/" not in page.url or page.url.endswith("/chat"):
        goto(page, "/")
        pause(1.0, "settle")

    # Find the Upload button — it's a <label> that wraps a hidden file input.
    # Locator by visible text since the i18n strings are stable.
    step("locate the Upload control in the header")
    # Match either EN or ZH demo language.
    upload_btn = page.get_by_text("Upload", exact=False).first
    if upload_btn.count() == 0:
        upload_btn = page.get_by_text("上传", exact=False).first

    if upload_btn.count() == 0:
        note("Upload control not found by text — skipping hover")
        pause(2.0, "narrator describes upload flow without visual aid")
        return

    # Scroll into view + hover. The viewer sees the cursor land on the
    # button while the narrator describes what dropping a PDF would do.
    upload_btn.scroll_into_view_if_needed()
    pause(0.5, "scroll-into-view settle")
    step("hover the Upload button — narrator describes the auto-classify flow")
    upload_btn.hover()
    pause(4.0, "hover dwell while narrator talks about auto-classification")

    # Drift cursor a bit so the recording doesn't feel frozen on the button.
    box = upload_btn.bounding_box()
    if box:
        cx = box["x"] + box["width"] / 2
        cy = box["y"] + box["height"] / 2
        page.mouse.move(cx + 200, cy + 100, steps=20)
        pause(2.0, "cursor drifts back into the doc area")


if __name__ == "__main__":
    run_standalone(run)
