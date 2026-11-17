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
  await expect(page.getByRole('table')).toContainText('Петров Иван');
  await expect(page.getByRole('table')).toContainText('4,50');
  await expect(page.getByLabel('Класс')).toHaveValue('7');
  await page.getByText('Данные события', { exact: true }).click();
  await expect(page.getByText('"grade": 4', { exact: false })).toBeVisible();
  await page.setViewportSize({ width: 360, height: 800 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(
    true,
  );
});
