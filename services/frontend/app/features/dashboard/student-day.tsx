import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router';
import { useFeatures } from '../../lib/api/context';
import { displayHomeworkDescription } from '../homework/display-description';
import {
  addSchoolDays,
  formatSchoolDay,
  schoolDay,
  schoolDatetime,
  schoolTime,
  schoolWeek,
} from '../schedule/school-dates';

export function StudentDay() {
  const { schedule, homework } = useFeatures();
  const today = schoolDay();
  const week = schoolWeek(today);
  const lessons = useQuery({
    queryKey: ['my-schedule', week],
    queryFn: ({ signal }) => schedule.getMySchedule(week, signal),
  });
  const tasks = useQuery({
    queryKey: ['student-day-homework', today],
    queryFn: ({ signal }) =>
      homework.listMyHomework(today, addSchoolDays(today, 30), 'needs_action', 0, signal),
  });
  const todayLessons = lessons.data?.days.find((day) => day.date === today)?.lessons ?? [];

  return (
    <div className="student-day">
      <header className="student-day-heading">
        <div>
          <span className="eyebrow">Личный кабинет</span>
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
          {lessons.isError && (
            <p role="alert">
              Не удалось загрузить расписание. <Link to="/schedule">Открыть расписание</Link>
            </p>
          )}
          {lessons.data && !lessons.data.has_class && (
            <p>Вы пока не зачислены в класс. Обратитесь к сотруднику школы.</p>
          )}
          {lessons.data?.has_class && !todayLessons.length && (
            <div className="student-day-empty">
              <strong>На сегодня уроков нет</strong>
              <p>Посмотрите расписание на другие дни.</p>
              <Link to="/schedule">Открыть расписание</Link>
            </div>
          )}
          <div className="student-day-list">
            {todayLessons.map((lesson) => (
              <Link className="student-day-lesson" key={lesson.id} to={`/lessons/${lesson.id}`}>
                <span className="student-day-time">
                  {schoolTime(lesson.starts_at)}–{schoolTime(lesson.ends_at)}
                </span>
                <span>
                  <strong>{lesson.subject_name}</strong>
                  <small>
                    {lesson.teacher_name} · {lesson.class_name}
                  </small>
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
              <h2>Ближайшие задания</h2>
              <Link to="/homework">Все задания</Link>
            </div>
            {tasks.isPending && <p role="status">Загружаем задания…</p>}
            {tasks.isError && <p role="alert">Не удалось загрузить задания.</p>}
            {tasks.data && !tasks.data.items.length && <p>На ближайшие 30 дней заданий нет.</p>}
            <div className="student-day-list">
              {tasks.data?.items.slice(0, 3).map((task) => (
                <Link className="student-day-item" key={task.id} to={`/homework/${task.id}`}>
                  <strong>{task.subject_name}</strong>
                  <span>{displayHomeworkDescription(task.description)}</span>
                  <small>
                    {task.final_due_datetime
                      ? `Сдать до ${schoolDatetime(task.final_due_datetime)}`
                      : 'Срок сдачи не указан'}
                  </small>
                </Link>
              ))}
            </div>
          </section>
        </aside>
      </div>
    </div>
  );
}
