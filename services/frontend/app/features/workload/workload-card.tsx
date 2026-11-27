import { Clock3 } from 'lucide-react';
import type { ClassDailyWorkload } from '../../lib/api/contracts';
import { utcDateTime } from '../schedule/utc';

function number(value: number) {
  return value.toLocaleString('ru-RU');
}

function hoursWord(hours: number) {
  const mod10 = hours % 10;
  const mod100 = hours % 100;
  if (mod10 === 1 && mod100 !== 11) return 'академический час';
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) return 'академических часа';
  return 'академических часов';
}

/* Макет a03 — визуальный ориентир: KPI-карточки с капс-меткой и крупным
   числом. Данные — только готовой дневной сводки Analytics; недельных
   показателей макета (СанПиН, дисциплины) у API нет, они не рисуются. */
export function WorkloadCard({ workload }: { workload: ClassDailyWorkload }) {
  const hours = Math.round((workload.planned_minutes / 45) * 10) / 10;
  return (
    <section className="workload-sheet" aria-label="Готовый расчёт нагрузки">
      <div className="workload-kpi-grid">
        <div className="workload-kpi">
          <span className="workload-kpi-label">Всего уроков</span>
          <strong className="workload-kpi-value">{number(workload.planned_lessons_count)}</strong>
          <span className="workload-kpi-note">плановых уроков в этот день</span>
        </div>
        <div className="workload-kpi">
          <span className="workload-kpi-label">Суммарная длительность</span>
          <strong className="workload-kpi-value">{number(workload.planned_minutes)}</strong>
          <span className="workload-kpi-note">
            минут · {hours.toLocaleString('ru-RU')} {hoursWord(hours)}
          </span>
        </div>
        <div className="workload-kpi workload-kpi--meta">
          <span className="workload-kpi-label">Сверка данных</span>
          <strong className="workload-kpi-time">
            <Clock3 size={17} aria-hidden="true" />
            <time dateTime={workload.refreshed_at}>{utcDateTime(workload.refreshed_at)}</time>
          </strong>
          <span className="workload-kpi-note">
            <span className="workload-dot" aria-hidden="true" /> Автоматический расчёт
          </span>
        </div>
      </div>
      <footer className="workload-sheet-meta">
        <span>
          Класс · ID {workload.class_id} · день {workload.day}
        </span>
        <span>
          «Обновить» читает последний готовый расчёт и не запускает новый пересчёт.
        </span>
      </footer>
    </section>
  );
}
