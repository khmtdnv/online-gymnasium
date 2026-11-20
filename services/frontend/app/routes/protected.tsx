import * as Dialog from '@radix-ui/react-dialog';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Bell, X } from 'lucide-react';
import { useState } from 'react';
import { Link, Navigate, Outlet } from 'react-router';
import { AppShell } from '../components/app-shell';
import { AsyncState } from '../components/async-state';
import { enterBackoffice, readCsrfCookie } from '../features/auth/backoffice-sso';
import { useSession } from '../features/auth/session-context';
import { useFeatures } from '../lib/api/context';

function NotificationControl() {
  const { notifications } = useFeatures();
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const count = useQuery({
    queryKey: ['notifications-count'],
    queryFn: ({ signal }) => notifications.count(signal),
    refetchInterval: 30000,
    refetchIntervalInBackground: false,
  });
  const unread = count.data?.unread ?? 0;
  const list = useQuery({
    queryKey: ['notifications', 0],
    queryFn: ({ signal }) => notifications.list(0, signal),
    enabled: open,
  });
  const markRead = async (ids: number[]) => {
    setBusy(true);
    setError('');
    try {
      for (const id of ids) await notifications.markRead(id);
    } catch {
      setError('Не удалось отметить все выбранные уведомления. Попробуйте ещё раз.');
    } finally {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['notifications'] }),
        queryClient.invalidateQueries({ queryKey: ['notifications-count'] }),
      ]);
      setBusy(false);
    }
  };
  const unreadIds = list.data?.filter((item) => !item.read_at).map((item) => item.id) ?? [];
  return (
    <Dialog.Root open={open} onOpenChange={setOpen} modal={false}>
      <Dialog.Trigger asChild>
        <button
          type="button"
          className="header-notifications"
          aria-label={unread ? `Уведомления: непрочитанных ${unread}` : 'Уведомления'}
        >
          <Bell size={20} aria-hidden="true" />
          {unread > 0 && (
            <span className="header-notifications-count" aria-hidden="true">
              {unread > 99 ? '99+' : unread}
            </span>
          )}
        </button>
      </Dialog.Trigger>
      <Dialog.Portal>
        <Dialog.Content className="notification-popover" aria-describedby={undefined}>
          <div className="notification-popover-header">
            <div>
              <Dialog.Title>Уведомления</Dialog.Title>
              <span>
                {count.isError
                  ? 'Счётчик недоступен'
                  : unread
                    ? `Непрочитанных: ${unread}`
                    : 'Нет новых уведомлений'}
              </span>
            </div>
            <Dialog.Close className="notification-popover-close" aria-label="Закрыть уведомления">
              <X size={19} />
            </Dialog.Close>
          </div>
          {list.isPending && (
            <p className="notification-popover-message" role="status">
              Загружаем уведомления…
            </p>
          )}
          {list.isError && (
            <div className="notification-popover-message" role="alert">
              Не удалось загрузить уведомления.{' '}
              <button type="button" onClick={() => void list.refetch()}>
                Повторить
              </button>
            </div>
          )}
          {error && (
            <p className="notification-popover-error" role="alert">
              {error}
            </p>
          )}
          {list.data?.length === 0 && (
            <p className="notification-popover-message">Уведомлений пока нет.</p>
          )}
          {list.data && list.data.length > 0 && (
            <>
              <div className="notification-popover-toolbar">
                <button
                  type="button"
                  disabled={busy || !unreadIds.length}
                  onClick={() => void markRead(unreadIds)}
                >
                  Прочитать показанные
                </button>
              </div>
              <div className="notification-popover-list">
                {list.data.map((item) => (
                  <article
                    className={`notification-popover-item${item.read_at ? '' : ' is-unread'}`}
                    key={item.id}
                  >
                    <div className="notification-popover-item-heading">
                      <strong>{item.title}</strong>
                      {!item.read_at && (
                        <span className="notification-unread-dot" aria-label="Не прочитано" />
                      )}
                    </div>
                    <p>{item.body}</p>
                    <time dateTime={item.created_at}>
                      {new Date(item.created_at).toLocaleString('ru-RU', {
                        day: 'numeric',
                        month: 'short',
                        hour: '2-digit',
                        minute: '2-digit',
                      })}
                    </time>
                    <div className="notification-popover-actions">
                      <Link to={item.link} onClick={() => setOpen(false)}>
                        Открыть
                      </Link>
                      {!item.read_at && (
                        <button
                          type="button"
                          disabled={busy}
                          onClick={() => void markRead([item.id])}
                        >
                          Отметить прочитанным
                        </button>
                      )}
                    </div>
                  </article>
                ))}
              </div>
            </>
          )}
          <Link
            className="notification-popover-footer"
            to="/notifications"
            onClick={() => setOpen(false)}
          >
            Все уведомления
          </Link>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

export default function ProtectedLayout() {
  const { state, session } = useSession();
  if (state.status === 'checking')
    return (
      <main className="content">
        <AsyncState state="loading" title="Открываем ваше пространство" />
      </main>
    );
  if (state.status === 'unavailable')
    return (
      <main className="content">
        <AsyncState
          state="error"
          title="Проверка сессии недоступна"
          message={state.message}
          onRetry={() => {
            void session?.bootstrap();
          }}
        />
      </main>
    );
  if (state.status === 'anonymous') return <Navigate to="/login" replace />;
  return (
    <AppShell
      user={state.user}
      notificationControl={<NotificationControl />}
      onLogout={() => (session ? session.logout() : Promise.resolve())}
      onEnterAdmin={async (target) => {
        if (!session) throw new Error('Сессия недоступна.');
        const accessToken = await session.refresh();
        await enterBackoffice(
          target,
          accessToken,
          window.fetch.bind(window),
          readCsrfCookie,
          (url) => window.location.assign(url),
        );
      }}
    >
      <Outlet />
    </AppShell>
  );
}
