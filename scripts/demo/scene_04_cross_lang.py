"""Scene 4 — Cross-language synthesis (scoped to AI-policy docs).

Wow moment: ask in Chinese, system understands intent, retrieves from
the explicitly-scoped English subset (4 CRS AI-policy reports), answers
in Chinese with citations pointing to those English PDFs. The viewer
sees the '4 selected documents' chip in the chat input area, so the
synthesis is clearly across that deliberate subset (not random luck).

Standalone: python scripts/demo/scene_04_cross_lang.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _common import (
    BASE_URL, USER_ID,
    goto, scene_marker, step, note, pause, warn,
    type_into, run_standalone,
    wait_for_streaming_done,
)


# The 4 AI-policy CRS reports — explicit scope demonstrates "user
# selected these specific docs, then asked across them."
SCOPE_FILENAME_FRAGMENTS = [
    "crs_R46751_section230",
    "crs_R47843_ai_eo2023",
    "crs_R47569_genai_privacy",
    "crs_R46795_ai_background",
]

DEMO_QUESTION = (
    "请用中文解释 Section 230 的平台责任框架与 "
    "2023 年 AI 行政命令的治理思路有什么不同。"
)


def _resolve_doc_ids(fragments: list[str]) -> list[str]:
    import urllib.request, json
    req = urllib.request.Request(
        f"{BASE_URL.replace('5173', '8000')}/documents?limit=200",
        headers={"X-User-Id": USER_ID},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            docs = json.load(resp).get("documents", [])
    except Exception as e:
        warn(f"could not list docs: {e}")
        return []
    by_frag = {}
    for frag in fragments:
        for d in docs:
            if frag.lower() in d["filename"].lower():
                by_frag[frag] = d["doc_id"]
                break
    return [by_frag[f] for f in fragments if f in by_frag]


def run(page) -> None:
    scene_marker("Scene 4", "跨语言综合查询 (~75s)")

    # Ensure chat panel is expanded — same localStorage issue scene 3 hit.
    page.evaluate("localStorage.setItem('meinrag.chatPanel.collapsed', '0')")

    # Resolve the 4 AI-policy CRS reports → doc_ids → URL scope param.
    # The chat page renders a "4 selected documents" chip when ?doc_ids=
    # is present, giving the viewer a clear signal that the synthesis is
    # across a deliberate subset.
    doc_ids = _resolve_doc_ids(SCOPE_FILENAME_FRAGMENTS)
    if len(doc_ids) < 2:
        warn(f"only resolved {len(doc_ids)} CRS doc(s) — falling back to all docs")
        goto(page, "/chat")
    else:
        note(f"scoping to {len(doc_ids)} AI-policy docs: {SCOPE_FILENAME_FRAGMENTS}")
        goto(page, f"/chat?doc_ids={','.join(doc_ids)}")

    pause(2.5, "viewer sees the 'N selected documents' chip in the input area")

    step("type the cross-language synthesis question")
    chat_input = page.get_by_placeholder("Ask anything about your documents…").first
    chat_input.click()
    pause(0.5, "input focus")
    chat_input.type(DEMO_QUESTION, delay=70)
    pause(1.5, "let viewer read the question — it's longer than scene 3")

    step("send")
    chat_input.press("Enter")
    pause(1.0, "first-token latency")

    wait_for_streaming_done(page, timeout_s=90)
    pause(2.5, "let viewer see the Chinese answer + English citations")

    # Hover over the sources panel briefly so the recording shows the
    # citation list (English PDF filenames despite the Chinese question).
    step("highlight that source PDFs are English while answer is Chinese")
    try:
        sources_section = page.get_by_text("Sources", exact=False).first
        if sources_section.count() > 0:
            sources_section.scroll_into_view_if_needed()
            sources_section.hover()
            pause(2.0, "sources dwell")
    except Exception as e:
        note(f"sources hover skipped: {e}")

    pause(2.0, "absorb the cross-language moment")


if __name__ == "__main__":
    run_standalone(run)
