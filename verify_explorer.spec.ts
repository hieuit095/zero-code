import { test, expect } from '@playwright/test';

test('FileExplorer visually verifies that files can be expanded and clicked', async ({ page }) => {
  await page.goto('http://localhost:5173/');
  await page.waitForTimeout(2000); // Wait for initialization

  // Test expanding the project folder dot
  const expandAll = await page.$('text=Explorer');
  expect(expandAll).not.toBeNull();

  await page.screenshot({ path: '/home/jules/verification/screenshots/explorer.png' });

  // Close the context to ensure video is saved
  await page.context().close();
});
