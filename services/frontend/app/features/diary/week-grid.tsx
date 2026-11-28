import { addSchoolDays, formatSchoolDay, schoolTime } from '../schedule/school-dates';
import type { DiaryLessonSlot, DiaryWeek } from './api';
import { absenceReasonLabel, gradeKindLabel, homeworkStatusLabel } from './labels';

const WEEKDAY_NAMES = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб'] as const;

/** Сетка недели дневника: шесть школьных дней от понедельника week_start. */
export function WeekGrid({ week }: { week: DiaryWeek }) {
  const days = Array.from({ length: 6 }, (_, index) => {
    const date = addSchoolDays(week.week_start, index);
    return {
      date,
      weekday: WEEKDAY_NAMES[index],
      lessons: week.lessons.filter((lesson) => lesson.date === date),
    };
  });
  return (
    <div className="diary-grid" data-testid="diary-grid">
      {days.map((day) => (
        <DayColumn key={day.date} {...day} />
      ))}
    </div>
  );
}

function DayColumn({
  date,
  weekday,
  lessons,
}: {
  date: string;
  weekday: string;
  lessons: DiaryLessonSlot[];
}) {
  return (
    <div className="diary-day" data-date={date}>
      <h3 className="diary-day-header">
        {weekday} {formatSchoolDay(date)}
      </h3>
      {lessons.length === 0 && <p className="diary-empty">Нет уроков</p>}
      {lessons.map((lesson) => (
        <LessonRow key={lesson.lesson_id} lesson={lesson} />
      ))}
    </div>
  );
}

function LessonRow({ lesson }: { lesson: DiaryLessonSlot }) {
  if (lesson.status === 'canceled') {
    return (
      <div
        className="diary-lesson diary-lesson-cancelled"
        data-testid={`lesson-${lesson.lesson_id}`}
      >
        <span className="diary-lesson-time">{schoolTime(lesson.starts_at)}</span>
        <span>Урок отменён</span>
      </div>
    );
  }
  return (
    <div className="diary-lesson" data-testid={`lesson-${lesson.lesson_id}`}>
      <span className="diary-lesson-time">{schoolTime(lesson.starts_at)}</span>
      <div className="diary-lesson-body">
        {lesson.grades.length > 0 && (
          <div className="diary-grades">
            {lesson.grades.map(([grade, kind], index) => (
              <span key={index} className={`diary-grade grade-${grade}`}>
                {grade} <small>({gradeKindLabel[kind]})</small>
              </span>
            ))}
          </div>
        )}
        {lesson.attendance !== 'present' && (
          <span className={`diary-attendance attendance-${lesson.attendance}`}>
            {lesson.attendance === 'absent' ? 'не был' : 'не отмечено'}
            {lesson.absence_reason && ` (${absenceReasonLabel[lesson.absence_reason]})`}
          </span>
        )}
        {lesson.homework_status && (
          <span className={`diary-homework homework-${lesson.homework_status}`}>
            {homeworkStatusLabel[lesson.homework_status]}
            {lesson.homework_grade != null && ` — ${lesson.homework_grade}`}
          </span>
        )}
      </div>
    </div>
  );
}
