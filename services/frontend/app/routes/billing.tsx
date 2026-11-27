import { useQuery } from '@tanstack/react-query';
import { useRef, useState } from 'react';
import { Link } from 'react-router';
import {
  ArrowRight,
  CalendarClock,
  CircleCheck,
  FileText,
  HelpCircle,
  LoaderCircle,
  RotateCcw,
  XCircle,
} from 'lucide-react';
import { PageHeader } from '../components/page-header';
import { Alert } from '../components/ui/alert';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { useSession } from '../features/auth/session-context';
import type { Payment } from '../features/billing/api';
import { utcDateTime } from '../features/schedule/utc';
import { useFeatures } from '../lib/api/context';
import { ApiError, explainError } from '../lib/api/errors';

/** Подписи семи статусов оплаты — таблица «Статусы оплаты» docs/designs/stitch-migration.md. */
export const labels = {
  creating: 'Создаём платёж',
  pending: 'Ожидает оплаты',
  succeeded: 'Оплачено',
  canceled: 'Отменено',
  unknown: 'Уточняем результат',
  manual_review: 'Нужна ручная сверка',
  refunded: 'Возвращено',
} as const;

type Status = keyof typeof labels;

/** Иконка состояния внутри чипа: индикатор для «в процессе», знак для остальных. */
const statusIcons: Record<Status, typeof CircleCheck> = {
  creating: LoaderCircle,
  pending: CircleCheck,
  succeeded: CircleCheck,
  canceled: XCircle,
  unknown: LoaderCircle,
  manual_review: HelpCircle,
  refunded: RotateCcw,
};

const money = (value: number) =>
  new Intl.NumberFormat('ru-RU', { style: 'currency', currency: 'RUB' }).format(value / 100);
const monthLabel = (value: string) =>
  new Date(value + 'T12:00:00Z').toLocaleDateString('ru-RU', {
    month: 'long',
    year: 'numeric',
    timeZone: 'UTC',
  });
const periodLabel = (payment: Payment) => {
  if (payment.period_type !== 'quarter') return `Месяц: ${monthLabel(payment.study_month)}`;
  const year = payment.study_month.slice(0, 4);
  const quarter = payment.study_month.slice(5, 7);
  const names: Record<string, string> = {
    '09': `1-я четверть · сентябрь — октябрь ${year}`,
    '11': `2-я четверть · ноябрь — декабрь ${year}`,
    '01': `3-я четверть · январь — март ${year}`,
    '04': `4-я четверть · апрель — май ${year}`,
  };
  return names[quarter] ?? `Четверть · ${monthLabel(payment.study_month)}`;
};
const quarterNames: Record<string, (year: number) => string> = {
  '09': (year) => `1-я четверть: сентябрь — октябрь ${year}`,
  '11': (year) => `2-я четверть: ноябрь — декабрь ${year}`,
  '01': (year) => `3-я четверть: январь — март ${year + 1}`,
  '04': (year) => `4-я четверть: апрель — май ${year + 1}`,
};

/** Фильтр реестра — клиентский, по загруженной странице (серверного фильтра в API нет). */
const statusFilters: readonly {
  id: string;
  label: string;
  statuses: readonly Status[] | null;
}[] = [
  { id: 'all', label: 'Все статусы', statuses: null },
  { id: 'open', label: 'Ожидает оплаты', statuses: ['creating', 'pending', 'unknown'] },
  { id: 'paid', label: 'Оплачено', statuses: ['succeeded'] },
  { id: 'review', label: 'Возвраты и сверки', statuses: ['refunded', 'manual_review'] },
];

export default function BillingPage() {
  const { state } = useSession();
  if (state.status !== 'authenticated') return null;
  if (state.user.role === 'teacher')
    return <Alert>Этот раздел доступен ученикам, родителям и администратору.</Alert>;
  return (
    <BillingContent admin={state.user.role === 'admin'} parent={state.user.role === 'parent'} />
  );
}

function BillingContent({ admin, parent }: { admin: boolean; parent: boolean }) {
  const { billing } = useFeatures();
  const [selection, setSelection] = useState('');
  const [year, setYear] = useState(() => {
    const now = new Date();
    return now.getUTCMonth() < 5 ? now.getUTCFullYear() - 1 : now.getUTCFullYear();
  });
  const [quarter, setQuarter] = useState(() => {
    const month = new Date().getUTCMonth();
    if (month < 3) return '01';
    if (month < 5) return '04';
    if (month < 10) return '09';
    return '11';
  });
  const quarterYear = quarter === '01' || quarter === '04' ? year + 1 : year;
  const month = `${quarterYear}-${quarter}`;
  const dueDate = /^\d{4}-\d{2}$/.test(month)
    ? new Date(month + '-01T12:00:00Z').toLocaleDateString('ru-RU', {
        day: 'numeric',
        month: 'long',
        year: 'numeric',
        timeZone: 'UTC',
      })
    : 'Укажите учебный год';
  const [offset, setOffset] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [latest, setLatest] = useState<Payment | null>(null);
  const [refundId, setRefundId] = useState<number | null>(null);
  const [providerId, setProviderId] = useState('');
  const [filter, setFilter] = useState<(typeof statusFilters)[number]['id']>('all');
  // Ключ живёт до подтверждённого результата: сетевой сбой не начинает новую попытку.
  const keys = useRef(new Map<string, string>());
  const keyFor = (name: string) => {
    const old = keys.current.get(name);
    if (old) return old;
    const key = crypto.randomUUID();
    keys.current.set(name, key);
    return key;
  };
  const config = useQuery({
    queryKey: ['billing-config'],
    queryFn: ({ signal }) => billing.config(signal),
  });
  const students = useQuery({
    queryKey: ['billing-students'],
    enabled: !admin,
    queryFn: ({ signal }) => billing.students(signal),
  });
  const student = selection || students.data?.[0]?.id || '';
  const orders = useQuery({
    queryKey: ['billing-orders', student, offset],
    enabled: !admin && !!student,
    queryFn: ({ signal }) => billing.orders(student, offset, signal),
    refetchInterval: 30000,
  });
  const payments = useQuery({
    queryKey: ['billing-payments', offset],
    enabled: admin,
    queryFn: ({ signal }) => billing.payments(offset, signal),
    refetchInterval: 30000,
  });
  const page = admin ? payments : orders;
  const rows = admin
    ? (payments.data ?? [])
    : (orders.data ?? []).flatMap((order) => (order.payment ? [order.payment] : []));
  const selectedOrder = orders.data?.find(
    (order) => order.study_month === month + '-01' && order.period_type === 'quarter',
  );
  const activeFilter = statusFilters.find((item) => item.id === filter) ?? statusFilters[0];
  const visibleRows = activeFilter.statuses
    ? rows.filter((payment) => activeFilter.statuses!.includes(payment.status))
    : rows;
  const run = async (operation: () => Promise<Payment>) => {
    setBusy(true);
    setError('');
    try {
      setLatest(await operation());
      await page.refetch();
    } catch (failure) {
      setError(
        failure instanceof ApiError && failure.status === 409
          ? 'Состояние платежа уже изменилось или для четверти есть другая попытка. Обновите историю и проверьте её статус.'
          : explainError(failure),
      );
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="workspace-page billing-page">
      <PageHeader
        title="Оплата обучения и расчёты"
        eyebrow="Личный кабинет · Оплата обучения"
        description="Оплата за учебную четверть и история платежей."
      />
      <Alert>
        Только тестовый магазин ЮKassa. Настоящих списаний нет. Возвращение с платёжной страницы
        само по себе не подтверждает оплату.
      </Alert>
      {config.error && <Alert tone="error">{explainError(config.error)}</Alert>}
      {config.data && !config.data.configured && (
        <Alert>
          ЮKassa пока не подключена. Тестовые ключи нужно указать в настройках Billing; имитации
          оплаты здесь нет.
        </Alert>
      )}
      {error && (
        <Alert tone="error">
          {error} При неизвестном результате повторите действие: ключ попытки сохранён.
        </Alert>
      )}
      {!admin && (
        <section className="card form-grid billing-form billing-invoice">
          <div className="billing-invoice-head">
            <div className="billing-form-heading">
              <span className="workspace-kicker">Учебное начисление</span>
              <h2>Оплата за четверть</h2>
              <p>
                {parent
                  ? 'Выберите ученика и период, чтобы проверить счёт.'
                  : 'Выберите период, чтобы проверить счёт.'}
              </p>
            </div>
            <span className="billing-deadline">
              <CalendarClock size={15} aria-hidden="true" />
              {quarterNames[quarter](year)}
            </span>
          </div>
          {parent && (
            <label>
              Ученик
              <select
                value={student}
                disabled={busy}
                onChange={(event) => {
                  setSelection(event.target.value);
                  setOffset(0);
                  setLatest(null);
                }}
              >
                {(students.data ?? []).map((row) => (
                  <option key={row.id} value={row.id}>
                    {row.name}
                  </option>
                ))}
              </select>
            </label>
          )}
          {parent && students.isPending && <p role="status">Загружаем учеников…</p>}
          {parent && students.error && <Alert tone="error">{explainError(students.error)}</Alert>}
          {parent && students.data?.length === 0 && <p>Нет связанных учеников для оплаты.</p>}
          <label>
            Начало учебного года
            <Input
              type="number"
              min="2020"
              max="2099"
              value={year}
              disabled={busy}
              onChange={(event) => {
                setYear(Number(event.target.value));
                setLatest(null);
              }}
            />
          </label>
          <label>
            Учебная четверть
            <select
              value={quarter}
              disabled={busy}
              onChange={(event) => {
                setQuarter(event.target.value);
                setLatest(null);
              }}
            >
              {Object.entries(quarterNames).map(([value, name]) => (
                <option key={value} value={value}>
                  {name(year)}
                </option>
              ))}
            </select>
          </label>
          <div className="billing-summary">
            <div>
              <span>Стоимость четверти</span>
              <strong>
                {config.data
                  ? money(selectedOrder?.amount_kopecks ?? config.data.quarter_price_kopecks)
                  : 'Загружаем…'}
              </strong>
              <small>НДС не облагается</small>
            </div>
            <div>
              <span>Оплатить до начала четверти</span>
              <strong>{dueDate}</strong>
              <small>по московскому времени</small>
            </div>
            <div>
              <span>Состояние счёта</span>
              <strong role="status">
                {orders.isPending || orders.isFetching
                  ? 'Проверяем счёт…'
                  : orders.isError || offset !== 0
                    ? 'Состояние счёта недоступно'
                    : !selectedOrder
                      ? 'Счёт ещё не создан'
                      : selectedOrder.status === 'paid'
                        ? 'Счёт оплачен'
                        : selectedOrder.status === 'refunded'
                          ? 'Оплата возвращена'
                          : 'Счёт выставлен, ожидает оплаты'}
              </strong>
            </div>
          </div>
          {selectedOrder?.payment?.status === 'pending' &&
            selectedOrder.payment.confirmation_url && (
              <div className="billing-resume">
                <p>
                  Для этой четверти уже создан платёж. Продолжите оплату или проверьте её статус в
                  истории ниже.
                </p>
                <a
                  className="button button-primary"
                  href={selectedOrder.payment.confirmation_url}
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  Продолжить оплату в ЮKassa
                </a>
              </div>
            )}
          {!(
            selectedOrder?.payment?.status === 'pending' && selectedOrder.payment.confirmation_url
          ) && (
            <div className="billing-cta">
              <Button
                disabled={
                  busy ||
                  !student ||
                  !/^\d{4}-\d{2}$/.test(month) ||
                  year < 2020 ||
                  year > 2099 ||
                  !config.data?.configured ||
                  !orders.isSuccess ||
                  offset !== 0 ||
                  (!!selectedOrder?.payment &&
                    !['canceled', 'refunded'].includes(selectedOrder.payment.status))
                }
                onClick={() => {
                  const name = `${student}:${month}`;
                  void run(async () => {
                    const result = await billing.start(
                      student,
                      month + '-01',
                      keyFor(name),
                      'quarter',
                    );
                    if (['canceled', 'refunded'].includes(result.status)) keys.current.delete(name);
                    return result;
                  });
                }}
              >
                Перейти к оплате четверти
              </Button>
              <p className="billing-cta-note">
                Переход на защищённый шлюз ЮKassa. Тестовый режим: реальные списания не проходят.
              </p>
            </div>
          )}
        </section>
      )}
      {latest && (
        <section className="card billing-result">
          <p role="status">
            Платёж №{latest.id}: {labels[latest.status]}
          </p>
          {latest.confirmation_url && latest.status === 'pending' && (
            <a
              className="button button-primary"
              href={latest.confirmation_url}
              target="_blank"
              rel="noopener noreferrer"
            >
              Открыть ЮKassa
            </a>
          )}
        </section>
      )}
      <section className="card billing-history">
        <div className="billing-history-header">
          <div className="billing-history-heading">
            <span className="workspace-kicker">Реестр операций</span>
            <h2>История платежей</h2>
          </div>
          <div className="billing-history-tools">
            {page.isSuccess && rows.length > 0 && (
              <span className="billing-count">{rows.length} операций на странице</span>
            )}
            <Button
              variant="secondary"
              disabled={busy || page.isFetching}
              onClick={() => {
                void page.refetch();
              }}
            >
              Обновить список
            </Button>
          </div>
        </div>
        <div className="billing-filters" role="group" aria-label="Фильтр статусов">
          {statusFilters.map((item) => (
            <button
              key={item.id}
              type="button"
              className="billing-filter-chip"
              aria-pressed={filter === item.id}
              disabled={busy}
              onClick={() => setFilter(item.id)}
            >
              {item.label}
            </button>
          ))}
          <span className="billing-filters-note">фильтр по загруженной странице</span>
        </div>
        {page.isPending && <p role="status">Загружаем историю…</p>}
        {page.error && <Alert tone="error">{explainError(page.error)}</Alert>}
        {page.isSuccess && rows.length === 0 && <p>Платежей пока нет.</p>}
        {page.isSuccess && rows.length > 0 && visibleRows.length === 0 && (
          <p>На этой странице нет платежей выбранного статуса.</p>
        )}
        {visibleRows.map((payment) => (
          <PaymentRow
            key={payment.id}
            payment={payment}
            admin={admin}
            busy={busy}
            configured={!!config.data?.configured}
            refundOpen={refundId === payment.id}
            providerId={providerId}
            onProviderId={setProviderId}
            onRefresh={() => {
              void run(() => billing.refresh(payment.id));
            }}
            onRefundOpen={() => setRefundId(payment.id)}
            onRefundCancel={() => setRefundId(null)}
            onRefund={() => {
              void run(async () => {
                const result = await billing.refund(payment.id, keyFor(`refund:${payment.id}`));
                setRefundId(null);
                return result;
              });
            }}
            onReconcile={() => {
              void run(() => billing.reconcile(payment.id, providerId));
            }}
          />
        ))}
        <div className="billing-pagination">
          <Button
            variant="secondary"
            disabled={busy || offset === 0}
            onClick={() => setOffset(Math.max(0, offset - 50))}
          >
            Назад
          </Button>
          <Button
            variant="secondary"
            disabled={busy || !page.isSuccess || page.data.length < 50}
            onClick={() => setOffset(offset + 50)}
          >
            Дальше
          </Button>
        </div>
      </section>
    </div>
  );
}

/** Одна операция реестра: подпись статуса и действия строго по таблице статусов спецификации. */
function PaymentRow({
  payment,
  admin,
  busy,
  configured,
  refundOpen,
  providerId,
  onProviderId,
  onRefresh,
  onRefundOpen,
  onRefundCancel,
  onRefund,
  onReconcile,
}: {
  payment: Payment & { student_name?: string };
  admin: boolean;
  busy: boolean;
  configured: boolean;
  refundOpen: boolean;
  providerId: string;
  onProviderId: (value: string) => void;
  onRefresh: () => void;
  onRefundOpen: () => void;
  onRefundCancel: () => void;
  onRefund: () => void;
  onReconcile: () => void;
}) {
  const Icon = statusIcons[payment.status];
  const inFlight = payment.status === 'creating' || payment.status === 'unknown';
  const hints: Partial<Record<Status, string>> = {
    canceled: admin
      ? 'Платёж отменён в шлюзе — счёт можно оплатить заново.'
      : 'Платёж отменён — создайте новый в форме выше.',
    unknown: 'Результат уточняется автоматически; списание пока не подтверждено.',
    manual_review: admin
      ? undefined
      : 'Платёж на ручной сверке — администратор проверит его вручную.',
  };
  const hint = hints[payment.status];
  return (
    <article className="billing-payment billing-row" data-status={payment.status}>
      <div className="billing-payment-details billing-row-details">
        <h3>{periodLabel(payment)}</h3>
        <p>
          Платёж №{payment.id} · {utcDateTime(payment.created_at)}
        </p>
        {admin && 'student_name' in payment && <p>Ученик: {String(payment.student_name)}</p>}
        {payment.refund_status && <p>Возврат: {labels[payment.refund_status]}</p>}
        {hint && <p className="billing-row-hint">{hint}</p>}
      </div>
      <strong className="billing-payment-amount billing-row-amount">
        {money(payment.amount_kopecks)}
      </strong>
      <span className={`billing-payment-status billing-payment-status--${payment.status}`}>
        <Icon size={13} className={inFlight ? 'spinner' : undefined} aria-hidden="true" />
        {labels[payment.status]}
      </span>
      <div className="billing-payment-actions billing-row-actions">
        {payment.confirmation_url && payment.status === 'pending' && (
          <a
            className="button button-primary"
            href={payment.confirmation_url}
            target="_blank"
            rel="noopener noreferrer"
          >
            Оплатить в ЮKassa
            <ArrowRight size={15} aria-hidden="true" />
          </a>
        )}
        {admin && payment.status === 'succeeded' && !payment.refund_status && (
          <Link
            className="button button-secondary"
            to={`/documents?type=receipt&payment=${payment.id}`}
          >
            <FileText size={15} aria-hidden="true" />
            Квитанция PDF
          </Link>
        )}
        <Button
          variant="secondary"
          disabled={busy || !configured || payment.status === 'creating'}
          onClick={onRefresh}
        >
          Проверить статус в ЮKassa
        </Button>
        {admin && payment.status === 'succeeded' && !payment.refund_status && (
          <Button variant="danger" disabled={busy} onClick={onRefundOpen}>
            Полный возврат
          </Button>
        )}
      </div>
      {admin && payment.status === 'manual_review' && (
        <label>
          UUID платежа из тестового кабинета
          <Input
            value={providerId}
            placeholder="00000000-0000-0000-0000-000000000000"
            onChange={(event) => onProviderId(event.target.value)}
          />
          <Button disabled={busy || !providerId} onClick={onReconcile}>
            Сверить платёж
          </Button>
        </label>
      )}
      {refundOpen && (
        <div role="group" aria-label="Подтверждение возврата">
          <p>
            Вернуть всю сумму {money(payment.amount_kopecks)}? Частичный возврат не поддерживается.
          </p>
          <Button variant="danger" disabled={busy} onClick={onRefund}>
            Подтвердить полный возврат
          </Button>
          <Button variant="secondary" disabled={busy} onClick={onRefundCancel}>
            Отмена
          </Button>
        </div>
      )}
    </article>
  );
}
