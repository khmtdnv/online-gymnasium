import { Clock3 } from 'lucide-react';
import type { ClassDailyWorkload } from '../../lib/api/contracts';
import { utcDateTime } from '../schedule/utc';

export function WorkloadCard({ workload }: { workload: ClassDailyWorkload }) {
  return (
    <section className="card">
      <span className="badge">Класс · ID {workload.class_id}</span>
      <h2 className="section-title">Нагрузка на {workload.day}</h2>
      <div className="metric-grid">
        <div className="metric">
          <strong>{workload.planned_lessons_count}</strong>
          <span>Плановых уроков</span>
        </div>
        <div className="metric">
          <strong>{workload.planned_minutes}</strong>
          <span>Плановых минут</span>
        </div>
      </div>
      <p>
        <Clock3 size={17} aria-hidden="true" style={{ display: 'inline' }} /> Пересчитано:{' '}
        {utcDateTime(workload.refreshed_at)}
      </p>
      <p className="field-hint">
        Расчёт обновляется примерно раз в минуту. Кнопка «Обновить» читает результат, а не запускает
        пересчёт.
      </p>
    </section>
  );
}
