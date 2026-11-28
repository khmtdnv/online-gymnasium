import { expect, test } from '@playwright/test';

const student = '75ef34f4-2588-41b1-b41e-cbd058c6025c';
const secondChild = '95ef34f4-2588-41b1-b41e-cbd058c6025c';
const teacher = '85ef34f4-2588-41b1-b41e-cbd058c6025c';
const ivan = student;
const maria = secondChild;

function diaryLesson(overrides: Record<string, unknown>) {
  return {
    lesson_id: 501,
    subject_id: 1000,
    date: '2026-11-16',
    starts_at: '2026-11-16T04:00:00Z',
    ends_at: '2026-11-16T04:45:00Z',
    status: 'planned',
    attendance: 'present',
    absence_reason: null,
    grades: [],
    homework_status: null,
    homework_grade: null,
    ...overrides,
  };
}

/** Неделя ученика: оценка с типом, «не отмечено», пропуск по болезни и отмена. */
function diaryWeek(weekStart: string) {
  return {
    week_start: weekStart,
    timezone: 'Asia/Yekaterinburg',
    demo_cutoff: '2026-11-19',
    quarter: 2,
    lessons: [
      diaryLesson({ grades: [[5, 'oral']], homework_status: 'submitted' }),
      diaryLesson({
        lesson_id: 502,
        starts_at: '2026-11-16T05:00:00Z',
        ends_at: '2026-11-16T05:45:00Z',
        attendance: 'unmarked',
      }),
      diaryLesson({
        lesson_id: 503,
        subject_id: 1001,
        date: '2026-11-17',
        starts_at: '2026-11-17T04:00:00Z',
        ends_at: '2026-11-17T04:45:00Z',
        attendance: 'absent',
        absence_reason: 'sick',
        homework_status: 'not_submitted',
      }),
      diaryLesson({
        lesson_id: 504,
        subject_id: 1002,
        date: '2026-11-17',
        starts_at: '2026-11-17T05:00:00Z',
        ends_at: '2026-11-17T05:45:00Z',
        status: 'canceled',
        attendance: 'unmarked',
      }),
    ],
    summary: {
      quarter: 2,
      quarter_from: '2026-11-09',
      quarter_to: '2026-12-28',
      subject_averages: [
        { subject_id: 1000, average: 4.5, grade_count: 10, quarter_grade: 5 },
      ],
      absences: [{ lesson_id: 503, lesson_date: '2026-11-17', reason: 'sick' }],
    },
  };
}

function quarterSummary(quarter: number) {
  return {
    quarter,
    quarter_from: '2026-09-01',
    quarter_to: '2026-12-28',
    subject_averages:
      quarter <= 2
        ? [{ subject_id: 1000, average: 4 + quarter * 0.25, grade_count: 8 + quarter, quarter_grade: 4 }]
        : [],
    absences: [],
  };
}

test('ученик: неделя со статусами, навигация и сводка прошедшей четверти', async ({
  page,
  context,
}) => {
  const diaryRequests: string[] = [];
  await context.route('**/api/v1/**', async (route) => {
    const url = new URL(route.request().url());
    const path = url.pathname;
    if (path === '/api/v1/auth/refresh')
      return route.fulfill({ json: { access_token: 'mock' } });
    if (path === '/api/v1/auth/me')
      return route.fulfill({ json: { id: student, role: 'student', email: 'student@example.test' } });
    if (path === '/api/v1/notifications/count') return route.fulfill({ json: { unread: 0 } });
    if (path === '/api/v1/diary') {
      diaryRequests.push(url.search);
      const weekStart = url.searchParams.get('week_start') ?? '2026-11-16';
      return route.fulfill({ json: diaryWeek(weekStart) });
    }
    if (path === '/api/v1/diary/summary')
      return route.fulfill({ json: quarterSummary(Number(url.searchParams.get('quarter'))) });
    return route.fulfill({ json: [] });
  });
  await page.goto('/diary');
  await expect(page.getByTestId('diary-grid')).toBeVisible();
  // Дефолт — якорная неделя сервера: запрос ушёл без week_start.
  expect(diaryRequests.at(-1)).toBe('');
  await expect(page.getByText('Пн 16 ноября')).toBeVisible();
  await expect(page.getByText('не отмечено')).toBeVisible();
  await expect(page.getByText('не был (болезнь)')).toBeVisible();
  await expect(page.getByText('не сдано')).toBeVisible();
  await expect(page.getByText('Урок отменён')).toBeVisible();
  await expect(page.getByText('Демо-срез на дату 19 ноября')).toBeVisible();
  await expect(page.getByTestId('diary-summary')).toContainText('предварительно');
  await expect(page.getByTestId('diary-dynamics')).toContainText('4.25');

  await page.getByRole('button', { name: 'Следующая →' }).click();
  await expect(page.getByText('Пн 23 ноября')).toBeVisible();
  expect(diaryRequests.at(-1)).toBe('?week_start=2026-11-23');

  await page.getByLabel('Четверть сводки').selectOption('1');
  await expect(page.getByTestId('diary-summary')).toContainText('Четверть 1');
  await expect(page.getByTestId('diary-summary')).not.toContainText('предварительно');
  await page.setViewportSize({ width: 360, height: 800 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

test('учитель: отмечает посещаемость и оценки урока одним пакетом', async ({
  page,
  context,
}) => {
  let saved: { attendance: unknown[]; grades: unknown[] } | null = null;
  const lessonView = {
    lesson: {
      id: 501,
      class_id: 7,
      teacher_id: teacher,
      subject_id: 3,
      starts_at: '2026-11-16T04:00:00Z',
      ends_at: '2026-11-16T04:45:00Z',
      status: 'planned',
      version: 1,
      class_name: '7А',
      subject_name: 'Математика',
      teacher_name: 'Анна Смирнова',
    },
    next_lesson: null,
    homework_for_lesson: [],
    homework_from_lesson: [],
  };
  await context.route('**/api/v1/**', async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path === '/api/v1/auth/refresh')
      return route.fulfill({ json: { access_token: 'mock' } });
    if (path === '/api/v1/auth/me')
      return route.fulfill({ json: { id: teacher, role: 'teacher', email: 'teacher@example.test' } });
    if (path === '/api/v1/notifications/count') return route.fulfill({ json: { unread: 0 } });
    if (path === '/api/v1/my-schedule/lessons/501')
      return route.fulfill({ json: lessonView });
    if (path === '/api/v1/pen/lessons/501/students')
      return route.fulfill({
        json: [
          { id: ivan, name: 'Иван Петров' },
          { id: maria, name: 'Мария Петрова' },
        ],
      });
    if (path === '/api/v1/lessons/501/entries') {
      if (route.request().method() === 'POST') {
        const body = route.request().postDataJSON();
        // Контракт Gateway: lesson_id живёт в адресе, тела без него.
        expect(body.lesson_id).toBeUndefined();
        expect(body.context).toEqual({
          class_id: 7,
          subject_id: 3,
          lesson_date: '2026-11-16',
          status: 'planned',
          teacher_id: teacher,
        });
        saved = body;
        return route.fulfill({
          json: {
            attendance: body.attendance.map((row: object) => ({ lesson_id: 501, ...row })),
            grades: body.grades.map((row: object) => ({ lesson_id: 501, ...row })),
          },
        });
      }
      return route.fulfill({
        json: {
          attendance: [
            { lesson_id: 501, student_id: ivan, status: 'present' },
          ],
          grades: [{ lesson_id: 501, student_id: ivan, grade: 5, kind: 'oral' }],
        },
      });
    }
    return route.fulfill({ json: [] });
  });
  await page.goto('/lessons/501');
  await expect(page.getByRole('heading', { name: 'Посещаемость и оценки' })).toBeVisible();
  const mariaGroup = page.getByRole('radiogroup', { name: 'Посещаемость: Мария Петрова' });
  await expect(mariaGroup.getByRole('radio', { name: 'не отмечено' })).toBeChecked();
  await mariaGroup.getByRole('radio', { name: 'Был', exact: true }).check();
  await page.getByLabel('Оценка 1: тип — Мария Петрова').selectOption('written');
  await page.getByLabel('Оценка 1: балл — Мария Петрова').selectOption('4');
  await page.getByRole('button', { name: 'Сохранить записи урока' }).click();
  await expect(page.getByText('Записи урока сохранены.')).toBeVisible();
  await page.setViewportSize({ width: 360, height: 800 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  expect(saved).toEqual({
    context: {
      class_id: 7,
      subject_id: 3,
      lesson_date: '2026-11-16',
      status: 'planned',
      teacher_id: teacher,
    },
    attendance: [
      { student_id: ivan, status: 'present' },
      { student_id: maria, status: 'present' },
    ],
    grades: [
      { student_id: ivan, kind: 'oral', grade: 5 },
      { student_id: maria, kind: 'written', grade: 4 },
    ],
  });
});

test('родитель: переключает ребёнка и читает его дневник', async ({ page, context }) => {
  const diaryRequests: string[] = [];
  await context.route('**/api/v1/**', async (route) => {
    const url = new URL(route.request().url());
    const path = url.pathname;
    if (path === '/api/v1/auth/refresh')
      return route.fulfill({ json: { access_token: 'mock' } });
    if (path === '/api/v1/auth/me')
      return route.fulfill({ json: { id: '00000000-0000-4000-8000-000000000004', role: 'parent', email: 'parent@example.test' } });
    if (path === '/api/v1/notifications/count') return route.fulfill({ json: { unread: 0 } });
    if (path === '/api/v1/billing/students')
      return route.fulfill({
        json: [
          { id: ivan, name: 'Иван Петров' },
          { id: maria, name: 'Мария Петрова' },
        ],
      });
    if (path === '/api/v1/diary') {
      diaryRequests.push(url.searchParams.get('student_id') ?? '(none)');
      const weekStart = url.searchParams.get('week_start') ?? '2026-11-16';
      return route.fulfill({ json: diaryWeek(weekStart) });
    }
    if (path === '/api/v1/diary/summary')
      return route.fulfill({ json: quarterSummary(Number(url.searchParams.get('quarter'))) });
    return route.fulfill({ json: [] });
  });
  await page.goto('/diary');
  await expect(page.getByTestId('diary-grid')).toBeVisible();
  // Дневник открывается по первому ребёнку — запрос без student_id не уходит.
  expect(diaryRequests).toHaveLength(1);
  expect(diaryRequests[0]).toBe(ivan);
  await page.getByRole('button', { name: 'Мария Петрова' }).click();
  await expect(page.getByRole('button', { name: 'Мария Петрова' })).toHaveAttribute(
    'aria-pressed',
    'true',
  );
  await expect(page.getByTestId('diary-grid')).toBeVisible();
  expect(diaryRequests.at(-1)).toBe(maria);
  expect(diaryRequests).toHaveLength(2);
  // С домашней страницы родителя ведёт ссылка «Дневник ребёнка».
  await page.goto('/');
  await expect(page.locator('.day-diary').getByRole('link', { name: 'Открыть' })).toHaveAttribute(
    'href',
    '/diary',
  );
});
