import { useInfiniteQuery, useQuery } from '@tanstack/react-query';
import { Fragment, useState } from 'react';
import { PageHeader } from '../components/page-header';
import { Alert } from '../components/ui/alert';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { AuditPayload, ProgressTable } from '../features/analytics/progress-table';
import type { AuditEvent } from '../features/analytics/api';
import { schoolTime } from '../features/schedule/school-dates';
import { useFeatures } from '../lib/api/context';
import { explainError } from '../lib/api/errors';

const AUDIT_PAGE_SIZE = 50;

function utcTime(instant: string) {
  return new Date(instant).toLocaleTimeString('ru-RU', {
    timeZone: 'UTC',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  });
}

/* Журнал аудита: строки-события с раскрытием технического JSON (a06 —
   визуальный ориентир; колонки соответствуют реальным полям события). */
function AuditJournal({ events }: { events: AuditEvent[] }) {
  const [openId, setOpenId] = useState<string | null>(null);
  if (!events.length) return <p>Событий на этой странице нет.</p>;
  return (
    <div className="audit-table-wrap">
      <table className="data-table audit-table">
        <caption>Журнал действий за выбранный период</caption>
        <thead>
          <tr>
            <th scope="col">Время (UTC+5 / UTC)</th>
            <th scope="col">Инициатор</th>
            <th scope="col">Событие</th>
            <th scope="col">Источник</th>
            <th scope="col">Данные</th>
          </tr>
        </thead>
        <tbody>
          {events.map((event) => {
            const open = openId === event.event_id;
            return (
              <Fragment key={event.event_id}>
                <tr>
                  <td>
                    <time dateTime={event.occurred_at} className="audit-time">
                      {schoolTime(event.occurred_at)}
                    </time>
                    <span className="audit-time-utc">{utcTime(event.occurred_at)} UTC</span>
                  </td>
                  <td>
                    <span className="audit-actor">{event.actor.source}</span>
                    <span className="audit-actor-id">{event.actor.id}</span>
                  </td>
                  <td>{event.event_type}</td>
                  <td>{event.event_source}</td>
                  <td>
                    <Button
                      variant="ghost"
                      className="audit-toggle"
                      aria-expanded={open}
                      aria-controls={`audit-payload-${event.event_id}`}
                      onClick={() => setOpenId(open ? null : event.event_id)}
                    >
                      {open ? 'Скрыть данные' : 'Данные события'}
                    </Button>
                  </td>
                </tr>
                {open && (
                  <tr className="audit-payload-row">
                    <td colSpan={5} id={`audit-payload-${event.event_id}`}>
                      <AuditPayload payload={event.payload} />
                    </td>
                  </tr>
                )}
              </Fragment>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

export default function AnalyticsPage() {
  const { analytics } = useFeatures();
  const today = new Date().toISOString().slice(0, 10);
  const [from, setFrom] = useState(today.slice(0, 8) + '01');
  const [to, setTo] = useState(today);
  const [selection, setSelection] = useState('');
  const [offset, setOffset] = useState(0);
  const classes = useInfiniteQuery({
    queryKey: ['analytics-classes'],
    initialPageParam: 0,
    queryFn: ({ pageParam, signal }) => analytics.getClasses(pageParam, signal),
    getNextPageParam: (last, all) => (last.length === 100 ? all.length * 100 : undefined),
  });
  const choices = classes.data?.pages.flat() ?? [];
  const classId = Number(selection || choices[0]?.id || 0);
  const days = (Date.parse(to) - Date.parse(from)) / 86400000;
  const valid = Number.isFinite(days) && days >= 0 && days < 366;
  const progress = useQuery({
    queryKey: ['progress', classId, from, to],
    enabled: valid && classId > 0,
    queryFn: ({ signal }) => analytics.getProgress(classId, from, to, signal),
  });
  const audit = useQuery({
    queryKey: ['audit', from, to, offset],
    enabled: valid,
    queryFn: ({ signal }) => analytics.getAudit(from, to, offset, signal),
  });
  const changePeriod = (update: () => void) => {
    update();
    setOffset(0);
  };
  const page = offset / AUDIT_PAGE_SIZE + 1;
  return (
    <>
      <PageHeader
        title="Успеваемость и аудит"
        description="История действий и оценки проверенных работ. Период — по датам событий UTC."
      />
      <Alert>
        Отчёт включает события после подключения аудита. Старые оценки автоматически в историю не
        переносились.
      </Alert>
      <section className="card form-grid">
        <label>
          С даты
          <Input
            type="date"
            value={from}
            onChange={(e) => changePeriod(() => setFrom(e.target.value))}
          />
        </label>
        <label>
          По дату
          <Input
            type="date"
            value={to}
            onChange={(e) => changePeriod(() => setTo(e.target.value))}
          />
        </label>
        <label>
          Класс
          <select
            className="input"
            value={classId || ''}
            onChange={(e) => setSelection(e.target.value)}
          >
            {!choices.length && <option value="">Классы не загружены</option>}
            {choices.map((row) => (
              <option key={row.id} value={row.id}>
                {row.name} · {row.study_year}/{row.study_year + 1}
              </option>
            ))}
          </select>
        </label>
        {classes.hasNextPage && (
          <Button
            variant="secondary"
            onClick={() => void classes.fetchNextPage()}
            disabled={classes.isFetchingNextPage}
          >
            Загрузить ещё классы
          </Button>
        )}
        <Button
          variant="secondary"
          disabled={!valid || progress.isFetching || audit.isFetching}
          onClick={() => {
            if (classId > 0) void progress.refetch();
            void audit.refetch();
          }}
        >
          Обновить
        </Button>
      </section>
      {!valid && <Alert tone="error">Выберите период от1до366дней.</Alert>}
      {classes.isError && <Alert tone="error">{explainError(classes.error)}</Alert>}
      <section className="card">
        <h2>Успеваемость класса</h2>
        {progress.isFetching && <p role="status">Загружаем оценки…</p>}
        {progress.isError && <Alert tone="error">{explainError(progress.error)}</Alert>}
        {valid && !progress.isError && progress.data && <ProgressTable rows={progress.data} />}
        {!classId && !classes.isFetching && <p>Для отчёта нужен класс.</p>}
      </section>
      <section className="card">
        <h2>Общий журнал действий</h2>
        {audit.isFetching && <p role="status">Загружаем события…</p>}
        {audit.isError && <Alert tone="error">{explainError(audit.error)}</Alert>}
        {valid && !audit.isError && audit.data && (
          <>
            <AuditJournal events={audit.data} />
            <div className="form-actions audit-pagination">
              <span className="audit-page" aria-live="polite">
                Страница {page}
              </span>
              <Button
                variant="secondary"
                disabled={offset === 0 || audit.isFetching}
                onClick={() => setOffset((value) => Math.max(0, value - AUDIT_PAGE_SIZE))}
              >
                Предыдущие
              </Button>
              <Button
                variant="secondary"
                disabled={audit.data.length < AUDIT_PAGE_SIZE || audit.isFetching}
                onClick={() => setOffset((value) => value + AUDIT_PAGE_SIZE)}
              >
                Следующие
              </Button>
            </div>
          </>
        )}
      </section>
    </>
  );
}
