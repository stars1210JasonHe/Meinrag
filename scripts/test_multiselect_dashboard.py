"""Verify multi-select via DocRow checkboxes + SelectionActionBar surfacing."""
import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    b = p.chromium.launch(headless=True)
    pg = b.new_page()
    pg.on('pageerror', lambda e: print(f'[err] {e}'))
    pg.goto('http://localhost:5173/', wait_until='domcontentloaded')
    pg.wait_for_function(
        "document.querySelectorAll('svg[width=\"280\"] path').length >= 4",
        timeout=20000,
    )
    pg.wait_for_timeout(1500)

    # Clear any prior selection
    pg.evaluate("localStorage.removeItem('meinrag.selection.admin')")

    # Find checkboxes inside doc rows. Hover-reveal + the button has aria-pressed
    cb_count = pg.evaluate("document.querySelectorAll('button[aria-pressed]').length")
    print(f'checkbox buttons: {cb_count}')

    # Click first 3 doc-row checkboxes
    pg.evaluate("""() => {
        const boxes = Array.from(document.querySelectorAll('button[aria-pressed=false]'));
        for (let i = 0; i < 3 && i < boxes.length; i++) {
            boxes[i].scrollIntoView({block: 'center'});
            boxes[i].click();
        }
    }""")
    pg.wait_for_timeout(500)

    # Selection action bar should now be visible
    state = pg.evaluate("""() => ({
        selectedCount: document.querySelectorAll('button[aria-pressed=true]').length,
        hasActionBar: document.body.innerText.includes('Save') && (
            document.body.innerText.includes('selected') ||
            document.body.innerText.includes('Ask') ||
            document.body.innerText.includes('Visualize')
        ),
        actionBarText: (document.querySelector('[class*=\"fixed\"][class*=\"bottom\"]')?.innerText || '').substring(0, 200),
    })""")
    print(f'selected: {state["selectedCount"]}')
    print(f'action bar surfaced: {state["hasActionBar"]}')
    print(f'action bar text: {state["actionBarText"]}')

    pg.screenshot(path='/tmp/multiselect_dashboard.png', full_page=False)
    print('screenshot: /tmp/multiselect_dashboard.png')

    b.close()
