import { fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router';
import { expect, it, vi } from 'vitest';
import { WeeklySchedule } from '../app/features/schedule/weekly-schedule';
import { addSchoolDays, schoolDay, schoolWeek } from '../app/features/schedule/school-dates';

/** Семь периодов из контракта Schedule (местное время школы). */
const periods = [
  { number: 1, start_at: '09:00', end_at: '09:45' },
  { number: 2, start_at: '09:55', end_at: '10:40' },
  { number: 3, start_at: '11:00', end_at: '11:45' },
  { number: 4, start_at: '11:55', end_at: '12:40' },
  { number: 5, start_at: '13:00', end_at: '13:45' },
  { number: 6, start_at: '13:55', end_at: '14:40' },
  { number: 7, start_at: '15:00', end_at: '15:45' },
];

const base = {
  class_id: 7,
  subject_id: 1,
  teacher_id: '00000000-0000-4000-8000-000000000001',
  status: 'planned' as const,
  version: 1,
  class_name: '7А',
  teacher_name: 'Иванов Иван Иванович',
};
const monday = [
  {
    ...base,
    id: 1,
    subject_name: 'Математика',
    starts_at: '2026-10-19T04:00:00Z',
    ends_at: '2026-10-19T04:45:00Z',
  },
  {
    ...base,
    id: 2,
    subject_name:
      'Основы религиозных культур и светской этики в современной общеобразовательной школе',
    starts_at: '2026-10-19T10:00:00Z',
    ends_at: '2026-10-19T10:45:00Z',
  },
];
// Legacy-день: 09:20–10:05 местного времени не совпадает ни с одним периодом.
const tuesday = [
  {
    ...base,
    id: 3,
    subject_name: 'История древнего мира',
    starts_at: '2026-10-20T04:20:00Z',
    ends_at: '2026-10-20T05:05:00Z',
  },
];

function renderWeek(change = vi.fn()) {
  render(
    <MemoryRouter>
      <WeeklySchedule
        weekStart="2026-10-19"
        timezone="Asia/Yekaterinburg"
        periods={periods}
        days={Array.from({ length: 6 }, (_, i) => ({
          date: addSchoolDays('2026-10-19', i),
          lessons: i === 0 ? monday : i === 1 ? tuesday : [],
        }))}
        onWeekChange={change}
      />
    </MemoryRouter>,
  );
  return change;
}

it('строит неделю по семи периодам API и сохраняет переходы между неделями', () => {
  const change = renderWeek();
  expect(schoolDay(new Date('2026-10-18T20:00:00Z'))).toBe('2026-10-19');
  expect(schoolWeek('2026-10-25')).toBe('2026-10-26');
  const sheet = document.querySelector('.week-sheet') as HTMLElement;
  const head = sheet.querySelector('.week-sheet-head') as HTMLElement;
  // Семь колонок-периодов, включая седьмой урок 15:00–15:45.
  expect(within(head).getAllByText(/–/)).toHaveLength(7);
  expect(within(head).getByText('15:00–15:45')).toBeInTheDocument();
  // Урок первого периода лежит в своей колонке с реальным временем.
  expect(within(sheet).getByRole('link', { name: /Математика/ })).toHaveAttribute(
    'href',
    '/lessons/1',
  );
  expect(sheet.textContent).toContain('09:00–09:45');
  expect(screen.getAllByText('Уроков нет')).toHaveLength(4);
  fireEvent.click(screen.getByRole('button', { name: 'Следующая неделя' }));
  expect(change).toHaveBeenCalledWith('2026-10-26');
});

it('показывает вне-сеточные уроки legacy-дня с реальным временем на столе и телефоне', async () => {
  renderWeek();
  const sheet = document.querySelector('.week-sheet') as HTMLElement;
  // Шесть строк-дней и строка «Вне сетки» вторника.
  expect(sheet.querySelectorAll('.week-sheet-row')).toHaveLength(7);
  const offgridRow = sheet.querySelector('.week-sheet-row--offgrid') as HTMLElement;
  expect(within(offgridRow).getByRole('link', { name: /История древнего мира/ })).toHaveAttribute(
    'href',
    '/lessons/3',
  );
  expect(offgridRow.textContent).toContain('09:20–10:05');
  // Выбран понедельник — мобильная секция «Вне сетки» ещё не показана.
  expect(screen.getAllByText('Вне сетки')).toHaveLength(1);
  await userEvent.click(screen.getByRole('tab', { name: /вт\s*20/i }));
  expect(screen.getAllByText('Вне сетки')).toHaveLength(2);
  const mobileDay = document.querySelector('.week-mobile-day') as HTMLElement;
  expect(within(mobileDay).getByRole('link', { name: /История древнего мира/ })).toHaveAttribute(
    'href',
    '/lessons/3',
  );
  expect(within(mobileDay).getByText('09:20–10:05')).toBeInTheDocument();
});

it('показывает одинаковый набор уроков дня на столе и в мобильном списке', async () => {
  renderWeek();
  const sheet = document.querySelector('.week-sheet') as HTMLElement;
  const mobileDay = document.querySelector('.week-mobile-day') as HTMLElement;
  // Понедельник: два урока на сетке, включая длинное название предмета.
  expect(
    within(sheet).getByText(
      'Основы религиозных культур и светской этики в современной общеобразовательной школе',
    ),
  ).toBeInTheDocument();
  expect(
    within(mobileDay).getByText(
      'Основы религиозных культур и светской этики в современной общеобразовательной школе',
    ),
  ).toBeInTheDocument();
  const mondayLinks = Array.from(
    sheet.querySelectorAll('.week-sheet-row')[0].querySelectorAll('a'),
  ).map((link) => link.getAttribute('href'));
  expect(mondayLinks.sort()).toEqual(['/lessons/1', '/lessons/2']);
  const mobileLinks = Array.from(mobileDay.querySelectorAll('a')).map((link) =>
    link.getAttribute('href'),
  );
  expect(mobileLinks.sort()).toEqual(['/lessons/1', '/lessons/2']);
  // Вторник: один вне-сеточный урок одинаков на столе и в мобильном списке.
  await userEvent.click(screen.getByRole('tab', { name: /вт\s*20/i }));
  const offgridRow = sheet.querySelector('.week-sheet-row--offgrid') as HTMLElement;
  const desktop = Array.from(offgridRow.querySelectorAll('a')).map((link) =>
    link.getAttribute('href'),
  );
  const mobile = Array.from(mobileDay.querySelectorAll('a')).map((link) =>
    link.getAttribute('href'),
  );
  expect(mobile).toEqual(desktop);
});

it('сохраняет клавиатурную навигацию по дням на телефоне', () => {
  renderWeek();
  const mondayTab = screen.getByRole('tab', { name: /пн\s*19/i });
  mondayTab.focus();
  fireEvent.keyDown(mondayTab, { key: 'ArrowRight' });
  expect(screen.getByRole('tab', { name: /вт\s*20/i })).toHaveFocus();
  fireEvent.keyDown(screen.getByRole('tab', { name: /вт\s*20/i }), { key: 'Home' });
  expect(screen.getByRole('tab', { name: /пн\s*19/i })).toHaveFocus();
  expect(screen.getByRole('tab', { name: /вт\s*20/i }).getAttribute('aria-selected')).toBe('false');
});
