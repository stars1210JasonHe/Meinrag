"""Verify Dashboard click flows after bug fixes."""
import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
from playwright.sync_api import sync_playwright

WAIT_SUNBURST = "document.querySelectorAll('svg[width=\"280\"] path').length >= 4"
GET_STATE = """() => ({
    noMatch: document.body.innerText.includes('No documents match'),
    docCardCount: document.querySelectorAll('[class*="cursor-pointer"]').length,
})"""

with sync_playwright() as p:
    b = p.chromium.launch(headless=True)
    pg = b.new_page()
    pg.on('pageerror', lambda e: print(f'[err] {e}'))
    pg.goto('http://localhost:5173/', wait_until='domcontentloaded')
    pg.wait_for_function(WAIT_SUNBURST, timeout=20000)
    pg.wait_for_timeout(1000)

    def state(label):
        s = pg.evaluate(GET_STATE)
        print(f'  {label:<40} noMatch={s["noMatch"]:<5} cards={s["docCardCount"]}')

    state('initial (no scope)')

    paths = pg.locator('svg[width="280"] path').all()
    print(f'sunburst paths: {len(paths)}')

    # Click an outer-ring path (deeper segments are at the end of partition order)
    paths[-1].click(force=True)
    pg.wait_for_timeout(400)
    state('after sunburst outer-ring click')

    # Click All sidebar
    pg.locator('text=All').first.click()
    pg.wait_for_timeout(400)
    state('after sidebar "All" click')

    # Click Legal Compliance category
    pg.locator('text=Legal Compliance').first.click()
    pg.wait_for_timeout(400)
    state('after sidebar "Legal Compliance" click')

    # Click sunburst inner ring (category-level segment)
    paths[0].click(force=True)
    pg.wait_for_timeout(400)
    state('after sunburst inner-ring click')

    # Click All again to reset
    pg.locator('text=All').first.click()
    pg.wait_for_timeout(400)
    state('final All click')

    b.close()
