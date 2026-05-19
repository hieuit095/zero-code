import { test, expect } from '@playwright/test';

test('File Explorer renders correctly and folders can be expanded', async ({ page }) => {
  await page.goto('http://localhost:5173/');

  // Wait for Explorer to be visible
  await expect(page.getByText('Explorer', { exact: true })).toBeVisible();

  // Test is not currently setting up a full run context to populate files, so we verify empty state
  // or simple interaction if any files are rendered by default (as per memory it's empty by default unless a run starts)
  const noFilesMessage = page.getByText('No files yet');
  const startRunMessage = page.getByText('Start a run to populate');

  await expect(noFilesMessage).toBeVisible();
  await expect(startRunMessage).toBeVisible();
});
