import { expect, test } from '@playwright/test';

const user = '00000000-0000-4000-8000-000000000003';

function notification(id: number, read: boolean) {
  return {
    id,
    event_id: '00000000-0000-4000-8000-000000000007',
    recipient_id: user,
    title: 'Домашнее задание проверено',
    body: 'Оценка: 5.',
    link: '/homework/7',
    created_at: '2026-10-22T12:00:00Z',
    read_at: read ? '2026-10-22T12:01:00Z' : null,
  };
}

test('личные уведомления: панель и страница после отметки всех', async ({ page, context }) => {
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
    if (path === '/api/v1/notifications') return route.fulfill({ json: [notification(1, read)] });
    return route.fulfill({ json: [] });
  });
  await page.goto('/notifications');
  await expect(page.getByRole('heading', { level: 1, name: 'Уведомления' })).toBeVisible();
  await expect(page.getByText('Непрочитанных: 1', { exact: true })).toBeVisible();

  // Панель из шапки: заголовок, бейдж, вкладки и действия по макету g02.
  await page.getByRole('button', { name: 'Уведомления: непрочитанных 1' }).click();
  const popup = page.getByRole('dialog', { name: 'Уведомления' });
  await expect(popup).toBeVisible();
  await expect(popup.getByText('1 новых', { exact: true })).toBeVisible();
  await expect(popup.getByText('Домашнее задание проверено')).toBeVisible();
  await expect(popup.getByText('Домашние задания', { exact: true })).toBeVisible();
  await expect(popup.getByRole('link', { name: 'Открыть' })).toHaveAttribute('href', '/homework/7');
  await expect(popup.getByRole('button', { name: 'Закрыть (Esc)' })).toBeVisible();
  await popup.getByRole('button', { name: 'Непрочитанные' }).click();
  await expect(popup.getByText('Домашнее задание проверено')).toBeVisible();
  await popup.getByRole('button', { name: /^Все/ }).click();

  await popup.getByRole('button', { name: 'Отметить все как прочитанные' }).click();
  await expect(page.getByText('Непрочитанных: 0', { exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Уведомления', exact: true })).toBeVisible();
  await expect(popup.getByText('нет новых', { exact: true })).toBeVisible();
  await expect(popup.getByRole('button', { name: 'Отметить прочитанным' })).toHaveCount(0);

  // Возврат: Esc закрывает панель, страница остаётся собой.
  await page.keyboard.press('Escape');
  await expect(popup).not.toBeVisible();
  await expect(page).toHaveURL(/\/notifications$/);
  await expect(page.getByRole('button', { name: 'Отметить прочитанным' })).toHaveCount(0);
  await expect(page.getByRole('link', { name: 'Открыть', exact: true })).toHaveAttribute(
    'href',
    '/homework/7',
  );
  await expect(page.getByRole('link', { name: 'На главную' })).toHaveAttribute('href', '/');
  await expect(page.getByRole('button', { name: 'Назад' })).toBeDisabled();
  await expect(page.getByRole('button', { name: 'Дальше' })).toBeDisabled();
});

test('пустые уведомления: страница и панель показывают «Все прочитано»', async ({
  page,
  context,
}) => {
  await context.route('**/api/v1/**', async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path === '/api/v1/auth/refresh') return route.fulfill({ json: { access_token: 'test' } });
    if (path === '/api/v1/auth/me')
      return route.fulfill({ json: { id: user, role: 'student', email: 'student@example.test' } });
    if (path === '/api/v1/notifications/count') return route.fulfill({ json: { unread: 0 } });
    if (path === '/api/v1/notifications') return route.fulfill({ json: [] });
    return route.fulfill({ json: [] });
  });
  await page.goto('/notifications');
  await expect(page.getByRole('heading', { level: 1, name: 'Уведомления' })).toBeVisible();
  await expect(page.getByText('Непрочитанных: 0', { exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Отметить все как прочитанные' })).toBeDisabled();
  await expect(page.getByText('Все прочитано').first()).toBeVisible();

  await page.getByRole('button', { name: 'Уведомления', exact: true }).click();
  const popup = page.getByRole('dialog', { name: 'Уведомления' });
  await expect(popup.getByText('нет новых', { exact: true })).toBeVisible();
  await expect(popup.getByText('Все прочитано')).toBeVisible();
  await expect(popup.getByRole('link', { name: 'Все уведомления и архив' })).toHaveAttribute(
    'href',
    '/notifications',
  );
  await popup.getByRole('button', { name: 'Закрыть (Esc)' }).click();
  await expect(popup).not.toBeVisible();
});
