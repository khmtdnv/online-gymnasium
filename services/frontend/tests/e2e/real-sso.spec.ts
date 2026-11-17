import { expect, test } from '@playwright/test';

test('real backend: общий вход в админку и выход', async ({ page }) => {
  const email = process.env.E2E_ADMIN_EMAIL;
  const password = process.env.E2E_ADMIN_PASSWORD;
  if (!email || !password) throw new Error('Не заданы учётные данные демо-администратора.');

  await page.goto('/login');
  await page.getByLabel('Email', { exact: true }).fill(email);
  await page.getByLabel('Пароль', { exact: true }).fill(password);
  await page.getByRole('button', { name: 'Войти', exact: true }).click();
  await page.getByRole('link', { name: 'Администрирование', exact: true }).click();
  await expect(page).toHaveURL(/\/admin\/$/);
  await expect(page.getByText('Общий вход')).toBeVisible();
  await page.getByRole('button', { name: 'Выйти' }).click();
  await expect(page).toHaveURL(/\/login$/);
  await expect(page.getByRole('heading', { name: 'Вход в гимназию' })).toBeVisible();
});

test('real backend: смена аккаунта в другой вкладке закрывает старую админку', async ({
  page,
  context,
}) => {
  const email = process.env.E2E_ADMIN_EMAIL;
  const password = process.env.E2E_ADMIN_PASSWORD;
  if (!email || !password) throw new Error('Не заданы учётные данные демо-администратора.');
  await page.goto('/login');
  await page.getByLabel('Email', { exact: true }).fill(email);
  await page.getByLabel('Пароль', { exact: true }).fill(password);
  await page.getByRole('button', { name: 'Войти', exact: true }).click();
  await page.getByRole('link', { name: 'Администрирование', exact: true }).click();
  await expect(page.getByText('Общий вход')).toBeVisible();
  const secondTab = await context.newPage();
  await secondTab.goto('/login');
  const switched = await secondTab.evaluate(async (demoPassword) => {
    const response = await fetch('/api/v1/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email: 'student01.1@demo.og.test', password: demoPassword }),
    });
    return response.status;
  }, password);
  expect(switched).toBe(200);
  const reload = await page.reload();
  expect(reload?.status()).toBe(401);
  await secondTab.evaluate(() => fetch('/api/v1/auth/logout', { method: 'POST' }));
});
