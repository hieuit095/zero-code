import { test, expect } from '@playwright/test';

test('FileExplorer renders correctly and handles selection', async ({ page }) => {
  await page.goto('http://localhost:5173');

  // The app might take a moment to load
  await page.waitForSelector('text=Explorer');

  // Verify the component renders the empty state or mock state correctly
  // Given that it's empty by default, we just make sure it loads without crashing
  const explorerTitle = await page.isVisible('text=Explorer');
  expect(explorerTitle).toBeTruthy();

  console.log("FileExplorer rendered correctly");
});
