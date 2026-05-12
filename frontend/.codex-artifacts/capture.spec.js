import { test } from '@playwright/test';

test('capture desktop', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1024 });
  await page.goto('http://127.0.0.1:5173', { waitUntil: 'networkidle' });
  await page.waitForSelector('text=GP 对话助手');
  await page.evaluate(() => {
    const el = document.querySelector('.chat-thread');
    if (el) el.scrollTop = 0;
  });
  await page.screenshot({ path: '.codex-artifacts/capture-desktop.png', fullPage: true });
});

test('capture mobile', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('http://127.0.0.1:5173', { waitUntil: 'networkidle' });
  await page.waitForSelector('text=GP 对话助手');
  await page.evaluate(() => {
    const el = document.querySelector('.chat-thread');
    if (el) el.scrollTop = 0;
  });
  await page.screenshot({ path: '.codex-artifacts/capture-mobile.png', fullPage: true });
});
