import { expect, test } from '@playwright/test';

test('student sends points through WebSocket, receives ACK and restores the saved stroke', async ({
  page,
  context,
}) => {
  const studentId = '75ef34f4-2588-41b1-b41e-cbd058c6025c';
  const saved: Record<string, unknown>[] = [];
  await context.route('**/api/v1/**', async (route) => {
    if (route.request().url().endsWith('/refresh'))
      return route.fulfill({ json: { access_token: 'mock-access' } });
    if (route.request().url().endsWith('/me'))
      return route.fulfill({
        json: { id: studentId, email: 'student@example.test', role: 'student' },
      });
    return route.fulfill({ status: 404, json: {} });
  });
  await page.routeWebSocket('**/api/v1/pen/**', (ws) => {
    ws.onMessage((raw) => {
      const value = JSON.parse(String(raw));
      if (value.access_token) {
        expect(ws.url()).not.toContain('mock-access');
        for (const batch of saved) ws.send(JSON.stringify({ type: 'batch', batch }));
        ws.send(JSON.stringify({ type: 'ready', after: saved.length }));
      } else {
        const existing = saved.find((batch) => batch.batch_id === value.batch_id);
        const batch = existing ?? { ...value, id: saved.length + 1 };
        if (!existing) saved.push(batch);
        if (saved.length === 1 && !existing) {
          // База сохранила данные, но ACK не дошёл до браузера.
          ws.close({ code: 1013, reason: 'temporary network failure' });
        } else ws.send(JSON.stringify({ type: 'ack', batch }));
      }
    });
  });
  await page.goto('/pen/lessons/1');
  await expect(page.getByText('Подключено. Все штрихи сохранены.')).toBeVisible();
  const canvas = page.getByRole('img', { name: 'Холст умной ручки' });
  const box = await canvas.boundingBox();
  expect(box).not.toBeNull();
  await page.mouse.move(box!.x + 30, box!.y + 30);
  await page.mouse.down();
  await page.mouse.move(box!.x + 150, box!.y + 80, { steps: 12 });
  await page.mouse.up();
  await expect.poll(() => saved.length).toBeGreaterThan(0);
  await expect(canvas.locator('polyline')).toHaveCount(1);
  await page.reload();
  await expect(canvas.locator('polyline')).toHaveCount(1);
  await expect(page.getByText('Подключено. Все штрихи сохранены.')).toBeVisible();
});

test('teacher chooses a named student and cannot draw on the read-only page', async ({
  page,
  context,
}) => {
  const id = '75ef34f4-2588-41b1-b41e-cbd058c6025c';
  const studentId = '5c030f6b-6581-49a7-ad3a-4279d7305027';
  let writes = 0;
  await context.route('**/api/v1/**', async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith('/refresh'))
      return route.fulfill({ json: { access_token: 'teacher-token' } });
    if (path.endsWith('/me'))
      return route.fulfill({ json: { id, email: 'teacher@example.test', role: 'teacher' } });
    if (path.endsWith('/students'))
      return route.fulfill({ json: [{ id: studentId, name: 'Петров Иван' }] });
    return route.fulfill({ status: 404, json: {} });
  });
  await page.routeWebSocket('**/api/v1/pen/**', (ws) => {
    ws.onMessage((raw) => {
      const value = JSON.parse(String(raw));
      if (!value.access_token) {
        writes++;
        return;
      }
      ws.send(
        JSON.stringify({
          type: 'batch',
          batch: {
            id: 1,
            batch_id: id,
            sequence: 1,
            stroke_id: id,
            points: [
              { x: 0.1, y: 0.1 },
              { x: 0.2, y: 0.2 },
            ],
            finished: true,
          },
        }),
      );
      ws.send(JSON.stringify({ type: 'ready', after: 1 }));
    });
  });
  await page.goto('/pen/lessons/1');
  await expect(page.getByLabel('Ученик')).toHaveValue(studentId);
  const canvas = page.getByRole('img', { name: 'Холст умной ручки' });
  await expect(canvas.locator('polyline')).toHaveCount(1);
  const box = await canvas.boundingBox();
  await page.mouse.move(box!.x + 30, box!.y + 30);
  await page.mouse.down();
  await page.mouse.move(box!.x + 150, box!.y + 80, { steps: 10 });
  await page.mouse.up();
  expect(writes).toBe(0);
  await expect(canvas.locator('polyline')).toHaveCount(1);
});
