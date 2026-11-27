import { useMemo, type PointerEvent } from 'react';
import { Button } from '../../components/ui/button';
import { usePen, type PenConnectionStatus } from './use-pen';

/** SVG — только холст симулятора; сами точки нормализованы и хранятся на сервере. */
const CONNECTION_LABELS: Record<PenConnectionStatus, string> = {
  online: 'Подключено',
  connecting: 'Подключаем',
  offline: 'Нет связи',
  failure: 'Ошибка связи',
};

/** Очередь несохранённых пачек: 0 — всё на сервере (макет s06 «Синхронизировано»). */
function queueLabel(queue: number) {
  if (queue >= 50) return 'Очередь заполнена';
  if (queue === 0) return 'Синхронизировано (0 в очереди)';
  return `Сохраняем (${queue} в очереди)`;
}

export function PenCanvas({
  lessonId,
  studentId,
  readonly,
}: {
  lessonId: number;
  studentId: string;
  readonly: boolean;
}) {
  const pen = usePen(lessonId, studentId, readonly);
  const strokes = useMemo(() => {
    const result = new Map<string, string[]>();
    for (const batch of pen.batches) {
      const points = result.get(batch.stroke_id) ?? [];
      points.push(...batch.points.map((point) => `${point.x * 1000},${point.y * 600}`));
      result.set(batch.stroke_id, points);
    }
    return [...result.entries()];
  }, [pen.batches]);
  function point(event: PointerEvent<SVGSVGElement>) {
    const box = event.currentTarget.getBoundingClientRect();
    return {
      x: Math.min(1, Math.max(0, (event.clientX - box.left) / box.width)),
      y: Math.min(1, Math.max(0, (event.clientY - box.top) / box.height)),
    };
  }
  const queueTone = pen.queue >= 50 ? ' pen-queue--full' : pen.queue > 0 ? ' pen-queue--busy' : '';
  return (
    <section className="workspace-panel pen-workspace">
      <div className="pen-workspace-heading">
        <div>
          <span className="workspace-kicker">Рабочая область</span>
          <h2>{readonly ? 'Записи ученика' : 'Мои записи'}</h2>
        </div>
        <div className="pen-status-panel">
          <span className={`pen-status pen-status--${pen.status}`}>
            <span className="pen-status-dot" aria-hidden="true" />
            {CONNECTION_LABELS[pen.status]}
          </span>
          {readonly ? (
            <span className="pen-queue">Только просмотр</span>
          ) : (
            <span className={`pen-queue${queueTone}`}>{queueLabel(pen.queue)}</span>
          )}
        </div>
      </div>
      <p className="pen-workspace-hint">
        {readonly
          ? 'Режим преподавателя: рисунок ученика, только просмотр.'
          : 'Пишите мышью, пальцем или стилусом. Не закрывайте вкладку, пока штрихи сохраняются.'}
      </p>
      <svg
        role="img"
        aria-label="Холст умной ручки"
        viewBox="0 0 1000 600"
        preserveAspectRatio="none"
        className="pen-writing-surface"
        style={{
          width: '100%',
          height: 'min(55vh, 500px)',
          minHeight: 240,
          touchAction: readonly ? 'auto' : 'none',
          cursor: readonly ? 'default' : 'crosshair',
        }}
        onPointerDown={(event) => {
          if (readonly || !pen.ready || !event.isPrimary || event.button !== 0) return;
          event.currentTarget.setPointerCapture(event.pointerId);
          pen.start(point(event));
        }}
        onPointerMove={(event) => {
          if (event.isPrimary && event.buttons) pen.move(point(event));
        }}
        onPointerUp={() => pen.end()}
        onPointerCancel={() => pen.end()}
        onLostPointerCapture={() => pen.end()}
      >
        <title>
          {readonly ? 'Сохранённые штрихи ученика' : 'Учебная страница для рукописных штрихов'}
        </title>
        {strokes.map(([id, points]) => (
          <polyline
            key={id}
            points={points.join(' ')}
            fill="none"
            className="pen-stroke"
            strokeWidth="3"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        ))}
      </svg>
      <div className="pen-workspace-footer">
        <div>
          <p className="pen-connection" role="status" aria-live="polite">
            {pen.message}
          </p>
          <p className="pen-autosave-note">
            Штрихи сохраняются на сервере этого урока. Симулятор не распознаёт рукописный текст.
          </p>
        </div>
        <Button variant="secondary" onClick={pen.reconnect}>
          Переподключить
        </Button>
      </div>
    </section>
  );
}
