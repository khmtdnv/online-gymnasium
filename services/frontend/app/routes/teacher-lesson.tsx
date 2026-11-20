import { useQuery } from '@tanstack/react-query';
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
import { schoolDatetime } from '../features/schedule/school-dates';

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
  const { homework, schedule } = useFeatures();
  const query = useQuery({
    queryKey: ['homework', 'teacher-lesson', id],
    enabled: valid,
    queryFn: ({ signal }) => schedule.getLessonView(id, signal),
  });
  if (!valid) return <Alert tone="error">Некорректный номер урока.</Alert>;
  return (
    <div className="workspace-page teacher-lesson-page">
      <PageHeader
        title="Урок и домашние задания"
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
          Умная ручка
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
        <>
          <section className="workspace-panel teacher-lesson-section">
            <h2>Подготовить к этому уроку</h2>
            {query.data.homework_for_lesson.length === 0 && (
              <p>
                Заданий к этому уроку нет. Задания с датой вручную смотрите в общем списке ученика.
              </p>
            )}
            {query.data.homework_for_lesson.map((row) => (
              <article key={row.id}>
                <p style={{ whiteSpace: 'pre-wrap' }}>
                  {displayHomeworkDescription(row.description)}
                </p>
                <HomeworkFiles files={row.files} api={homework} />
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
          {[
            ...new Map(
              [...query.data.homework_for_lesson, ...query.data.homework_from_lesson].map((row) => [
                row.id,
                row,
              ]),
            ).values(),
          ].map((row) => (
            <section
              id={`homework-${row.id}`}
              className="workspace-panel teacher-lesson-section"
              key={row.id}
            >
              <h2>Проверка задания: {displayHomeworkDescription(row.description).slice(0, 100)}</h2>
              <HomeworkAnswerReview homeworkId={row.id} api={homework} />
            </section>
          ))}
        </>
      )}
    </div>
  );
}
