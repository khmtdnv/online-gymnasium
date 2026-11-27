import * as Dialog from '@radix-ui/react-dialog';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { ArrowRight, Bell, CheckCheck, X } from 'lucide-react';
import { useState } from 'react';
import { Link, Navigate, Outlet } from 'react-router';
import { AppShell } from '../components/app-shell';
import { AsyncState } from '../components/async-state';
import { enterBackoffice, readCsrfCookie } from '../features/auth/backoffice-sso';
import { useSession } from '../features/auth/session-context';
import { NotificationRow, NotificationsEmpty } from '../features/notifications/notification-row';
import { useFeatures } from '../lib/api/context';

function NotificationControl() {
  const { notifications } = useFeatures();
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [tab, setTab] = useState<'all' | 'unread'>('all');
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
  const all = list.data ?? [];
  const unreadIds = all.filter((item) => !item.read_at).map((item) => item.id);
  const items = tab === 'unread' ? all.filter((item) => !item.read_at) : all;
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
            <div className="notification-popover-heading">
              <span className="notification-popover-emblem" aria-hidden="true">
                <Bell size={17} />
              </span>
              <Dialog.Title>Уведомления</Dialog.Title>
              {count.isError ? (
                <span className="notif-badge is-muted">счётчик недоступен</span>
              ) : (
                <span className={`notif-badge${unread ? '' : ' is-muted'}`}>
                  {unread ? `${unread} новых` : 'нет новых'}
                </span>
              )}
            </div>
            <div className="notification-popover-tools">
              <button
                type="button"
                className="notification-popover-mark-all"
                disabled={busy || !unreadIds.length}
                onClick={() => void markRead(unreadIds)}
              >
                <CheckCheck size={15} aria-hidden="true" />
                Отметить все как прочитанные
              </button>
              <Dialog.Close className="notification-popover-close" aria-label="Закрыть уведомления">
                <X size={18} aria-hidden="true" />
              </Dialog.Close>
            </div>
          </div>
          <div className="notif-tabs">
            <button
              type="button"
              aria-pressed={tab === 'all'}
              className={tab === 'all' ? 'is-active' : ''}
              onClick={() => setTab('all')}
            >
              Все{list.data ? ` (${all.length})` : ''}
            </button>
            <button
              type="button"
              aria-pressed={tab === 'unread'}
              className={tab === 'unread' ? 'is-active' : ''}
              onClick={() => setTab('unread')}
            >
              Непрочитанные{unreadIds.length ? ` (${unreadIds.length})` : ''}
            </button>
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
          {list.data && items.length === 0 && <NotificationsEmpty compact />}
          {items.length > 0 && (
            <div className="notification-popover-list">
              {items.map((item) => (
                <NotificationRow
                  key={item.id}
                  item={item}
                  busy={busy}
                  onMarkRead={(id) => void markRead([id])}
                  onOpen={() => setOpen(false)}
                />
              ))}
            </div>
          )}
          <div className="notification-popover-footer">
            <Link to="/notifications" onClick={() => setOpen(false)}>
              Все уведомления и архив
              <ArrowRight size={15} aria-hidden="true" />
            </Link>
            <Dialog.Close className="notification-popover-esc">Закрыть (Esc)</Dialog.Close>
          </div>
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
