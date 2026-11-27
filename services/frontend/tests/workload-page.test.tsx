import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router';
import { expect, it, vi } from 'vitest';
import { FeaturesContext, type Features } from '../app/lib/api/context';
import { ApiError } from '../app/lib/api/errors';
import Workload from '../app/routes/workload';

function setup(getWorkload: Features['workload']['getWorkload']) {
  const spy = vi.fn(getWorkload);
  const features = { workload: { getWorkload: spy } } as unknown as Features;
  render(
    <MemoryRouter initialEntries={['/workload?class_id=9021&day=2026-10-05']}>
      <QueryClientProvider
        client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
      >
        <FeaturesContext.Provider value={features}>
          <Workload />
        </FeaturesContext.Provider>
      </QueryClientProvider>
    </MemoryRouter>,
  );
  return spy;
}

it('не выдаёт отсутствие расчёта за нулевую нагрузку', async () => {
  setup(vi.fn().mockRejectedValue(new ApiError(404, 'not_found', 'Workload was not found')));
  expect(await screen.findByText('Расчёт пока отсутствует')).toBeInTheDocument();
  expect(screen.queryByText('Суммарная длительность')).not.toBeInTheDocument();
});

it('показывает готовые показатели, форматирование и UTC-время пересчёта', async () => {
  setup(
    vi.fn().mockResolvedValue({
      class_id: 9021,
      day: '2026-10-05',
      planned_lessons_count: 6,
      planned_minutes: 1530,
      refreshed_at: '2026-10-03T09:00:00',
    }),
  );
  expect(
    await screen.findByText(
      (_, el) => el?.tagName === 'STRONG' && el.textContent === (1530).toLocaleString('ru-RU'),
    ),
  ).toBeInTheDocument();
  expect(screen.getByText('6')).toBeInTheDocument();
  expect(
    screen.getByText(
      (_, el) =>
        el?.classList.contains('workload-kpi-note') === true &&
        (el.textContent ?? '').includes('34 академических часа'),
    ),
  ).toBeInTheDocument();
  expect(screen.getByText(/09:00.*UTC/)).toBeInTheDocument();
});

it('«Обновить» перечитывает готовый расчёт и не запускает пересчёт', async () => {
  const spy = setup(
    vi.fn().mockResolvedValue({
      class_id: 9021,
      day: '2026-10-05',
      planned_lessons_count: 3,
      planned_minutes: 135,
      refreshed_at: '2026-10-03T09:00:00',
    }),
  );
  await screen.findByText('135');
  expect(spy).toHaveBeenCalledTimes(1);
  const keyboard = userEvent.setup();
  await keyboard.click(screen.getByRole('button', { name: /Обновить/ }));
  await waitFor(() => expect(spy).toHaveBeenCalledTimes(2));
  // Только чтение: повторный вызов — тот же GET без параметров пересчёта.
  expect(spy).toHaveBeenLastCalledWith(
    9021,
    '2026-10-05',
    expect.anything(),
  );
  // Честная пометка о смысле кнопки присутствует на карточке.
  expect(
    screen.getByText(/«Обновить» читает последний готовый расчёт и не запускает новый/),
  ).toBeInTheDocument();
});
