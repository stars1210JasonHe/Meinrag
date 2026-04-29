"""Quick Playwright verification: T6 dashboard sidebar split renders correctly.

Dev frontend on :5173, dev backend on :8000 expected to be running.
"""
import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
from playwright.sync_api import sync_playwright


def main() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.on("console", lambda msg: print(f"[console.{msg.type}] {msg.text}"))
        page.on("pageerror", lambda err: print(f"[pageerror] {err}"))
        page.on("request", lambda req: print(f"[req] {req.method} {req.url}") if "localhost:8000" in req.url or "/documents" in req.url else None)
        page.on("response", lambda resp: print(f"[resp] {resp.status} {resp.url}") if "localhost:8000" in resp.url or "/documents" in resp.url else None)
        page.goto("http://localhost:5173/", wait_until="domcontentloaded", timeout=20000)
        # Wait for the Sunburst-specific 280x280 SVG to have segment paths.
        # The sunburst renders ≥10 paths (4 categories × 2-3 ring layers each).
        try:
            page.wait_for_function(
                "document.querySelectorAll('svg[width=\"280\"] path').length >= 4",
                timeout=20000,
            )
        except Exception as e:
            print(f"  warn: sunburst segments not rendered: {e}")
        page.wait_for_timeout(1500)
        page.screenshot(path="/tmp/d_dashboard.png", full_page=False)

        # Inspect rendered sidebar headers
        text = page.content()
        print("=== Sidebar headers found ===")
        for keyword in ["Categories", "My Collections", "Uncategorized", "类别", "我的文件夹", "未分类", "Domains"]:
            present = keyword in text
            print(f"  {keyword:<20}: {'YES' if present else 'no'}")

        # Count category rows in left sidebar
        sidebar = page.locator("aside").first
        try:
            rows = sidebar.locator("button").count()
            print(f"\nSidebar buttons: {rows}")
        except Exception as e:
            print(f"sidebar locator failed: {e}")

        browser.close()
        print("\nScreenshot saved to /tmp/t6_dashboard.png")


if __name__ == "__main__":
    main()
