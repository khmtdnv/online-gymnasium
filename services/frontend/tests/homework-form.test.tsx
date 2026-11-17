import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { HomeworkForm } from '../app/features/homework/homework-form';
import type { HomeworkApi } from '../app/features/homework/api';
import { ApiNetworkError } from '../app/lib/api/errors';

const saved = {
  id: 42,
  issued_lesson_id: 501,
  class_id: 7,
  subject_id: 3,
  author_id: '75ef34f4-2588-41b1-b41e-cbd058c6025c',
  description: 'Решить задачи',
  due_lesson_id: 508,
  manual_due_datetime: null,
  created_at: '2026-10-20T10:00:00Z',
  files: [],
};
const nextLesson = {
  id: 508,
  class_id: 7,
  subject_id: 3,
  teacher_id: saved.author_id,
  starts_at: '2030-10-23T10:00:00Z',
  ends_at: '2030-10-23T11:00:00Z',
  status: 'planned' as const,
  version: 1,
};

describe('форма задания', () => {
  it('двойное нажатие не создаёт два ДЗ; текст появляется после201', async () => {
    let finish!: (value: typeof saved) => void;
    const createHomework = vi.fn().mockImplementation(
      () =>
        new Promise((resolve) => {
          finish = resolve;
        }),
    );
    render(
      <HomeworkForm
        lessonId={501}
        nextLesson={nextLesson}
        api={{ createHomework } as unknown as HomeworkApi}
      />,
    );
    fireEvent.change(screen.getByLabelText('Что нужно выполнить'), {
      target: { value: 'Решить задачи' },
    });
    const button = screen.getByRole('button', { name: 'Задать ДЗ' });
    fireEvent.click(button);
    fireEvent.click(button);
    await waitFor(() => expect(createHomework).toHaveBeenCalledTimes(1));
    finish(saved);
    expect(await screen.findByText('Задание создано и доступно ученикам.')).toBeInTheDocument();
  });

  it('не повторяет создание при неизвестном результате POST', async () => {
    const createHomework = vi.fn().mockRejectedValue(new ApiNetworkError());
    render(
      <HomeworkForm
        lessonId={501}
        nextLesson={nextLesson}
        api={{ createHomework } as unknown as HomeworkApi}
      />,
    );
    fireEvent.change(screen.getByLabelText('Что нужно выполнить'), {
      target: { value: 'Решить задачи' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Задать ДЗ' }));
    expect(await screen.findByText(/Результат создания не подтверждён/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Задать ДЗ' })).toBeDisabled();
    expect(createHomework).toHaveBeenCalledTimes(1);
  });

  it('после перезагрузки оставляет текст и pending, не требует создавать заново', () => {
    const homework = {
      ...saved,
      files: [
        {
          id: 8,
          homework_id: 42,
          file_name: 'Задачи.txt',
          size_bytes: 6,
          content_type: 'text/plain',
          upload_status: 'pending' as const,
        },
      ],
    };
    render(
      <HomeworkForm
        lessonId={501}
        nextLesson={nextLesson}
        homework={homework}
        api={{} as HomeworkApi}
      />,
    );
    expect(screen.getByText('Решить задачи')).toBeInTheDocument();
    expect(screen.getByText('Задачи.txt')).toBeInTheDocument();
    expect(screen.getByLabelText('Выбрать файл заново: Задачи.txt')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Задать ДЗ' })).not.toBeInTheDocument();
  });
});
