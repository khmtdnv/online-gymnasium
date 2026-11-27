import { Clock3, Pencil, Plus, X } from 'lucide-react';
import { Button } from '../../components/ui/button';
import type { Lesson } from '../../lib/api/contracts';
import type { SchoolPeriod } from './school-periods';
import { splitByPeriods } from './school-periods';
import { utcTime } from './utc';

export function LessonList({
  lessons,
  periods,
  onEdit,
  onCancel,
  onCreateAtPeriod,
}: {
  lessons: Lesson[];
  periods: SchoolPeriod[];
  onEdit: (lesson: Lesson) => void;
  onCancel: (lesson: Lesson) => void;
  onCreateAtPeriod?: (period: SchoolPeriod) => void;
}) {
  const sorted = [...lessons].sort((a, b) => Date.parse(a.starts_at) - Date.parse(b.starts_at));
  // Без справочника периодов (сбой directory) показываем простой список по времени.
  if (!periods.length)
    return (
      <div className="lesson-list">
        {sorted.map((lesson) => (
          <LessonRow key={lesson.id} lesson={lesson} onEdit={onEdit} onCancel={onCancel} />
        ))}
      </div>
    );
  const { byPeriod, offGrid } = splitByPeriods(sorted, periods);
  return (
    <div className="lesson-list">
      {periods.map((period) => {
        const rows = byPeriod.get(period.number) ?? [];
        return (
          <div className="lesson-period" key={period.number} data-period={period.number}>
            <div className="lesson-period-head">
              <strong>{period.number}-й урок</strong>
              <span>
                {period.start_at}–{period.end_at} · школа
              </span>
            </div>
            {rows.map((lesson) => (
              <LessonRow key={lesson.id} lesson={lesson} onEdit={onEdit} onCancel={onCancel} />
            ))}
            {rows.length === 0 && onCreateAtPeriod && (
              <button
                type="button"
                className="lesson-cell-empty"
                aria-label={`Создать урок в периоде ${period.number}`}
                onClick={() => onCreateAtPeriod(period)}
              >
                <Plus size={15} aria-hidden="true" />
                Создать урок
              </button>
            )}
          </div>
        );
      })}
      {offGrid.length > 0 && (
        <div className="lesson-period lesson-period--offgrid">
          <div className="lesson-period-head">
            <strong>Вне сетки</strong>
            <span>время сохранено</span>
          </div>
          {offGrid.map((lesson) => (
            <LessonRow
              key={lesson.id}
              lesson={lesson}
              offGrid
              onEdit={onEdit}
              onCancel={onCancel}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function LessonRow({
  lesson,
  offGrid = false,
  onEdit,
  onCancel,
}: {
  lesson: Lesson;
  offGrid?: boolean;
  onEdit: (lesson: Lesson) => void;
  onCancel: (lesson: Lesson) => void;
}) {
  return (
    <article className={`card lesson-card${offGrid ? ' lesson-card--offgrid' : ''}`}>
      <div className="lesson-time">
        {utcTime(lesson.starts_at)}
        <small>{utcTime(lesson.ends_at)} · UTC</small>
      </div>
      <div className="lesson-details">
        <h3>Предмет · ID {lesson.subject_id}</h3>
        {offGrid && <p className="lesson-offgrid">вне сетки</p>}
        <p>
          Учитель · ID {lesson.teacher_id} / Класс · ID {lesson.class_id}
        </p>
        <p>
          <Clock3 size={14} aria-hidden="true" style={{ display: 'inline' }} />{' '}
          {Math.round((Date.parse(lesson.ends_at) - Date.parse(lesson.starts_at)) / 60000)} мин ·
          урок {lesson.id} · версия {lesson.version}
        </p>
      </div>
      <div className="lesson-actions">
        <Button
          variant="secondary"
          onClick={() => onEdit(lesson)}
          aria-label={`Перенести урок ${lesson.id}`}
        >
          <Pencil size={17} aria-hidden="true" />
          Перенести
        </Button>
        <Button
          variant="ghost"
          onClick={() => onCancel(lesson)}
          aria-label={`Отменить урок ${lesson.id}`}
        >
          <X size={18} aria-hidden="true" />
          Отменить
        </Button>
      </div>
    </article>
  );
}
