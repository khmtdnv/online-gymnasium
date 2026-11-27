import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { expect, it } from 'vitest';
import { HomeworkList } from '../app/features/homework/homework-list';
import type { HomeworkListItem } from '../app/features/homework/api';

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

it('отделяет просроченные действия, оценку и неизвестный срок понятными подписями', () => {
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

it('группирует по школьному дню срока: день недели и дата в заголовке группы', () => {
  // 2026-10-22 — четверг школьного календаря (UTC+5).
  const items = [
    {
      ...base,
      final_due_datetime: '2026-10-22T12:00:00Z',
      manual_due_datetime: '2026-10-22T12:00:00Z',
    },
  ] as HomeworkListItem[];
  render(
    <MemoryRouter>
      <HomeworkList items={items} now={new Date('2026-10-22T10:00:00Z')} />
    </MemoryRouter>,
  );
  expect(screen.getByRole('heading', { name: 'Четверг, 22 октября 2026 г.' })).toBeInTheDocument();
});

it('помечает группу сегодняшнего срока, не называя её просроченной', () => {
  const items = [
    {
      ...base,
      final_due_datetime: '2026-10-22T12:00:00Z',
      manual_due_datetime: '2026-10-22T12:00:00Z',
    },
  ] as HomeworkListItem[];
  render(
    <MemoryRouter>
      <HomeworkList items={items} now={new Date('2026-10-22T10:00:00Z')} />
    </MemoryRouter>,
  );
  expect(screen.getByText('Сегодня')).toBeInTheDocument();
  expect(
    screen.queryByRole('heading', { name: 'Просрочено — нужно выполнить' }),
  ).not.toBeInTheDocument();
});

it('показывает предмет и преподавателя строкой над заданием', () => {
  render(
    <MemoryRouter>
      <HomeworkList items={[base] as HomeworkListItem[]} now={new Date('2026-10-21T10:00:00Z')} />
    </MemoryRouter>,
  );
  expect(screen.getByText('Математика', { exact: true })).toBeInTheDocument();
  expect(screen.getByText('Иванов Иван')).toBeInTheDocument();
});
