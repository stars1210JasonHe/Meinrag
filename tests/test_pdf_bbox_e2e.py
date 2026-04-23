"""PDF bbox-highlight regression test — Playwright E2E.

Guards against the class of bug that bit us on 2026-04-23:
`.pdf-highlight-overlay` / `.pdf-highlight-bbox` CSS can silently go dark
if the stylesheet isn't imported, while the React tree still renders the
div. Runtime check: after clicking a source card, the bbox element must
have a nonzero bounding rect.

Excluded from the default offline suite (needs both servers + corpus):
  uv run pytest tests/ --ignore=tests/test_pdf_bbox_e2e.py ...

Run explicitly:
  uv run pytest tests/test_pdf_bbox_e2e.py -v -s

Requires:
  - Backend on http://localhost:8000 with at least one PDF indexed
  - Frontend on http://localhost:5173
"""
from __future__ import annotations

import pytest
import requests
from playwright.sync_api import sync_playwright

FRONTEND_URL = "http://localhost:5173"
BACKEND_URL = "http://localhost:8000"


def _servers_ready() -> tuple[bool, str]:
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
    # Need at least one document in the corpus so the chat has something to cite.
    try:
        docs = requests.get(
            f"{BACKEND_URL}/documents", headers={"X-User-Id": "admin"}, timeout=5
        ).json()
        if not (docs.get("documents") or []):
            return False, "no documents indexed"
    except requests.RequestException as e:
        return False, f"documents fetch failed: {e}"
    return True, "ok"


pytestmark = pytest.mark.skipif(
    not _servers_ready()[0],
    reason=f"servers or corpus not ready: {_servers_ready()[1]}",
)


def test_source_click_renders_visible_bbox():
    """Click a source card → bbox div must appear in DOM AND have nonzero height."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_context(viewport={"width": 1400, "height": 900}).new_page()
            page.goto(f"{FRONTEND_URL}/chat", wait_until="networkidle")
            page.wait_for_timeout(1500)

            textarea = page.locator("textarea, input[type=text]").first
            textarea.wait_for(timeout=15000)
            textarea.fill("what is the main idea?")
            textarea.press("Enter")

            # Wait for source cards (they carry a "p." page label).
            first_card = page.locator("button").filter(has_text="p.").first
            first_card.wait_for(state="visible", timeout=60000)
            page.wait_for_timeout(2000)  # let stream finish, tabs open

            first_card.click()
            page.wait_for_timeout(2500)  # allow Page onLoadSuccess + re-render

            bbox = page.locator(".pdf-highlight-bbox")
            count = bbox.count()
            assert count >= 1, f"no .pdf-highlight-bbox in DOM (count={count})"

            rect = bbox.first.bounding_box()
            assert rect is not None, "bbox element has no bounding rect"
            # The 2026-04-23 bug symptom was h=0 despite the element being in DOM.
            # Both dimensions must be positive pixels.
            assert rect["width"] > 4, f"bbox width too small: {rect}"
            assert rect["height"] > 4, f"bbox height too small: {rect}"
        finally:
            browser.close()
