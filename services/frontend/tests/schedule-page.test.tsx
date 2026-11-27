import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, useLocation } from 'react-router';
import { describe, expect, it, vi } from 'vitest';
import { FeaturesContext, type Features } from '../app/lib/api/context';
import Schedule from '../app/routes/schedule';
import { LessonForm } from '../app/features/schedule/lesson-form';
import { ApiError, ApiNetworkError } from '../app/lib/api/errors';

/** Контракная сетка: семь периодов школьского дня (местное время школы). */
const periods = [
  { number: 1, start_at: '09:00', end_at: '09:45' },
  { number: 2, start_at: '09:55', end_at: '10:40' },
  { number: 3, start_at: '11:00', end_at: '11:45' },
  { number: 4, start_at: '11:55', end_at: '12:40' },
  { number: 5, start_at: '13:00', end_at: '13:45' },
  { number: 6, start_at: '13:55', end_at: '14:40' },
  { number: 7, start_at: '15:00', end_at: '15:45' },
];

/** Урок первого периода: 09:00–09:45 школы = 04:00–04:45 UTC. */
const lesson = {
  id: 501,
  class_id: 9021,
  teacher_id: '8df96b7a-7d30-44e7-b577-f6581300e101',
  subject_id: 1000,
  starts_at: '2026-10-05T04:00:00Z',
  ends_at: '2026-10-05T04:45:00Z',
  status: 'planned' as const,
  version: 3,
};

function setup(listLessons = vi.fn().mockResolvedValue([])) {
  const schedule = {
    listLessons,
    directory: vi.fn().mockResolvedValue({
      classes: [{ id: 9021, name: '9А' }],
      subjects: [{ id: 1000, name: 'Математика' }],
      periods,
    }),
    searchTeachers: vi.fn().mockResolvedValue([]),
    createLesson: vi.fn().mockResolvedValue(lesson),
    updateLesson: vi.fn().mockResolvedValue(lesson),
    cancelLesson: vi.fn().mockResolvedValue({ ...lesson, status: 'canceled' }),
  };
  const features = { schedule } as unknown as Features;
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <MemoryRouter initialEntries={['/schedule?class_id=9021&day=2026-10-05']}>
      <QueryClientProvider client={queryClient}>
        <FeaturesContext.Provider value={features}>
          <Schedule />
          <UrlProbe />
        </FeaturesContext.Provider>
      </QueryClientProvider>
    </MemoryRouter>,
  );
  return { schedule, queryClient };
}

function UrlProbe() {
  const location = useLocation();
  return <data data-testid="url-probe" value={location.search} />;
}

async function fillCreateForm() {
  // На странице формы включён поиск преподавателя: UUID вводится резервным полем.
  const teacherInput = document.querySelector<HTMLInputElement>('#lesson-teacher_id');
  if (!teacherInput) throw new Error('Поле UUID преподавателя не найдено');
  await userEvent.type(teacherInput, lesson.teacher_id);
  await userEvent.selectOptions(screen.getByLabelText('Предмет'), '1000');
}

describe('расписание', () => {
  it('после конфликта отмены требует сверки и отправляет новую версию только вручную', async () => {
    const list = vi
      .fn()
      .mockResolvedValueOnce([lesson])
      .mockResolvedValue([{ ...lesson, version: 4 }]);
    const { schedule } = setup(list);
    schedule.cancelLesson.mockRejectedValueOnce(new ApiError(409, 'version_conflict', 'Conflict'));
    await screen.findByText('Предмет · ID 1000');
    await userEvent.click(screen.getByRole('button', { name: 'Отменить урок 501' }));
    await userEvent.click(screen.getByRole('button', { name: 'Подтвердить отмену' }));
    await screen.findByText(/Текущая версия 4:/);
    expect(schedule.cancelLesson).toHaveBeenCalledTimes(1);
    expect(screen.getByRole('button', { name: 'Подтвердить отмену' })).toBeDisabled();
    await userEvent.click(
      screen.getByRole('button', { name: 'Использовать версию 4 после сверки' }),
    );
    await userEvent.click(screen.getByRole('button', { name: 'Подтвердить отмену' }));
    await waitFor(() => expect(schedule.cancelLesson).toHaveBeenCalledTimes(2));
    expect(schedule.cancelLesson.mock.calls[1]).toEqual([501, 4]);
  });

  it('после 409 перечитывает урок, сохраняет выбранный период и переносит на него', async () => {
    const list = vi
      .fn()
      .mockResolvedValueOnce([lesson])
      .mockResolvedValue([{ ...lesson, version: 4 }]);
    const { schedule } = setup(list);
    schedule.updateLesson.mockRejectedValueOnce(
      new ApiError(409, 'version_conflict', 'Lesson version conflict'),
    );
    await screen.findByText('Предмет · ID 1000');
    await userEvent.click(screen.getByRole('button', { name: 'Перенести урок 501' }));
    const period = screen.getByLabelText('Период');
    expect(period).toHaveValue('1');
    await userEvent.selectOptions(period, '3');
    await userEvent.click(screen.getByRole('button', { name: 'Сохранить перенос' }));
    await screen.findByText(/Текущее состояние: версия 4/);
    await waitFor(() => expect(list).toHaveBeenCalledTimes(2));
    expect(period).toHaveValue('3');
    expect(screen.getByRole('button', { name: 'Сохранить перенос' })).toBeDisabled();
    await userEvent.click(
      screen.getByRole('button', { name: 'Использовать версию 4 после сверки' }),
    );
    await userEvent.click(screen.getByRole('button', { name: 'Сохранить перенос' }));
    await waitFor(() => expect(schedule.updateLesson).toHaveBeenCalledTimes(2));
    expect(schedule.updateLesson.mock.calls[1]).toEqual([
      501,
      expect.objectContaining({
        expected_version: 4,
        starts_at: '2026-10-05T06:00:00.000Z',
        ends_at: '2026-10-05T06:45:00.000Z',
      }),
    ]);
  });

  it('показывает пустой день сеткой семи периодов с созданием по клику', async () => {
    const { schedule } = setup();
    expect(screen.getByLabelText('Класс')).toHaveValue('9021');
    expect(
      await screen.findAllByRole('button', { name: /Создать урок в периоде \d/ }),
    ).toHaveLength(7);
    expect(schedule.listLessons).toHaveBeenCalledWith(9021, '2026-10-05', expect.any(AbortSignal));
  });

  it('создаёт урок кликом по пустой ячейке периода с готовой датой и периодом', async () => {
    const { schedule } = setup();
    await screen.findAllByRole('button', { name: /Создать урок в периоде \d/ });
    await userEvent.click(screen.getByRole('button', { name: 'Создать урок в периоде 3' }));
    expect(screen.getByLabelText('Период')).toHaveValue('3');
    expect(screen.getByLabelText('Дата · школа')).toHaveValue('2026-10-05');
    await fillCreateForm();
    await userEvent.click(screen.getByRole('button', { name: 'Создать урок' }));
    await waitFor(() => expect(schedule.createLesson).toHaveBeenCalledTimes(1));
    const [input, key] = schedule.createLesson.mock.calls[0];
    expect(input).toEqual({
      class_id: 9021,
      teacher_id: lesson.teacher_id,
      subject_id: 1000,
      starts_at: '2026-10-05T06:00:00.000Z',
      ends_at: '2026-10-05T06:45:00.000Z',
    });
    expect(typeof key).toBe('string');
    expect(key.length).toBeGreaterThan(0);
    expect(await screen.findByText(/Урок 501 создан/)).toBeInTheDocument();
    // Выбранные класс и день остаются в URL после сохранения.
    const url = screen.getByTestId('url-probe').getAttribute('value') ?? '';
    expect(url).toContain('class_id=9021');
    expect(url).toContain('day=2026-10-05');
  });

  it('показывает ошибку 422 сервера и не закрывает форму', async () => {
    const { schedule } = setup();
    schedule.createLesson.mockRejectedValueOnce(
      new ApiError(422, 'invalid_school_period', 'Lesson time is outside school periods'),
    );
    await screen.findAllByRole('button', { name: /Создать урок в периоде \d/ });
    await userEvent.click(screen.getByRole('button', { name: 'Создать урок в периоде 1' }));
    await fillCreateForm();
    await userEvent.click(screen.getByRole('button', { name: 'Создать урок' }));
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Проверьте введённые значения и повторите отправку.',
    );
    expect(screen.getByRole('button', { name: 'Создать урок' })).toBeEnabled();
    expect(schedule.createLesson).toHaveBeenCalledTimes(1);
  });

  it('показывает UTC, ID и подтверждение отмены с текущей версией', async () => {
    const { schedule } = setup(vi.fn().mockResolvedValue([lesson]));
    expect(await screen.findByText('Предмет · ID 1000')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Отменить урок 501' }));
    expect(schedule.cancelLesson).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole('button', { name: 'Подтвердить отмену' }));
    await waitFor(() => expect(schedule.cancelLesson).toHaveBeenCalledWith(501, 3));
    expect(await screen.findByText(/Урок 501 отменён/)).toBeInTheDocument();
  });

  it('показывает отказ доступа как ошибку, а не пустую выборку', async () => {
    setup(
      vi.fn().mockRejectedValue(new ApiError(403, 'forbidden', 'Access denied', 'r-forbidden')),
    );
    expect(await screen.findByRole('alert')).toHaveTextContent('недостаточно прав');
    expect(screen.queryByText('На этот день уроков нет')).not.toBeInTheDocument();
  });

  it('legacy-урок вне сетки требует период и показывает старое время', async () => {
    const legacy = {
      ...lesson,
      starts_at: '2026-10-05T04:20:00Z',
      ends_at: '2026-10-05T05:05:00Z',
      version: 2,
    };
    const { schedule } = setup(vi.fn().mockResolvedValue([legacy]));
    expect(await screen.findByText('Вне сетки')).toBeInTheDocument();
    expect(screen.getByText('вне сетки')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Перенести урок 501' }));
    expect(screen.getByLabelText('Период')).toHaveValue('');
    expect(screen.getByText(/вне сетки \(старое время 09:20\)/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Сохранить перенос' }));
    await waitFor(() => expect(screen.getByText('Выберите период урока.')).toBeInTheDocument());
    expect(schedule.updateLesson).not.toHaveBeenCalled();
    await userEvent.selectOptions(screen.getByLabelText('Период'), '5');
    await userEvent.click(screen.getByRole('button', { name: 'Сохранить перенос' }));
    await waitFor(() => expect(schedule.updateLesson).toHaveBeenCalledTimes(1));
    expect(schedule.updateLesson).toHaveBeenCalledWith(501, {
      starts_at: '2026-10-05T08:00:00.000Z',
      ends_at: '2026-10-05T08:45:00.000Z',
      expected_version: 2,
    });
  });

  it('сохраняет данные формы при конфликте версии', async () => {
    const submit = vi
      .fn()
      .mockRejectedValue(new ApiError(409, 'version_conflict', 'Lesson version conflict'));
    render(
      <LessonForm
        lesson={lesson}
        classId={9021}
        day="2026-10-05"
        periods={periods}
        onSubmit={submit}
      />,
    );
    const period = screen.getByLabelText('Период');
    await userEvent.selectOptions(period, '2');
    await userEvent.click(screen.getByRole('button', { name: 'Сохранить перенос' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Урок уже изменён');
    expect(period).toHaveValue('2');
    expect(submit).toHaveBeenCalledOnce();
  });

  it('повтор неизвестного результата использует тот же ключ и тело', async () => {
    const submit = vi
      .fn()
      .mockRejectedValueOnce(new ApiNetworkError())
      .mockResolvedValueOnce(undefined);
    render(
      <LessonForm
        classId={9021}
        day="2026-10-05"
        periods={periods}
        presetPeriod={periods[0]}
        onSubmit={submit}
      />,
    );
    await userEvent.type(screen.getByLabelText('Преподаватель'), lesson.teacher_id);
    await userEvent.type(screen.getByLabelText('Предмет'), '1000');
    await userEvent.click(screen.getByRole('button', { name: 'Создать урок' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Результат отправки неизвестен');
    await userEvent.click(screen.getByRole('button', { name: 'Повторить ту же попытку' }));
    expect(submit.mock.calls[1]).toEqual(submit.mock.calls[0]);
    expect(submit.mock.calls[0][0].teacher_id).toBe(lesson.teacher_id);
    expect(submit.mock.calls[0][0].starts_at).toBe('2026-10-05T04:00:00.000Z');
    expect(submit.mock.calls[0][0].ends_at).toBe('2026-10-05T04:45:00.000Z');
  });
});
