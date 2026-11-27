import { useQuery } from '@tanstack/react-query';
import { PenLine } from 'lucide-react';
import { Link } from 'react-router';
import { useSession } from '../auth/session-context';
import { useFeatures } from '../../lib/api/context';
import { displayHomeworkDescription } from '../homework/display-description';
import {
  schoolDay,
  schoolTime,
  schoolWeek,
} from '../schedule/school-dates';
import { matchPeriod } from '../schedule/school-periods';
import {
  dayTitle,
  isLessonRunning,
  lessonCountdown,
  nearestLesson,
  pluralRu,
  shortSchoolStamp,
} from './student-day';

/** Инициалы ученика для аватара очереди: «Иванов Артём» → «ИА». */
function initialsOf(name: string): string {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((word) => word[0])
    .join('')
    .toUpperCase();
}

export function TeacherDay() {
  const { state } = useSession();
  const { schedule, homework } = useFeatures();
  const today = schoolDay();
  const week = schoolWeek(today);
  const lessons = useQuery({
    queryKey: ['my-schedule', week],
    queryFn: ({ signal }) => schedule.getMySchedule(week, signal),
  });
  const reviews = useQuery({
    queryKey: ['teacher-reviews-preview'],
    queryFn: ({ signal }) => homework.listTeacherReviews(0, signal),
  });
  const todayLessons = lessons.data?.days.find((day) => day.date === today)?.lessons ?? [];
  const periods = lessons.data?.periods ?? [];
  const active = nearestLesson(todayLessons);
  const activeRunning = active ? isLessonRunning(active) : false;
  const submitted = reviews.data?.items.filter((item) => item.status === 'submitted') ?? [];
  const plannedCount = todayLessons.filter((lesson) => lesson.status !== 'canceled').length;
  const user = state.status === 'authenticated' ? state.user : null;
  const teacherName = [user?.first_name, user?.middle_name].filter(Boolean).join(' ');

  const lessonNumber = (lesson: { starts_at: string; ends_at: string }) =>
    matchPeriod(lesson.starts_at, lesson.ends_at, periods)?.number;

  return (
    <div className="day-sheet">
      <header className="day-heading">
        <div className="day-heading-main">
          <span className="day-kicker">Кабинет преподавателя · UTC+5 (Екатеринбург)</span>
          <h1>Сегодня</h1>
          <p className="day-date">{dayTitle(today)}</p>
          {teacherName && <p className="day-greeting">Здравствуйте, {teacherName}</p>}
          <p className="day-sub">
            {lessons.data &&
              (plannedCount
                ? `${pluralRu(plannedCount, 'урок', 'урока', 'уроков')} сегодня`
                : 'уроков сегодня нет')}
            {reviews.data &&
              submitted.length > 0 &&
              ` · в очереди проверки ${
                reviews.data.next_cursor
                  ? `больше ${submitted.length}`
                  : pluralRu(submitted.length, 'работа', 'работы', 'работ')
              }`}
          </p>
        </div>
        <div className="day-heading-actions">
          <Link className="button button-secondary" to="/homework">
            Выдать домашнее задание
          </Link>
          <Link className="button button-secondary" to="/schedule">
            Расписание недели
          </Link>
        </div>
      </header>
      <div className="day-grid">
        <section className="day-panel">
          <div className="day-panel-head">
            <h2>Мои уроки на сегодня</h2>
            <span className="day-panel-note">
              {lessons.data && todayLessons.length > 0
                ? `Всего ${pluralRu(todayLessons.length, 'урок', 'урока', 'уроков')}`
                : null}
            </span>
          </div>
          {lessons.isPending && <p role="status">Загружаем расписание…</p>}
          {lessons.isError && <p role="alert">Не удалось загрузить расписание.</p>}
          {lessons.data && !todayLessons.length && <p>На сегодня уроков нет.</p>}
          {active && activeRunning && (
            <article className="day-active-lesson" aria-label="Текущий урок">
              <div className="day-active-head">
                <span className="day-hero-time">
                  {schoolTime(active.starts_at)} — {schoolTime(active.ends_at)}
                </span>
                <span className="day-live is-block">
                  <span className="day-live-dot" aria-hidden="true" />
                  {lessonCountdown(active)}
                </span>
              </div>
              <h3>
                {active.subject_name} <small>{active.class_name}</small>
              </h3>
              <div className="day-hero-actions">
                <Link className="button button-primary" to={`/lessons/${active.id}`}>
                  Войти в урок
                </Link>
                <Link className="button button-secondary" to={`/pen/lessons/${active.id}`}>
                  <PenLine size={16} aria-hidden="true" />
                  Умная ручка
                </Link>
              </div>
            </article>
          )}
          <div className="day-timeline">
            {todayLessons.map((lesson) => {
              const number = lessonNumber(lesson);
              return (
                <Link
                  className={`day-lesson${lesson.status === 'canceled' ? ' is-canceled' : ''}${
                    active && lesson.id === active.id ? ' is-focus' : ''
                  }`}
                  key={lesson.id}
                  to={`/lessons/${lesson.id}`}
                  data-subject={lesson.subject_name}
                >
                  <span className="day-lesson-time">
                    <b>
                      {schoolTime(lesson.starts_at)}–{schoolTime(lesson.ends_at)}
                    </b>
                    {number ? <small>Урок {number}</small> : null}
                  </span>
                  <span className="day-lesson-body">
                    <span className="day-lesson-title">
                      <strong>{lesson.subject_name}</strong>
                      {isLessonRunning(lesson) && (
                        <span className="day-live">
                          <span className="day-live-dot" aria-hidden="true" />
                          Сейчас
                        </span>
                      )}
                    </span>
                    <small>{lesson.class_name}</small>
                  </span>
                  <span
                    className={`day-lesson-open${lesson.status === 'canceled' ? ' is-canceled-status' : ''}`}
                  >
                    {lesson.status === 'canceled' ? 'Отменён' : 'Открыть урок'}
                  </span>
                </Link>
              );
            })}
          </div>
        </section>
        <aside className="day-side">
          <section className="day-panel">
            <div className="day-panel-head">
              <h2>Очередь проверки</h2>
              <Link to="/homework">
                Все работы
                {reviews.data && submitted.length > 0
                  ? ` (${submitted.length}${reviews.data.next_cursor ? '+' : ''})`
                  : ''}
              </Link>
            </div>
            {reviews.isPending && <p role="status">Загружаем работы…</p>}
            {reviews.isError && <p role="alert">Не удалось загрузить работы.</p>}
            {reviews.data && !submitted.length && (
              <p>
                {reviews.data.next_cursor
                  ? 'В первых записях работ на проверке нет. Посмотрите полный список.'
                  : 'Нет работ на проверке.'}
              </p>
            )}
            <div className="day-queue">
              {submitted.slice(0, 4).map((item) => (
                <Link
                  className="day-queue-item"
                  key={item.answer_id}
                  to={`/homework?answer=${item.answer_id}&homework=${item.homework_id}`}
                >
                  <span className="day-avatar" aria-hidden="true">
                    {initialsOf(item.student_name)}
                  </span>
                  <span className="day-queue-body">
                    <strong>{item.student_name}</strong>
                    <small>
                      {item.class_name} · {item.subject_name}
                    </small>
                    <span>{displayHomeworkDescription(item.description)}</span>
                  </span>
                  <span className="day-queue-side">
                    <time dateTime={item.submitted_at}>
                      {shortSchoolStamp(item.submitted_at)}
                    </time>
                    <span className="day-queue-action">Проверить</span>
                  </span>
                </Link>
              ))}
            </div>
            {reviews.data?.next_cursor && submitted.length > 0 && (
              <p className="day-queue-more">
                Показаны первые работы. Остальные — по ссылке «Все работы».
              </p>
            )}
          </section>
        </aside>
      </div>
    </div>
  );
}
