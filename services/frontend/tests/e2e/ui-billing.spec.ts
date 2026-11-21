import { expect, test } from '@playwright/test';

test('администратор открывает историю платежей в Backoffice', async ({ page, context }) => {
  await context.route('**/api/v1/**', async (route) => {
    if (route.request().url().endsWith('/refresh'))
      return route.fulfill({ json: { access_token: 'test' } });
    if (route.request().url().endsWith('/me'))
      return route.fulfill({
        json: {
          id: '75ef34f4-2588-41b1-b41e-cbd058c6025c',
          email: 'admin@example.test',
          role: 'admin',
        },
      });
    return route.fulfill({ status: 404, json: {} });
  });
  await page.goto('/');
  await expect(page.getByRole('link', { name: 'История платежей' })).toHaveAttribute(
    'href',
    '/admin/payments/',
  );
});

test('оплата: отключённый магазин и безопасный повтор после потери ответа', async ({
  page,
  context,
}) => {
  const student = '00000000-0000-4000-8000-000000000003';
  let configured = false;
  const keys: string[] = [];
  await context.route('**/api/v1/**', async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path === '/api/v1/auth/refresh') return route.fulfill({ json: { access_token: 'test' } });
    if (path === '/api/v1/auth/me')
      return route.fulfill({
        json: { id: student, role: 'student', email: 'student@example.test' },
      });
    if (path === '/api/v1/billing/config')
      return route.fulfill({
        json: { configured, test_only: true, price_kopecks: 300000, currency: 'RUB' },
      });
    if (path === '/api/v1/billing/students')
      return route.fulfill({ json: [{ id: student, name: 'Петров Иван' }] });
    if (path === '/api/v1/billing/orders')
      return route.fulfill({
        json: [
          {
            id: 8,
            student_id: student,
            study_month: '2026-11-01',
            period_type: 'quarter',
            amount_kopecks: 900000,
            currency: 'RUB',
            status: 'unpaid',
            payment: null,
          },
        ],
      });
    if (path === '/api/v1/billing/payments') {
      const body = route.request().postDataJSON();
      expect(body.amount_kopecks).toBeUndefined();
      expect(body.period_type).toBe('quarter');
      keys.push(body.request_key);
      if (keys.length === 1) return route.abort();
      return route.fulfill({
        status: 202,
        json: {
          id: 7,
          order_id: 3,
          student_id: student,
          payer_id: student,
          study_month: body.study_month,
          period_type: 'quarter',
          amount_kopecks: 900000,
          currency: 'RUB',
          status: 'pending',
          confirmation_url: 'https://yoomoney.ru/test',
          provider_id: null,
          created_at: '2026-10-22T12:00:00Z',
          refund_status: null,
        },
      });
    }
    return route.fulfill({ json: [] });
  });
  await page.goto('/billing');
  await page.getByLabel('Начало учебного года').fill('');
  await expect(page.getByText('Укажите учебный год')).toBeVisible();
  await page.getByLabel('Начало учебного года').fill('2026');
  await page.getByLabel('Учебная четверть').selectOption('11');
  await expect(page.getByText('Счёт выставлен, ожидает оплаты')).toBeVisible();
  await expect(page.getByText('Оплатить до начала четверти', { exact: false })).toBeVisible();
  await expect(page.getByText('ЮKassa пока не подключена.', { exact: false })).toBeVisible();
  const start = page.getByRole('button', { name: 'Перейти к оплате четверти' });
  await expect(start).toBeDisabled();
  configured = true;
  await page.reload();
  await expect(start).toBeEnabled();
  await start.click();
  await expect(
    page.getByText('При неизвестном результате повторите действие:', { exact: false }),
  ).toBeVisible();
  await start.click();
  await expect(page.getByRole('link', { name: 'Открыть ЮKassa' })).toHaveAttribute(
    'href',
    'https://yoomoney.ru/test',
  );
  expect(keys).toHaveLength(2);
  expect(keys[0]).toBe(keys[1]);
  await page.setViewportSize({ width: 360, height: 800 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});
