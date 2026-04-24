"""Graph page mindmap-toggle smoke — Playwright E2E.

Asserts:
  1. Mind Map toggle is present and enabled on /graph/:docId
  2. Clicking it updates the URL to ?mode=mindmap and renders role="tree"
  3. Clicking a branch (role="treeitem") reveals additional treeitems

Self-guarding via module-level skipif: auto-skips if backend (:8000),
frontend (:5173), or corpus is not ready. Safe to include in default
offline suite.

Run explicitly:
  uv run pytest tests/test_graph_mindmap_toggle.py -v -s
"""
from __future__ import annotations

import re

import pytest
import requests
from playwright.sync_api import sync_playwright

FRONTEND_URL = "http://localhost:5173"
BACKEND_URL = "http://localhost:8000"


def _servers_ready():
    try:
        r = requests.get(f"{BACKEND_URL}/health", timeout=2)
        if r.status_code != 200:
            return False, f"backend {r.status_code}"
    except requests.RequestException as e:
        return False, f"backend unreachable: {e}"
    try:
        r = requests.get(FRONTEND_URL, timeout=2)
        if r.status_code != 200:
            return False, f"frontend {r.status_code}"
    except requests.RequestException as e:
        return False, f"frontend unreachable: {e}"
    try:
        docs = requests.get(
            f"{BACKEND_URL}/documents", headers={"X-User-Id": "admin"}, timeout=5
        ).json()
        items = docs.get("documents") or []
        if not items:
            return False, "no documents indexed"
        return True, items[0]["doc_id"]
    except requests.RequestException as e:
        return False, f"documents fetch failed: {e}"


_ready, _reason_or_docid = _servers_ready()

pytestmark = pytest.mark.skipif(
    not _ready, reason=f"servers or corpus not ready: {_reason_or_docid}"
)


def test_graph_mindmap_toggle_renders_tree():
    doc_id = _reason_or_docid
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_context(viewport={"width": 1400, "height": 900}).new_page()
            page.goto(f"{FRONTEND_URL}/graph/{doc_id}", wait_until="networkidle")
            page.wait_for_timeout(1500)

            # Mind Map toggle must be visible and enabled on a doc-scoped page.
            # Use a regex so the test is locale-tolerant (EN "Mind Map" vs ZH "思维导图").
            mindmap_tab = page.get_by_role(
                "tab", name=re.compile(r"mind|思维", re.IGNORECASE)
            )
            mindmap_tab.wait_for(timeout=10000)
            assert mindmap_tab.is_enabled(), (
                "Mind Map toggle should be enabled on /graph/:docId"
            )

            mindmap_tab.click()
            # URL must reflect the mode switch
            page.wait_for_url(lambda url: "mode=mindmap" in url, timeout=5000)

            # Tree can take up to 30 s on first view (cached thereafter).
            # Give 75 s tolerance for LLM tail latency.
            tree_root = page.locator('[role="tree"]')
            tree_root.wait_for(state="visible", timeout=75000)

            # At initialDepth=1, only root + branches are visible.
            treeitems = page.locator('[role="treeitem"]')
            count_before_expand = treeitems.count()
            assert count_before_expand >= 2, (
                f"expected root + >=1 branch at initialDepth=1, got {count_before_expand}"
            )

            # Click the second treeitem (first branch after root) to expand.
            treeitems.nth(1).click()
            page.wait_for_timeout(600)
            count_after_expand = treeitems.count()
            assert count_after_expand > count_before_expand, (
                f"branch click should reveal leaves: "
                f"before={count_before_expand} after={count_after_expand}"
            )
        finally:
            browser.close()
