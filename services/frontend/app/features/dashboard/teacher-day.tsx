import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router';
import { useFeatures } from '../../lib/api/context';
import { formatSchoolDay, schoolDay, schoolTime, schoolWeek } from '../schedule/school-dates';
import { displayHomeworkDescription } from '../homework/display-description';

export function TeacherDay() {
  const { schedule, homework } = useFeatures();
  const today = schoolDay();
  const week = schoolWeek(today);
  const lessons = useQuery({
    queryKey: ['my-schedule', week],
    queryFn: ({ signal }) => schedule.getMySchedule(week, signal),
  });
  const todayLessons = lessons.data?.days.find((day) => day.date === today)?.lessons ?? [];
  const reviews = useQuery({
    queryKey: ['teacher-reviews-preview'],
    queryFn: ({ signal }) => homework.listTeacherReviews(0, signal),
  });

  return (
    <div className="student-day">
      <header className="student-day-heading">
        <div>
          <span className="eyebrow">Кабинет преподавателя</span>
          <h1>Сегодня</h1>
          <p>{formatSchoolDay(today, { weekday: 'long', year: 'numeric' })}</p>
        </div>
      </header>
      <div className="student-day-grid">
        <section className="student-day-panel student-day-lessons">
          <div className="student-day-panel-heading">
            <div>
              <span className="student-day-kicker">Ваш день</span>
              <h2>Уроки сегодня</h2>
            </div>
            <Link to="/schedule">Вся неделя</Link>
          </div>
          {lessons.isPending && <p role="status">Загружаем расписание…</p>}
          {lessons.isError && <p role="alert">Не удалось загрузить расписание.</p>}
          {lessons.data && !todayLessons.length && <p>На сегодня уроков нет.</p>}
          <div className="student-day-list">
            {todayLessons.map((lesson) => (
              <Link className="student-day-lesson" key={lesson.id} to={`/lessons/${lesson.id}`}>
                <span className="student-day-time">
                  {schoolTime(lesson.starts_at)}–{schoolTime(lesson.ends_at)}
                </span>
                <span>
                  <strong>{lesson.subject_name}</strong>
                  <small>{lesson.class_name}</small>
                </span>
                <span
                  className={`student-day-open${lesson.status === 'canceled' ? ' is-canceled-status' : ''}`}
                >
                  {lesson.status === 'canceled' ? 'Отменён' : 'Открыть'}
                </span>
              </Link>
            ))}
          </div>
        </section>
        <aside className="student-day-side">
          <section className="student-day-panel">
            <div className="student-day-panel-heading">
              <h2>Работы на проверке</h2>
              <Link to="/homework">Все работы</Link>
            </div>
            {reviews.isPending && <p role="status">Загружаем работы…</p>}
            {reviews.isError && <p role="alert">Не удалось загрузить работы.</p>}
            {reviews.data && !reviews.data.items.some((item) => item.status === 'submitted') && (
              <p>
                {reviews.data.next_cursor
                  ? 'В первых записях работ на проверке нет. Посмотрите полный список.'
                  : 'Нет работ на проверке.'}
              </p>
            )}
            <div className="student-day-list">
              {reviews.data?.items
                .filter((item) => item.status === 'submitted')
                .slice(0, 3)
                .map((item) => (
                  <Link
                    className="student-day-item"
                    key={item.answer_id}
                    to={`/homework?answer=${item.answer_id}&homework=${item.homework_id}`}
                  >
                    <strong>{item.student_name}</strong>
                    <span>{displayHomeworkDescription(item.description)}</span>
                  </Link>
                ))}
            </div>
          </section>
        </aside>
      </div>
    </div>
  );
}
