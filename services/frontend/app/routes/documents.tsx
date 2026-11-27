import { useRef, useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router';
import { useQuery } from '@tanstack/react-query';
import {
  ClipboardCheck,
  FileSignature,
  GraduationCap,
  RefreshCw,
  Receipt as ReceiptIcon,
} from 'lucide-react';
import { PageHeader } from '../components/page-header';
import { Input } from '../components/ui/input';
import { Button } from '../components/ui/button';
import { CertificateForm } from '../features/documents/certificate-form';
import { documentNames, jobStatusLabels } from '../features/documents/names';
import { useFeatures } from '../lib/api/context';
import { uuidSchema } from '../lib/api/contracts';
import { Alert } from '../components/ui/alert';
import { explainError } from '../lib/api/errors';
import { utcDateTime } from '../features/schedule/utc';
import type { DocumentType } from '../features/documents/api';

/** Каталог типов для «шага 1»: карточка с описанием, выбор — радио, клавиатура нативная. */
const documentTypes: {
  value: DocumentType;
  label: string;
  icon: typeof GraduationCap;
  description: string;
}[] = [
  {
    value: 'certificate',
    label: 'Справка об обучении',
    icon: GraduationCap,
    description: 'Подтверждение обучения для соцзащиты, военкомата и визовых центров.',
  },
  {
    value: 'contract',
    label: 'Договор об обучении',
    icon: FileSignature,
    description: 'Договор на образовательные услуги гимназии.',
  },
  {
    value: 'act',
    label: 'Акт об оказании услуг',
    icon: ClipboardCheck,
    description: 'Закрытие образовательного периода: месяц или учебная четверть.',
  },
  {
    value: 'receipt',
    label: 'Квитанция тестовой оплаты',
    icon: ReceiptIcon,
    description: 'Платёжный документ по подтверждённой тестовой оплате.',
  },
];

const isDocumentType = (value: string | null): value is DocumentType =>
  documentTypes.some((type) => type.value === value);

export default function Documents() {
  const { documents } = useFeatures();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  // Глубокая ссылка из истории платежей: /documents?type=receipt&payment=N
  const requestedType = searchParams.get('type');
  const requestedPayment = Number(searchParams.get('payment'));
  const [jobId, setJobId] = useState('');
  const [invalidId, setInvalidId] = useState(false);
  const [kind, setKind] = useState<DocumentType>(() =>
    isDocumentType(requestedType) ? requestedType : 'certificate',
  );
  const [offset, setOffset] = useState(0);
  const [paymentId, setPaymentId] = useState(() =>
    Number.isInteger(requestedPayment) && requestedPayment > 0 ? String(requestedPayment) : '',
  );
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
        eyebrow="Канцелярия · Документооборот"
        description="Справки, договоры, акты и квитанции. Здесь находятся ваши задания генерации PDF."
      />
      <Alert>
        Все шаблоны учебные. Они не заменяют юридические документы и фискальные чеки. Квитанция
        доступна только для подтверждённой тестовой оплаты.
      </Alert>
      <div className="documents-layout">
        <div className="documents-main">
          <section className="card doc-create">
            <span className="workspace-kicker">Шаг 1 · Тип документа</span>
            <fieldset className="doc-types">
              <legend>Тип документа</legend>
              {documentTypes.map(({ value, label, icon: Icon, description }) => (
                <label key={value} className={`doc-type${kind === value ? ' is-selected' : ''}`}>
                  <input
                    type="radio"
                    name="document-type"
                    value={value}
                    checked={kind === value}
                    disabled={sending}
                    onChange={() => {
                      setKind(value);
                      setReceiptError('');
                    }}
                  />
                  <span className="doc-type-icon" aria-hidden="true">
                    <Icon size={20} />
                  </span>
                  <span className="doc-type-body">
                    <span className="doc-type-name">{label}</span>
                    <span className="doc-type-description">{description}</span>
                  </span>
                  {kind === value && <span className="doc-type-selected">Выбран</span>}
                </label>
              ))}
            </fieldset>
            <span className="workspace-kicker">Шаг 2 · Данные для формуляра</span>
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
                    {receiptError} При неизвестном результате повторите с тем же номером: ключ
                    запроса сохранён.
                  </Alert>
                )}
                <Button type="submit" disabled={sending}>
                  {sending ? 'Отправляем…' : 'Создать квитанцию'}
                </Button>
              </form>
            )}
          </section>
          <section className="card doc-open">
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
            <p className="field-hint">
              ФИО и документы не сохраняются в локальном хранилище браузера.
            </p>
          </section>
        </div>
        <aside className="documents-aside">
          <section className="card document-history doc-registry">
            <div className="doc-registry-head">
              <div>
                <span className="workspace-kicker">Журнал регистрации</span>
                <h2>Реестр заданий</h2>
              </div>
              <Button
                variant="secondary"
                disabled={jobs.isFetching}
                onClick={() => {
                  void jobs.refetch();
                }}
              >
                <RefreshCw size={15} aria-hidden="true" />
                Обновить реестр
              </Button>
            </div>
            {jobs.isPending && <p role="status">Загружаем задания…</p>}
            {jobs.error && <Alert tone="error">{explainError(jobs.error)}</Alert>}
            {jobs.data?.length === 0 && <p>Вы ещё не создавали документы.</p>}
            <ul className="doc-registry-list">
              {(jobs.data ?? []).map((job) => (
                <li key={job.id}>
                  <Link
                    to={`/documents/${job.id}`}
                    className="doc-registry-row"
                    data-status={job.status}
                  >
                    <span className="doc-registry-main">
                      <span className="doc-registry-name">{documentNames[job.document_type]}</span>
                      <span className="doc-registry-date">{utcDateTime(job.created_at)}</span>
                    </span>
                    <span className={`doc-registry-status doc-registry-status--${job.status}`}>
                      {jobStatusLabels[job.status]}
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
            <div className="billing-pagination">
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
            </div>
          </section>
        </aside>
      </div>
    </div>
  );
}
