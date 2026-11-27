import { expect, test } from '@playwright/test';

test('real backend: демо-вход кнопкой роли без пароля из окружения', async ({ page }) => {
  // Демо-кнопки зашиты во фронтенд: этот тест — детектор дрейфа пароля
  // «бандл ≠ прод-БД» (см. concepts_brief.md, п. 6 анализа).
  await page.goto('/login');
  await page.getByRole('button', { name: 'Учитель', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Сегодня', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Выйти', exact: true }).first().click();
  await expect(page.getByRole('heading', { name: 'Вход в гимназию' })).toBeVisible();
  await page.getByRole('button', { name: 'Ученик', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Сегодня', exact: true })).toBeVisible();
});

test('real backend: вход, reload и серверный выход', async ({ page }) => {
  const email = process.env.E2E_ADMIN_EMAIL;
  const password = process.env.E2E_ADMIN_PASSWORD;
  if (!email || !password)
    throw new Error(
      'Для real E2E задайте E2E_ADMIN_EMAIL и E2E_ADMIN_PASSWORD в приватном локальном окружении.',
    );
  await page.goto('/login');
  await page.getByLabel('Email', { exact: true }).fill(email);
  await page.getByLabel('Пароль', { exact: true }).fill(password);
  await page.getByRole('button', { name: 'Войти', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Онлайн-гимназия', exact: true })).toBeVisible();
  await page.reload();
  await expect(page.getByRole('heading', { name: 'Онлайн-гимназия', exact: true })).toBeVisible();
  const logout = page.waitForResponse(
    (response) =>
      response.url().endsWith('/api/v1/auth/logout') && response.request().method() === 'POST',
  );
  await page.getByRole('button', { name: 'Выйти', exact: true }).first().click();
  expect((await logout).status()).toBe(204);
  await page.reload();
  await expect(page.getByRole('heading', { name: 'Вход в гимназию' })).toBeVisible();
});
