import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { Link } from 'react-router';
import { PageHeader } from '../components/page-header';
import { AsyncState } from '../components/async-state';
import { Alert } from '../components/ui/alert';
import { Button } from '../components/ui/button';
import { NotificationRow, NotificationsEmpty } from '../features/notifications/notification-row';
import { useFeatures } from '../lib/api/context';
import { explainError } from '../lib/api/errors';

const PAGE_SIZE = 50;

/** Полная страница уведомлений по макету g02: состояния, отметки, пусто, пагинация. */
export default function NotificationsPage() {
  const { notifications } = useFeatures();
  const [offset, setOffset] = useState(0);
  const [pendingId, setPendingId] = useState<number | null>(null);
  const [markingAll, setMarkingAll] = useState(false);
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
  const unreadIds = (list.data ?? []).filter((row) => !row.read_at).map((row) => row.id);
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
  const markAllShown = async () => {
    setMarkingAll(true);
    setError('');
    try {
      for (const id of unreadIds) await notifications.markRead(id);
      await refresh();
    } catch (failure) {
      setError(explainError(failure));
    } finally {
      setMarkingAll(false);
    }
  };
  return (
    <div className="workspace-page notification-page">
      <PageHeader
        eyebrow="Личный кабинет"
        title="Уведомления"
        description="Проверка домашних заданий, оплата и готовность документов. Только сообщения для вашего аккаунта."
        action={
          <Link to="/" className="button button-secondary notif-back">
            На главную
          </Link>
        }
      />
      <section className="notification-toolbar">
        {count.data && <p role="status">Непрочитанных: {count.data.unread}</p>}
        <div className="notification-toolbar-actions">
          <Button
            variant="secondary"
            disabled={markingAll || pendingId !== null || !unreadIds.length || list.isFetching}
            onClick={() => {
              void markAllShown();
            }}
          >
            {markingAll ? 'Отмечаем…' : 'Отметить все как прочитанные'}
          </Button>
          <Button
            variant="secondary"
            disabled={list.isFetching || count.isFetching}
            onClick={() => {
              void refresh();
            }}
          >
            Обновить уведомления
          </Button>
        </div>
      </section>
      {error && <Alert tone="error">{error}</Alert>}
      {count.error && <Alert tone="error">Счётчик недоступен: {explainError(count.error)}</Alert>}
      {list.isPending && <AsyncState state="loading" title="Загружаем уведомления" />}
      {list.error && <Alert tone="error">{explainError(list.error)}</Alert>}
      {list.data?.length === 0 && <NotificationsEmpty />}
      <div className="notif-list">
        {(list.data ?? []).map((row) => (
          <NotificationRow
            key={row.id}
            item={row}
            busy={pendingId !== null || markingAll}
            onMarkRead={(id) => {
              void markRead(id);
            }}
          />
        ))}
      </div>
      <nav className="notif-pagination" aria-label="Постраничный выбор уведомлений">
        <Button
          variant="secondary"
          disabled={offset === 0 || list.isFetching}
          onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
        >
          Назад
        </Button>
        <span role="status">
          {list.data
            ? `Показаны уведомления с ${offset + 1} по ${offset + list.data.length}`
            : `Страница ${Math.floor(offset / PAGE_SIZE) + 1}`}
        </span>
        <Button
          variant="secondary"
          disabled={!list.data || list.data.length < PAGE_SIZE || list.isFetching}
          onClick={() => setOffset(offset + PAGE_SIZE)}
        >
          Дальше
        </Button>
      </nav>
    </div>
  );
}
