import { chromium } from 'playwright';

(async () => {
  const browser = await chromium.launch();
  const context = await browser.newContext({
    recordVideo: {
      dir: '/home/jules/verification/videos',
    }
  });
  const page = await context.newPage();

  try {
    console.log('Navigating to http://localhost:5173/');
    await page.goto('http://localhost:5173/');

    // Wait for the app to load
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(1000);

    console.log('Taking screenshot...');
    await page.screenshot({ path: '/home/jules/verification/screenshots/explorer-initial.png' });
    console.log('Screenshot saved to /home/jules/verification/screenshots/explorer-initial.png');

  } catch (error) {
    console.error('Verification failed:', error);
  } finally {
    // Explicitly close context to save video
    await context.close();
    await browser.close();
  }
})();
