import { useQuery } from '@tanstack/react-query';
import { ArrowUpRight, PenLine } from 'lucide-react';
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
import { matchPeriod } from '../schedule/school-periods';

/** Русская плюрализация счётчиков дня: «5 занятий», «1 минута». */
export function pluralRu(count: number, one: string, few: string, many: string): string {
  const mod10 = count % 10;
  const mod100 = count % 100;
  if (mod10 === 1 && mod100 !== 11) return `${count} ${one}`;
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 10 || mod100 >= 20)) return `${count} ${few}`;
  return `${count} ${many}`;
}

/** «Понедельник, 23 ноября 2026 года» — заголовок дня с большой буквы. */
export function dayTitle(day: string): string {
  const text = formatSchoolDay(day, { weekday: 'long', year: 'numeric' }).replace(
    / г\.$/u,
    ' года',
  );
  return text.charAt(0).toUpperCase() + text.slice(1);
}

export interface DayLessonSlot {
  id: number;
  starts_at: string;
  ends_at: string;
  status: string;
}

/** Первый неотменённый урок дня, который ещё не закончился. */
export function nearestLesson<T extends DayLessonSlot>(
  lessons: T[],
  now = Date.now(),
): T | undefined {
  return [...lessons]
    .sort((a, b) => a.starts_at.localeCompare(b.starts_at))
    .find((lesson) => lesson.status !== 'canceled' && Date.parse(lesson.ends_at) > now);
}

export function isLessonRunning(lesson: DayLessonSlot, now = Date.now()): boolean {
  return Date.parse(lesson.starts_at) <= now && now < Date.parse(lesson.ends_at);
}

/** Подпись периода фокус-урока: «Идёт сейчас» / «Начнётся через N минут». */
export function lessonCountdown(lesson: DayLessonSlot, now = Date.now()): string {
  if (isLessonRunning(lesson, now)) return 'Идёт сейчас';
  const minutes = Math.ceil((Date.parse(lesson.starts_at) - now) / 60000);
  if (minutes > 59) return `Начало в ${schoolTime(lesson.starts_at)}`;
  if (minutes <= 0) return 'Начинается';
  return `Начнётся через ${pluralRu(minutes, 'минуту', 'минуты', 'минут')}`;
}

/** «Сегодня, 08:45» / «22 нояб, 21:10» по школьному времени. */
export function shortSchoolStamp(instant: string): string {
  const day = schoolDay(new Date(instant));
  const time = schoolTime(instant);
  if (day === schoolDay()) return `Сегодня, ${time}`;
  return `${formatSchoolDay(day, { month: 'short' }).replace(/\./g, '')}, ${time}`;
}

/** Сумма счёта: копейки Billing → «9 000,00 ₽». */
export function rubles(kopecks: number): string {
  return new Intl.NumberFormat('ru-RU', { style: 'currency', currency: 'RUB' }).format(
    kopecks / 100,
  );
}

/** Учебный период счёта теми же подписями, что и на странице оплаты. */
export function studyPeriodLabel(month: string, period: 'month' | 'quarter'): string {
  const monthName = new Date(`${month}T12:00:00Z`).toLocaleDateString('ru-RU', {
    month: 'long',
    year: 'numeric',
    timeZone: 'UTC',
  });
  if (period !== 'quarter') return `Месяц: ${monthName}`;
  const year = month.slice(0, 4);
  const names: Record<string, string> = {
    '09': `1-я четверть · сентябрь — октябрь ${year}`,
    '11': `2-я четверть · ноябрь — декабрь ${year}`,
    '01': `3-я четверть · январь — март ${year}`,
    '04': `4-я четверть · апрель — май ${year}`,
  };
  return names[month.slice(5, 7)] ?? `Четверть · ${monthName}`;
}

export function StudentDay() {
  const { schedule, homework, billing } = useFeatures();
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
  const periods = lessons.data?.periods ?? [];
  const focus = nearestLesson(todayLessons);
  const focusTask = focus ? tasks.data?.items.find((task) => task.due_lesson_id === focus.id) : undefined;

  // Оплата: карточка появляется только при реальном неоплаченном счёте.
  const students = useQuery({
    queryKey: ['day-billing-students'],
    queryFn: ({ signal }) => billing.students(signal),
  });
  const payerId = students.data?.[0]?.id ?? '';
  const orders = useQuery({
    queryKey: ['day-billing-orders', payerId],
    enabled: payerId !== '',
    queryFn: ({ signal }) => billing.orders(payerId, 0, signal),
  });
  const unpaidOrder = orders.data?.find((order) => order.status === 'unpaid');

  const lessonNumber = (lesson: { starts_at: string; ends_at: string }) =>
    matchPeriod(lesson.starts_at, lesson.ends_at, periods)?.number;
  const taskFor = (lessonId: number) =>
    tasks.data?.items.find((task) => task.due_lesson_id === lessonId);

  return (
    <div className="day-sheet">
      <header className="day-heading">
        <div className="day-heading-main">
          <span className="day-kicker">Академический день · UTC+5 (Екатеринбург)</span>
          <h1>Сегодня</h1>
          <p className="day-date">{dayTitle(today)}</p>
        </div>
        <Link to="/schedule" className="button button-secondary day-week-link">
          Вся неделя
          <ArrowUpRight size={16} aria-hidden="true" />
        </Link>
      </header>
      <div className="day-grid">
        <div className="day-main">
          {focus && (
            <section className="day-hero" aria-labelledby="day-focus-heading">
              <div className="day-hero-head">
                <span className="badge badge-peach day-hero-badge">Ближайший урок</span>
                <span className="day-hero-time">
                  {schoolTime(focus.starts_at)} — {schoolTime(focus.ends_at)}
                </span>
                <span className={`day-hero-note${isLessonRunning(focus) ? ' is-live' : ''}`}>
                  {lessonCountdown(focus)}
                </span>
              </div>
              <h2 id="day-focus-heading">{focus.subject_name}</h2>
              <p className="day-hero-meta">
                {[
                  lessonNumber(focus) ? `Урок ${lessonNumber(focus)}` : null,
                  focus.teacher_name,
                  focus.class_name,
                ]
                  .filter(Boolean)
                  .join(' · ')}
              </p>
              <div className="day-hero-actions">
                <Link className="button button-primary" to={`/lessons/${focus.id}`}>
                  Открыть урок
                </Link>
                <Link className="button button-secondary" to={`/pen/lessons/${focus.id}`}>
                  <PenLine size={16} aria-hidden="true" />
                  Умная ручка
                </Link>
              </div>
              {focusTask && (
                <div className="day-hero-homework">
                  <div className="day-hero-homework-head">
                    <span>Подготовить к этому уроку</span>
                    <span className="badge badge-peach">Требуется сдача</span>
                  </div>
                  <p>{displayHomeworkDescription(focusTask.description)}</p>
                  <div className="day-hero-homework-actions">
                    <Link className="button button-primary" to={`/homework/${focusTask.id}`}>
                      Сдать работу
                    </Link>
                    <small>
                      {focusTask.final_due_datetime
                        ? `Сдать до ${schoolDatetime(focusTask.final_due_datetime)}`
                        : 'Срок уточняется'}
                    </small>
                  </div>
                </div>
              )}
            </section>
          )}
          <section className="day-panel">
            <div className="day-panel-head">
              <h2>Уроки сегодня</h2>
              <span className="day-panel-note">
                {lessons.data && todayLessons.length > 0
                  ? `Всего ${pluralRu(todayLessons.length, 'занятие', 'занятия', 'занятий')}`
                  : null}
              </span>
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
              <div className="day-empty">
                <strong>На сегодня уроков нет</strong>
                <p>Посмотрите расписание на другие дни.</p>
                <Link to="/schedule">Открыть расписание</Link>
              </div>
            )}
            <div className="day-timeline">
              {todayLessons.map((lesson) => {
                const number = lessonNumber(lesson);
                const task = taskFor(lesson.id);
                return (
                  <Link
                    className={`day-lesson${lesson.status === 'canceled' ? ' is-canceled' : ''}${
                      focus && lesson.id === focus.id ? ' is-focus' : ''
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
                      <small>
                        {lesson.teacher_name} · {lesson.class_name}
                      </small>
                    </span>
                    {task && (
                      <span className="day-hw-chip">
                        ДЗ: {displayHomeworkDescription(task.description)}
                      </span>
                    )}
                    <span
                      className={`day-lesson-open${lesson.status === 'canceled' ? ' is-canceled-status' : ''}`}
                    >
                      {lesson.status === 'canceled' ? 'Отменён' : 'Открыть'}
                    </span>
                  </Link>
                );
              })}
            </div>
          </section>
        </div>
        <aside className="day-side">
          {unpaidOrder && (
            <section className="day-panel day-access" aria-labelledby="day-access-heading">
              <div className="day-panel-head">
                <h2 id="day-access-heading">Учебный доступ</h2>
                <span className="badge badge-peach">Счёт выставлен</span>
              </div>
              <strong className="day-access-amount">
                {rubles(unpaidOrder.amount_kopecks)}
              </strong>
              <p className="day-access-period">
                {studyPeriodLabel(unpaidOrder.study_month, unpaidOrder.period_type)}
              </p>
              {unpaidOrder.payment?.status === 'pending' &&
              unpaidOrder.payment.confirmation_url ? (
                <a
                  className="button button-primary"
                  href={unpaidOrder.payment.confirmation_url}
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  Продолжить оплату в ЮKassa
                </a>
              ) : (
                <Link className="button button-primary" to="/billing">
                  Перейти к оплате
                </Link>
              )}
              <Link className="day-panel-more" to="/billing">
                История платежей
              </Link>
            </section>
          )}
          <section className="day-panel">
            <div className="day-panel-head">
              <h2>Ближайшие дедлайны</h2>
              <Link to="/homework">Все задания</Link>
            </div>
            {tasks.isPending && <p role="status">Загружаем задания…</p>}
            {tasks.isError && <p role="alert">Не удалось загрузить задания.</p>}
            {tasks.data && !tasks.data.items.length && <p>На ближайшие 30 дней заданий нет.</p>}
            <div className="day-deadlines">
              {tasks.data?.items.slice(0, 3).map((task) => (
                <Link className="day-deadline" key={task.id} to={`/homework/${task.id}`}>
                  <span className="day-deadline-eyebrow">
                    {task.final_due_datetime
                      ? `Сдать до ${schoolDatetime(task.final_due_datetime)}`
                      : 'Срок уточняется'}
                  </span>
                  <strong>{task.subject_name}</strong>
                  <span>{displayHomeworkDescription(task.description)}</span>
                  <small>
                    {task.latest_answer_status === 'returned'
                      ? 'Возвращено — нужно доработать'
                      : 'Ожидает сдачи'}
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
