import { useRef, useState } from 'react';
import { Link, useNavigate } from 'react-router';
import { useQuery } from '@tanstack/react-query';
import { PageHeader } from '../components/page-header';
import { Input } from '../components/ui/input';
import { Button } from '../components/ui/button';
import { CertificateForm } from '../features/documents/certificate-form';
import { useFeatures } from '../lib/api/context';
import { uuidSchema } from '../lib/api/contracts';
import { Alert } from '../components/ui/alert';
import { explainError } from '../lib/api/errors';
import type { DocumentType } from '../features/documents/api';

const documentNames = {
  certificate: 'Справка об обучении',
  contract: 'Договор об обучении',
  act: 'Акт об оказании услуг',
  receipt: 'Квитанция тестовой оплаты',
};
const jobStatuses = {
  pending: 'В очереди',
  processing: 'Готовим PDF',
  completed: 'Готов',
  failed: 'Ошибка генерации',
};

export default function Documents() {
  const { documents } = useFeatures();
  const navigate = useNavigate();
  const [jobId, setJobId] = useState('');
  const [invalidId, setInvalidId] = useState(false);
  const [kind, setKind] = useState<DocumentType>('certificate');
  const [offset, setOffset] = useState(0);
  const [paymentId, setPaymentId] = useState('');
  const [receiptError, setReceiptError] = useState('');
  const [sending, setSending] = useState(false);
  const keys = useRef(new Map<string, string>());
  const keyFor = (input: unknown) => {
    const signature = JSON.stringify({ kind, input });
    const old = keys.current.get(signature);
    if (old) return old;
    const key = crypto.randomUUID();
    keys.current.set(signature, key);
    return key;
  };
  const jobs = useQuery({
    queryKey: ['document-jobs', offset],
    queryFn: ({ signal }) => documents.listJobs(offset, signal),
  });
  return (
    <div className="workspace-page documents-page">
      <PageHeader
        title="Документы"
        eyebrow="Школьные документы"
        description="Справки, договоры, акты и квитанции. Здесь находятся ваши задания генерации PDF."
      />
      <Alert>
        Все шаблоны учебные. Они не заменяют юридические документы и фискальные чеки. Квитанция
        доступна только для подтверждённой тестовой оплаты.
      </Alert>
      <div className="document-grid documents-workspace">
        <section className="card">
          <h2>Новый документ</h2>
          <label>
            Тип документа
            <select
              value={kind}
              disabled={sending}
              onChange={(event) => {
                setKind(event.target.value as DocumentType);
                setReceiptError('');
              }}
            >
              {Object.entries(documentNames).map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
          </label>
          <p>Укажите данные, которые должны попасть в документ.</p>
          {kind !== 'receipt' ? (
            <CertificateForm
              key={kind}
              kind={kind}
              onCreate={async (input) => {
                const key = keyFor(input);
                const job =
                  kind === 'certificate'
                    ? await documents.createCertificate(input, key)
                    : await documents.createTemplate(kind, input, key);
                navigate(`/documents/${uuidSchema.parse(job.id)}`);
              }}
            />
          ) : (
            <form
              className="form-stack"
              onSubmit={async (event) => {
                event.preventDefault();
                if (sending) return;
                setSending(true);
                setReceiptError('');
                try {
                  const input = { payment_id: Number(paymentId) };
                  const job = await documents.createTemplate('receipt', input, keyFor(input));
                  navigate(`/documents/${uuidSchema.parse(job.id)}`);
                } catch (error) {
                  setReceiptError(explainError(error));
                } finally {
                  setSending(false);
                }
              }}
            >
              <label>
                Номер платежа в портале
                <Input
                  type="number"
                  min="1"
                  max="2147483647"
                  step="1"
                  required
                  value={paymentId}
                  disabled={sending}
                  onChange={(event) => setPaymentId(event.target.value)}
                />
              </label>
              <p className="field-hint">
                Номер виден в разделе оплаты. Имя ученика, месяц и сумму сервер подставит по
                подтверждённому платежу.
              </p>
              {receiptError && (
                <Alert tone="error">
                  {receiptError} При неизвестном результате повторите с тем же номером: ключ запроса
                  сохранён.
                </Alert>
              )}
              <Button type="submit" disabled={sending}>
                {sending ? 'Отправляем…' : 'Создать квитанцию'}
              </Button>
            </form>
          )}
        </section>
        <section className="card">
          <span className="feature-icon peach" aria-hidden="true">
            PDF
          </span>
          <h2>Уже есть задание?</h2>
          <p>Откройте сохранённую ссылку или введите его UUID.</p>
          <form
            className="form-stack"
            noValidate
            onSubmit={(event) => {
              event.preventDefault();
              const parsed = uuidSchema.safeParse(jobId.trim());
              setInvalidId(!parsed.success);
              if (parsed.success) navigate(`/documents/${parsed.data}`);
            }}
          >
            <div className="field">
              <label htmlFor="known-job">ID задания</label>
              <Input
                id="known-job"
                value={jobId}
                onChange={(event) => setJobId(event.target.value)}
                autoComplete="off"
                placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
                aria-invalid={invalidId}
                aria-describedby={invalidId ? 'known-job-error' : undefined}
              />
              {invalidId && (
                <p className="field-error" id="known-job-error">
                  Введите корректный UUID.
                </p>
              )}
            </div>
            <Button type="submit" variant="secondary">
              Открыть задание
            </Button>
          </form>
          <p className="field-hint" style={{ marginTop: 20 }}>
            ФИО и документы не сохраняются в локальном хранилище браузера.
          </p>
        </section>
      </div>
      <section className="card document-history">
        <h2>Мои задания</h2>
        <Button
          variant="secondary"
          disabled={jobs.isFetching}
          onClick={() => {
            void jobs.refetch();
          }}
        >
          Обновить задания
        </Button>
        {jobs.isPending && <p role="status">Загружаем задания…</p>}
        {jobs.error && <Alert tone="error">{explainError(jobs.error)}</Alert>}
        {jobs.data?.length === 0 && <p>Вы ещё не создавали документы.</p>}
        <ul>
          {(jobs.data ?? []).map((job) => (
            <li key={job.id}>
              <Link to={`/documents/${job.id}`}>
                {documentNames[job.document_type]} · {jobStatuses[job.status]} ·{' '}
                {new Date(job.created_at).toLocaleString('ru-RU')}
              </Link>
            </li>
          ))}
        </ul>
        <Button
          variant="secondary"
          disabled={offset === 0}
          onClick={() => setOffset(Math.max(0, offset - 50))}
        >
          Назад
        </Button>
        <Button
          variant="secondary"
          disabled={!jobs.data || jobs.data.length < 50}
          onClick={() => setOffset(offset + 50)}
        >
          Дальше
        </Button>
      </section>
    </div>
  );
}
