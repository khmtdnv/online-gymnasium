import { useMemo, type PointerEvent } from 'react';
import { Button } from '../../components/ui/button';
import { usePen } from './use-pen';

/** SVG — только холст симулятора; сами точки нормализованы и хранятся на сервере. */
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
  return (
    <section className="card">
      <p role="status" aria-live="polite">
        {pen.message}
      </p>
      <p>
        {readonly
          ? 'Режим преподавателя: рисунок ученика, только просмотр.'
          : 'Пишите мышью, пальцем или стилусом. Не закрывайте вкладку, пока штрихи сохраняются.'}
      </p>
      <svg
        role="img"
        aria-label="Холст умной ручки"
        viewBox="0 0 1000 600"
        preserveAspectRatio="none"
        style={{
          width: '100%',
          height: 'min(55vh, 500px)',
          minHeight: 240,
          background: '#fff',
          border: '1px solid #9caea8',
          borderRadius: 16,
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
            stroke="#203e38"
            strokeWidth="3"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        ))}
      </svg>
      <Button variant="secondary" onClick={pen.reconnect}>
        Переподключить
      </Button>
      <p className="muted">
        Штрихи сохраняются для этого урока. Симулятор не распознаёт рукописный текст.
      </p>
    </section>
  );
}
