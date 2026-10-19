import { Clock3, Pencil, X } from 'lucide-react';
import { Button } from '../../components/ui/button';
import type { Lesson } from '../../lib/api/contracts';
import { utcTime } from './utc';

export function LessonList({
  lessons,
  onEdit,
  onCancel,
}: {
  lessons: Lesson[];
  onEdit: (lesson: Lesson) => void;
  onCancel: (lesson: Lesson) => void;
}) {
  return (
    <div className="lesson-list">
      {[...lessons]
        .sort((a, b) => Date.parse(a.starts_at) - Date.parse(b.starts_at))
        .map((lesson) => (
          <article className="card lesson-card" key={lesson.id}>
            <div className="lesson-time">
              {utcTime(lesson.starts_at)}
              <small>{utcTime(lesson.ends_at)} · UTC</small>
            </div>
            <div className="lesson-details">
              <h3>Предмет · ID {lesson.subject_id}</h3>
              <p>
                Учитель · ID {lesson.teacher_id} / Класс · ID {lesson.class_id}
              </p>
              <p>
                <Clock3 size={14} aria-hidden="true" style={{ display: 'inline' }} />{' '}
                {Math.round((Date.parse(lesson.ends_at) - Date.parse(lesson.starts_at)) / 60000)}{' '}
                мин · урок {lesson.id} · версия {lesson.version}
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
        ))}
    </div>
  );
}
