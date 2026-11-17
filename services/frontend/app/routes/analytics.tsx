import { useInfiniteQuery, useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { PageHeader } from '../components/page-header';
import { Alert } from '../components/ui/alert';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { ProgressTable } from '../features/analytics/progress-table';
import { useFeatures } from '../lib/api/context';
import { explainError } from '../lib/api/errors';

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
            {!audit.data.length && <p>Событий на этой странице нет.</p>}
            <ol>
              {audit.data.map((event) => (
                <li key={event.event_id}>
                  <p>
                    <time dateTime={event.occurred_at}>
                      {new Date(event.occurred_at).toLocaleString('ru-RU', { timeZone: 'UTC' })} UTC
                    </time>{' '}
                    · {event.event_type}
                  </p>
                  <p>
                    Источник: {event.event_source}; инициатор: {event.actor.source} /{' '}
                    {event.actor.id}
                  </p>
                  <details>
                    <summary>Данные события</summary>
                    <pre style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>
                      {JSON.stringify(event.payload, null, 2)}
                    </pre>
                  </details>
                </li>
              ))}
            </ol>
            <div className="form-actions">
              <Button
                variant="secondary"
                disabled={offset === 0 || audit.isFetching}
                onClick={() => setOffset((value) => Math.max(0, value - 50))}
              >
                Предыдущие
              </Button>
              <Button
                variant="secondary"
                disabled={audit.data.length < 50 || audit.isFetching}
                onClick={() => setOffset((value) => value + 50)}
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
