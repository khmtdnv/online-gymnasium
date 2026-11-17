import { expect, test } from '@playwright/test';

test('личные уведомления: прочтение обновляет список и счётчик', async ({ page, context }) => {
  const user = '00000000-0000-4000-8000-000000000003';
  let read = false;
  await context.route('**/api/v1/**', async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path === '/api/v1/auth/refresh') return route.fulfill({ json: { access_token: 'test' } });
    if (path === '/api/v1/auth/me')
      return route.fulfill({ json: { id: user, role: 'student', email: 'student@example.test' } });
    if (path === '/api/v1/notifications/count')
      return route.fulfill({ json: { unread: read ? 0 : 1 } });
    if (path === '/api/v1/notifications/1/read') {
      expect(route.request().postDataJSON()).toEqual({});
      read = true;
      return route.fulfill({ json: { read: true } });
    }
    if (path === '/api/v1/notifications')
      return route.fulfill({
        json: [
          {
            id: 1,
            event_id: '00000000-0000-4000-8000-000000000007',
            recipient_id: user,
            title: 'Домашнее задание проверено',
            body: 'Оценка: 5.',
            link: '/homework/7',
            created_at: '2026-10-22T12:00:00Z',
            read_at: read ? '2026-10-22T12:01:00Z' : null,
          },
        ],
      });
    return route.fulfill({ json: [] });
  });
  await page.goto('/notifications');
  await expect(page.getByRole('heading', { level: 1, name: 'Уведомления' })).toBeVisible();
  await expect(page.getByText('Непрочитанных: 1', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Отметить прочитанным' }).click();
  await expect(page.getByText('Непрочитанных: 0', { exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Отметить прочитанным' })).toHaveCount(0);
  await expect(page.getByRole('link', { name: 'Открыть', exact: true })).toHaveAttribute(
    'href',
    '/homework/7',
  );
});
