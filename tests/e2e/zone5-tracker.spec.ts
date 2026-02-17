import { test, expect } from '@playwright/test';
import path from 'path';

const HTML_PATH = `file://${path.resolve(__dirname, '../../zone5-tracker.html')}`;

test.describe('Zone 5 Tracker', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto(HTML_PATH);
  });

  test('page loads with correct title and header', async ({ page }) => {
    await expect(page).toHaveTitle(/Zone 5 Heart Rate Tracker/);
    await expect(page.locator('h1')).toContainText('Zone 5 Heart Rate Tracker');
  });

  test('displays heart rate zone information', async ({ page }) => {
    // Verify stats cards are present
    await expect(page.locator('.stat-card')).toHaveCount(4);

    // Check Max HR display
    await expect(page.locator('.stat-value').first()).toContainText('190');

    // Check Zone 5 Range
    await expect(page.locator('.stat-card').nth(1)).toContainText('171-190');
  });

  test('contribution grid initializes with cells', async ({ page }) => {
    const grid = page.locator('#contributionGrid');
    await expect(grid).toBeVisible();

    // Grid should have day cells (371 = 53 weeks * 7 days)
    const cells = page.locator('.day-cell');
    const count = await cells.count();
    expect(count).toBeGreaterThan(300);
  });

  test('generate demo data button populates the tracker', async ({ page }) => {
    // Initial state - placeholders shown
    await expect(page.locator('#todayMaxHR')).toContainText('--');
    await expect(page.locator('#zone5Minutes')).toContainText('--');

    // Click generate demo data
    await page.click('button:has-text("Generate Demo Data")');

    // Wait for UI update
    await page.waitForTimeout(500);

    // Status should update (either achieved or not achieved)
    const status = page.locator('#todayStatus');
    await expect(status).not.toContainText('Upload your Apple Health data');

    // Some cells should now have color levels
    const coloredCells = page.locator('.day-cell:not(.level-0)');
    const coloredCount = await coloredCells.count();
    expect(coloredCount).toBeGreaterThan(0);
  });

  test('file input accepts XML files', async ({ page }) => {
    const fileInput = page.locator('#healthDataFile');
    await expect(fileInput).toBeVisible();
    await expect(fileInput).toHaveAttribute('accept', '.xml');
  });

  test('legend displays all activity levels', async ({ page }) => {
    const legend = page.locator('.legend');
    await expect(legend).toBeVisible();
    await expect(legend).toContainText('Less');
    await expect(legend).toContainText('More');

    // 5 level indicators (0-4)
    const legendItems = page.locator('.legend .legend-item');
    await expect(legendItems).toHaveCount(5);
  });

  test('displays Zone 5 training benefits', async ({ page }) => {
    await expect(page.locator('text=Zone 5 Training Benefits')).toBeVisible();
    await expect(page.locator('text=VO2 Max Improvement')).toBeVisible();
    await expect(page.locator('text=Lactate Tolerance')).toBeVisible();
  });

  test('has accessible labels for screen readers', async ({ page }) => {
    // File input has label
    const fileLabel = page.locator('label[for="healthDataFile"]');
    await expect(fileLabel).toHaveClass(/sr-only/);

    // Stats have aria-labels
    await expect(page.locator('#todayMaxHR')).toHaveAttribute('aria-label');
    await expect(page.locator('#zone5Minutes')).toHaveAttribute('aria-label');
  });
});
