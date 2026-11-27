import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { it, expect, vi } from 'vitest';
import { HomeworkAnswerForm } from '../app/features/homework/homework-answer-form';
import type { HomeworkApi } from '../app/features/homework/api';
import { ApiNetworkError } from '../app/lib/api/errors';

it('повтор неизвестной сдачи сохраняет ключ и текст, а не создаёт новую команду', async () => {
  const submitAnswer = vi.fn().mockRejectedValue(new ApiNetworkError());
  const api = {
    listAnswers: vi.fn().mockResolvedValue([]),
    submitAnswer,
  } as unknown as HomeworkApi;
  render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <HomeworkAnswerForm homeworkId={7} api={api} />
    </QueryClientProvider>,
  );
  await screen.findByText('Вы ещё не сдавали работу.');
  fireEvent.change(screen.getByLabelText('Ваш ответ'), { target: { value: 'Решение' } });
  const submit = screen.getByRole('button', { name: 'Сдать работу' });
  fireEvent.click(submit);
  fireEvent.click(submit);
  await screen.findByText(/Результат отправки не подтверждён/);
  expect(submitAnswer).toHaveBeenCalledTimes(1);
  expect(screen.getByLabelText('Ваш ответ')).toBeDisabled();
  fireEvent.click(screen.getByRole('button', { name: 'Повторить отправку' }));
  await waitFor(() => expect(submitAnswer).toHaveBeenCalledTimes(2));
  expect(submitAnswer.mock.calls[0].slice(0, 3)).toEqual(submitAnswer.mock.calls[1].slice(0, 3));
});

it('показывает счётчик символов ответа рядом с полем', async () => {
  const api = {
    listAnswers: vi.fn().mockResolvedValue([]),
    submitAnswer: vi.fn(),
  } as unknown as HomeworkApi;
  render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <HomeworkAnswerForm homeworkId={7} api={api} />
    </QueryClientProvider>,
  );
  await screen.findByText('Вы ещё не сдавали работу.');
  expect(screen.getByText('0 / 10000 симв.')).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText('Ваш ответ'), { target: { value: 'Решение' } });
  expect(screen.getByText('7 / 10000 симв.')).toBeInTheDocument();
});
