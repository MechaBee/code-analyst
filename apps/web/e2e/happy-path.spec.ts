import { test, expect } from '@playwright/test';

const TEST_REPO = 'https://github.com/octocat/Hello-World';
const TEST_BRANCH = 'master';

test.describe('Code Analyst E2E', () => {
  test('import page loads and has correct elements', async ({ page }) => {
    await page.goto('/');

    await expect(page.getByRole('heading', { name: 'Code Analyst' })).toBeVisible();
    await expect(page.getByLabel('GitHub Repository URL')).toBeVisible();
    await expect(page.getByLabel('Branch / Tag / Ref')).toBeVisible();
    await expect(page.getByRole('button', { name: 'Import Repository' })).toBeVisible();
  });

  test('happy path: import repo, ask question, receive answer', async ({ page }) => {
    test.setTimeout(120_000); // Generous timeout for analysis backend

    await page.goto('/');

    // Fill import form (leave branch empty to test auto-detection)
    await page.getByLabel('GitHub Repository URL').fill(TEST_REPO);
    await page.getByRole('button', { name: 'Import Repository' }).click();

    // Wait for navigation to chat view
    await expect(page.getByText('Ready to analyze')).toBeVisible({ timeout: 10_000 });
    await expect(page.getByPlaceholder('Ask a question about the codebase...')).toBeVisible();

    // Ask a question
    const question = 'What files are in this repository?';
    await page.getByPlaceholder('Ask a question about the codebase...').fill(question);
    await page.getByRole('button', { name: 'Send' }).click();

    // Verify user message appears
    await expect(page.getByText(question)).toBeVisible();

    // Wait for assistant response (loading state first, then content)
    const assistantBubble = page.locator('[class*="rounded-bl-sm"]').last();
    await expect(assistantBubble).toBeVisible({ timeout: 5_000 });

    // Wait for answer content to appear (not just loading spinner)
    await expect(async () => {
      const text = await assistantBubble.textContent();
      expect(text).toBeTruthy();
      expect(text!.length).toBeGreaterThan(10);
    }).toPass({ timeout: 90_000 });
  });
});
