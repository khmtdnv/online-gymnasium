import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router';
import { describe, expect, it, vi } from 'vitest';
import { FeaturesContext, type Features } from '../app/lib/api/context';
import Schedule from '../app/routes/schedule';
import { LessonForm } from '../app/features/schedule/lesson-form';
import { ApiError, ApiNetworkError } from '../app/lib/api/errors';

const lesson = {
  id: 501,
  class_id: 9021,
  teacher_id: '8df96b7a-7d30-44e7-b577-f6581300e101',
  subject_id: 1000,
  starts_at: '2026-10-05T09:00:00Z',
  ends_at: '2026-10-05T09:45:00Z',
  status: 'planned' as const,
  version: 3,
};

function setup(listLessons = vi.fn().mockResolvedValue([])) {
  const schedule = {
    listLessons,
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
        </FeaturesContext.Provider>
      </QueryClientProvider>
    </MemoryRouter>,
  );
  return { schedule, queryClient };
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
  it('после 409 ручное сохранение берёт перечитанную версию и сохраняет введённое время', async () => {
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
    const end = screen.getByLabelText('Окончание · UTC');
    await userEvent.clear(end);
    await userEvent.type(end, '2026-10-05T10:00');
    await userEvent.click(screen.getByRole('button', { name: 'Сохранить перенос' }));
    await screen.findByText(/Текущее состояние: версия 4/);
    await waitFor(() => expect(list).toHaveBeenCalledTimes(2));
    expect(end).toHaveValue('2026-10-05T10:00');
    expect(screen.getByRole('button', { name: 'Сохранить перенос' })).toBeDisabled();
    await userEvent.click(
      screen.getByRole('button', { name: 'Использовать версию 4 после сверки' }),
    );
    await userEvent.click(screen.getByRole('button', { name: 'Сохранить перенос' }));
    await waitFor(() => expect(schedule.updateLesson).toHaveBeenCalledTimes(2));
    expect(schedule.updateLesson.mock.calls[1]).toEqual([
      501,
      expect.objectContaining({ expected_version: 4, ends_at: '2026-10-05T10:00:00.000Z' }),
    ]);
  });
  it('читает фильтры из URL и показывает пустой день отдельно', async () => {
    const { schedule } = setup();
    expect(screen.getByLabelText('Класс')).toHaveValue('9021');
    expect(await screen.findByText('На этот день уроков нет')).toBeInTheDocument();
    expect(schedule.listLessons).toHaveBeenCalledWith(9021, '2026-10-05', expect.any(AbortSignal));
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

  it('сохраняет данные формы при конфликте версии', async () => {
    const submit = vi
      .fn()
      .mockRejectedValue(new ApiError(409, 'version_conflict', 'Lesson version conflict'));
    render(<LessonForm lesson={lesson} classId={9021} day="2026-10-05" onSubmit={submit} />);
    const end = screen.getByLabelText('Окончание · UTC');
    await userEvent.clear(end);
    await userEvent.type(end, '2026-10-05T10:00');
    await userEvent.click(screen.getByRole('button', { name: 'Сохранить перенос' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Урок уже изменён');
    expect(end).toHaveValue('2026-10-05T10:00');
    expect(submit).toHaveBeenCalledOnce();
  });

  it('повтор неизвестного результата использует тот же ключ и тело', async () => {
    const submit = vi
      .fn()
      .mockRejectedValueOnce(new ApiNetworkError())
      .mockResolvedValueOnce(undefined);
    render(<LessonForm classId={9021} day="2026-10-05" onSubmit={submit} />);
    await userEvent.type(screen.getByLabelText('Преподаватель'), lesson.teacher_id);
    await userEvent.type(screen.getByLabelText('Предмет'), '1000');
    await userEvent.click(screen.getByRole('button', { name: 'Создать урок' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Результат отправки неизвестен');
    await userEvent.click(screen.getByRole('button', { name: 'Повторить ту же попытку' }));
    expect(submit.mock.calls[1]).toEqual(submit.mock.calls[0]);
    expect(submit.mock.calls[0][0].teacher_id).toBe(lesson.teacher_id);
  });
});
