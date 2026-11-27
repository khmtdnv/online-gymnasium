import { expect, test } from '@playwright/test';

test('admin navigation opens reports in Django Backoffice', async ({ page, context }) => {
  await context.route('**/api/v1/**', async (route) => {
    if (route.request().url().endsWith('/refresh'))
      return route.fulfill({ json: { access_token: 'mock' } });
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
  await expect(page.getByRole('link', { name: 'Успеваемость и аудит' })).toHaveAttribute(
    'href',
    '/admin/analytics/',
  );
});

test('admin sees named progress and separate audit details', async ({ page, context }) => {
  await page.clock.setFixedTime(new Date('2026-10-22T10:00:00Z'));
  const userId = '75ef34f4-2588-41b1-b41e-cbd058c6025c';
  await context.route('**/api/v1/**', async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname.endsWith('/refresh')) return route.fulfill({ json: { access_token: 'mock' } });
    if (url.pathname.endsWith('/me'))
      return route.fulfill({ json: { id: userId, email: 'admin@example.test', role: 'admin' } });
    if (url.pathname === '/api/v1/analytics/classes')
      return route.fulfill({
        json: [{ id: 7, name: '7А', study_year: 2026, created_at: '2026-10-01T00:00:00Z' }],
      });
    if (url.pathname === '/api/v1/analytics/progress')
      return route.fulfill({
        json: [
          {
            student_id: userId,
            subject_id: 3,
            graded_count: 2,
            average_grade: 4.5,
            student_name: 'Петров Иван',
            subject_name: 'Математика',
          },
        ],
      });
    if (url.pathname === '/api/v1/analytics/audit')
      return route.fulfill({
        json: [
          {
            event_id: userId,
            event_source: 'homework',
            event_type: 'homework.answer.reviewed',
            schema_version: 1,
            occurred_at: '2026-10-22T09:00:00Z',
            request_id: null,
            actor: { source: 'gateway', id: userId },
            payload: { grade: 4, status: 'graded' },
          },
        ],
      });
    return route.fulfill({ status: 404, json: {} });
  });
  await page.goto('/analytics');
  await expect(page.getByRole('heading', { name: 'Успеваемость и аудит' })).toBeVisible();
  await expect(page.getByRole('table').first()).toContainText('Петров Иван');
  await expect(page.getByRole('table').first()).toContainText('4,50');
  await expect(page.getByLabel('Класс')).toHaveValue('7');
  const toggle = page.getByRole('button', { name: 'Данные события' });
  await toggle.click();
  await expect(page.getByText('"grade": 4', { exact: false })).toBeVisible();
  // Раскрытое состояние: кнопка меняет подпись и сообщает aria-expanded.
  await expect(page.getByRole('button', { name: 'Скрыть данные' })).toHaveAttribute(
    'aria-expanded',
    'true',
  );
  await page.setViewportSize({ width: 360, height: 800 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(
    true,
  );
});

test('analytics filters, audit pagination and safe truncated JSON', async ({ page, context }) => {
  await page.clock.setFixedTime(new Date('2026-10-22T10:00:00Z'));
  const userId = '75ef34f4-2588-41b1-b41e-cbd058c6025c';
  const uuid = (n: number) => `00000000-0000-4000-8000-${String(n).padStart(12, '0')}`;
  const event = (n: number, payload: Record<string, unknown> = { grade: 4 }) => ({
    event_id: uuid(n),
    event_source: 'homework',
    event_type: 'homework.answer.reviewed',
    schema_version: 1,
    occurred_at: '2026-10-22T09:00:00Z',
    request_id: null,
    actor: { source: 'gateway', id: userId },
    payload,
  });
  const auditCalls: { offset: string }[] = [];
  const progressCalls: string[] = [];
  await context.route('**/api/v1/**', async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname.endsWith('/refresh')) return route.fulfill({ json: { access_token: 'mock' } });
    if (url.pathname.endsWith('/me'))
      return route.fulfill({ json: { id: userId, email: 'admin@example.test', role: 'admin' } });
    if (url.pathname === '/api/v1/analytics/classes')
      return route.fulfill({
        json: [
          { id: 7, name: '7А', study_year: 2026, created_at: '2026-10-01T00:00:00Z' },
          { id: 8, name: '8А', study_year: 2026, created_at: '2026-10-01T00:00:00Z' },
        ],
      });
    if (url.pathname === '/api/v1/analytics/progress') {
      progressCalls.push(url.searchParams.get('class_id') ?? '');
      return route.fulfill({
        json: [
          {
            student_id: userId,
            subject_id: 3,
            graded_count: 1,
            average_grade: 5,
            student_name: 'Иванова Анна',
            subject_name: 'Литература',
          },
        ],
      });
    }
    if (url.pathname === '/api/v1/analytics/audit') {
      const offset = url.searchParams.get('offset') ?? '0';
      auditCalls.push({ offset });
      // Полная страница на offset=0, одиноко короткая на offset=50.
      const list = offset === '0' ? Array.from({ length: 50 }, (_, i) => event(i + 1)) : [event(51)];
      return route.fulfill({ json: list });
    }
    return route.fulfill({ status: 404, json: {} });
  });
  await page.goto('/analytics');
  await expect(page.getByRole('heading', { name: 'Успеваемость и аудит' })).toBeVisible();

  // Фильтр классом: смена класса перечитывает успеваемость с новым class_id.
  await expect(page.getByLabel('Класс')).toHaveValue('7');
  await page.getByLabel('Класс').selectOption('8');
  await expect
    .poll(() => progressCalls.at(-1))
    .toBe('8');

  // Пагинация журнала: полная страница включает «Следующие», offset идёт шагом 50.
  await expect(page.getByText('Страница 1')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Предыдущие' })).toBeDisabled();
  await expect(page.getByRole('button', { name: 'Следующие' })).toBeEnabled();
  await page.getByRole('button', { name: 'Следующие' }).click();
  await expect(page.getByText('Страница 2')).toBeVisible();
  await expect(auditCalls.at(-1)?.offset).toBe('50');
  // Короткая страница выключает «Следующие».
  await expect(page.getByRole('button', { name: 'Следующие' })).toBeDisabled();
  await page.getByRole('button', { name: 'Предыдущие' }).click();
  await expect(page.getByText('Страница 1')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Предыдущие' })).toBeDisabled();
  // Возврат на страницу 1 читается из кеша того же периода — без нового запроса.
  expect(auditCalls).toHaveLength(2);

  // Раскрытие события: технический JSON — экранированный текст, без исполнения HTML.
  const dangerous = page.getByRole('button', { name: 'Данные события' }).first();
  await dangerous.click();
  const payloadCell = page.locator('.audit-payload-row');
  await expect(payloadCell).toContainText('"grade": 4');
  await expect(payloadCell.locator('script')).toHaveCount(0);
  await expect(payloadCell.locator('img')).toHaveCount(0);
});

test('long audit payload is truncated with an indicator', async ({ page, context }) => {
  await page.clock.setFixedTime(new Date('2026-10-22T10:00:00Z'));
  const userId = '75ef34f4-2588-41b1-b41e-cbd058c6025c';
  await context.route('**/api/v1/**', async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname.endsWith('/refresh')) return route.fulfill({ json: { access_token: 'mock' } });
    if (url.pathname.endsWith('/me'))
      return route.fulfill({ json: { id: userId, email: 'admin@example.test', role: 'admin' } });
    if (url.pathname === '/api/v1/analytics/classes') return route.fulfill({ json: [] });
    if (url.pathname === '/api/v1/analytics/audit')
      return route.fulfill({
        json: [
          {
            event_id: userId,
            event_source: 'backoffice',
            event_type: 'user.renamed',
            schema_version: 1,
            occurred_at: '2026-10-22T09:00:00Z',
            request_id: null,
            actor: { source: 'backoffice', id: userId },
            payload: {
              comment: '<script>alert(1)</script>',
              blob: 'y'.repeat(4000),
            },
          },
        ],
      });
    return route.fulfill({ status: 404, json: {} });
  });
  await page.goto('/analytics');
  await page.getByRole('button', { name: 'Данные события' }).click();
  await expect(page.getByText(/усечены/)).toBeVisible();
  // HTML в payload остаётся текстом.
  await expect(page.locator('.technical-json pre')).toContainText('<script>alert(1)</script>');
  await expect(page.locator('.technical-json script')).toHaveCount(0);
});
