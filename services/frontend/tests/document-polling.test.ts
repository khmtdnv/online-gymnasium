import { createElement } from 'react';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router';
import { describe, expect, it, vi } from 'vitest';
import { getDocumentPollInterval } from '../app/features/documents/polling';
import { JobStatus } from '../app/features/documents/job-status';
import type { DocumentJob } from '../app/lib/api/contracts';

describe('опрос генерации', () => {
  it('замедляется через минуту и останавливается через две', () => {
    expect(getDocumentPollInterval(0, 'pending')).toBe(2000);
    expect(getDocumentPollInterval(59999, 'processing')).toBe(2000);
    expect(getDocumentPollInterval(60000, 'processing')).toBe(5000);
    expect(getDocumentPollInterval(119999, 'processing')).toBe(5000);
    expect(getDocumentPollInterval(120000, 'processing')).toBe(false);
  });

  it('не опрашивает конечные состояния', () => {
    expect(getDocumentPollInterval(0, 'completed')).toBe(false);
    expect(getDocumentPollInterval(0, 'failed')).toBe(false);
  });
});

function job(status: DocumentJob['status']): DocumentJob {
  return {
    id: '6c6f3434-e4cc-4619-8c2a-8d733913ecda',
    document_type: 'certificate',
    status,
    created_at: '2026-11-05T12:00:00Z',
  };
}
function setup(status: DocumentJob['status'], paused = false) {
  const onContinue = vi.fn();
  render(
    createElement(
      MemoryRouter,
      null,
      createElement(JobStatus, { job: job(status), paused, onContinue }),
    ),
  );
  return { onContinue };
}

describe('состояния задания генерации (A05)', () => {
  it('ожидание: подпись статуса и автоматическая проверка', () => {
    setup('pending');
    expect(screen.getByText('В очереди')).toBeInTheDocument();
    expect(screen.getByRole('status')).toHaveTextContent(/Проверяем статус автоматически/);
  });
  it('обработка: подпись «Готовим PDF» и тип документа', () => {
    setup('processing');
    expect(screen.getByText('Готовим PDF')).toBeInTheDocument();
    expect(screen.getByText('Справка об обучении')).toBeInTheDocument();
  });
  it('пауза: продолжение проверки по кнопке', async () => {
    const { onContinue } = setup('processing', true);
    await userEvent.click(screen.getByRole('button', { name: 'Продолжить проверку' }));
    expect(onContinue).toHaveBeenCalledOnce();
  });
  it('ошибка: безопасное сообщение и возврат к новому документу', () => {
    setup('failed');
    expect(screen.getByText('Не удалось создать')).toBeInTheDocument();
    expect(screen.getByRole('alert')).toHaveTextContent(/не удалось подготовить/);
    expect(screen.getByRole('link', { name: 'К новому документу' })).toHaveAttribute(
      'href',
      '/documents',
    );
  });
});
