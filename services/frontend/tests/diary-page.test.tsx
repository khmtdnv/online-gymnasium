import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { FeaturesContext, type Features } from '../app/lib/api/context';
import Diary from '../app/routes/diary';

const student = '75ef34f4-2588-41b1-b41e-cbd058c6025c';
const secondChild = '85ef34f4-2588-41b1-b41e-cbd058c6025c';

const state = vi.hoisted(() => ({ role: 'student' as 'student' | 'parent' }));
vi.mock('../app/features/auth/session-context', () => ({
  useSession: () => ({
    state: {
      status: 'authenticated',
      user: { id: student, email: 'student@example.test', role: state.role },
    },
    session: null,
  }),
}));

/** Неделя с полным набором статусов: оценки, «не отмечено», пропуск, отмена. */
const week = {
  week_start: '2026-11-16',
  timezone: 'Asia/Yekaterinburg',
  demo_cutoff: '2026-11-19',
  quarter: 2,
  lessons: [
    {
      lesson_id: 501,
      subject_id: 1000,
      date: '2026-11-16',
      starts_at: '2026-11-16T04:00:00Z',
      ends_at: '2026-11-16T04:45:00Z',
      status: 'planned',
      attendance: 'present',
      absence_reason: null,
      grades: [[5, 'oral']] as Array<[number, 'oral' | 'written' | 'control']>,
      homework_status: 'submitted',
      homework_grade: null,
    },
    {
      lesson_id: 502,
      subject_id: 1001,
      date: '2026-11-16',
      starts_at: '2026-11-16T05:00:00Z',
      ends_at: '2026-11-16T05:45:00Z',
      status: 'planned',
      attendance: 'unmarked',
      absence_reason: null,
      grades: [],
      homework_status: null,
      homework_grade: null,
    },
    {
      lesson_id: 503,
      subject_id: 1002,
      date: '2026-11-17',
      starts_at: '2026-11-17T04:00:00Z',
      ends_at: '2026-11-17T04:45:00Z',
      status: 'planned',
      attendance: 'absent',
      absence_reason: 'sick',
      grades: [],
      homework_status: 'not_submitted',
      homework_grade: 4,
    },
    {
      lesson_id: 504,
      subject_id: 1003,
      date: '2026-11-17',
      starts_at: '2026-11-17T05:00:00Z',
      ends_at: '2026-11-17T05:45:00Z',
      status: 'canceled',
      attendance: 'unmarked',
      absence_reason: null,
      grades: [],
      homework_status: null,
      homework_grade: null,
    },
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

function summaryFor(quarter: number) {
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

function setup() {
  const getDiaryWeek = vi.fn().mockImplementation((weekStart?: string) =>
    Promise.resolve({ ...week, week_start: weekStart ?? week.week_start }),
  );
  const getDiarySummary = vi.fn().mockImplementation((quarter: number) =>
    Promise.resolve(summaryFor(quarter)),
  );
  const students = vi.fn().mockResolvedValue([
    { id: student, name: 'Иван Петров' },
    { id: secondChild, name: 'Мария Петрова' },
  ]);
  const features = {
    diary: { getDiaryWeek, getDiarySummary },
    billing: { students },
  } as unknown as Features;
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  render(
    <MemoryRouter initialEntries={['/diary']}>
      <QueryClientProvider client={queryClient}>
        <FeaturesContext.Provider value={features}>
          <Diary />
        </FeaturesContext.Provider>
      </QueryClientProvider>
    </MemoryRouter>,
  );
  return { getDiaryWeek, getDiarySummary, students };
}

beforeEach(() => {
  state.role = 'student';
});

describe('страница дневника', () => {
  it('дефолтная неделя без week_start, сетка со статусами и «не отмечено»', async () => {
    const { getDiaryWeek } = setup();
    await screen.findByTestId('diary-grid');
    // Дефолт — якорная неделя сервера: клиент не передаёт week_start и student_id.
    expect(getDiaryWeek).toHaveBeenCalledWith(undefined, undefined, expect.anything());
    expect(screen.getByText('Пн 16 ноября')).toBeInTheDocument();
    const lesson501 = screen.getByTestId('lesson-501');
    expect(within(lesson501).getByText('5')).toBeInTheDocument();
    expect(within(lesson501).getByText('(устный)')).toBeInTheDocument();
    expect(screen.getByText('сдано')).toBeInTheDocument();
    expect(screen.getByText('не отмечено')).toBeInTheDocument();
    expect(screen.getByText('не был (болезнь)')).toBeInTheDocument();
    expect(screen.getByText('не сдано — 4')).toBeInTheDocument();
    expect(screen.getByText('Урок отменён')).toBeInTheDocument();
    expect(screen.getByText('Демо-срез на дату 19 ноября')).toBeInTheDocument();
  });

  it('навигация по неделям передаёт новый понедельник и возврат к якорной', async () => {
    const { getDiaryWeek } = setup();
    await screen.findByTestId('diary-grid');
    await userEvent.click(screen.getByRole('button', { name: 'Следующая →' }));
    await waitFor(() =>
      expect(getDiaryWeek).toHaveBeenLastCalledWith('2026-11-23', undefined, expect.anything()),
    );
    await userEvent.click(screen.getByRole('button', { name: '← Предыдущая' }));
    await waitFor(() =>
      expect(getDiaryWeek).toHaveBeenLastCalledWith('2026-11-16', undefined, expect.anything()),
    );
    await userEvent.click(screen.getByRole('button', { name: 'Последняя заполненная' }));
    await waitFor(() =>
      expect(getDiaryWeek).toHaveBeenLastCalledWith(undefined, undefined, expect.anything()),
    );
  });

  it('сводка текущей четверти помечена «предварительно», динамика рядом', async () => {
    setup();
    const summary = await screen.findByTestId('diary-summary');
    // Средняя и ячейка динамики второй четверти; ячейка «четвертной» — среднее с пометкой.
    expect(screen.getAllByText('4.50')).toHaveLength(2);
    expect(within(summary).getAllByText('(предварительно)')).toHaveLength(1);
    const dynamics = await screen.findByTestId('diary-dynamics');
    // Динамика: средние первой и второй четверти, пустые — прочерком.
    expect(within(dynamics).getByText('4.25')).toBeInTheDocument();
    expect(within(dynamics).getAllByText('—')).toHaveLength(2);
    expect(within(summary).getByText('17 нояб. — болезнь')).toBeInTheDocument();
  });

  it('выбор прошедшей четверти подгружает сводку без «предварительно»', async () => {
    const { getDiarySummary } = setup();
    await screen.findByTestId('diary-summary');
    await userEvent.selectOptions(screen.getByLabelText('Четверть сводки'), '1');
    await waitFor(() =>
      expect(getDiarySummary).toHaveBeenCalledWith(1, undefined, expect.anything()),
    );
    const summary = await screen.findByTestId('diary-summary');
    expect(within(summary).getByText(/Четверть 1 /)).toBeInTheDocument();
    expect(within(summary).queryByText('(предварительно)')).not.toBeInTheDocument();
  });

  it('режим родителя: дети из биллинга, дневник запрашивается по student_id', async () => {
    state.role = 'parent';
    const { getDiaryWeek, students } = setup();
    await screen.findByTestId('diary-grid');
    expect(students).toHaveBeenCalled();
    expect(getDiaryWeek).toHaveBeenCalledWith(undefined, student, expect.anything());
    await userEvent.click(screen.getByRole('button', { name: 'Мария Петрова' }));
    await waitFor(() =>
      expect(getDiaryWeek).toHaveBeenLastCalledWith(undefined, secondChild, expect.anything()),
    );
    expect(screen.getByRole('button', { name: 'Мария Петрова' })).toHaveAttribute(
      'aria-pressed',
      'true',
    );
  });
});
