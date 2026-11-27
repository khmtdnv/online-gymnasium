import { ArrowRight, CheckCheck } from 'lucide-react';
import { Link } from 'react-router';

/** Категория выводится из реальной ссылки уведомления; отдельного поля в API нет. */
export function notificationCategory(link: string): string {
  if (link.startsWith('/billing')) return 'Оплата';
  if (link.startsWith('/homework')) return 'Домашние задания';
  if (link.startsWith('/documents')) return 'Документы';
  return 'Уведомление';
}

/** «Сегодня, 09:12» / «Вчера, 18:30» / «22 ноя, 15:40» — местное время браузера. */
export function formatNotificationTime(iso: string): string {
  const date = new Date(iso);
  const now = new Date();
  const sameDay = (a: Date, b: Date) =>
    a.getFullYear() === b.getFullYear() &&
    a.getMonth() === b.getMonth() &&
    a.getDate() === b.getDate();
  const time = date.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' });
  if (sameDay(date, now)) return `Сегодня, ${time}`;
  const yesterday = new Date(now);
  yesterday.setDate(now.getDate() - 1);
  if (sameDay(date, yesterday)) return `Вчера, ${time}`;
  const day = date
    .toLocaleDateString('ru-RU', { day: 'numeric', month: 'short' })
    .replace('нояб.', 'ноя')
    .replace('.', '');
  return `${day}, ${time}`;
}

export interface NotificationRowData {
  id: number;
  title: string;
  body: string;
  link: string;
  created_at: string;
  read_at: string | null;
}

/** Строка уведомления по макету g02: точка, категория, время, заголовок и действия. */
export function NotificationRow({
  item,
  busy,
  onMarkRead,
  onOpen,
}: {
  item: NotificationRowData;
  busy: boolean;
  onMarkRead: (id: number) => void;
  onOpen?: () => void;
}) {
  return (
    <article className={`notif-item${item.read_at ? '' : ' is-unread'}`}>
      <span className="notif-dot" aria-hidden="true">
        {!item.read_at && <span className="notif-dot-core" />}
      </span>
      <div className="notif-item-body">
        <div className="notif-item-meta">
          <span className="notif-chip">{notificationCategory(item.link)}</span>
          <time dateTime={item.created_at}>{formatNotificationTime(item.created_at)}</time>
        </div>
        <h3>{item.title}</h3>
        <p>{item.body}</p>
        <div className="notif-item-actions">
          <Link className="notif-open" to={item.link} onClick={onOpen}>
            Открыть
            <ArrowRight size={15} aria-hidden="true" />
          </Link>
          {!item.read_at && (
            <button type="button" disabled={busy} onClick={() => onMarkRead(item.id)}>
              Отметить прочитанным
            </button>
          )}
        </div>
      </div>
    </article>
  );
}

/** Пустое состояние «Все прочитано» из спецификации пустой панели g02. */
export function NotificationsEmpty({ compact = false }: { compact?: boolean }) {
  return (
    <div className={`notif-empty${compact ? ' is-compact' : ''}`} aria-live="polite">
      <span className="notif-empty-icon" aria-hidden="true">
        <CheckCheck size={26} />
      </span>
      <h3>Все прочитано</h3>
      <p>Новых уведомлений нет. Задания и оценки ищите в журнале.</p>
    </div>
  );
}
