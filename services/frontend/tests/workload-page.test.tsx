import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { expect, it, vi } from 'vitest';
import { FeaturesContext, type Features } from '../app/lib/api/context';
import { ApiError } from '../app/lib/api/errors';
import Workload from '../app/routes/workload';

function setup(getWorkload: Features['workload']['getWorkload']) {
  const features = { workload: { getWorkload } } as Features;
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
}

it('не выдаёт отсутствие расчёта за нулевую нагрузку', async () => {
  setup(vi.fn().mockRejectedValue(new ApiError(404, 'not_found', 'Workload was not found')));
  expect(await screen.findByText('Расчёт пока отсутствует')).toBeInTheDocument();
  expect(screen.queryByText('Плановых минут')).not.toBeInTheDocument();
});

it('показывает готовые показатели и UTC-время пересчёта', async () => {
  setup(
    vi.fn().mockResolvedValue({
      class_id: 9021,
      day: '2026-10-05',
      planned_lessons_count: 3,
      planned_minutes: 135,
      refreshed_at: '2026-10-03T09:00:00',
    }),
  );
  expect(await screen.findByText('135')).toBeInTheDocument();
  expect(screen.getByText(/09:00.*UTC/)).toBeInTheDocument();
});
