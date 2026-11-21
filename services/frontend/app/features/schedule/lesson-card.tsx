import { Link } from 'react-router';
import type { LessonCardData } from './my-schedule-api';
import { schoolTime } from './school-dates';
export function LessonCard({
  lesson,
  compact = false,
}: {
  lesson: LessonCardData;
  compact?: boolean;
}) {
  return (
    <Link
      to={`/lessons/${lesson.id}`}
      data-subject={lesson.subject_name}
      className={`calendar-lesson${compact ? ' calendar-lesson--compact' : ''}${
        lesson.status === 'canceled' ? ' is-canceled' : ''
      }`}
    >
      <span className="lesson-time">
        {schoolTime(lesson.starts_at)}–{schoolTime(lesson.ends_at)}
      </span>
      <h3>{lesson.subject_name}</h3>
      <span className="lesson-class">{lesson.class_name}</span>
      <span className="lesson-teacher">{lesson.teacher_name}</span>
      {lesson.status === 'canceled' ? (
        <span className="lesson-canceled">Урок отменён</span>
      ) : (
        <span className="lesson-open">Открыть урок и ДЗ →</span>
      )}
    </Link>
  );
}
