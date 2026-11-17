import { useQuery } from '@tanstack/react-query';
import { Link, useParams } from 'react-router';
import { PageHeader } from '../components/page-header';
import { Alert } from '../components/ui/alert';
import { Button } from '../components/ui/button';
import { useFeatures } from '../lib/api/context';
import { explainError } from '../lib/api/errors';
import { schoolDatetime } from '../features/schedule/school-dates';
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
    <>
      <PageHeader
        title={query.data?.lesson.subject_name ?? 'Урок и домашние задания'}
        description={
          query.data
            ? `${schoolDatetime(query.data.lesson.starts_at)} · ${query.data.lesson.teacher_name}`
            : undefined
        }
      />
      <Link to="/my-schedule">← Моё расписание</Link>{' '}
      <Link className="button button-secondary" to={`/pen/lessons/${id}`}>
        Умная ручка
      </Link>{' '}
      <Button variant="secondary" disabled={query.isFetching} onClick={() => void query.refetch()}>
        Обновить
      </Button>
      {query.isPending && <p role="status">Загружаем урок…</p>}
      {query.isError && <Alert tone="error">{explainError(query.error)}</Alert>}
      {query.data && (
        <>
          {query.data.lesson.status === 'canceled' && <Alert>Этот урок отменён.</Alert>}
          {(
            [
              ['Подготовить к этому уроку', query.data.homework_for_lesson],
              ['Задано на этом уроке', query.data.homework_from_lesson],
            ] as const
          ).map(([title, tasks]) => (
            <section className="card lesson-homework-group" key={title}>
              <h2>{title}</h2>
              {!tasks.length && <p>Заданий нет.</p>}
              {tasks.map((task) => (
                <article key={task.id}>
                  <p className="homework-description">{task.description}</p>
                  <p>
                    {task.final_due_datetime
                      ? `Сдать до ${schoolDatetime(task.final_due_datetime)}`
                      : 'Срок уточняется'}
                  </p>
                  <Link className="button button-primary" to={`/homework/${task.id}`}>
                    Открыть задание
                  </Link>
                </article>
              ))}
            </section>
          ))}
          <p>
            Задания с вручную указанной датой также доступны в{' '}
            <Link to="/homework">списке домашних заданий</Link>.
          </p>
        </>
      )}
    </>
  );
}
