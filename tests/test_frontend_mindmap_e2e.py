"""End-to-end test for the mind map page.

Requires:
- backend running on http://localhost:8000
- frontend running on http://localhost:5173
- playwright installed (uv add --dev playwright; python -m playwright install)

Skipped by default. Run with `--run-e2e` (if conftest supports it) or
manually by removing the skip marker.
"""
from __future__ import annotations

import pytest


# If --run-e2e option exists in conftest, use it. Otherwise fall back
# to a module-level skip so collection succeeds.
pytestmark = pytest.mark.skip(
    reason="E2E test — requires running backend + frontend + playwright. "
           "Remove this marker manually to run."
)


def test_mindmap_page_renders_with_existing_doc(page):
    """Smoke test: open mindmap for any existing doc, verify graph renders.

    Precondition: the test user (admin) has at least one doc with chunks
    already uploaded. Use the docs uploaded by other integration tests or
    manually seed one.
    """
    page.goto("http://localhost:5173")
    page.wait_for_load_state("networkidle")

    # The Task 8 implementation added the button with title/aria-label=t('mindmap.title')
    # which in EN renders as "Mind map"
    mindmap_btn = page.locator("button[aria-label='Mind map']").first
    mindmap_btn.click()

    # Wait for navigation to /mindmap/:docId
    page.wait_for_url("**/mindmap/**")

    # react-force-graph renders inside a <canvas> element
    page.wait_for_selector("canvas", timeout=15_000)

    # Legend shows "Node types" heading (from i18n mindmap.nodeTypes)
    page.wait_for_selector("text=Node types", timeout=5_000)


def test_mindmap_error_state_for_nonexistent_doc(page):
    """Navigating directly to an unknown doc_id shows the error state.

    The page should display 'Failed to load mind map' (from i18n mindmap.error),
    not crash the React app.
    """
    page.goto("http://localhost:5173/mindmap/nonexistent-doc-id-xyz")
    page.wait_for_load_state("networkidle")
    page.wait_for_selector("text=Failed to load mind map", timeout=5_000)
