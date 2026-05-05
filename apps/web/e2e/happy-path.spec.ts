import { test, expect } from '@playwright/test';

const TEST_REPO = 'https://github.com/octocat/Hello-World';

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
    const composer = page.getByLabel('Message composer');
    await expect(composer).toBeVisible();

    // Ask a question
    const question = 'Summarize the README.md file.';
    await composer.fill(question);
    await page.getByRole('button', { name: 'Send' }).click();

    // Verify user message appears
    await expect(page.getByTestId('user-message').last()).toContainText(question);

    // Wait for assistant response, title auto-generation, and follow-up content.
    const assistantMessage = page.getByTestId('assistant-message').last();
    await expect(assistantMessage).toBeVisible({ timeout: 5_000 });
    await expect(page.getByRole('heading', { name: question })).toBeVisible({ timeout: 90_000 });
    await expect(page.getByTestId('followup-chip').first()).toBeVisible({ timeout: 90_000 });
    await expect(page.getByTestId('citation-card').first()).toBeVisible({ timeout: 90_000 });

    await expect(async () => {
      const text = await assistantMessage.textContent();
      expect(text).toBeTruthy();
      expect(text!.length).toBeGreaterThan(10);
    }).toPass({ timeout: 90_000 });

    // Citation preview opens from a source card and shows line numbers/highlighted lines.
    const citationCard = page.getByTestId('citation-card').first();
    const citationLabel = (await citationCard.textContent()) ?? '';
    const citationPath = citationLabel.split(' L')[0];
    await citationCard.click();
    await expect(page.getByTestId('citation-preview-drawer')).toBeVisible();
    await expect(page.getByTestId('citation-preview-drawer')).toContainText(citationPath);
    await expect(page.getByTestId('citation-preview-line-number').first()).toBeVisible();
    await expect(page.getByTestId('citation-preview-highlighted-line').first()).toBeVisible();
    await page.getByLabel('Close source preview').first().click();

    // Sidebar collapse persists across reloads.
    await page.getByTestId('sidebar-collapse-toggle').first().click();
    await expect
      .poll(async () => page.locator('aside').evaluate((element) => Math.round(element.getBoundingClientRect().width)))
      .toBeLessThan(90);
    await page.reload();
    await expect(page.getByRole('heading', { name: question })).toBeVisible({ timeout: 20_000 });
    await expect
      .poll(async () => page.locator('aside').evaluate((element) => Math.round(element.getBoundingClientRect().width)))
      .toBeLessThan(90);

    // Clicking a follow-up sends it without disturbing the user's in-progress draft.
    const draft = 'keep this draft intact';
    const followupText = ((await page.getByTestId('followup-chip').first().textContent()) ?? '').trim();
    await composer.fill(draft);
    await page.getByTestId('followup-chip').first().click();
    await expect(page.getByTestId('user-message').last()).toContainText(followupText, { timeout: 10_000 });
    await expect(composer).toHaveValue(draft);
  });
});
