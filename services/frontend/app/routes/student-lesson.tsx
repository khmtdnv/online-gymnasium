import { useQuery } from '@tanstack/react-query';
import { ArrowLeft, BookOpen, CalendarDays, Clock3, PenLine, UserRound } from 'lucide-react';
import { Link, useParams } from 'react-router';
import { Alert } from '../components/ui/alert';
import { Button } from '../components/ui/button';
import { useFeatures } from '../lib/api/context';
import { displayHomeworkDescription } from '../features/homework/display-description';
import { explainError } from '../lib/api/errors';
import {
  formatSchoolDay,
  schoolDay,
  schoolDatetime,
  schoolTime,
} from '../features/schedule/school-dates';

export default function StudentLessonPage() {
  const id = Number(useParams().lessonId);
  const valid = Number.isInteger(id) && id > 0 && id <= 2147483647;
  const { schedule } = useFeatures();
  const query = useQuery({
    queryKey: ['student-lesson', id],
    enabled: valid,
    queryFn: ({ signal }) => schedule.getLessonView(id, signal),
  });
  if (!valid) return <Alert tone="error">Некорректный номер урока.</Alert>;
  return (
    <div className="workspace-page lesson-page">
      <Link className="workspace-back" to="/schedule">
        <ArrowLeft size={16} /> Расписание
      </Link>
      <header className="lesson-heading">
        <div>
          <span className="workspace-kicker">Информация об уроке</span>
          <h1>{query.data?.lesson.subject_name ?? 'Урок и домашние задания'}</h1>
          <p>
            {query.data
              ? `${query.data.lesson.class_name} · ${query.data.lesson.teacher_name}`
              : 'Занятие и связанные задания'}
          </p>
        </div>
        <div className="lesson-header-actions">
          <Link className="button button-secondary" to={`/pen/lessons/${id}`}>
            <PenLine size={17} /> Умная ручка
          </Link>
          <Button
            variant="secondary"
            disabled={query.isFetching}
            onClick={() => void query.refetch()}
          >
            Обновить
          </Button>
        </div>
      </header>
      {query.isPending && <p role="status">Загружаем урок…</p>}
      {query.isError && <Alert tone="error">{explainError(query.error)}</Alert>}
      {query.data && (
        <>
          {query.data.lesson.status === 'canceled' && <Alert>Этот урок отменён.</Alert>}
          <div className="lesson-layout">
            <div className="lesson-content">
              {(
                [
                  [
                    'Подготовить к этому уроку',
                    'Работы, которые нужно было выполнить к занятию.',
                    query.data.homework_for_lesson,
                  ],
                ] as const
              ).map(([title, description, tasks]) => (
                <section className="workspace-panel lesson-tasks" key={title}>
                  <div className="workspace-panel-head">
                    <div>
                      <h2>{title}</h2>
                      <p>{description}</p>
                    </div>
                    <span className="workspace-icon">
                      <BookOpen size={20} />
                    </span>
                  </div>
                  {!tasks.length && (
                    <div className="workspace-empty">
                      <BookOpen size={21} />
                      <div>
                        <strong>Заданий нет</strong>
                        <p>Здесь появятся задания, связанные с уроком.</p>
                      </div>
                    </div>
                  )}
                  {tasks.map((task) => (
                    <article className="lesson-task" key={task.id}>
                      <div>
                        <p className="homework-description">
                          {displayHomeworkDescription(task.description)}
                        </p>
                        <span className="lesson-task-deadline">
                          <Clock3 size={15} />
                          {task.final_due_datetime
                            ? `Сдать до ${schoolDatetime(task.final_due_datetime)}`
                            : 'Срок уточняется'}
                        </span>
                      </div>
                      <Link className="button button-primary" to={`/homework/${task.id}`}>
                        Открыть задание
                      </Link>
                    </article>
                  ))}
                </section>
              ))}
            </div>
            <aside className="workspace-panel lesson-info">
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
              <Link to="/homework" className="lesson-info-link">
                Все домашние задания
              </Link>
            </aside>
          </div>
        </>
      )}
    </div>
  );
}
