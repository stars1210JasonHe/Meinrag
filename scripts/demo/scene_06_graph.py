"""Scene 6 — Graph + Open chunk.

You record this scene MANUALLY (per the demo plan) — relive-rendered
graphs are sensitive to network jitter and you wanted control over the
camera. This script is here as a REHEARSAL helper: it walks the same
flow Playwright-controlled so you can see the path before recording.

Standalone: python scripts/demo/scene_06_graph.py

If you want to skip this scene during a `run_all.py` pass, set the
env var `SKIP_SCENE_6=1`.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _common import (
    BASE_URL, USER_ID,
    goto, scene_marker, step, note, pause, warn,
    type_into, run_standalone,
    wait_for_streaming_done,
)


TARGET_FILENAME_FRAGMENT = "attention_is_all_you_need"


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
    scene_marker("Scene 6", "Graph + Open chunk (你录屏) (~75s)")

    if os.environ.get("SKIP_SCENE_6") == "1":
        note("SKIP_SCENE_6=1 set — skipping (you record this manually)")
        return

    # 1. Document-level graph.
    goto(page, "/graph")
    pause(2.5, "wait for force-graph + edges to render and settle")
    note("the doc-level graph is now visible — narrator covers G1 weighting")
    pause(3.0, "narrator: 'edges thickness = supporting pairs, opacity = mean score'")

    # 2. Drill into the Transformer paper.
    doc_id = _resolve_doc_id(TARGET_FILENAME_FRAGMENT)
    if not doc_id:
        warn("Transformer paper not found — abort scene")
        return

    goto(page, f"/graph/{doc_id}")
    pause(3.0, "wait for chunk-level subgraph to render")
    note("now showing chunk-level graph — colors = chunk types (text/table/image/formula)")
    pause(3.0, "narrator: explain chunk-type color coding")

    # 3. Click a node — at this point you'd click a Table or Figure chunk.
    # Since clicking specific nodes via Playwright is fragile (force-graph
    # canvas), leave the actual click to the manual recording. Just print
    # a reminder.
    note("[manual step] click a Table or Figure chunk node, then 'Open chunk'")
    note("[manual step] back in chat, the prepared question fires off")
    pause(5.0, "manual interaction window")


if __name__ == "__main__":
    run_standalone(run)
