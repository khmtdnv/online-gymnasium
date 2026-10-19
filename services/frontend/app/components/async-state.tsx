import { Inbox, LoaderCircle, TriangleAlert } from 'lucide-react';
import { Button } from './ui/button';

/** Пустая выборка, загрузка и ошибка не выглядят как один успешный результат. */
export function AsyncState({
  state,
  title,
  message,
  requestId,
  onRetry,
}: {
  state: 'loading' | 'empty' | 'error';
  title: string;
  message?: string;
  requestId?: string;
  onRetry?: () => void;
}) {
  const Icon = state === 'loading' ? LoaderCircle : state === 'error' ? TriangleAlert : Inbox;
  return (
    <section
      className="async-state"
      role={state === 'error' ? 'alert' : 'status'}
      aria-live="polite"
    >
      <Icon size={38} className={state === 'loading' ? 'spinner' : undefined} aria-hidden="true" />
      <h2>{title}</h2>
      {message && <p>{message}</p>}
      {requestId && <p className="request-id">ID запроса: {requestId}</p>}
      {onRetry && (
        <Button variant="secondary" onClick={onRetry}>
          Повторить
        </Button>
      )}
    </section>
  );
}
