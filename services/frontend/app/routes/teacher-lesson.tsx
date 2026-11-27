import { useQuery } from '@tanstack/react-query';
import { BookOpen, CalendarDays, Clock3, PenLine, UserRound, Users } from 'lucide-react';
import { Link, useParams } from 'react-router';
import { PageHeader } from '../components/page-header';
import { Alert } from '../components/ui/alert';
import { Button } from '../components/ui/button';
import { useSession } from '../features/auth/session-context';
import { HomeworkForm } from '../features/homework/homework-form';
import { HomeworkFiles } from '../features/homework/homework-files';
import { displayHomeworkDescription } from '../features/homework/display-description';
import { HomeworkAnswerReview } from '../features/homework/homework-answer-review';
import { useFeatures } from '../lib/api/context';
import { explainError } from '../lib/api/errors';
import StudentLessonPage from './student-lesson';
import {
  formatSchoolDay,
  schoolDay,
  schoolDatetime,
  schoolTime,
} from '../features/schedule/school-dates';

function studentsLabel(count: number) {
  const mod10 = count % 10;
  const mod100 = count % 100;
  const word =
    mod10 === 1 && mod100 !== 11
      ? 'ученик'
      : mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)
        ? 'ученика'
        : 'учеников';
  return `${count} ${word}`;
}

export default function TeacherLessonPage() {
  const { state } = useSession();
  if (state.status === 'authenticated' && state.user.role === 'student')
    return <StudentLessonPage />;
  if (state.status !== 'authenticated' || state.user.role !== 'teacher')
    return <Alert>Раздел доступен преподавателю.</Alert>;
  return <TeacherLesson />;
}

function TeacherLesson() {
  const { lessonId } = useParams();
  const id = Number(lessonId);
  const valid = Number.isInteger(id) && id > 0 && id <= 2147483647;
  const { homework, pen, schedule } = useFeatures();
  const query = useQuery({
    queryKey: ['homework', 'teacher-lesson', id],
    enabled: valid,
    queryFn: ({ signal }) => schedule.getLessonView(id, signal),
  });
  // Состав класса — реальный список учеников урока (тот же API, что и ручка);
  // несущая часть страницы от него не зависит.
  const roster = useQuery({
    queryKey: ['pen-students', id],
    enabled: valid && query.isSuccess,
    queryFn: ({ signal }) => pen.listStudents(id, signal),
  });
  if (!valid) return <Alert tone="error">Некорректный номер урока.</Alert>;
  return (
    <div className="workspace-page teacher-lesson-page">
      <PageHeader
        title="Урок и домашние задания"
        eyebrow="Журнал заданий"
        description={
          query.data
            ? `${query.data.lesson.subject_name} · ${query.data.lesson.class_name} · ${schoolDatetime(query.data.lesson.starts_at)}`
            : undefined
        }
      />
      <div className="teacher-lesson-actions">
        <Link className="workspace-back" to="/schedule">
          ← Моё расписание
        </Link>{' '}
        <Link className="button button-secondary" to={`/pen/lessons/${id}`}>
          <PenLine size={17} /> Умная ручка
        </Link>{' '}
        <Button
          variant="secondary"
          disabled={query.isFetching}
          onClick={() => void query.refetch()}
        >
          Обновить карточку
        </Button>
      </div>
      {query.isPending && <p role="status">Загружаем урок…</p>}
      {query.isError && <Alert tone="error">{explainError(query.error)}</Alert>}
      {query.data && (
        <div className="lesson-layout">
          <div className="lesson-content">
            <section className="workspace-panel lesson-tasks">
              <div className="workspace-panel-head">
                <div>
                  <h2>Подготовить к этому уроку</h2>
                  <p>Задания, выданные раньше к этому занятию.</p>
                </div>
                <span className="workspace-icon">
                  <BookOpen size={20} />
                </span>
              </div>
              {!query.data.homework_for_lesson.length && (
                <div className="workspace-empty">
                  <BookOpen size={21} />
                  <div>
                    <strong>Заданий нет</strong>
                    <p>
                      Ученикам заранее ничего не задано. Задания с датой вручную смотрите в общем
                      списке ученика.
                    </p>
                  </div>
                </div>
              )}
              {query.data.homework_for_lesson.map((row) => (
                <article className="lesson-task" key={row.id}>
                  <div className="lesson-task-body">
                    <p className="homework-description">
                      {displayHomeworkDescription(row.description)}
                    </p>
                    <span className="lesson-task-deadline">
                      <Clock3 size={15} />
                      {row.final_due_datetime
                        ? `Сдать до ${schoolDatetime(row.final_due_datetime)}`
                        : 'Срок уточняется'}
                    </span>
                    {row.files.length > 0 && (
                      <div className="lesson-task-files">
                        <HomeworkFiles files={row.files} api={homework} />
                      </div>
                    )}
                  </div>
                </article>
              ))}
            </section>
            {query.data.lesson.status === 'canceled' && !query.data.homework_from_lesson.length ? (
              <Alert>Урок отменён. Выдать новое задание нельзя.</Alert>
            ) : (
              <HomeworkForm
                key={id}
                lessonId={id}
                nextLesson={query.data.next_lesson}
                homework={query.data.homework_from_lesson[0]}
                api={homework}
                onCreated={() => void query.refetch()}
              />
            )}
            {query.data.homework_from_lesson.slice(1).map((row) => (
              <section className="workspace-panel" key={row.id}>
                <h2>Задано на этом уроке</h2>
                <p className="homework-description" style={{ whiteSpace: 'pre-wrap' }}>
                  {displayHomeworkDescription(row.description)}
                </p>
                <HomeworkFiles files={row.files} api={homework} />
              </section>
            ))}
            {[
              ...new Map(
                [...query.data.homework_for_lesson, ...query.data.homework_from_lesson].map(
                  (row) => [row.id, row],
                ),
              ).values(),
            ].map((row) => (
              <section id={`homework-${row.id}`} className="workspace-panel" key={row.id}>
                <h2>
                  Проверка задания: {displayHomeworkDescription(row.description).slice(0, 100)}
                </h2>
                <HomeworkAnswerReview homeworkId={row.id} api={homework} />
              </section>
            ))}
          </div>
          <aside className="lesson-aside">
            <section className="workspace-panel lesson-info">
              <h2>Об уроке</h2>
              <div className="lesson-info-row">
                <CalendarDays size={18} />
                <div>
                  <span>Дата</span>
                  <strong>
                    {formatSchoolDay(schoolDay(new Date(query.data.lesson.starts_at)), {
                      weekday: 'long',
                      year: 'numeric',
                    })}
                  </strong>
                </div>
              </div>
              <div className="lesson-info-row">
                <Clock3 size={18} />
                <div>
                  <span>Время школы</span>
                  <strong>
                    {schoolTime(query.data.lesson.starts_at)}–
                    {schoolTime(query.data.lesson.ends_at)}
                  </strong>
                </div>
              </div>
              <div className="lesson-info-row">
                <UserRound size={18} />
                <div>
                  <span>Преподаватель</span>
                  <strong>{query.data.lesson.teacher_name}</strong>
                </div>
              </div>
              <div className="lesson-info-row">
                <Users size={18} />
                <div>
                  <span>Класс</span>
                  <strong>{query.data.lesson.class_name}</strong>
                </div>
              </div>
              {query.data.lesson.status === 'canceled' && (
                <p className="lesson-canceled-note">Урок отменён.</p>
              )}
              <Link className="lesson-info-link" to="/homework">
                Домашние задания и проверка
              </Link>
            </section>
            <section className="workspace-panel lesson-roster" aria-label="Состав класса">
              <div className="workspace-panel-head">
                <div>
                  <h2>Состав класса</h2>
                  <p>
                    {roster.data
                      ? roster.data.length
                        ? studentsLabel(roster.data.length)
                        : 'В классе нет учеников'
                      : `Класс ${query.data.lesson.class_name}`}
                  </p>
                </div>
                <span className="workspace-icon">
                  <Users size={20} />
                </span>
              </div>
              {roster.isPending && (
                <p role="status" className="lesson-roster-state">
                  Загружаем состав класса…
                </p>
              )}
              {roster.isError && (
                <div className="lesson-roster-error">
                  <p>Состав класса временно недоступен.</p>
                  <Button
                    variant="secondary"
                    disabled={roster.isFetching}
                    onClick={() => void roster.refetch()}
                  >
                    Обновить
                  </Button>
                </div>
              )}
              {roster.data && !roster.data.length && (
                <div className="workspace-empty lesson-roster-empty">
                  <Users size={21} />
                  <div>
                    <strong>Учеников нет</strong>
                    <p>В классе пока нет активных учеников.</p>
                  </div>
                </div>
              )}
              {roster.data?.length ? (
                <ul className="lesson-roster-list">
                  {roster.data.map((row) => (
                    <li key={row.id}>{row.name}</li>
                  ))}
                </ul>
              ) : null}
            </section>
          </aside>
        </div>
      )}
    </div>
  );
}
