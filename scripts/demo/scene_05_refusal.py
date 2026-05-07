"""Scene 5 — Honest refusal + web-search fallback.

Wow moment: the system refuses to fabricate when the corpus doesn't
cover the question. Then we point at the "搜索网络" button as the user-
opt-in escape hatch — without clicking it, just describing it.

Standalone: python scripts/demo/scene_05_refusal.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _common import (
    goto, scene_marker, step, note, pause,
    type_into, run_standalone,
    wait_for_streaming_done,
)


DEMO_QUESTION = "中国 2024 年的 GDP 是多少？"


def run(page) -> None:
    scene_marker("Scene 5", "诚实拒答 + 网搜兜底 (~60s)")

    # Ensure chat panel is expanded.
    page.evaluate("localStorage.setItem('meinrag.chatPanel.collapsed', '0')")
    # Fresh chat session — no doc / collection scope.
    goto(page, "/chat")
    # Hard-reload to make sure we're on the latest frontend bundle (HMR
    # sometimes misses module-level const changes like REFUSAL_MARKERS).
    page.reload(wait_until="networkidle")
    pause(2.0, "settle after reload")

    step("type an out-of-corpus question")
    chat_input = page.get_by_placeholder("Ask anything about your documents…").first
    chat_input.click()
    pause(0.5, "input focus")
    chat_input.type(DEMO_QUESTION, delay=70)
    pause(1.0, "let viewer read")

    step("send")
    chat_input.press("Enter")
    pause(1.0, "first-token latency")
    wait_for_streaming_done(page, timeout_s=30)

    pause(3.0, "let viewer absorb the honest refusal")

    # Hover (don't click) the web-search button. Narrator describes
    # the two-step model: refuses by default, user opts into web search.
    # Wait for SupplementActions to render — they appear AFTER the streamed
    # answer is detected as a refusal (small delay for the parent ChatPage
    # to evaluate the answer text and mount the buttons).
    pause(2.0, "wait for supplement-action buttons to mount")

    step("hover '网络搜索' button — narrator describes the escape hatch")
    try:
        # Match by visible text. The button's accessible-name comes from a
        # nested <span>; matching the text directly then walking to the
        # parent button is more robust across Playwright versions.
        web_text = page.get_by_text(
            re.compile(r"网络搜索|search the web", re.IGNORECASE)
        ).first
        if web_text.count() > 0:
            web_text.scroll_into_view_if_needed()
            web_text.hover()
            pause(4.0, "narrator: 'click this and it goes to DuckDuckGo'")
        else:
            note("web-search button not found — narrator describes from script only")
            pause(4.0, "narration without visual aid")
    except Exception as e:
        note(f"hover failed: {e}")

    pause(1.5, "scene close")


if __name__ == "__main__":
    run_standalone(run)
