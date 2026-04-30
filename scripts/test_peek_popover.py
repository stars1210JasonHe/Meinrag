"""Verify M2 peek-selection popover behavior."""
import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    b = p.chromium.launch(headless=True)
    pg = b.new_page()
    pg.on('pageerror', lambda e: print(f'[pageerror] {e}'))
    pg.on('console', lambda m: print(f'[con.{m.type}] {m.text[:200]}') if m.type in ('error','warning') else None)
    pg.goto('http://localhost:5173/', wait_until='domcontentloaded')
    pg.wait_for_function(
        "document.querySelectorAll('svg[width=\"280\"] path').length >= 4",
        timeout=20000,
    )
    pg.wait_for_timeout(1500)
    pg.evaluate("localStorage.removeItem('meinrag.selection.admin')")

    # Diagnostic
    diag = pg.evaluate("""() => ({
        unchecked: document.querySelectorAll('button[aria-pressed=false]').length,
        checked: document.querySelectorAll('button[aria-pressed=true]').length,
        triggers: document.querySelectorAll('button[data-peek-trigger]').length,
    })""")
    print(f'pre-click: {diag}')

    # Select 3 docs by clicking the first 3 unchecked checkboxes in the doc list
    pg.evaluate("""() => {
        const boxes = Array.from(document.querySelectorAll('button[aria-pressed=false]'));
        for (let i = 0; i < 3 && i < boxes.length; i++) {
            boxes[i].scrollIntoView({block: 'center'});
            boxes[i].click();
        }
    }""")
    pg.wait_for_timeout(800)

    # Verify count is 3, peek is closed
    s = pg.evaluate("""() => ({
        bar: (document.body.innerText.match(/(\\d+) selected/) || [])[1],
        peekVisible: !!document.querySelector('[role=dialog][aria-label*=\"Selected\"]'),
    })""")
    print(f'after 3 selects (different searches): bar="{s["bar"]} selected" peek-visible={s["peekVisible"]}')

    # Click the count text → expect peek to open with 3 filenames
    pg.evaluate("document.querySelector('button[data-peek-trigger]')?.click()")
    pg.wait_for_timeout(300)
    s = pg.evaluate("""() => {
        const dlg = document.querySelector('[role=dialog][aria-label*=\"Selected\"]');
        return {
            peekVisible: !!dlg,
            rowCount: dlg ? dlg.querySelectorAll('button[aria-label*=\"Remove\"]').length : 0,
            filenames: dlg ? Array.from(dlg.querySelectorAll('span[title]')).map(s => s.title.substring(0, 30)) : [],
        };
    }""")
    print(f'after click count: peek={s["peekVisible"]} rows={s["rowCount"]}')
    for fn in s['filenames']:
        print(f'  - {fn}')

    # Click first × button to remove a doc
    pg.evaluate("""() => {
        const dlg = document.querySelector('[role=dialog][aria-label*=\"Selected\"]');
        const btn = dlg?.querySelector('button[aria-label*=\"Remove\"]');
        if (btn) btn.click();
    }""")
    pg.wait_for_timeout(300)
    s = pg.evaluate("""() => ({
        bar: (document.body.innerText.match(/(\\d+) selected/) || [])[1],
        rowCount: document.querySelectorAll('[role=dialog][aria-label*=\"Selected\"] button[aria-label*=\"Remove\"]').length,
    })""")
    print(f'after × on row 1: bar="{s["bar"]} selected" peek-rows={s["rowCount"]}')

    # ESC should close peek WITHOUT clearing the selection
    pg.keyboard.press('Escape')
    pg.wait_for_timeout(300)
    s = pg.evaluate("""() => ({
        peekVisible: !!document.querySelector('[role=dialog][aria-label*=\"Selected\"]'),
        bar: (document.body.innerText.match(/(\\d+) selected/) || [])[1],
        clearedToast: document.body.innerText.includes('Cleared'),
    })""")
    print(f'after ESC: peek={s["peekVisible"]} bar="{s["bar"]} selected" cleared-toast={s["clearedToast"]}')

    pg.screenshot(path='/tmp/peek_popover.png', full_page=False)
    b.close()
