import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { expect, it, vi } from 'vitest';
import { WeeklySchedule } from '../app/features/schedule/weekly-schedule';
import { addSchoolDays, schoolDay, schoolWeek } from '../app/features/schedule/school-dates';

it('показывает школьную неделю, названия и переходы без зависимости от timezone браузера', () => {
  const change = vi.fn();
  expect(schoolDay(new Date('2026-10-18T20:00:00Z'))).toBe('2026-10-19');
  expect(schoolWeek('2026-10-25')).toBe('2026-10-26');
  const lesson = {
    id: 1,
    class_id: 7,
    subject_id: 1,
    teacher_id: '00000000-0000-4000-8000-000000000001',
    starts_at: '2026-10-19T04:00:00Z',
    ends_at: '2026-10-19T04:45:00Z',
    status: 'planned' as const,
    version: 1,
    subject_name: 'Математика',
    class_name: '7А',
    teacher_name: 'Иванов Иван Иванович',
  };
  render(
    <MemoryRouter>
      <WeeklySchedule
        weekStart="2026-10-19"
        timezone="Asia/Yekaterinburg"
        days={Array.from({ length: 6 }, (_, i) => ({
          date: addSchoolDays('2026-10-19', i),
          lessons: i ? [] : [lesson],
        }))}
        onWeekChange={change}
      />
    </MemoryRouter>,
  );
  expect(screen.getByRole('link', { name: /Математика/ })).toHaveAttribute('href', '/lessons/1');
  expect(screen.getByText('09:00–09:45')).toBeInTheDocument();
  expect(screen.getAllByText('Уроков нет')).toHaveLength(5);
  fireEvent.click(screen.getByRole('button', { name: 'Следующая неделя' }));
  expect(change).toHaveBeenCalledWith('2026-10-26');
});
