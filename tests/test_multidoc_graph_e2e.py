"""Frontend E2E — multi-doc chunk graph (Phase 4 of the 2026-05-11 batch).

Requires both servers running:
  - Backend:  uv run uvicorn app.main:app --reload     (port 8000)
  - Frontend: cd frontend && npm run dev               (port 5173)
  - Corpus:   at least 3 docs already ingested for the admin user

Skips cleanly when the servers aren't reachable so the offline pytest
suite stays green.

Run:
  uv run pytest tests/test_multidoc_graph_e2e.py -v -s
"""
from __future__ import annotations

import time

import pytest
import requests
from playwright.sync_api import expect, sync_playwright

FRONTEND_URL = "http://localhost:5173"
BACKEND_URL = "http://localhost:8000"
USER_ID = "admin"


def _servers_up() -> bool:
    try:
        requests.get(f"{BACKEND_URL}/health", timeout=2).raise_for_status()
        requests.get(FRONTEND_URL, timeout=2).raise_for_status()
        return True
    except Exception:
        return False


@pytest.fixture(scope="module")
def doc_ids() -> list[str]:
    """Pick three real doc_ids from the corpus. Skip the whole module if
    fewer than three are available — these tests have no value otherwise."""
    if not _servers_up():
        pytest.skip("Backend or frontend not reachable on :8000 / :5173")
    resp = requests.get(
        f"{BACKEND_URL}/documents?limit=20",
        headers={"X-User-Id": USER_ID},
        timeout=5,
    )
    resp.raise_for_status()
    docs = resp.json().get("documents", [])
    if len(docs) < 3:
        pytest.skip(f"Need at least 3 docs in corpus, found {len(docs)}")
    return [d["doc_id"] for d in docs[:3]]


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        yield browser
        browser.close()


@pytest.fixture
def page(browser):
    context = browser.new_context()
    page = context.new_page()
    yield page
    context.close()


def _multi_doc_url(doc_ids: list[str], **extra) -> str:
    qs = "&".join([f"docs={','.join(doc_ids)}"] + [f"{k}={v}" for k, v in extra.items()])
    return f"{FRONTEND_URL}/graph?{qs}"


class TestEntryAndToggle:
    """Entry into the multi-doc chunk view and the view toggle."""

    def test_doc_chunk_toggle_appears_for_multi_doc(self, page, doc_ids):
        page.goto(_multi_doc_url(doc_ids))
        page.wait_for_load_state("networkidle")
        # Doc + Chunk tab buttons should both exist when ≥2 docs are pre-
        # selected. Match by visible text — labels come from i18n defaults.
        expect(page.get_by_role("tab", name="Doc")).to_be_visible()
        expect(page.get_by_role("tab", name="Chunk")).to_be_visible()

    def test_clicking_chunk_tab_updates_url_and_renders_legend(self, page, doc_ids):
        page.goto(_multi_doc_url(doc_ids))
        page.wait_for_load_state("networkidle")
        page.get_by_role("tab", name="Chunk").click()
        # URL gains ?view=chunk
        page.wait_for_url(lambda url: "view=chunk" in url, timeout=5_000)
        # Legend renders with one entry per doc.
        legend = page.get_by_role("group", name="Documents in graph")
        expect(legend).to_be_visible(timeout=10_000)

    def test_single_doc_url_redirects_to_single_doc_view(self, page, doc_ids):
        only_one = doc_ids[0]
        page.goto(f"{FRONTEND_URL}/graph?docs={only_one}")
        # Should bounce to /graph/<id> (the single-doc URL).
        page.wait_for_url(lambda url: f"/graph/{only_one}" in url, timeout=5_000)


class TestFilterAndToggle:
    """Filter input + intra-doc toggle behaviours."""

    def test_filter_input_present_in_chunk_view(self, page, doc_ids):
        page.goto(_multi_doc_url(doc_ids, view="chunk"))
        page.wait_for_load_state("networkidle")
        # Filter input is identified by placeholder text — kept stable in
        # the i18n defaults so this selector survives translation tweaks.
        filter_input = page.get_by_placeholder("Filter chunks (e.g., \"attention\")")
        expect(filter_input).to_be_visible(timeout=10_000)

    def test_typing_filter_updates_url_after_debounce(self, page, doc_ids):
        page.goto(_multi_doc_url(doc_ids, view="chunk"))
        page.wait_for_load_state("networkidle")
        filter_input = page.get_by_placeholder("Filter chunks (e.g., \"attention\")")
        filter_input.fill("attention")
        # 250 ms debounce, then URL should reflect the filter.
        page.wait_for_url(lambda url: "filter=attention" in url, timeout=5_000)

    def test_intra_doc_toggle_updates_url(self, page, doc_ids):
        page.goto(_multi_doc_url(doc_ids, view="chunk"))
        page.wait_for_load_state("networkidle")
        toggle = page.get_by_label("Show intra-doc edges")
        expect(toggle).to_be_visible(timeout=10_000)
        toggle.check()
        page.wait_for_url(lambda url: "intra=1" in url, timeout=5_000)


class TestDeepLinkRestore:
    """Loading a URL with the full state should restore the UI."""

    def test_deep_link_with_view_filter_intra_restores(self, page, doc_ids):
        page.goto(_multi_doc_url(doc_ids, view="chunk", intra=1, filter="model"))
        page.wait_for_load_state("networkidle")
        # All three pieces of state should be reflected in the UI.
        chunk_tab = page.get_by_role("tab", name="Chunk")
        expect(chunk_tab).to_have_attribute("aria-selected", "true", timeout=10_000)
        filter_input = page.get_by_placeholder("Filter chunks (e.g., \"attention\")")
        expect(filter_input).to_have_value("model")
        intra_toggle = page.get_by_label("Show intra-doc edges")
        expect(intra_toggle).to_be_checked()


class TestPerformanceSmoke:
    """Cheap "is it fast enough" sanity check — not a benchmark, just a
    canary. If chunk-view fetch + first canvas paint takes > 8 s in the
    smoke environment, something has degraded badly."""

    def test_chunk_view_first_paint_under_8s(self, page, doc_ids):
        t0 = time.perf_counter()
        page.goto(_multi_doc_url(doc_ids, view="chunk"))
        # Wait for the Legend to mount — proxy for "first paint of the new
        # view is done". Allows up to 8 s; flag visible at the bottom of the
        # canvas indicates rendering started.
        page.get_by_role("group", name="Documents in graph").wait_for(
            state="visible", timeout=8_000,
        )
        elapsed = time.perf_counter() - t0
        print(f"\n[perf] chunk-view first paint: {elapsed:.2f}s")
        assert elapsed < 8.0, f"first paint too slow: {elapsed:.2f}s"
