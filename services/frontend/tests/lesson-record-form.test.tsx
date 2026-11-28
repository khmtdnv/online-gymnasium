import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { LessonRecordForm } from '../app/features/diary/lesson-record-form';
import { ApiNetworkError } from '../app/lib/api/errors';

const teacher = '85ef34f4-2588-41b1-b41e-cbd058c6025c';
const ivan = '75ef34f4-2588-41b1-b41e-cbd058c6025c';
const maria = '95ef34f4-2588-41b1-b41e-cbd058c6025c';

const lesson = { class_id: 7, subject_id: 3, lesson_date: '2026-11-16' };
const roster = [
  { id: ivan, name: 'Иван Петров' },
  { id: maria, name: 'Мария Петрова' },
];

/** Сохранённые записи: Иван был с устной пятёркой, Мария болела. */
const entries = {
  attendance: [
    { lesson_id: 501, student_id: ivan, status: 'present' },
    { lesson_id: 501, student_id: maria, status: 'absent_sick' },
  ],
  grades: [{ lesson_id: 501, student_id: ivan, grade: 5, kind: 'oral' }],
};

const savedBatch = {
  lesson_id: 501,
  context: { ...lesson, status: 'planned', teacher_id: teacher },
  attendance: [
    { student_id: ivan, status: 'present' },
    { student_id: maria, status: 'absent_sick' },
  ],
  grades: [{ student_id: ivan, kind: 'oral', grade: 5 }],
};

function radio(name: string, student: string) {
  return within(screen.getByRole('radiogroup', { name: `Посещаемость: ${student}` })).getByRole(
    'radio',
    { name },
  );
}

function setup(entriesMock = vi.fn().mockResolvedValue(entries)) {
  const api = {
    getLessonEntries: entriesMock,
    recordLessonEntries: vi.fn().mockResolvedValue(entries),
  };
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <LessonRecordForm
        lessonId={501}
        teacherId={teacher}
        lesson={lesson}
        roster={roster}
        api={api}
      />
    </QueryClientProvider>,
  );
  return api;
}

async function waitForForm() {
  await screen.findByTestId('lesson-record-form');
}

describe('форма записи урока', () => {
  it('показывает ростер с сохранёнными записями для правки', async () => {
    setup();
    await waitForForm();
    expect(radio('Был', 'Иван Петров')).toBeChecked();
    expect(radio('Не был (болезнь)', 'Мария Петрова')).toBeChecked();
    expect(screen.getByLabelText('Оценка 1: тип — Иван Петров')).toHaveValue('oral');
    expect(screen.getByLabelText('Оценка 1: балл — Иван Петров')).toHaveValue('5');
    expect(screen.getByLabelText('Оценка 2: тип — Мария Петрова')).toHaveValue('');
  });

  it('отправляет пакет-замену одной кнопкой; повторный клик в полёте игнорируется', async () => {
    const api = setup();
    let finish!: (value: typeof entries) => void;
    api.recordLessonEntries.mockImplementation(
      () =>
        new Promise((resolve) => {
          finish = resolve;
        }),
    );
    await waitForForm();
    const button = screen.getByRole('button', { name: 'Сохранить записи урока' });
    await userEvent.click(button);
    await userEvent.click(button);
    expect(api.recordLessonEntries).toHaveBeenCalledTimes(1);
    expect(api.recordLessonEntries).toHaveBeenCalledWith(savedBatch);
    finish(entries);
    expect(await screen.findByText('Записи урока сохранены.')).toBeInTheDocument();
  });

  it('после сбоя сети повтор отправляет тот же пакет — дублей не будет', async () => {
    const api = setup();
    api.recordLessonEntries.mockRejectedValueOnce(new ApiNetworkError());
    await waitForForm();
    await userEvent.click(screen.getByRole('button', { name: 'Сохранить записи урока' }));
    expect(await screen.findByText(/Не удалось сохранить записи/)).toBeInTheDocument();
    expect(screen.getByText(/Повторная отправка заменит записи/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Сохранить записи урока' }));
    await screen.findByText('Записи урока сохранены.');
    expect(api.recordLessonEntries).toHaveBeenCalledTimes(2);
    expect(api.recordLessonEntries.mock.calls[0]).toEqual(api.recordLessonEntries.mock.calls[1]);
  });

  it('правки попадают в пакет: отметка и вторая оценка с другим типом', async () => {
    const api = setup();
    await waitForForm();
    await userEvent.click(radio('Не был (уважительная)', 'Мария Петрова'));
    await userEvent.selectOptions(screen.getByLabelText('Оценка 2: тип — Иван Петров'), 'written');
    await userEvent.selectOptions(screen.getByLabelText('Оценка 2: балл — Иван Петров'), '4');
    await userEvent.click(screen.getByRole('button', { name: 'Сохранить записи урока' }));
    await screen.findByText('Записи урока сохранены.');
    expect(api.recordLessonEntries).toHaveBeenCalledWith({
      ...savedBatch,
      attendance: [
        { student_id: ivan, status: 'present' },
        { student_id: maria, status: 'absent_excused' },
      ],
      grades: [
        { student_id: ivan, kind: 'oral', grade: 5 },
        { student_id: ivan, kind: 'written', grade: 4 },
      ],
    });
  });

  it('блокирует оценку отсутствовавшему до отправки', async () => {
    const api = setup();
    await waitForForm();
    await userEvent.selectOptions(
      screen.getByLabelText('Оценка 1: тип — Мария Петрова'),
      'written',
    );
    await userEvent.click(screen.getByRole('button', { name: 'Сохранить записи урока' }));
    expect(
      await screen.findByText('«Мария Петрова»: оценка ставится только присутствовавшему ученику.'),
    ).toBeInTheDocument();
    expect(api.recordLessonEntries).not.toHaveBeenCalled();
  });

  it('блокирует две оценки одного типа у ученика', async () => {
    const api = setup();
    await waitForForm();
    await userEvent.selectOptions(screen.getByLabelText('Оценка 2: тип — Иван Петров'), 'oral');
    await userEvent.click(screen.getByRole('button', { name: 'Сохранить записи урока' }));
    expect(
      await screen.findByText('«Иван Петров»: типы двух оценок должны различаться.'),
    ).toBeInTheDocument();
    expect(api.recordLessonEntries).not.toHaveBeenCalled();
  });

  it('«не отмечено» убирает ученика из пакета — запись на сервере удаляется', async () => {
    const api = setup();
    await waitForForm();
    await userEvent.click(radio('не отмечено', 'Мария Петрова'));
    await userEvent.click(screen.getByRole('button', { name: 'Сохранить записи урока' }));
    await screen.findByText('Записи урока сохранены.');
    expect(api.recordLessonEntries).toHaveBeenCalledWith({
      ...savedBatch,
      attendance: [{ student_id: ivan, status: 'present' }],
    });
  });
});
