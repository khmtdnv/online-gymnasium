import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router';
import { describe, expect, it, vi } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import Documents from '../app/routes/documents';
import DocumentJob from '../app/routes/document-job';
import { FeaturesContext, type Features } from '../app/lib/api/context';
import { ApiNetworkError } from '../app/lib/api/errors';

const id = '6c6f3434-e4cc-4619-8c2a-8d733913ecda';
function setup(
  createCertificate = vi
    .fn()
    .mockResolvedValue({ id, document_type: 'certificate', status: 'pending' }),
  entry = '/documents',
) {
  const getDocument = vi.fn();
  const features = {
    documents: { createCertificate, getDocument, listJobs: vi.fn().mockResolvedValue([]) },
  } as unknown as Features;
  render(
    <MemoryRouter initialEntries={[entry]}>
      <QueryClientProvider
        client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
      >
        <FeaturesContext.Provider value={features}>
          <Routes>
            <Route path="/documents" element={<Documents />} />
            <Route
              path="/documents/:jobId"
              element={entry === '/documents' ? <h1>Задание {id}</h1> : <DocumentJob />}
            />
          </Routes>
        </FeaturesContext.Provider>
      </QueryClientProvider>
    </MemoryRouter>,
  );
  return { createCertificate, getDocument };
}
async function fill() {
  await userEvent.type(screen.getByLabelText('ФИО ученика'), 'Иван Петров');
  await userEvent.type(screen.getByLabelText('Класс'), '7А');
  await userEvent.type(screen.getByLabelText('Учебный год'), '2026/2027');
}
function radio(name: string) {
  return screen.getByRole('radio', { name: new RegExp(name) });
}

describe('справки', () => {
  it('проверяет пустые поля до отправки', async () => {
    const { createCertificate } = setup();
    await userEvent.click(screen.getByRole('button', { name: 'Создать справку' }));
    expect(await screen.findByText('Укажите ФИО ученика.')).toBeInTheDocument();
    expect(createCertificate).not.toHaveBeenCalled();
  });
  it('открывает UUID принятого задания', async () => {
    const { createCertificate } = setup();
    await fill();
    await userEvent.click(screen.getByRole('button', { name: 'Создать справку' }));
    expect(await screen.findByRole('heading', { name: `Задание ${id}` })).toBeInTheDocument();
    expect(createCertificate).toHaveBeenCalledOnce();
  });
  it('не повторяет POST после неизвестного результата', async () => {
    const createCertificate = vi.fn().mockRejectedValue(new ApiNetworkError());
    setup(createCertificate);
    await fill();
    await userEvent.click(screen.getByRole('button', { name: 'Создать справку' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Повторите с тем же ключом');
    expect(createCertificate).toHaveBeenCalledOnce();
    await userEvent.click(screen.getByRole('button', { name: 'Повторить с тем же ключом' }));
    expect(createCertificate).toHaveBeenCalledTimes(2);
    expect(createCertificate.mock.calls[0][1]).toBe(createCertificate.mock.calls[1][1]);
  });
  it('не запрашивает задание по некорректному UUID', () => {
    const { getDocument } = setup(undefined, '/documents/broken');
    expect(screen.getByText('Неверный ID задания')).toBeInTheDocument();
    expect(getDocument).not.toHaveBeenCalled();
  });
});

describe('типы документов (A04)', () => {
  it('переключает формуляр по выбранной карточке типа', async () => {
    setup();
    expect(screen.getByRole('button', { name: 'Создать справку' })).toBeInTheDocument();
    expect(screen.queryByLabelText('Начало периода')).not.toBeInTheDocument();
    await userEvent.click(radio('Акт об оказании услуг'));
    expect(screen.getByRole('button', { name: 'Создать акт' })).toBeInTheDocument();
    expect(screen.getByLabelText('Начало периода')).toBeInTheDocument();
    expect(screen.getByLabelText('Конец периода')).toBeInTheDocument();
    await userEvent.click(radio('Договор об обучении'));
    expect(screen.getByRole('button', { name: 'Создать договор' })).toBeInTheDocument();
    await userEvent.click(radio('Квитанция тестовой оплаты'));
    expect(screen.getByRole('button', { name: 'Создать квитанцию' })).toBeInTheDocument();
    expect(screen.getByLabelText('Номер платежа в портале')).toBeInTheDocument();
  });
  it('готовит квитанцию по глубокой ссылке из истории платежей', () => {
    setup(undefined, '/documents?type=receipt&payment=7');
    expect(radio('Квитанция тестовой оплаты')).toBeChecked();
    expect(screen.getByLabelText('Номер платежа в портале')).toHaveValue(7);
  });
});
