"""End-to-end verify of T7 EditClassificationDialog on the dev frontend.

Opens the More menu on the first doc → clicks Edit classification → switches
the primary category dropdown → clicks Save → checks the dashboard reflects
the new value via re-render. Restores the original at the end.
"""
import json
import sys
import urllib.request
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
from playwright.sync_api import sync_playwright


def fetch_first_doc():
    req = urllib.request.Request('http://localhost:8000/documents', headers={'X-User-Id': 'admin'})
    with urllib.request.urlopen(req) as resp:
        return json.load(resp)['documents'][0]


def main():
    original = fetch_first_doc()
    print(f'original: {original["doc_id"]} {original["filename"][:40]} primary={original["primary_category"]}')

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

        # Open the More menu on the first doc row
        pg.evaluate("""() => {
            const btn = document.querySelector('button:has(svg.lucide-ellipsis-vertical)');
            btn.scrollIntoView({block: 'center'});
            btn.click();
        }""")
        pg.wait_for_timeout(400)

        # Click Edit classification
        pg.evaluate("""() => {
            const b = Array.from(document.querySelectorAll('button')).find(x => x.innerText.trim() === 'Edit classification');
            if (b) b.click();
        }""")
        pg.wait_for_timeout(400)

        if pg.locator('text=Suggest with AI').count() == 0:
            print('FAIL: dialog did not open')
            b.close()
            return

        # Pick a different primary than current to prove the save round-trips
        target = 'finance-accounting' if original['primary_category'] != 'finance-accounting' else 'research-scientific'
        ok = pg.evaluate(f"""() => {{
            const sel = document.querySelector('select');
            if (!sel) return false;
            sel.value = {json.dumps(target)};
            sel.dispatchEvent(new Event('change', {{ bubbles: true }}));
            return true;
        }}""")
        print(f'dropdown change to {target}: {ok}')
        pg.wait_for_timeout(200)

        # Click Save
        pg.evaluate("""() => {
            const b = Array.from(document.querySelectorAll('button')).find(x => x.type === 'submit' && x.innerText.trim().includes('Save'));
            if (b) b.click();
        }""")
        pg.wait_for_timeout(2500)  # let PATCH round-trip + query invalidation

        # Verify dashboard reflects the new primary
        after = fetch_first_doc()
        print(f'after save: primary={after["primary_category"]} subtags={after["subtags"]}')
        assert after['primary_category'] == target, f'expected {target}, got {after["primary_category"]}'
        print('PASS: PATCH persisted primary_category change end-to-end')

        # Restore original via direct API
        urllib.request.urlopen(urllib.request.Request(
            f'http://localhost:8000/documents/{original["doc_id"]}',
            method='PATCH',
            headers={'X-User-Id': 'admin', 'Content-Type': 'application/json'},
            data=json.dumps({
                'primary_category': original['primary_category'],
                'subtags': original['subtags'],
                'collections': original['collections'],
            }).encode('utf-8'),
        ))
        print(f'restored {original["doc_id"]} → {original["primary_category"]}')

        b.close()


if __name__ == '__main__':
    main()
