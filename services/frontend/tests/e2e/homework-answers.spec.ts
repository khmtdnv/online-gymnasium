import { expect, test } from '@playwright/test';

test('ученик сдаёт, преподаватель возвращает, ученик исправляет и получает оценку', async ({
  page,
  context,
}) => {
  const student = '75ef34f4-2588-41b1-b41e-cbd058c6025c';
  const teacher = '85ef34f4-2588-41b1-b41e-cbd058c6025c';
  let role = 'student';
  const answers: Record<string, unknown>[] = [];
  const lesson = {
    id: 501,
    class_id: 7,
    subject_id: 3,
    teacher_id: teacher,
    starts_at: '2030-10-20T10:00:00Z',
    ends_at: '2030-10-20T11:00:00Z',
    status: 'planned',
    version: 1,
  };
  const homework = {
    id: 42,
    issued_lesson_id: 501,
    class_id: 7,
    subject_id: 3,
    author_id: teacher,
    description: 'Решить уравнение',
    due_lesson_id: null,
    manual_due_datetime: '2030-10-21T12:00:00Z',
    created_at: '2030-10-20T10:00:00Z',
    files: [],
    final_due_datetime: '2030-10-21T12:00:00Z',
    due_status: 'manual',
  };
  await context.route('**/api/v1/**', async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (path.endsWith('/refresh')) return route.fulfill({ json: { access_token: 'test' } });
    if (path.endsWith('/me'))
      return route.fulfill({
        json: { id: role === 'student' ? student : teacher, email: `${role}@example.test`, role },
      });
    if (path === '/api/v1/homework/42') return route.fulfill({ json: homework });
    if (path === '/api/v1/lessons/501' || path === '/api/v1/my-schedule/lessons/501')
      return route.fulfill({
        json: {
          lesson: {
            ...lesson,
            class_name: '7А',
            subject_name: 'Математика',
            teacher_name: 'Иванов Иван',
          },
          next_lesson: null,
          homework_for_lesson: [],
          homework_from_lesson: [homework],
        },
      });
    if (path === '/api/v1/homework/42/answers') {
      if (request.method() === 'GET')
        return route.fulfill({ json: role === 'teacher' ? answers.slice(0, 1) : answers });
      expect(request.headers()['idempotency-key']).toBeTruthy();
      const body = request.postDataJSON();
      const answer = {
        id: answers.length + 1,
        homework_id: 42,
        student_id: student,
        student_name: 'Петров Иван',
        attempt_number: answers.length + 1,
        answer_text: body.answer_text,
        status: 'submitted',
        submitted_at: '2030-10-20T12:00:00Z',
        grade: null,
        teacher_comment: '',
        reviewer_id: null,
        reviewed_at: null,
        files: body.files.map(
          (
            file: { file_name: string; size_bytes: number; content_type: string },
            index: number,
          ) => ({
            id: index + 1,
            answer_id: answers.length + 1,
            file_name: file.file_name,
            size_bytes: file.size_bytes,
            content_type: file.content_type,
            upload_status: 'pending',
          }),
        ),
      };
      answers.unshift(answer);
      return route.fulfill({ status: 201, json: answer });
    }
    const fileMatch = path.match(/^\/api\/v1\/homework\/42\/answers\/(\d+)\/files\/(\d+)$/);
    if (fileMatch) {
      const answer = answers.find((row) => row.id === Number(fileMatch[1]))!;
      const file = (answer.files as { id: number; upload_status: string }[]).find(
        (row) => row.id === Number(fileMatch[2]),
      )!;
      if (request.method() === 'PUT') {
        file.upload_status = 'ready';
        return route.fulfill({ json: file });
      }
      return route.fulfill({
        body: 'answer',
        headers: { 'Content-Type': 'text/plain', 'Content-Length': '6' },
      });
    }
    if (path.endsWith('/review')) {
      const id = Number(path.split('/').at(-2));
      const answer = answers.find((row) => row.id === id)!;
      Object.assign(answer, request.postDataJSON(), {
        reviewer_id: teacher,
        reviewed_at: '2030-10-20T13:00:00Z',
      });
      return route.fulfill({ json: answer });
    }
    return route.fulfill({
      status: 404,
      json: { error: { code: 'not_found', message: 'Not found', request_id: 'test' } },
    });
  });
  await page.goto('/homework/42');
  await expect(page.getByRole('heading', { name: 'Условие задания' })).toBeVisible();
  await expect(page.getByText('Иванов Иван', { exact: true })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Урок, на котором задано' })).toBeVisible();
  await page.getByLabel('Ваш ответ').fill('Первый ответ');
  await page
    .getByLabel('Файлы ответа', { exact: true })
    .setInputFiles({ name: 'answer.txt', mimeType: 'text/plain', buffer: Buffer.from('answer') });
  await page.getByRole('button', { name: 'Сдать работу' }).click();
  await expect(page.getByText('Работа ожидает проверки.')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Скачать answer.txt' })).toBeVisible();
  role = 'teacher';
  await page.goto('/lessons/501');
  const downloading = page.waitForEvent('download');
  await page.getByRole('button', { name: 'Скачать answer.txt' }).click();
  expect((await downloading).suggestedFilename()).toBe('answer.txt');
  await page.getByLabel('Комментарий преподавателя').fill('Исправь знак');
  await page.getByRole('button', { name: 'Вернуть на исправление' }).click();
  await expect(page.getByText('Комментарий преподавателя: Исправь знак')).toBeVisible();
  role = 'student';
  await page.goto('/homework/42');
  await page.getByLabel('Ваш ответ').fill('Исправленный ответ');
  await page.getByRole('button', { name: 'Сдать работу' }).click();
  await expect(page.getByText(/Попытка №2/)).toBeVisible();
  role = 'teacher';
  await page.goto('/lessons/501');
  await page.getByRole('combobox', { name: 'Оценка', exact: true }).selectOption('4');
  await page.getByRole('button', { name: 'Поставить оценку' }).click();
  await expect(page.getByText('Оценка: 4')).toBeVisible();
  role = 'student';
  await page.goto('/homework/42');
  await expect(page.getByText('Оценка: 4')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Сдать работу' })).toHaveCount(0);
  expect(answers).toHaveLength(2);
});
