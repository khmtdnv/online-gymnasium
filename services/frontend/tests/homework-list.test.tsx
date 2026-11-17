import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { expect, it } from 'vitest';
import { HomeworkList } from '../app/features/homework/homework-list';
import type { HomeworkListItem } from '../app/features/homework/api';

it('отделяет просроченные действия, оценку и неизвестный срок понятными подписями', () => {
  const base = {
    id: 1,
    issued_lesson_id: 1,
    class_id: 7,
    subject_id: 1,
    author_id: '00000000-0000-4000-8000-000000000001',
    description: 'Решить задачи',
    due_lesson_id: null,
    manual_due_datetime: '2026-10-20T05:00:00Z',
    final_due_datetime: '2026-10-20T05:00:00Z',
    due_status: 'manual',
    created_at: '2026-10-19T05:00:00Z',
    files: [],
    latest_answer_status: null,
    grade: null,
    subject_name: 'Математика',
    teacher_name: 'Иванов Иван',
  };
  const items = [
    base,
    { ...base, id: 2, latest_answer_status: 'graded', grade: 4 },
    {
      ...base,
      id: 3,
      due_lesson_id: 5,
      manual_due_datetime: null,
      final_due_datetime: null,
      due_status: 'lesson_cancelled',
    },
  ] as HomeworkListItem[];
  render(
    <MemoryRouter>
      <HomeworkList items={items} now={new Date('2026-10-21T10:00:00Z')} />
    </MemoryRouter>,
  );
  expect(screen.getByRole('heading', { name: 'Просрочено — нужно выполнить' })).toBeInTheDocument();
  expect(screen.getByText('Проверено · оценка 4')).toBeInTheDocument();
  expect(screen.getByRole('heading', { name: 'Срок уточняется' })).toBeInTheDocument();
});
