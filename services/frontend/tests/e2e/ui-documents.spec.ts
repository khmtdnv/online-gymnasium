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
  // Шаг 1 — карточка типа документа вместо выпадающего списка.
  await page.getByLabel('Договор об обучении').check();
  await expect(page.getByLabel('Договор об обучении')).toBeChecked();
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

test('задание документа: ожидание, готовый PDF (A05)', async ({ page, context }) => {
  const id = '00000000-0000-4000-8000-000000000011';
  let polls = 0;
  await context.route('**/api/v1/**', async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path === '/api/v1/auth/refresh') return route.fulfill({ json: { access_token: 'test' } });
    if (path === '/api/v1/auth/me')
      return route.fulfill({
        json: {
          id: '00000000-0000-4000-8000-000000000003',
          role: 'admin',
          email: 'admin@example.test',
        },
      });
    if (path === `/api/v1/documents/${id}`) {
      polls += 1;
      return route.fulfill({
        json: {
          id,
          document_type: 'certificate',
          status: polls === 1 ? 'processing' : 'completed',
          created_at: '2026-11-05T12:00:00Z',
        },
      });
    }
    if (path === `/api/v1/documents/${id}/content`)
      return route.fulfill({
        headers: { 'Content-Type': 'application/pdf' },
        body: '%PDF-1.4 готовый документ',
      });
    return route.fulfill({ json: [] });
  });
  await page.goto(`/documents/${id}`);
  await expect(page.locator('.job-status-card')).toHaveAttribute('data-status', 'processing');
  await expect(page.getByText('Готовим PDF')).toBeVisible();
  await expect(page.locator('.job-status-card')).toHaveAttribute('data-status', 'completed', {
    timeout: 10000,
  });
  await expect(page.getByRole('link', { name: 'Скачать PDF' })).toHaveAttribute(
    'download',
    `document-${id}.pdf`,
  );
  const frame = page.locator('.pdf-frame');
  await expect(frame).toHaveAttribute('title', 'Учебный документ — PDF');
  expect(await frame.getAttribute('src')).toMatch(/^blob:/);
});

test('задание документа: ошибка генерации (A05)', async ({ page, context }) => {
  const id = '00000000-0000-4000-8000-000000000012';
  await context.route('**/api/v1/**', async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path === '/api/v1/auth/refresh') return route.fulfill({ json: { access_token: 'test' } });
    if (path === '/api/v1/auth/me')
      return route.fulfill({
        json: {
          id: '00000000-0000-4000-8000-000000000003',
          role: 'admin',
          email: 'admin@example.test',
        },
      });
    if (path === `/api/v1/documents/${id}`)
      return route.fulfill({
        json: {
          id,
          document_type: 'receipt',
          status: 'failed',
          created_at: '2026-11-05T12:00:00Z',
        },
      });
    return route.fulfill({ json: [] });
  });
  await page.goto(`/documents/${id}`);
  await expect(page.getByText('Не удалось создать')).toBeVisible();
  await expect(page.getByRole('alert')).toContainText('не удалось подготовить');
  await page.getByRole('link', { name: 'К новому документу' }).click();
  await expect(page).toHaveURL(/\/documents$/);
  await expect(page.getByRole('heading', { name: 'Документы' })).toBeVisible();
});
