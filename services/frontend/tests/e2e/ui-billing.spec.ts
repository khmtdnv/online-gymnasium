import { expect, test } from '@playwright/test';

const student = '00000000-0000-4000-8000-000000000003';
const payer = '00000000-0000-4000-8000-000000000004';

function payment(overrides: Record<string, unknown>) {
  return {
    id: 1,
    order_id: 2,
    student_id: student,
    payer_id: payer,
    study_month: '2026-11-01',
    period_type: 'quarter',
    amount_kopecks: 300000,
    currency: 'RUB',
    status: 'pending',
    confirmation_url: null,
    provider_id: null,
    created_at: '2026-11-05T12:00:00Z',
    refund_status: null,
    ...overrides,
  };
}

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
        json: payment({
          id: 7,
          order_id: 8,
          amount_kopecks: 900000,
          confirmation_url: 'https://yoomoney.ru/test',
        }),
      });
    }
    return route.fulfill({ json: [] });
  });
  await page.goto('/billing');
  // Ученик не выбирает ребёнка: селектор ученика есть только у родителя.
  await expect(page.getByLabel('Ученик')).toHaveCount(0);
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

test('история родителя: семь статусов из таблицы спецификации и действия по статусу', async ({
  page,
  context,
}) => {
  const statuses = [
    { status: 'pending', id: 11, url: 'https://yoomoney.ru/test-pending' },
    { status: 'creating', id: 12, url: null },
    { status: 'succeeded', id: 13, url: null },
    { status: 'canceled', id: 14, url: null },
    { status: 'unknown', id: 15, url: null },
    { status: 'manual_review', id: 16, url: null },
    { status: 'refunded', id: 17, url: null },
  ];
  await context.route('**/api/v1/**', async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path === '/api/v1/auth/refresh') return route.fulfill({ json: { access_token: 'test' } });
    if (path === '/api/v1/auth/me')
      return route.fulfill({
        json: { id: payer, role: 'parent', email: 'parent@example.test' },
      });
    if (path === '/api/v1/billing/config')
      return route.fulfill({
        json: { configured: true, test_only: true, price_kopecks: 300000, currency: 'RUB' },
      });
    if (path === '/api/v1/billing/students')
      return route.fulfill({ json: [{ id: student, name: 'Иванов Артём' }] });
    if (path === '/api/v1/billing/orders')
      return route.fulfill({
        json: [
          {
            id: 21,
            student_id: student,
            study_month: '2026-11-01',
            period_type: 'quarter',
            amount_kopecks: 300000,
            currency: 'RUB',
            status: 'unpaid',
            payment: payment({
              id: 11,
              order_id: 21,
              status: 'pending',
              confirmation_url: 'https://yoomoney.ru/test-pending',
            }),
          },
          ...statuses.slice(1).map((item) => ({
            id: 30 + statuses.indexOf(item),
            student_id: student,
            study_month: '2026-10-01',
            period_type: 'quarter',
            amount_kopecks: 300000,
            currency: 'RUB',
            status: 'unpaid',
            payment: payment({
              id: item.id,
              order_id: 30 + statuses.indexOf(item),
              status: item.status,
              confirmation_url: item.url,
            }),
          })),
        ],
      });
    return route.fulfill({ json: [] });
  });
  await page.goto('/billing');
  await expect(page.getByLabel('Ученик')).toBeVisible();
  // Продолжение начатого платежа: pending-счёт выбранной четверти.
  await expect(page.getByRole('link', { name: 'Продолжить оплату в ЮKassa' })).toHaveAttribute(
    'href',
    'https://yoomoney.ru/test-pending',
  );
  const row = (status: string) => page.locator(`.billing-row[data-status=${status}]`);
  await expect(page.locator('.billing-row')).toHaveCount(7);
  // pending: кнопка оплаты по confirmation_url.
  await expect(row('pending').getByRole('link', { name: 'Оплатить в ЮKassa' })).toHaveAttribute(
    'href',
    'https://yoomoney.ru/test-pending',
  );
  await expect(row('pending').locator('.billing-payment-status')).toHaveText(/Ожидает оплаты/);
  // creating: индикатор, действия заблокированы.
  await expect(row('creating').locator('.billing-payment-status')).toHaveText(/Создаём платёж/);
  await expect(
    row('creating').getByRole('button', { name: 'Проверить статус в ЮKassa' }),
  ).toBeDisabled();
  // succeeded: квитанция недоступна роли (раздел документов — только администратор).
  await expect(row('succeeded').locator('.billing-payment-status')).toHaveText(/Оплачено/);
  await expect(row('succeeded').getByRole('button', { name: 'Полный возврат' })).toHaveCount(0);
  // canceled: предложение создать новый платёж.
  await expect(row('canceled')).toContainText('создайте новый в форме выше');
  // unknown: безопасное сообщение без деталей.
  await expect(row('unknown').locator('.billing-payment-status')).toHaveText(/Уточняем результат/);
  await expect(row('unknown')).toContainText('уточняется автоматически');
  // manual_review: пометка, без служебных действий у родителя.
  await expect(row('manual_review').locator('.billing-payment-status')).toHaveText(
    /Нужна ручная сверка/,
  );
  await expect(row('manual_review')).toContainText('ручной сверке');
  await expect(row('manual_review').getByRole('button', { name: 'Сверить платёж' })).toHaveCount(0);
  // refunded: история без повторных действий.
  await expect(row('refunded').locator('.billing-payment-status')).toHaveText(/Возвращено/);
  await expect(row('refunded').getByRole('button', { name: 'Полный возврат' })).toHaveCount(0);
  // Клиентский фильтр по загруженной странице.
  await page.getByRole('button', { name: 'Оплачено' }).click();
  await expect(page.locator('.billing-row')).toHaveCount(1);
  await expect(row('succeeded')).toBeVisible();
  await page.getByRole('button', { name: 'Все статусы' }).click();
  await expect(page.locator('.billing-row')).toHaveCount(7);
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

test('административная сверка и полный возврат с подтверждением', async ({ page, context }) => {
  const providerId = '00000000-0000-4000-8000-000000000009';
  const posts: { path: string; body: unknown }[] = [];
  await context.route('**/api/v1/**', async (route) => {
    const url = new URL(route.request().url());
    const path = url.pathname;
    const method = route.request().method();
    if (path === '/api/v1/auth/refresh') return route.fulfill({ json: { access_token: 'test' } });
    if (path === '/api/v1/auth/me')
      return route.fulfill({
        json: {
          id: '75ef34f4-2588-41b1-b41e-cbd058c6025c',
          role: 'admin',
          email: 'admin@example.test',
        },
      });
    if (path === '/api/v1/billing/config')
      return route.fulfill({
        json: { configured: true, test_only: true, price_kopecks: 300000, currency: 'RUB' },
      });
    if (path === '/api/v1/billing/payments' && method === 'GET')
      return route.fulfill({
        json: [
          {
            ...payment({ id: 31, status: 'manual_review', study_month: '2026-10-01' }),
            student_name: 'Иванов Артём',
          },
          {
            ...payment({ id: 32, status: 'succeeded', study_month: '2026-09-01' }),
            student_name: 'Иванов Артём',
          },
        ],
      });
    if (method === 'POST' && (path.endsWith('/reconcile') || path.endsWith('/refund'))) {
      posts.push({ path, body: route.request().postDataJSON() });
      const id = Number(path.split('/')[5]);
      return route.fulfill({
        status: 202,
        json: payment({ id, status: path.endsWith('/refund') ? 'refunded' : 'succeeded' }),
      });
    }
    return route.fulfill({ json: [] });
  });
  await page.goto('/billing');
  const manual = page.locator('.billing-row[data-status=manual_review]');
  await expect(manual).toContainText('Ученик: Иванов Артём');
  await manual.getByLabel('UUID платежа из тестового кабинета').fill(providerId);
  await manual.getByRole('button', { name: 'Сверить платёж' }).click();
  await expect(page.getByText('Платёж №31: Оплачено')).toBeVisible();
  // Квитанция по подтверждённому платежу — существующий поток документов.
  await expect(
    page
      .locator('.billing-row[data-status=succeeded]')
      .getByRole('link', { name: 'Квитанция PDF' }),
  ).toHaveAttribute('href', '/documents?type=receipt&payment=32');
  // Полный возврат только через подтверждение с суммой.
  const succeeded = page.locator('.billing-row[data-status=succeeded]');
  await expect(succeeded.getByRole('button', { name: 'Подтвердить полный возврат' })).toHaveCount(
    0,
  );
  await succeeded.getByRole('button', { name: 'Полный возврат' }).click();
  const confirm = page.getByRole('group', { name: 'Подтверждение возврата' });
  await expect(confirm).toContainText('Вернуть всю сумму 3 000,00 ₽?');
  await confirm.getByRole('button', { name: 'Отмена' }).click();
  await expect(confirm).toHaveCount(0);
  await succeeded.getByRole('button', { name: 'Полный возврат' }).click();
  await confirm.getByRole('button', { name: 'Подтвердить полный возврат' }).click();
  await expect(page.getByText('Платёж №32: Возвращено')).toBeVisible();
  expect(posts.map((item) => item.path)).toEqual([
    '/api/v1/billing/payments/31/reconcile',
    '/api/v1/billing/payments/32/refund',
  ]);
  expect(posts[0].body).toEqual({ provider_id: providerId });
  expect(posts[1].body).toHaveProperty('request_key');
  expect(String((posts[1].body as { request_key: string }).request_key)).toMatch(
    /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/,
  );
});
