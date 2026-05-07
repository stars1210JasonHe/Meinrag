"""Scene 3 — Single-doc Q&A with multi-modal citations.

Wow moment: ask a question that draws on text + table + figure chunks.
Click each citation [N] in the answer and watch the PDF tab jump + bbox-
highlight to a different chunk type each time.

Standalone: python scripts/demo/scene_03_single_doc.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _common import (
    BASE_URL, USER_ID,
    goto, scene_marker, step, note, pause, warn,
    type_into, run_standalone,
    wait_for_streaming_done,
)


# Doc to query — the Transformer paper. Picked because it has all 4
# chunk types (text / table / figure / formula) so citations span them.
TARGET_FILENAME_FRAGMENT = "attention_is_all_you_need"

DEMO_QUESTION = "Transformer 架构相比 RNN 有哪些核心优势？请结合论文中的图表说明。"


def _find_doc_id_by_filename(page, fragment: str) -> str | None:
    """Hit the API directly to resolve a filename fragment → doc_id.
    More robust than scraping the DOM for the dashboard doc card."""
    import urllib.request, json
    req = urllib.request.Request(
        f"{BASE_URL.replace('5173', '8000')}/documents?limit=200",
        headers={"X-User-Id": USER_ID},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            docs = json.load(resp).get("documents", [])
    except Exception as e:
        warn(f"could not list docs from API: {e}")
        return None
    for d in docs:
        if fragment.lower() in d["filename"].lower():
            return d["doc_id"]
    return None


def run(page) -> None:
    scene_marker("Scene 3", "单文档问答 + 多模态引用 (~105s)")

    # 1. Resolve doc by filename → navigate directly to the chat page
    # scoped to that doc. This is more reliable than clicking a doc card
    # (cards re-order based on search/filter state from scene 1).
    doc_id = _find_doc_id_by_filename(page, TARGET_FILENAME_FRAGMENT)
    if not doc_id:
        warn(f"no doc found matching '{TARGET_FILENAME_FRAGMENT}' — abort scene")
        return
    note(f"resolved {TARGET_FILENAME_FRAGMENT}* → doc_id={doc_id[:8]}…")

    # Force the chat panel open BEFORE goto — it's stored in localStorage
    # and a previous demo session may have collapsed it. Without this,
    # the streaming answer renders into a hidden panel and the viewer
    # sees the typing but no response appear.
    step("ensure chat panel is expanded (clear localStorage collapse flag)")
    page.evaluate("localStorage.setItem('meinrag.chatPanel.collapsed', '0')")

    goto(page, f"/chat?doc={doc_id}&name=attention_is_all_you_need.pdf")
    pause(2.0, "let chat page mount + PDF tab load")

    # 2. Type the question. The chat input has a placeholder we can locate.
    step("type the multi-modal demo question")
    chat_input = page.get_by_placeholder("Ask anything about your documents…").first
    chat_input.click()
    pause(0.5, "input focus")
    chat_input.type(DEMO_QUESTION, delay=70)
    pause(1.0, "let viewer read the question before sending")

    # 3. Send. The Send button next to the input is enabled once text is present.
    step("send")
    chat_input.press("Enter")
    pause(1.0, "first-token latency")

    # 4. Wait for the streamed answer to finish.
    wait_for_streaming_done(page, timeout_s=90)
    pause(1.5, "let viewer skim the answer")

    # 5. Walk through citations. CitationBadges render as <sup> tags with
    # cursor-pointer class — visible text is just the number, e.g. "1".
    # See frontend/src/components/CitationBadge.jsx.
    pause(2.0, "extra wait for markdown re-render after streaming done")
    step("click each citation to demonstrate multi-modal jump-to-chunk")

    # Diagnostic: see what's actually in the DOM.
    n_sup = page.locator("sup").count()
    n_cursor = page.locator(".cursor-pointer").count()
    note(f"DOM probe: {n_sup} <sup>, {n_cursor} .cursor-pointer")

    citations = page.locator("sup.cursor-pointer")
    if citations.count() == 0:
        # Fallback: any <sup> whose text is a bare number.
        citations = page.locator("sup").filter(has_text=re.compile(r"^\s*\d+\s*$"))
    n_clicked = 0
    note(f"found {citations.count()} citation badges")
    for i in range(min(3, citations.count())):
        try:
            citation = citations.nth(i)
            citation.scroll_into_view_if_needed()
            citation.click()
            n_clicked += 1
            pause(2.5, f"citation {i + 1}: PDF should jump + bbox-highlight")
        except Exception as e:
            note(f"citation {i + 1} click failed: {e}")
            break

    if n_clicked == 0:
        warn("no citations clicked — viewer should manually click [1] [2] [3]")
    else:
        note(f"clicked {n_clicked} citations")

    pause(2.0, "absorb the multi-modal evidence trail")


if __name__ == "__main__":
    run_standalone(run)
