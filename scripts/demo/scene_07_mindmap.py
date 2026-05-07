"""Scene 7 — Mindmap (recursive, conditional 4th layer).

Wow moment: doc summary tree auto-generated from chunk summaries; system
keeps it at 3 layers when content doesn't earn a 4th. Honest framing.

Target doc: long CRS report (R46795) which has the richest structure
on this corpus. Backup: quantum_shell_model_2023.pdf.

Standalone: python scripts/demo/scene_07_mindmap.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _common import (
    BASE_URL, USER_ID,
    goto, scene_marker, step, note, pause, warn,
    type_into, run_standalone,
)


PRIMARY_TARGET = "crs_R46795"
BACKUP_TARGET = "quantum_shell_model_2023"


def _resolve_doc_id(fragment: str) -> str | None:
    import urllib.request, json
    req = urllib.request.Request(
        f"{BASE_URL.replace('5173', '8000')}/documents?limit=200",
        headers={"X-User-Id": USER_ID},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            docs = json.load(resp).get("documents", [])
    except Exception:
        return None
    for d in docs:
        if fragment.lower() in d["filename"].lower():
            return d["doc_id"]
    return None


def run(page) -> None:
    scene_marker("Scene 7", "Mindmap (~50s)")

    doc_id = _resolve_doc_id(PRIMARY_TARGET) or _resolve_doc_id(BACKUP_TARGET)
    if not doc_id:
        warn(f"neither {PRIMARY_TARGET} nor {BACKUP_TARGET} found — abort scene")
        return
    note(f"using doc_id={doc_id[:8]}…")

    goto(page, f"/graph/{doc_id}?mode=mindmap")
    pause(3.0, "let mindmap render — cached responses are <100ms, first gen 15-25s")

    # If the mindmap is loading (LLM call), wait it out.
    step("wait for mindmap tree to be visible")
    try:
        page.wait_for_selector("svg, .mindmap, [data-mindmap]", timeout=30_000)
    except Exception:
        warn("mindmap selector did not appear in 30s — may still be generating")
    pause(3.0, "viewer absorbs the tree shape")

    # Hover a leaf node — narrator points out 'click → jumps to chunk in PDF'
    step("hover a deeper-looking leaf to highlight click target")
    try:
        leaves = page.locator("g.rd3t-leaf-node-base, .rd3t-leaf-node, [data-leaf]")
        if leaves.count() > 0:
            leaves.first.hover()
            pause(3.0, "narrator: 'click any leaf → jumps to that chunk in the PDF'")
    except Exception as e:
        note(f"leaf hover skipped: {e}")

    pause(3.0, "scene close")


if __name__ == "__main__":
    run_standalone(run)
