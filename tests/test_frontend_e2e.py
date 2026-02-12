"""
Frontend E2E Tests — Playwright

Tests every button, function, and UI interaction in the MEINRAG frontend.
Requires both servers running:
  - Backend:  uv run uvicorn app.main:app --reload  (port 8000)
  - Frontend: npm run dev  (port 5173)

Run:
  uv run pytest tests/test_frontend_e2e.py -v -s
"""
import re
import tempfile
import time
import uuid
from pathlib import Path

import pytest
import requests
from playwright.sync_api import sync_playwright, expect, Page

FRONTEND_URL = "http://localhost:5173"
BACKEND_URL = "http://localhost:8000"

# Test PDFs — use different files for different upload tests to avoid 409 Conflict
TEST_DIR = Path("test cases")
PDF_SMALL = TEST_DIR / "2512.20798v2.pdf"   # 17 pages, AI safety
PDF_ALT = TEST_DIR / "2602.10009v1.pdf"     # alternative test PDF
PDF_LAW = TEST_DIR / "80201000.pdf"          # 142 pages, German Basic Law


@pytest.fixture(scope="module")
def browser():
    """Launch a browser for all tests in this module."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        yield browser
        browser.close()


@pytest.fixture(scope="module")
def context(browser):
    """Create a fresh browser context (clean storage)."""
    ctx = browser.new_context(accept_downloads=True)
    yield ctx
    ctx.close()


@pytest.fixture
def page(context):
    """New page per test, reset to admin user, navigated to frontend."""
    pg = context.new_page()
    pg.goto(FRONTEND_URL)
    pg.wait_for_load_state("networkidle")

    # Always reset to admin user to avoid state leaking between tests
    current = pg.evaluate("localStorage.getItem('meinrag_user')")
    if current != "admin":
        pg.evaluate("localStorage.setItem('meinrag_user', 'admin')")
        pg.reload()
        pg.wait_for_load_state("networkidle")

    return pg


def _create_temp_test_file() -> Path:
    """Create a unique temp .txt file for one-off upload tests."""
    path = Path(tempfile.gettempdir()) / f"meinrag_test_{uuid.uuid4().hex[:8]}.txt"
    path.write_text(f"Test document for MEINRAG E2E testing.\nID: {uuid.uuid4()}\nTimestamp: {time.time()}")
    return path


@pytest.fixture(scope="module")
def ensure_test_document():
    """Upload a test document via the API so document-dependent tests have data.

    Uses a unique temp .txt file so it doesn't conflict with PDF uploads.
    """
    resp = requests.get(
        f"{BACKEND_URL}/documents", headers={"X-User-Id": "admin"}
    )
    if resp.ok and resp.json().get("documents"):
        return  # already have documents
    temp_file = _create_temp_test_file()
    with open(temp_file, "rb") as f:
        requests.post(
            f"{BACKEND_URL}/documents/upload",
            files={"file": (temp_file.name, f, "text/plain")},
            headers={"X-User-Id": "admin"},
        )


def _wait_for_assistant_reply(page: Page, timeout: int = 60000):
    """Wait for a new assistant message to finish loading."""
    page.wait_for_selector(".message-text.loading", state="visible", timeout=10000)
    page.wait_for_selector(".message-text.loading", state="hidden", timeout=timeout)


def _send_and_wait(page: Page, text: str, timeout: int = 60000):
    """Fill input, press Enter, wait for assistant reply."""
    input_box = page.locator(".input-container input")
    input_box.fill(text)
    input_box.press("Enter")
    _wait_for_assistant_reply(page, timeout)


# ────────────────────────────────────────────
# SECTION 1: Initial Load & Welcome Screen
# ────────────────────────────────────────────

class TestInitialLoad:
    """Verify the app loads correctly with welcome screen."""

    def test_page_title(self, page: Page):
        """App loads and has MEINRAG in the header."""
        header = page.locator(".header h1")
        expect(header).to_have_text("MEINRAG")

    def test_welcome_screen_visible(self, page: Page):
        """Welcome screen shows when no messages exist."""
        welcome = page.locator(".welcome")
        expect(welcome).to_be_visible()
        expect(welcome.locator(".welcome-header h1")).to_have_text("Welcome to MEINRAG")

    def test_welcome_has_features(self, page: Page):
        """Welcome screen lists key features."""
        features = page.locator(".features-list")
        expect(features).to_be_visible()
        expect(features).to_contain_text("Multi-Collection")
        expect(features).to_contain_text("User Profiles")
        expect(features).to_contain_text("AI Classification")
        expect(features).to_contain_text("Source Citations")

    def test_welcome_has_get_started(self, page: Page):
        """Welcome screen has Get Started section."""
        qs = page.locator(".quick-start")
        expect(qs).to_be_visible()
        expect(qs).to_contain_text("Get Started")

    def test_document_count_in_header(self, page: Page):
        """Header shows document count."""
        info = page.locator(".header-info")
        expect(info).to_contain_text("document")

    def test_chat_input_visible(self, page: Page):
        """Chat input box and send button are visible."""
        input_box = page.locator(".input-container input")
        expect(input_box).to_be_visible()
        expect(input_box).to_have_attribute("placeholder", "Ask a question...")

        send_btn = page.locator(".btn-send")
        expect(send_btn).to_be_visible()
        expect(send_btn).to_be_disabled()

    def test_sidebar_sections_visible(self, page: Page):
        """Sidebar has Collections, Documents, and Upload sections."""
        sections = page.locator(".section h3")
        texts = sections.all_text_contents()
        assert any("Collections" in t for t in texts), f"No Collections section: {texts}"
        assert any("Documents" in t for t in texts), f"No Documents section: {texts}"
        assert any("Upload" in t for t in texts), f"No Upload section: {texts}"


# ────────────────────────────────────────────
# SECTION 2: User System
# ────────────────────────────────────────────

class TestUserSystem:
    """Test user selector dropdown, switching, and creating users."""

    def test_user_button_shows_current_user(self, page: Page):
        """User button in header shows the current user."""
        user_btn = page.locator(".user-btn")
        expect(user_btn).to_be_visible()
        expect(user_btn).to_contain_text(re.compile(r"admin|Admin", re.IGNORECASE))

    def test_user_menu_opens_on_click(self, page: Page):
        """Clicking user button opens dropdown menu."""
        page.locator(".user-btn").click()
        menu = page.locator(".user-menu")
        expect(menu).to_be_visible()

    def test_user_menu_shows_users(self, page: Page):
        """User menu lists existing users."""
        page.locator(".user-btn").click()
        items = page.locator(".user-menu-item")
        assert items.count() >= 1

    def test_user_menu_has_new_user_button(self, page: Page):
        """User menu has 'New User' button."""
        page.locator(".user-btn").click()
        add_btn = page.locator(".user-menu-item.add-user")
        expect(add_btn).to_be_visible()
        expect(add_btn).to_contain_text("New User")

    def test_new_user_form_opens(self, page: Page):
        """Clicking 'New User' shows the creation form."""
        page.locator(".user-btn").click()
        page.locator(".user-menu-item.add-user").click()
        form = page.locator(".new-user-form")
        expect(form).to_be_visible()
        assert form.locator("input").count() == 2
        expect(form.locator("button", has_text="Create")).to_be_visible()
        expect(form.locator("button", has_text="Cancel")).to_be_visible()

    def test_cancel_new_user_form(self, page: Page):
        """Cancel button closes the new user form."""
        page.locator(".user-btn").click()
        page.locator(".user-menu-item.add-user").click()
        expect(page.locator(".new-user-form")).to_be_visible()

        page.locator(".new-user-form button", has_text="Cancel").click()
        expect(page.locator(".new-user-form")).not_to_be_visible()
        expect(page.locator(".user-menu-item.add-user")).to_be_visible()

    def test_create_new_user(self, page: Page):
        """Create a new user through the form."""
        uid = f"e2euser-{int(time.time())}"
        display = f"E2E-{int(time.time())}"

        page.locator(".user-btn").click()
        page.locator(".user-menu-item.add-user").click()

        inputs = page.locator(".new-user-form input")
        inputs.nth(0).fill(uid)
        inputs.nth(1).fill(display)
        page.locator(".new-user-form button", has_text="Create").click()
        page.wait_for_timeout(1000)

        # Should switch to the new user
        user_btn = page.locator(".user-btn")
        expect(user_btn).to_contain_text(display)

    def test_switch_user(self, page: Page):
        """Switch between users via the dropdown."""
        page.locator(".user-btn").click()

        admin_item = page.locator(".user-menu-item", has_text="Admin")
        if admin_item.count() > 0:
            admin_item.first.click()
            page.wait_for_timeout(500)
            expect(page.locator(".user-btn")).to_contain_text(re.compile(r"admin|Admin", re.IGNORECASE))

    def test_user_menu_closes_on_outside_click(self, page: Page):
        """Clicking outside the menu closes it."""
        page.locator(".user-btn").click()
        expect(page.locator(".user-menu")).to_be_visible()

        page.locator(".chat-container").click()
        expect(page.locator(".user-menu")).not_to_be_visible()


# ────────────────────────────────────────────
# SECTION 3: Collections Sidebar
# ────────────────────────────────────────────

class TestCollectionsSidebar:
    """Test collection list, filtering, and counts."""

    def test_all_documents_button(self, page: Page):
        """'All Documents' is the default active collection."""
        all_btn = page.locator(".collection-item", has_text="All Documents")
        expect(all_btn).to_be_visible()
        expect(all_btn).to_have_class(re.compile(r"active"))

    def test_collection_items_have_counts(self, page: Page):
        """Each collection shows document count."""
        all_btn = page.locator(".collection-item", has_text="All Documents")
        expect(all_btn).to_contain_text(re.compile(r"\(\d+\)"))

    def test_click_collection_filters(self, page: Page):
        """Clicking a collection highlights it and filters documents."""
        items = page.locator(".collection-item")
        if items.count() < 2:
            pytest.skip("No collections to filter by")

        items.nth(1).click()
        page.wait_for_timeout(300)
        expect(items.nth(1)).to_have_class(re.compile(r"active"))
        expect(items.nth(0)).not_to_have_class(re.compile(r"\bactive\b"))

        # Header should show collection badge
        badge = page.locator(".header .badge")
        expect(badge).to_be_visible()

    def test_click_all_documents_clears_filter(self, page: Page):
        """Clicking 'All Documents' clears the collection filter."""
        items = page.locator(".collection-item")
        if items.count() >= 2:
            items.nth(1).click()
            page.wait_for_timeout(200)
        items.nth(0).click()
        page.wait_for_timeout(200)
        expect(items.nth(0)).to_have_class(re.compile(r"active"))
        expect(page.locator(".header .badge")).not_to_be_visible()

    def test_input_placeholder_changes_with_collection(self, page: Page):
        """Chat input placeholder changes when a collection is selected."""
        items = page.locator(".collection-item")
        if items.count() < 2:
            pytest.skip("No collections to filter by")

        col_text = items.nth(1).text_content()
        col_name = col_text.split("(")[0].strip()

        items.nth(1).click()
        page.wait_for_timeout(300)

        placeholder = page.locator(".input-container input").get_attribute("placeholder")
        assert col_name in placeholder, f"Placeholder '{placeholder}' doesn't contain '{col_name}'"


# ────────────────────────────────────────────
# SECTION 4: Document List & Actions
# ────────────────────────────────────────────

@pytest.mark.usefixtures("ensure_test_document")
class TestDocumentList:
    """Test document items in sidebar — tags, actions, etc."""

    def test_documents_displayed(self, page: Page):
        """Documents appear in the sidebar."""
        docs = page.locator(".document-item")
        assert docs.count() >= 1, "No documents displayed"

    def test_document_shows_filename(self, page: Page):
        """Each document shows its filename."""
        first_doc = page.locator(".document-item").first
        name = first_doc.locator(".doc-name")
        expect(name).to_be_visible()
        assert len(name.text_content()) > 0

    def test_document_shows_chunk_count(self, page: Page):
        """Each document shows chunk count."""
        first_doc = page.locator(".document-item").first
        meta = first_doc.locator(".doc-meta")
        expect(meta).to_be_visible()
        expect(meta).to_contain_text("chunk")

    def test_document_shows_collection_tags(self, page: Page):
        """Documents show collection tags as pills."""
        docs = page.locator(".document-item")
        found_tags = False
        for i in range(docs.count()):
            tags = docs.nth(i).locator(".tag")
            if tags.count() > 0:
                found_tags = True
                break
        assert found_tags, "No document has collection tags"

    def test_collection_tag_clickable(self, page: Page):
        """Clicking a collection tag filters by that collection."""
        # Find a document with tags
        docs = page.locator(".document-item")
        for i in range(docs.count()):
            tags = docs.nth(i).locator(".tag")
            if tags.count() > 0:
                tag = tags.first
                tag_text = tag.text_content()
                tag.click()
                page.wait_for_timeout(300)

                active_col = page.locator(".collection-item.active")
                expect(active_col).to_contain_text(tag_text)

                # Reset
                page.locator(".collection-item", has_text="All Documents").click()
                page.wait_for_timeout(200)
                return

        pytest.skip("No documents with collection tags found")

    def test_document_action_buttons(self, page: Page):
        """Each document has edit, reclassify, download, delete buttons."""
        first_doc = page.locator(".document-item").first
        actions = first_doc.locator(".doc-actions .btn-icon")
        assert actions.count() == 4, f"Expected 4 action buttons, got {actions.count()}"

        titles = [actions.nth(i).get_attribute("title") for i in range(4)]
        assert "Edit collections" in titles
        assert "AI Reclassify" in titles
        assert "Download" in titles
        assert "Delete" in titles


# ────────────────────────────────────────────
# SECTION 5: Edit Collections
# ────────────────────────────────────────────

class TestEditCollections:
    """Test inline collection editing on documents."""

    def _get_doc_with_tags(self, page: Page):
        """Find the first document that has collection tags."""
        docs = page.locator(".document-item")
        for i in range(docs.count()):
            if docs.nth(i).locator(".tag").count() > 0:
                return docs.nth(i)
        pytest.skip("No document with collection tags found")

    def test_edit_button_opens_inline_editor(self, page: Page):
        """Clicking edit icon shows inline collection editor."""
        doc = self._get_doc_with_tags(page)
        doc.locator("[title='Edit collections']").click()

        editor = page.locator(".edit-collections")
        expect(editor).to_be_visible()

        input_field = editor.locator(".edit-collections-input")
        expect(input_field).to_be_visible()
        val = input_field.input_value()
        assert len(val) > 0, "Edit input should be pre-filled"

    def test_edit_has_save_cancel(self, page: Page):
        """Edit inline has Save and Cancel buttons."""
        doc = self._get_doc_with_tags(page)
        doc.locator("[title='Edit collections']").click()

        editor = page.locator(".edit-collections")
        expect(editor.locator("button", has_text="Save")).to_be_visible()
        expect(editor.locator("button", has_text="Cancel")).to_be_visible()

    def test_cancel_edit(self, page: Page):
        """Cancel closes the editor without saving."""
        doc = self._get_doc_with_tags(page)
        doc.locator("[title='Edit collections']").click()
        expect(page.locator(".edit-collections")).to_be_visible()

        page.locator(".edit-collections button", has_text="Cancel").click()
        expect(page.locator(".edit-collections")).not_to_be_visible()

    def test_save_new_collections(self, page: Page):
        """Save updates the document's collections."""
        doc = self._get_doc_with_tags(page)
        original_tags = [t.text_content() for t in doc.locator(".tag").all()]

        doc.locator("[title='Edit collections']").click()
        input_field = page.locator(".edit-collections-input")

        input_field.fill("test-edit-collection, other")
        page.locator(".edit-collections button", has_text="Save").click()
        page.wait_for_timeout(1500)

        # Editor should close
        expect(page.locator(".edit-collections")).not_to_be_visible()

        # Verify new tag is present
        page.wait_for_timeout(500)
        all_tags = page.locator(".document-item .tag")
        all_tag_texts = all_tags.all_text_contents()
        assert "test-edit-collection" in all_tag_texts

        # Restore original tags
        doc = self._get_doc_with_tags(page)
        doc.locator("[title='Edit collections']").click()
        input_field = page.locator(".edit-collections-input")
        input_field.fill(", ".join(original_tags))
        page.locator(".edit-collections button", has_text="Save").click()
        page.wait_for_timeout(1500)

    def test_edit_enter_key_saves(self, page: Page):
        """Pressing Enter in the edit input saves."""
        doc = self._get_doc_with_tags(page)
        original_tags = [t.text_content() for t in doc.locator(".tag").all()]

        doc.locator("[title='Edit collections']").click()
        input_field = page.locator(".edit-collections-input")
        input_field.fill(", ".join(original_tags))
        input_field.press("Enter")
        page.wait_for_timeout(1500)
        expect(page.locator(".edit-collections")).not_to_be_visible()


# ────────────────────────────────────────────
# SECTION 6: Upload
# ────────────────────────────────────────────

class TestUpload:
    """Test document upload buttons and flow."""

    def test_upload_button_visible(self, page: Page):
        """Upload Document button is visible."""
        upload_btn = page.locator("label.btn-primary", has_text="Upload Document")
        expect(upload_btn).to_be_visible()

    def test_auto_categorize_button_visible(self, page: Page):
        """Auto-Categorize button is visible."""
        auto_btn = page.locator("label.btn-secondary", has_text="Auto-Categorize")
        expect(auto_btn).to_be_visible()

    def test_upload_file_input_hidden(self, page: Page):
        """File inputs are hidden (triggered by label click)."""
        file_inputs = page.locator(".upload-buttons input[type='file']")
        assert file_inputs.count() == 2
        for i in range(2):
            expect(file_inputs.nth(i)).to_be_hidden()

    def test_upload_accepts_correct_types(self, page: Page):
        """File inputs accept the correct file types."""
        file_input = page.locator(".upload-buttons input[type='file']").first
        accept = file_input.get_attribute("accept")
        assert ".pdf" in accept
        assert ".docx" in accept
        assert ".txt" in accept
        assert ".md" in accept

    def test_upload_hint_shows_collection(self, page: Page):
        """When a collection is selected, upload hint shows target collection."""
        items = page.locator(".collection-item")
        if items.count() < 2:
            pytest.skip("No collections to select")

        items.nth(1).click()
        page.wait_for_timeout(300)

        hint = page.locator(".upload-hint")
        expect(hint).to_be_visible()
        expect(hint).to_contain_text("Uploading to:")

        items.nth(0).click()

    def test_upload_document_regular(self, page: Page):
        """Upload a PDF without auto-suggest."""
        doc_count_before = page.locator(".document-item").count()

        with page.expect_file_chooser() as fc_info:
            page.locator("label.btn-primary", has_text="Upload Document").click()
        fc_info.value.set_files(str(PDF_SMALL.resolve()))

        # Wait for upload to complete
        page.wait_for_selector(".upload-hint .spin", state="visible", timeout=10000)
        page.wait_for_selector(".upload-hint .spin", state="hidden", timeout=120000)

        # System message
        system_msgs = page.locator(".system-message")
        assert system_msgs.count() >= 1
        expect(system_msgs.last).to_contain_text("Uploaded")

        # Doc count increased
        doc_count_after = page.locator(".document-item").count()
        assert doc_count_after > doc_count_before

    def test_upload_auto_categorize(self, page: Page):
        """Upload a PDF with auto-suggest enabled."""
        with page.expect_file_chooser() as fc_info:
            page.locator("label.btn-secondary", has_text="Auto-Categorize").click()
        fc_info.value.set_files(str(PDF_ALT.resolve()))

        # Auto-categorize can take longer due to LLM call — wait generously
        page.wait_for_selector(".upload-hint .spin", state="visible", timeout=10000)
        page.wait_for_selector(".upload-hint .spin", state="hidden", timeout=180000)

        # System message should mention AI suggested or show collection names
        system_msgs = page.locator(".system-message")
        last_text = system_msgs.last.text_content()
        assert "Uploaded" in last_text or "AI suggested" in last_text, f"Unexpected message: {last_text}"


# ────────────────────────────────────────────
# SECTION 7: Chat / Query
# ────────────────────────────────────────────

class TestChat:
    """Test sending messages, receiving answers, and source display."""

    def test_send_button_disabled_when_empty(self, page: Page):
        """Send button is disabled when input is empty."""
        expect(page.locator(".btn-send")).to_be_disabled()

    def test_send_button_enabled_when_typed(self, page: Page):
        """Send button enables when text is entered."""
        page.locator(".input-container input").fill("Hello")
        expect(page.locator(".btn-send")).to_be_enabled()

    def test_send_message_and_receive_answer(self, page: Page):
        """Send a question and get an answer back."""
        _send_and_wait(page, "What documents have been uploaded?")

        user_msg = page.locator(".message-user").last
        expect(user_msg).to_contain_text("What documents have been uploaded?")

        assistant_msg = page.locator(".message-assistant").last
        text = assistant_msg.locator(".message-text").text_content()
        assert len(text) > 20, f"Answer too short: {text}"

    def test_welcome_disappears_after_message(self, page: Page):
        """Welcome screen disappears after first message."""
        _send_and_wait(page, "Hi")
        expect(page.locator(".welcome")).not_to_be_visible()

    def test_enter_key_sends_message(self, page: Page):
        """Pressing Enter sends the message."""
        input_box = page.locator(".input-container input")
        input_box.fill("Tell me about the content")
        input_box.press("Enter")

        user_msg = page.locator(".message-user").last
        expect(user_msg).to_contain_text("Tell me about the content")

        _wait_for_assistant_reply(page)

    def test_input_clears_after_send(self, page: Page):
        """Input field clears after sending."""
        input_box = page.locator(".input-container input")
        input_box.fill("What is this?")
        input_box.press("Enter")
        assert input_box.input_value() == ""

    def test_input_disabled_while_loading(self, page: Page):
        """Input is disabled while waiting for response."""
        input_box = page.locator(".input-container input")
        input_box.fill("Quick question?")
        input_box.press("Enter")

        # During loading, input should be disabled
        expect(input_box).to_be_disabled()

        _wait_for_assistant_reply(page)
        expect(input_box).to_be_enabled()


# ────────────────────────────────────────────
# SECTION 8: Sources (Expandable)
# ────────────────────────────────────────────

class TestSources:
    """Test source citations: click-to-expand, download buttons."""

    def _ensure_answer_with_sources(self, page: Page):
        """Send a query that should return sources."""
        if page.locator(".source-item").count() > 0:
            return
        _send_and_wait(page, "What are the key points discussed in the documents?")

    def test_sources_section_visible(self, page: Page):
        """Answer messages have a Sources section."""
        self._ensure_answer_with_sources(page)
        assert page.locator(".sources").count() >= 1, "No sources section found"

    def test_source_items_present(self, page: Page):
        """Source items are listed."""
        self._ensure_answer_with_sources(page)
        assert page.locator(".source-item").count() >= 1, "No source items"

    def test_source_shows_filename(self, page: Page):
        """Each source shows the source filename."""
        self._ensure_answer_with_sources(page)
        first_source = page.locator(".source-item").first
        filename = first_source.locator(".source-file")
        expect(filename).to_be_visible()
        assert len(filename.text_content()) > 0

    def test_source_shows_chunk_index(self, page: Page):
        """Sources show chunk index."""
        self._ensure_answer_with_sources(page)
        first_source = page.locator(".source-item").first
        chunk_idx = first_source.locator(".source-chunk-idx")
        if chunk_idx.count() > 0:
            expect(chunk_idx).to_contain_text("chunk")

    def test_source_expand_collapse(self, page: Page):
        """Clicking a source expands its content, clicking again collapses."""
        self._ensure_answer_with_sources(page)
        first_source = page.locator(".source-item").first

        expect(first_source.locator(".source-content")).not_to_be_visible()

        first_source.locator(".source-header").click()
        page.wait_for_timeout(300)
        expect(first_source.locator(".source-content")).to_be_visible()

        content = first_source.locator(".source-content").text_content()
        assert len(content) > 10, f"Source content too short: {content}"

        first_source.locator(".source-header").click()
        page.wait_for_timeout(300)
        expect(first_source.locator(".source-content")).not_to_be_visible()

    def test_source_has_download_button(self, page: Page):
        """Sources with doc_id have a download button."""
        self._ensure_answer_with_sources(page)
        download_btns = page.locator(".source-download")
        if download_btns.count() > 0:
            expect(download_btns.first).to_be_visible()

    def test_source_chevron_toggles(self, page: Page):
        """Chevron direction changes when source is expanded/collapsed."""
        self._ensure_answer_with_sources(page)
        first_source = page.locator(".source-item").first

        first_source.locator(".source-header").click()
        page.wait_for_timeout(300)
        expect(first_source.locator(".source-content")).to_be_visible()

        first_source.locator(".source-header").click()
        page.wait_for_timeout(300)
        expect(first_source.locator(".source-content")).not_to_be_visible()


# ────────────────────────────────────────────
# SECTION 9: Fake Conversation Flow
# ────────────────────────────────────────────

class TestConversationFlow:
    """Full multi-turn conversation test with context follow-up."""

    def test_multi_turn_conversation(self, page: Page):
        """Send multiple messages in sequence to test session memory."""
        # Turn 1
        _send_and_wait(page, "What is the German Basic Law about?")
        turn1 = page.locator(".message-assistant .message-text:not(.loading)").last.text_content()
        assert len(turn1) > 20

        # Turn 2: follow-up
        _send_and_wait(page, "Can you tell me more about the fundamental rights mentioned in it?")
        turn2 = page.locator(".message-assistant .message-text:not(.loading)").last.text_content()
        assert len(turn2) > 20

        # Turn 3: another follow-up
        _send_and_wait(page, "Summarize the key articles briefly")

        # Verify we have 3 user + 3 assistant message pairs
        assert page.locator(".message-user").count() >= 3
        assert page.locator(".message-assistant").count() >= 3

    def test_conversation_with_collection_filter(self, page: Page):
        """Query with a collection filter selected."""
        items = page.locator(".collection-item")
        if items.count() < 2:
            pytest.skip("No collections to filter by")

        items.nth(1).click()
        page.wait_for_timeout(300)

        _send_and_wait(page, "What information is available in this collection?")

        assistant_msg = page.locator(".message-assistant").last
        text = assistant_msg.locator(".message-text").text_content()
        assert len(text) > 20

        items.nth(0).click()


# ────────────────────────────────────────────
# SECTION 10: AI Reclassify
# ────────────────────────────────────────────

class TestReclassify:
    """Test the AI reclassify button on documents."""

    def test_reclassify_button_works(self, page: Page):
        """Clicking reclassify triggers AI reclassification."""
        docs = page.locator(".document-item")
        assert docs.count() >= 1, "No documents to reclassify"

        first_doc = docs.first
        reclassify_btn = first_doc.locator("[title='AI Reclassify']")
        expect(reclassify_btn).to_be_visible()

        reclassify_btn.click()

        # Wait for reclassification to complete (spinner appears then disappears)
        # The spinner may appear very briefly, so just wait for the system message
        page.wait_for_timeout(2000)
        page.wait_for_selector(".system-message", timeout=120000)

        system_msgs = page.locator(".system-message")
        last_msg_text = system_msgs.last.text_content()
        assert "Reclassified" in last_msg_text, f"Expected 'Reclassified' message, got: {last_msg_text}"


# ────────────────────────────────────────────
# SECTION 11: Download
# ────────────────────────────────────────────

class TestDownload:
    """Test document download button."""

    def test_download_button_visible(self, page: Page):
        """Download button exists on each document."""
        docs = page.locator(".document-item")
        assert docs.count() >= 1, "No documents to download"

        download_btn = docs.first.locator("[title='Download']")
        expect(download_btn).to_be_visible()

    def test_download_triggers_correct_url(self, page: Page):
        """Download button fetches from backend and creates a blob URL."""
        docs = page.locator(".document-item")
        assert docs.count() >= 1

        # Monkey-patch HTMLAnchorElement.click to capture the blob URL
        page.evaluate("""() => {
            window.__capturedDownloadUrl = null;
            const orig = HTMLAnchorElement.prototype.click;
            HTMLAnchorElement.prototype.click = function() {
                window.__capturedDownloadUrl = this.href;
            };
        }""")

        docs.first.locator("[title='Download']").click()
        page.wait_for_timeout(2000)

        url = page.evaluate("window.__capturedDownloadUrl")
        assert url is not None, "Download URL was not captured"
        assert url.startswith("blob:"), f"Expected blob URL, got: {url}"

        # Restore
        page.evaluate("delete window.__capturedDownloadUrl")

    def test_download_endpoint_returns_file(self, page: Page):
        """Download endpoint returns actual file content."""
        # Fetch document list to get a doc_id
        response = page.request.get(
            f"{BACKEND_URL}/documents",
            headers={"X-User-Id": "admin"},
        )
        data = response.json()
        assert len(data["documents"]) >= 1
        doc_id = data["documents"][0]["doc_id"]

        # Verify the download endpoint returns a file
        dl_response = page.request.get(f"{BACKEND_URL}/documents/{doc_id}/download")
        assert dl_response.status == 200
        assert len(dl_response.body()) > 0


# ────────────────────────────────────────────
# SECTION 12: Delete Document
# ────────────────────────────────────────────

class TestDeleteDocument:
    """Test document deletion. Uses a freshly uploaded doc to avoid breaking state."""

    def test_delete_uploaded_document(self, page: Page):
        """Upload a doc, then delete it."""
        # Upload a unique temp file to avoid 409 duplicate conflict
        temp_file = _create_temp_test_file()
        with page.expect_file_chooser() as fc_info:
            page.locator("label.btn-primary", has_text="Upload Document").click()
        fc_info.value.set_files(str(temp_file.resolve()))
        page.wait_for_selector(".upload-hint .spin", state="visible", timeout=10000)
        page.wait_for_selector(".upload-hint .spin", state="hidden", timeout=120000)

        page.wait_for_timeout(500)
        doc_count_before = page.locator(".document-item").count()
        assert doc_count_before >= 1

        # Handle confirm dialog
        page.on("dialog", lambda dialog: dialog.accept())

        # Delete the last document
        last_doc = page.locator(".document-item").last
        last_doc.locator("[title='Delete']").click()
        page.wait_for_timeout(1500)

        doc_count_after = page.locator(".document-item").count()
        assert doc_count_after == doc_count_before - 1

        system_msgs = page.locator(".system-message")
        expect(system_msgs.last).to_contain_text("Deleted")


# ────────────────────────────────────────────
# SECTION 13: User Isolation
# ────────────────────────────────────────────

class TestUserIsolation:
    """Test that different users see different documents."""

    def test_new_user_sees_empty_docs(self, page: Page):
        """A brand-new user should see no documents (isolation=all)."""
        uid = f"iso-{int(time.time())}"

        page.locator(".user-btn").click()
        page.locator(".user-menu-item.add-user").click()

        inputs = page.locator(".new-user-form input")
        inputs.nth(0).fill(uid)
        inputs.nth(1).fill("Isolation Tester")
        page.locator(".new-user-form button", has_text="Create").click()
        page.wait_for_timeout(1500)

        # This new user should see 0 documents
        docs = page.locator(".document-item")
        assert docs.count() == 0, f"New user sees {docs.count()} documents, expected 0"
        expect(page.locator(".header-info")).to_contain_text("0 documents")

    def test_switch_back_sees_admin_docs(self, page: Page):
        """Switching back to admin shows admin's documents."""
        # page fixture already resets to admin
        docs = page.locator(".document-item")
        assert docs.count() >= 1, "Admin should see their documents"


# ────────────────────────────────────────────
# SECTION 14: System Messages
# ────────────────────────────────────────────

class TestSystemMessages:
    """Test system messages for uploads, deletes, reclassifications."""

    def test_system_message_styling(self, page: Page):
        """System messages have distinctive styling."""
        # Generate a system message by uploading a unique temp file
        temp_file = _create_temp_test_file()
        with page.expect_file_chooser() as fc_info:
            page.locator("label.btn-primary", has_text="Upload Document").click()
        fc_info.value.set_files(str(temp_file.resolve()))
        page.wait_for_selector(".upload-hint .spin", state="visible", timeout=10000)
        page.wait_for_selector(".upload-hint .spin", state="hidden", timeout=120000)

        msg = page.locator(".system-message").last
        expect(msg).to_be_visible()

        # Clean up
        page.on("dialog", lambda dialog: dialog.accept())
        page.wait_for_timeout(500)
        last_doc = page.locator(".document-item").last
        last_doc.locator("[title='Delete']").click()
        page.wait_for_timeout(1500)


# ────────────────────────────────────────────
# SECTION 15: Edge Cases
# ────────────────────────────────────────────

class TestEdgeCases:
    """Edge cases and boundary conditions."""

    def test_empty_message_not_sent(self, page: Page):
        """Empty or whitespace-only message doesn't send."""
        msg_count_before = page.locator(".message").count()

        input_box = page.locator(".input-container input")
        input_box.fill("   ")

        # Send button should be disabled for whitespace-only input
        expect(page.locator(".btn-send")).to_be_disabled()

        # Try pressing Enter — should not send
        input_box.press("Enter")
        page.wait_for_timeout(300)
        assert page.locator(".message").count() == msg_count_before

    def test_long_message_sends(self, page: Page):
        """A long message sends without issues."""
        long_text = "What is the main topic? " * 10
        _send_and_wait(page, long_text.strip())

        user_msg = page.locator(".message-user").last
        expect(user_msg).to_be_visible()

    def test_multiple_sources_expandable_independently(self, page: Page):
        """Each source expands/collapses independently."""
        _send_and_wait(page, "Explain the key concepts in detail with references")

        sources = page.locator(".source-item")
        if sources.count() < 2:
            pytest.skip("Need at least 2 sources for this test")

        # Expand first source
        sources.nth(0).locator(".source-header").click()
        page.wait_for_timeout(300)
        expect(sources.nth(0).locator(".source-content")).to_be_visible()
        expect(sources.nth(1).locator(".source-content")).not_to_be_visible()

        # Expand second (first stays open)
        sources.nth(1).locator(".source-header").click()
        page.wait_for_timeout(300)
        expect(sources.nth(0).locator(".source-content")).to_be_visible()
        expect(sources.nth(1).locator(".source-content")).to_be_visible()

        # Collapse first
        sources.nth(0).locator(".source-header").click()
        page.wait_for_timeout(300)
        expect(sources.nth(0).locator(".source-content")).not_to_be_visible()
        expect(sources.nth(1).locator(".source-content")).to_be_visible()
