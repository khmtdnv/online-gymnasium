import { expect, test, type BrowserContext } from '@playwright/test';

const user = {
  id: '75ef34f4-2588-41b1-b41e-cbd058c6025c',
  email: 'teacher@example.test',
  role: 'teacher',
};
const lesson = {
  id: 501,
  class_id: 7,
  subject_id: 3,
  teacher_id: user.id,
  starts_at: '2030-10-20T10:00:00Z',
  ends_at: '2030-10-20T11:00:00Z',
  status: 'planned',
  version: 1,
};
const nextLesson = {
  ...lesson,
  id: 508,
  starts_at: '2030-10-23T10:00:00Z',
  ends_at: '2030-10-23T11:00:00Z',
};

async function backend(context: BrowserContext, temporary = false) {
  let created = 0;
  let role = 'teacher';
  let allowSecond = false;
  let files: {
    id: number;
    homework_id: number;
    file_name: string;
    size_bytes: number;
    content_type: string;
    upload_status: string;
  }[] = [];
  const calls: Record<number, number> = {};
  let homework: Record<string, unknown> | null = null;
  await context.route('**/api/v1/**', async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (path.endsWith('/refresh')) return route.fulfill({ json: { access_token: 'test-access' } });
    if (path.endsWith('/me')) return route.fulfill({ json: { ...user, role } });
    if (path === '/api/v1/lessons') return route.fulfill({ json: [lesson] });
    if (path === '/api/v1/my-schedule') {
      const week = new URL(request.url()).searchParams.get('week_start')!;
      return route.fulfill({
        json: {
          week_start: week,
          timezone: 'Asia/Yekaterinburg',
          has_class: true,
          days: Array.from({ length: 6 }, (_, index) => {
            const day = new Date(week + 'T12:00:00Z');
            day.setUTCDate(day.getUTCDate() + index);
            return { date: day.toISOString().slice(0, 10), lessons: [] };
          }),
        },
      });
    }
    const full = () =>
      homework
        ? { ...homework, files, final_due_datetime: nextLesson.starts_at, due_status: 'lesson' }
        : null;
    if (path === '/api/v1/lessons/501' || path === '/api/v1/my-schedule/lessons/501')
      return route.fulfill({
        json: {
          lesson: {
            ...lesson,
            class_name: '7А',
            subject_name: 'Математика',
            teacher_name: 'Иванов Иван',
          },
          next_lesson: {
            ...nextLesson,
            class_name: '7А',
            subject_name: 'Математика',
            teacher_name: 'Иванов Иван',
          },
          homework_for_lesson: [],
          homework_from_lesson: homework ? [full()] : [],
        },
      });
    if (path === '/api/v1/lessons/501/homework') {
      created++;
      const body = request.postDataJSON();
      files = body.files.map(
        (file: { file_name: string; size_bytes: number; content_type: string }, index: number) => ({
          id: 8 + index,
          homework_id: 42,
          file_name: file.file_name,
          size_bytes: file.size_bytes,
          content_type: file.content_type,
          upload_status: 'pending',
        }),
      );
      homework = {
        id: 42,
        issued_lesson_id: 501,
        class_id: 7,
        subject_id: 3,
        author_id: user.id,
        description: body.description,
        due_lesson_id: 508,
        manual_due_datetime: null,
        created_at: '2030-10-20T10:00:00Z',
      };
      return route.fulfill({ status: 201, json: { ...homework, files } });
    }
    const match = path.match(/^\/api\/v1\/homework\/42\/files\/(\d+)$/);
    if (match) {
      const id = Number(match[1]);
      const file = files.find((row) => row.id === id)!;
      if (request.method() === 'PUT') {
        calls[id] = (calls[id] ?? 0) + 1;
        if (id === 9 && !allowSecond)
          return route.fulfill({
            status: temporary ? 503 : 422,
            json: {
              error: {
                code: temporary ? 'service_unavailable' : 'invalid_homework_file',
                message: 'Failed',
                request_id: 'test',
              },
            },
          });
        file.upload_status = 'ready';
        return route.fulfill({ json: file });
      }
      return route.fulfill({
        body: 'answer',
        headers: {
          'Content-Type': 'text/plain',
          'Content-Length': '6',
          'Content-Disposition': `attachment; filename*=UTF-8''${file.file_name}`,
        },
      });
    }
    if (path === '/api/v1/homework') return route.fulfill({ json: homework ? [full()] : [] });
    if (path === '/api/v1/homework/42') return route.fulfill({ json: full() });
    return route.fulfill({
      status: 404,
      json: { error: { code: 'not_found', message: 'Missing', request_id: 'test' } },
    });
  });
  return {
    calls,
    created: () => created,
    allow: () => {
      allowSecond = true;
    },
    student: () => {
      role = 'student';
    },
  };
}

test('one click: текст и частичный успех, reload, ручная догрузка, скачивание ученика', async ({
  page,
  context,
}) => {
  const state = await backend(context);
  await page.goto('/lessons/501');
  await page.getByLabel('Что нужно выполнить').fill('Решить задачи1–5');
  await page.getByLabel('Файлы задания', { exact: true }).setInputFiles([
    { name: 'one.txt', mimeType: 'text/plain', buffer: Buffer.from('answer') },
    { name: 'two.txt', mimeType: 'text/plain', buffer: Buffer.from('answer') },
  ]);
  await page.getByRole('button', { name: 'Задать ДЗ', exact: true }).click();
  await expect(page.getByText('Задание создано и доступно ученикам.')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Скачать one.txt', exact: true })).toBeVisible();
  await expect(
    page.getByRole('button', { name: 'Повторить загрузку two.txt', exact: true }),
  ).toBeVisible();
  expect(state.created()).toBe(1);
  expect(state.calls).toEqual({ 8: 1, 9: 1 });
  await page.reload();
  await expect(page.getByText('Решить задачи1–5', { exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Задать ДЗ', exact: true })).toHaveCount(0);
  state.allow();
  await page
    .getByLabel('Выбрать файл заново: two.txt')
    .setInputFiles({ name: 'two.txt', mimeType: 'text/plain', buffer: Buffer.from('answer') });
  await page.getByRole('button', { name: 'Повторить загрузку two.txt', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Скачать two.txt', exact: true })).toBeVisible();
  expect(state.created()).toBe(1);
  expect(state.calls).toEqual({ 8: 1, 9: 2 });
  for (const width of [360, 768, 1440]) {
    await page.setViewportSize({ width, height: 1000 });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
      true,
    );
  }
  if (process.env.QA_SCREENSHOT_DIR)
    await page.screenshot({
      path: `${process.env.QA_SCREENSHOT_DIR}/homework-teacher.png`,
      fullPage: true,
    });
  state.student();
  await page.goto('/homework/42');
  const download = page.waitForEvent('download');
  await page.getByRole('button', { name: 'Скачать one.txt', exact: true }).click();
  expect((await download).suggestedFilename()).toBe('one.txt');
  await expect(page.getByLabel('Выбрать файл заново: two.txt')).toHaveCount(0);
});

test('автоповтор прекращается при уходе со страницы; после reload нужен выбор файла', async ({
  page,
  context,
}) => {
  const state = await backend(context, true);
  await page.clock.install();
  await page.goto('/lessons/501');
  await page.getByLabel('Что нужно выполнить').fill('Задание');
  await page.getByLabel('Файлы задания', { exact: true }).setInputFiles([
    { name: 'one.txt', mimeType: 'text/plain', buffer: Buffer.from('answer') },
    { name: 'two.txt', mimeType: 'text/plain', buffer: Buffer.from('answer') },
  ]);
  await page.getByRole('button', { name: 'Задать ДЗ', exact: true }).click();
  await expect.poll(() => state.calls[9]).toBe(1);
  await page.goto('/my-schedule');
  await expect(page.getByRole('heading', { name: 'Моё расписание' })).toBeVisible();
  await page.clock.runFor(20000);
  expect(state.calls[9]).toBe(1);
  await page.goto('/lessons/501');
  await expect(
    page.getByRole('button', { name: 'Повторить загрузку two.txt', exact: true }),
  ).toBeDisabled();
});

test('временный сбой автоматически догружает файл без повторного создания ДЗ', async ({
  page,
  context,
}) => {
  const state = await backend(context, true);
  await page.clock.install();
  await page.goto('/lessons/501');
  await page.getByLabel('Что нужно выполнить').fill('Задание');
  await page.getByLabel('Файлы задания', { exact: true }).setInputFiles([
    { name: 'one.txt', mimeType: 'text/plain', buffer: Buffer.from('answer') },
    { name: 'two.txt', mimeType: 'text/plain', buffer: Buffer.from('answer') },
  ]);
  await page.getByRole('button', { name: 'Задать ДЗ', exact: true }).click();
  await expect.poll(() => state.calls[9]).toBe(1);
  await expect(page.getByRole('status').filter({ hasText: 'Загружаем файлы' })).toBeVisible();
  state.allow();
  await page.clock.runFor(2100);
  await expect(page.getByRole('button', { name: 'Скачать two.txt', exact: true })).toBeVisible();
  expect(state.calls).toEqual({ 8: 1, 9: 2 });
  expect(state.created()).toBe(1);
});
