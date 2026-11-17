import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { Link } from 'react-router';
import { PageHeader } from '../components/page-header';
import { Alert } from '../components/ui/alert';
import { Button } from '../components/ui/button';
import { useFeatures } from '../lib/api/context';
import { explainError } from '../lib/api/errors';

export default function NotificationsPage() {
  const { notifications } = useFeatures();
  const [offset, setOffset] = useState(0);
  const [pendingId, setPendingId] = useState<number | null>(null);
  const [error, setError] = useState('');
  const list = useQuery({
    queryKey: ['notifications', offset],
    queryFn: ({ signal }) => notifications.list(offset, signal),
    refetchInterval: 30000,
    refetchIntervalInBackground: false,
  });
  const count = useQuery({
    queryKey: ['notifications-count'],
    queryFn: ({ signal }) => notifications.count(signal),
    refetchInterval: 30000,
    refetchIntervalInBackground: false,
  });
  const refresh = async () => {
    await Promise.all([list.refetch(), count.refetch()]);
  };
  const markRead = async (id: number) => {
    setPendingId(id);
    setError('');
    try {
      await notifications.markRead(id);
      await refresh();
    } catch (failure) {
      setError(explainError(failure));
    } finally {
      setPendingId(null);
    }
  };
  return (
    <>
      <PageHeader
        title="Уведомления"
        description="Проверка домашних заданий, оплата и готовность документов. Только сообщения для вашего аккаунта."
      />
      <section className="card">
        {count.data && <p role="status">Непрочитанных: {count.data.unread}</p>}
        <Button
          variant="secondary"
          disabled={list.isFetching || count.isFetching}
          onClick={() => {
            void refresh();
          }}
        >
          Обновить уведомления
        </Button>
        <p className="field-hint">
          Проверяем новые сообщения каждые 30 секунд, пока страница открыта.
        </p>
      </section>
      {error && <Alert tone="error">{error}</Alert>}
      {count.error && <Alert tone="error">Счётчик недоступен: {explainError(count.error)}</Alert>}
      {list.isPending && <p role="status">Загружаем уведомления…</p>}
      {list.error && <Alert tone="error">{explainError(list.error)}</Alert>}
      {list.data?.length === 0 && (
        <section className="card">
          <p>На этой странице пока нет уведомлений.</p>
        </section>
      )}
      {(list.data ?? []).map((row) => (
        <article className="card" key={row.id}>
          <span className="badge">{row.read_at ? 'Прочитано' : 'Не прочитано'}</span>
          <h2>{row.title}</h2>
          <p>{row.body}</p>
          <p className="field-hint">
            <time dateTime={row.created_at}>
              {new Date(row.created_at).toLocaleString('ru-RU')}
            </time>
          </p>
          <div className="form-actions">
            <Link className="button button-secondary" to={row.link}>
              Открыть
            </Link>
            {!row.read_at && (
              <Button
                disabled={pendingId !== null}
                onClick={() => {
                  void markRead(row.id);
                }}
              >
                {pendingId === row.id ? 'Сохраняем…' : 'Отметить прочитанным'}
              </Button>
            )}
          </div>
        </article>
      ))}
      <div className="form-actions">
        <Button
          variant="secondary"
          disabled={offset === 0 || list.isFetching}
          onClick={() => setOffset(Math.max(0, offset - 50))}
        >
          Назад
        </Button>
        <Button
          variant="secondary"
          disabled={!list.data || list.data.length < 50 || list.isFetching}
          onClick={() => setOffset(offset + 50)}
        >
          Дальше
        </Button>
      </div>
    </>
  );
}
