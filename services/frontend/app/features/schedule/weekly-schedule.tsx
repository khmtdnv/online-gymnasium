import { useState } from 'react';
import { Button } from '../../components/ui/button';
import type { ScheduleDay } from './my-schedule-api';
import { LessonCard } from './lesson-card';
import { addSchoolDays, formatSchoolDay, schoolDay, schoolWeek } from './school-dates';
export function WeeklySchedule({
  weekStart,
  days,
  onWeekChange,
  timezone,
  loading = false,
  failed = false,
}: {
  weekStart: string;
  days: ScheduleDay[];
  onWeekChange: (day: string) => void;
  timezone: string;
  loading?: boolean;
  failed?: boolean;
}) {
  const today = schoolDay();
  const initial = days.some((day) => day.date === today) ? today : weekStart;
  const [selected, setSelected] = useState(initial);
  const selectedDay = days.some((day) => day.date === selected) ? selected : initial;
  return (
    <section className="weekly-schedule" aria-label="Расписание на неделю" aria-busy={loading}>
      <div className="calendar-toolbar">
        <div className="calendar-period">
          <Button
            variant="secondary"
            aria-label="Предыдущая неделя"
            onClick={() => onWeekChange(addSchoolDays(weekStart, -7))}
          >
            ←
          </Button>
          <h2>
            {formatSchoolDay(weekStart)} —{' '}
            {formatSchoolDay(addSchoolDays(weekStart, 5), { year: 'numeric' })}
          </h2>
          <Button
            variant="secondary"
            aria-label="Следующая неделя"
            onClick={() => onWeekChange(addSchoolDays(weekStart, 7))}
          >
            →
          </Button>
        </div>
        <Button variant="secondary" onClick={() => onWeekChange(schoolWeek(today))}>
          Сегодня
        </Button>
      </div>
      <p className="calendar-timezone">Время школы · {timezone} (UTC+5)</p>
      <div className="week-day-tabs" role="tablist" aria-label="Дни недели">
        {days.map((day, index) => (
          <button
            type="button"
            key={day.date}
            role="tab"
            aria-selected={selectedDay === day.date}
            aria-controls={`calendar-${day.date}`}
            tabIndex={selectedDay === day.date ? 0 : -1}
            data-day={day.date}
            onClick={() => setSelected(day.date)}
            onKeyDown={(event) => {
              let next: number | undefined;
              if (event.key === 'ArrowRight') next = (index + 1) % days.length;
              if (event.key === 'ArrowLeft') next = (index + days.length - 1) % days.length;
              if (event.key === 'Home') next = 0;
              if (event.key === 'End') next = days.length - 1;
              if (next === undefined) return;
              event.preventDefault();
              setSelected(days[next].date);
              event.currentTarget.parentElement
                ?.querySelector<HTMLButtonElement>(`[data-day="${days[next].date}"]`)
                ?.focus();
            }}
          >
            <span>
              {formatSchoolDay(day.date, { weekday: 'short', month: undefined, day: undefined })}
            </span>
            <strong>{Number(day.date.slice(-2))}</strong>
          </button>
        ))}
      </div>
      {!loading && !failed && (
        <div className="week-grid">
          {days.map((day) => (
            <section
              id={`calendar-${day.date}`}
              key={day.date}
              className={`week-day${day.date === today ? ' is-today' : ''}${day.date === selectedDay ? ' is-selected' : ''}`}
              aria-labelledby={`heading-${day.date}`}
            >
              <header>
                <h2 id={`heading-${day.date}`}>
                  {formatSchoolDay(day.date, { weekday: 'long', month: undefined, day: undefined })}
                </h2>
                <span>{formatSchoolDay(day.date)}</span>
                {day.date === today && <span className="week-today-label">Сегодня</span>}
              </header>
              <div className="day-lessons">
                {day.lessons.map((lesson) => (
                  <LessonCard key={lesson.id} lesson={lesson} />
                ))}
                {!day.lessons.length && <p className="empty-school-day">Уроков нет</p>}
              </div>
            </section>
          ))}
        </div>
      )}
    </section>
  );
}
