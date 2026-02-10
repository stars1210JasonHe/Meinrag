const { chromium } = require('playwright');
const path = require('path');
const fs = require('fs');

async function takeScreenshot(category = 'development') {
  const browser = await chromium.launch();
  const context = await browser.newContext({
    viewport: { width: 1920, height: 1080 }
  });
  const page = await context.newPage();

  // Listen for console messages
  page.on('console', msg => {
    const type = msg.type();
    const text = msg.text();
    console.log(`[Browser ${type}] ${text}`);
  });

  // Listen for errors
  page.on('pageerror', error => {
    console.error(`[Browser Error] ${error.message}`);
  });

  try {
    console.log('Navigating to http://localhost:5173...');
    await page.goto('http://localhost:5173', {
      waitUntil: 'networkidle',
      timeout: 30000
    });

    // Wait a bit for React to render
    await page.waitForTimeout(2000);

    // Check for key elements
    const headerExists = await page.locator('.header').count();
    const sidebarExists = await page.locator('.sidebar').count();
    const chatExists = await page.locator('.chat-container').count();
    const uploadBtnExists = await page.locator('.btn-primary').count();

    console.log('\n=== Component Detection ===');
    console.log(`Header: ${headerExists > 0 ? '✓' : '✗'}`);
    console.log(`Sidebar: ${sidebarExists > 0 ? '✓' : '✗'}`);
    console.log(`Chat Container: ${chatExists > 0 ? '✓' : '✗'}`);
    console.log(`Upload Buttons: ${uploadBtnExists}`);

    // Take screenshot
    const screenshotDir = path.join(__dirname, 'screenshots', category);
    if (!fs.existsSync(screenshotDir)) {
      fs.mkdirSync(screenshotDir, { recursive: true });
    }

    const timestamp = new Date().toISOString().replace(/:/g, '-').split('.')[0];
    const screenshotPath = path.join(screenshotDir, `${timestamp}.png`);

    await page.screenshot({
      path: screenshotPath,
      fullPage: true
    });

    console.log(`\n✅ Screenshot saved: ${screenshotPath}`);

  } catch (error) {
    console.error(`\n❌ Error taking screenshot: ${error.message}`);
    throw error;
  } finally {
    await browser.close();
  }
}

// Get category from command line args
const category = process.argv[2] || 'development';
takeScreenshot(category).catch(console.error);
