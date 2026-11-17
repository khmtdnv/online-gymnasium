import { expect, test } from '@playwright/test';

test('документы: договор, стабильный повтор и переход к своему заданию', async ({
  page,
  context,
}) => {
  const id = '00000000-0000-4000-8000-000000000007';
  const actor = '00000000-0000-4000-8000-000000000003';
  const keys: string[] = [];
  await context.route('**/api/v1/**', async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path === '/api/v1/auth/refresh') return route.fulfill({ json: { access_token: 'test' } });
    if (path === '/api/v1/auth/me')
      return route.fulfill({ json: { id: actor, role: 'admin', email: 'admin@example.test' } });
    if (path === '/api/v1/documents' && route.request().method() === 'POST') {
      const body = route.request().postDataJSON();
      expect(body.document_type).toBe('contract');
      expect(body.payload.student_full_name).toBe('Петров Иван');
      expect(body.creator_id).toBeUndefined();
      keys.push(body.request_key);
      if (keys.length === 1) return route.abort();
      return route.fulfill({
        status: 202,
        json: { id, document_type: 'contract', status: 'pending' },
      });
    }
    if (path === `/api/v1/documents/${id}`)
      return route.fulfill({
        json: {
          id,
          document_type: 'contract',
          status: 'pending',
          created_at: '2026-10-22T12:00:00Z',
        },
      });
    return route.fulfill({ json: [] });
  });
  await page.goto('/documents');
  await page.getByLabel('Тип документа').selectOption('contract');
  await page.getByLabel('ФИО ученика').fill('Петров Иван');
  await page.getByLabel('Класс', { exact: true }).fill('7А');
  await page.getByLabel('Учебный год').fill('2026/2027');
  await page.getByRole('button', { name: 'Создать договор' }).click();
  await expect(page.getByRole('button', { name: 'Повторить с тем же ключом' })).toBeVisible();
  await page.getByRole('button', { name: 'Повторить с тем же ключом' }).click();
  await expect(page.getByRole('heading', { name: 'Ваш документ' })).toBeVisible();
  expect(keys).toHaveLength(2);
  expect(keys[0]).toBe(keys[1]);
});
