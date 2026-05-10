import { chromium } from 'playwright';
import path from 'path';

(async () => {
  const browser = await chromium.launch();
  const context = await browser.newContext({
    recordVideo: {
      dir: '/home/jules/verification/videos/',
      size: { width: 1280, height: 720 },
    }
  });

  const page = await context.newPage();
  console.log('Navigating to http://localhost:5173...');
  await page.goto('http://localhost:5173', { waitUntil: 'networkidle' });

  // Wait for the UI to load
  await page.waitForTimeout(2000);

  // Take a screenshot
  const screenshotPath = '/home/jules/verification/screenshots/file_explorer.png';
  await page.screenshot({ path: screenshotPath });
  console.log(`Screenshot saved to ${screenshotPath}`);

  await context.close();
  await browser.close();
})();
