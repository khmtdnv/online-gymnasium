import { render, screen } from '@testing-library/react';
import { expect, it } from 'vitest';
import { MemoryRouter } from 'react-router';
import { HomeContent } from '../app/routes/home';

it('показывает название продукта и не выдумывает статистику', () => {
  render(
    <MemoryRouter>
      <HomeContent
        user={{
          id: '6c6f3434-e4cc-4619-8c2a-8d733913ecda',
          email: 'admin@school.ru',
          role: 'admin',
        }}
      />
    </MemoryRouter>,
  );
  expect(screen.getByRole('heading', { name: /онлайн-гимназия/i })).toBeInTheDocument();
  expect(screen.getByRole('heading', { name: 'Расписание' })).toBeInTheDocument();
  expect(screen.queryByText(/всего учеников/i)).not.toBeInTheDocument();
});
