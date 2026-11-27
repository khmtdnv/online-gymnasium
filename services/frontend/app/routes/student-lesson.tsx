import { useQuery } from '@tanstack/react-query';
import { ArrowLeft, BookOpen, CalendarDays, Clock3, PenLine, UserRound } from 'lucide-react';
import { Link, useParams } from 'react-router';
import { Alert } from '../components/ui/alert';
import { Button } from '../components/ui/button';
import { useFeatures } from '../lib/api/context';
import { displayHomeworkDescription } from '../features/homework/display-description';
import { HomeworkFiles } from '../features/homework/homework-files';
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
  const { schedule, homework } = useFeatures();
  const query = useQuery({
    queryKey: ['student-lesson', id],
    enabled: valid,
    queryFn: ({ signal }) => schedule.getLessonView(id, signal),
  });
  if (!valid) return <Alert tone="error">Некорректный номер урока.</Alert>;
  const lesson = query.data?.lesson;
  return (
    <div className="workspace-page lesson-page">
      <Link className="workspace-back" to="/schedule">
        <ArrowLeft size={16} /> Расписание
      </Link>
      <header className="lesson-heading">
        <div>
          <span className="workspace-kicker">Информация об уроке</span>
          <h1>{lesson?.subject_name ?? 'Урок и домашние задания'}</h1>
          <p>
            {lesson
              ? `${lesson.class_name} · ${lesson.teacher_name}`
              : 'Занятие и связанные задания'}
          </p>
          <p className="lesson-meta">
            {lesson
              ? `${formatSchoolDay(schoolDay(new Date(lesson.starts_at)), {
                  weekday: 'long',
                  day: 'numeric',
                  month: 'long',
                  year: 'numeric',
                })} · ${schoolTime(lesson.starts_at)}–${schoolTime(lesson.ends_at)}`
              : 'Дата и время появятся после загрузки урока'}
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
              {/* У ученика есть только подготовка: секции «Задано на этом уроке» у него нет. */}
              <section className="workspace-panel lesson-tasks">
                <div className="workspace-panel-head">
                  <div>
                    <h2>Подготовить к этому уроку</h2>
                    <p>Задания, которые нужно было выполнить к этому занятию.</p>
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
                      <p>Здесь появятся задания, связанные с уроком.</p>
                    </div>
                  </div>
                )}
                {query.data.homework_for_lesson.map((task) => (
                  <article className="lesson-task" key={task.id}>
                    <div className="lesson-task-body">
                      <p className="homework-description">
                        {displayHomeworkDescription(task.description)}
                      </p>
                      <span className="lesson-task-deadline">
                        <Clock3 size={15} />
                        {task.final_due_datetime
                          ? `Сдать до ${schoolDatetime(task.final_due_datetime)}`
                          : 'Срок уточняется'}
                      </span>
                      {task.files.length > 0 && (
                        <div className="lesson-task-files">
                          <HomeworkFiles files={task.files} api={homework} />
                        </div>
                      )}
                    </div>
                    <Link className="button button-primary" to={`/homework/${task.id}`}>
                      Открыть задание
                    </Link>
                  </article>
                ))}
              </section>
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
                <Link to="/homework" className="lesson-info-link">
                  Все домашние задания
                </Link>
              </section>
            </aside>
          </div>
        </>
      )}
    </div>
  );
}
