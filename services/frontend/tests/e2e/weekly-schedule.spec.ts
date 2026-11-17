import { expect, test } from '@playwright/test';

test('UI mock: неделя, мобильный день, урок и ДЗ с понятными названиями', async ({
  page,
  context,
}) => {
  await page.clock.setFixedTime(new Date('2026-10-21T07:00:00Z'));
  let role = 'student';
  const student = '75ef34f4-2588-41b1-b41e-cbd058c6025c';
  const teacher = '85ef34f4-2588-41b1-b41e-cbd058c6025c';
  const lesson = {
    id: 501,
    class_id: 7,
    subject_id: 1,
    teacher_id: teacher,
    starts_at: '2026-10-19T04:00:00Z',
    ends_at: '2026-10-19T04:45:00Z',
    status: 'planned',
    version: 1,
    subject_name: 'Математика',
    class_name: '7А',
    teacher_name: 'Иванов Иван Иванович',
  };
  const homework = {
    id: 42,
    issued_lesson_id: 501,
    class_id: 7,
    subject_id: 1,
    author_id: teacher,
    description: 'Решить задачи и объяснить решение',
    due_lesson_id: null,
    manual_due_datetime: '2026-10-23T05:00:00Z',
    final_due_datetime: '2026-10-23T05:00:00Z',
    due_status: 'manual',
    created_at: '2026-10-19T06:00:00Z',
    files: [],
  };
  await context.route('**/api/v1/**', async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname.endsWith('/refresh')) return route.fulfill({ json: { access_token: 'mock' } });
    if (url.pathname.endsWith('/me'))
      return route.fulfill({
        json: { id: role === 'student' ? student : teacher, email: role + '@example.test', role },
      });
    if (url.pathname === '/api/v1/my-schedule') {
      expect(url.searchParams.has('class_id')).toBe(false);
      expect(url.searchParams.has('student_id')).toBe(false);
      const week = url.searchParams.get('week_start')!;
      return route.fulfill({
        json: {
          week_start: week,
          timezone: 'Asia/Yekaterinburg',
          has_class: true,
          days: Array.from({ length: 6 }, (_, index) => {
            const day = new Date(week + 'T12:00:00Z');
            day.setUTCDate(day.getUTCDate() + index);
            const date = day.toISOString().slice(0, 10);
            return { date, lessons: date === '2026-10-19' ? [lesson] : [] };
          }),
        },
      });
    }
    if (url.pathname === '/api/v1/my-schedule/lessons/501')
      return route.fulfill({
        json: {
          lesson,
          next_lesson: null,
          homework_for_lesson: [],
          homework_from_lesson: [homework],
        },
      });
    if (url.pathname === '/api/v1/homework/42') return route.fulfill({ json: homework });
    if (url.pathname === '/api/v1/homework/42/answers') return route.fulfill({ json: [] });
    if (url.pathname === '/api/v1/my-homework')
      return route.fulfill({
        json: {
          date_from: url.searchParams.get('date_from'),
          date_to: url.searchParams.get('date_to'),
          timezone: 'Asia/Yekaterinburg',
          total: 1,
          items: [
            {
              ...homework,
              subject_name: 'Математика',
              teacher_name: 'Иванов Иван Иванович',
              latest_answer_status: null,
              grade: null,
            },
          ],
        },
      });
    return route.fulfill({
      status: 404,
      json: { error: { code: 'not_found', message: 'Not found', request_id: 'mock' } },
    });
  });
  await page.goto('/my-schedule');
  await expect(page.getByRole('heading', { name: 'Моё расписание' })).toBeVisible();
  for (const width of [1440, 768, 360]) {
    await page.setViewportSize({ width, height: 1000 });
    await expect(page.locator('.week-day:visible')).toHaveCount(width === 1440 ? 6 : 1);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(
      true,
    );
  }
  await page.getByRole('tab', { name: /пн\s*19/i }).click();
  await page.getByRole('link', { name: /Математика/ }).click();
  await expect(page.getByRole('heading', { name: 'Математика', exact: true })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Подготовить к этому уроку' })).toBeVisible();
  await page.getByRole('link', { name: 'Открыть задание', exact: true }).click();
  await expect(page.getByText('Решить задачи и объяснить решение', { exact: true })).toBeVisible();
  await page.goto('/homework');
  await expect(page.getByRole('link', { name: /Математика/ })).toBeVisible();
  await page.goto('/my-schedule');
  await page.getByRole('button', { name: 'Предыдущая неделя' }).focus();
  await page.getByRole('button', { name: 'Предыдущая неделя' }).press('Enter');
  await expect(page.getByRole('tab', { name: /пн\s*12/i })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Предыдущая неделя' })).toBeFocused();
  await page.getByRole('button', { name: 'Сегодня', exact: true }).click();
  await expect(page.getByRole('tab', { name: /пн\s*19/i })).toBeVisible();
  role = 'teacher';
  await page.goto('/lessons/501');
  await expect(page.getByRole('heading', { name: 'Урок и домашние задания' })).toBeVisible();
  await expect(page.getByText(/Математика · 7А/)).toBeVisible();
});
