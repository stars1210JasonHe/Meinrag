"""Verify: search doc1 → select → search doc2 → select → both still selected."""
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
    pg.evaluate("localStorage.removeItem('meinrag.selection.admin')")

    def state(label):
        s = pg.evaluate("""() => ({
            visibleRows: document.querySelectorAll('[class*=\"cursor-pointer\"][class*=\"border-b\"]').length,
            checked: document.querySelectorAll('button[aria-pressed=true]').length,
            actionBarCount: (document.body.innerText.match(/(\\d+) selected/) || [])[1] || '0',
        })""")
        print(f'  {label:50s} visible={s["visibleRows"]:2}  checked-on-screen={s["checked"]}  action-bar="{s["actionBarCount"]} selected"')

    # 1. search "tsunoda"
    pg.locator('input[placeholder*="Search"]').first.fill('tsunoda')
    pg.wait_for_timeout(500)
    state('after search "tsunoda"')

    # 2. check the first visible doc
    pg.evaluate("""() => {
        const cb = document.querySelector('button[aria-pressed=false]');
        if (cb) cb.click();
    }""")
    pg.wait_for_timeout(300)
    state('after check tsunoda')

    # 3. search "section230"
    pg.locator('input[placeholder*="Search"]').first.fill('section230')
    pg.wait_for_timeout(500)
    state('after search "section230"')

    # 4. check the first visible doc
    pg.evaluate("""() => {
        const cb = document.querySelector('button[aria-pressed=false]');
        if (cb) cb.click();
    }""")
    pg.wait_for_timeout(300)
    state('after check section230')

    # 5. search "physics"
    pg.locator('input[placeholder*="Search"]').first.fill('physics')
    pg.wait_for_timeout(500)
    state('after search "physics" (neither prev visible)')

    # 6. clear search
    pg.locator('input[placeholder*="Search"]').first.fill('')
    pg.wait_for_timeout(500)
    state('after clear search')

    pg.screenshot(path='/tmp/cross_search_selection.png', full_page=False)
    print()
    print('screenshot: /tmp/cross_search_selection.png')
    b.close()
