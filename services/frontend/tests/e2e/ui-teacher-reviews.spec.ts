import { expect, test } from '@playwright/test';

test('преподаватель открывает и проверяет работу из общего списка', async ({ page, context }) => {
  const teacher = '85ef34f4-2588-41b1-b41e-cbd058c6025c';
  const student = '75ef34f4-2588-41b1-b41e-cbd058c6025c';
  let graded = false;
  const answer = () => ({
    id: 9,
    homework_id: 42,
    student_id: student,
    student_name: 'Иван Петров',
    attempt_number: 1,
    answer_text: 'Мой ответ',
    status: graded ? 'graded' : 'submitted',
    submitted_at: '2026-10-19T06:00:00Z',
    grade: graded ? 5 : null,
    teacher_comment: '',
    reviewer_id: graded ? teacher : null,
    reviewed_at: graded ? '2026-10-19T07:00:00Z' : null,
    files: [],
  });
  await context.route('**/api/v1/**', async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith('/refresh')) return route.fulfill({ json: { access_token: 'mock' } });
    if (path.endsWith('/me'))
      return route.fulfill({
        json: { id: teacher, role: 'teacher', email: 'teacher@example.test' },
      });
    if (path === '/api/v1/homework/review-queue')
      return route.fulfill({
        json: {
          items: [
            {
              answer_id: 9,
              homework_id: 42,
              lesson_id: 501,
              class_id: 7,
              class_name: '7А',
              subject_id: 1,
              subject_name: 'Математика',
              student_id: student,
              student_name: 'Иван Петров',
              description: 'Решить задачу',
              status: graded ? 'graded' : 'submitted',
              submitted_at: '2026-10-19T06:00:00Z',
            },
          ],
          next_cursor: null,
        },
      });
    if (path === '/api/v1/homework/42/answers/9/review') {
      graded = true;
      return route.fulfill({ json: answer() });
    }
    if (path === '/api/v1/homework/42/answers/9') return route.fulfill({ json: answer() });
    if (path === '/api/v1/notifications/count') return route.fulfill({ json: { unread: 0 } });
    return route.fulfill({ json: [] });
  });
  await page.goto('/homework');
  await expect(
    page.getByRole('heading', { name: 'Очередь проверки домашних заданий' }),
  ).toBeVisible();
  await expect(page.getByText('Работ на проверке: 1')).toBeVisible();
  await expect(page.getByRole('button', { name: 'На проверке', exact: true })).toContainText('1');
  await page.getByLabel('Поиск ученика').fill('Неттакова');
  await expect(page.getByText('В загруженных работах ничего не найдено.')).toBeVisible();
  await page.getByLabel('Поиск ученика').fill('Иван');
  await page.getByRole('combobox', { name: 'Сортировка работ' }).selectOption('old');
  await expect(page.getByRole('article').getByText('Математика', { exact: true })).toBeVisible();
  await expect(page.getByRole('article').getByText('7А', { exact: true })).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(
    true,
  );
  await page.getByRole('link', { name: 'Открыть работу' }).click();
  await expect(page.getByText('Мой ответ')).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Оценка и рецензия' })).toBeVisible();
  await page.getByRole('button', { name: /Поставить оценку/ }).click();
  await expect(page.getByText('Оценка: 5')).toBeVisible();
  await page.getByRole('button', { name: 'Проверено', exact: true }).click();
  await expect(page.getByRole('link', { name: 'Открыть работу' })).toBeVisible();
});
