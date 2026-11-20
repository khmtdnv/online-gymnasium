import { useQuery } from '@tanstack/react-query';
import { Link, useParams } from 'react-router';
import { PageHeader } from '../components/page-header';
import { Alert } from '../components/ui/alert';
import { Button } from '../components/ui/button';
import { useSession } from '../features/auth/session-context';
import { HomeworkFiles } from '../features/homework/homework-files';
import { displayHomeworkDescription } from '../features/homework/display-description';
import { HomeworkAnswerForm } from '../features/homework/homework-answer-form';
import { useFeatures } from '../lib/api/context';
import { explainError } from '../lib/api/errors';
import { schoolDatetime } from '../features/schedule/school-dates';

export default function HomeworkDetailPage() {
  const { state } = useSession();
  if (state.status !== 'authenticated' || state.user.role !== 'student')
    return <Alert>Раздел доступен ученику.</Alert>;
  return <StudentHomeworkDetail />;
}

function StudentHomeworkDetail() {
  const { homeworkId } = useParams();
  const id = Number(homeworkId);
  const valid = Number.isInteger(id) && id > 0 && id <= 2147483647;
  const { homework, schedule } = useFeatures();
  const query = useQuery({
    queryKey: ['homework', 'student-detail', id],
    enabled: valid,
    queryFn: ({ signal }) => homework.getHomework(id, signal),
  });
  const lesson = useQuery({
    queryKey: ['student-lesson', query.data?.issued_lesson_id],
    enabled: !!query.data,
    queryFn: ({ signal }) => schedule.getLessonView(query.data!.issued_lesson_id, signal),
  });
  if (!valid) return <Alert tone="error">Некорректный номер задания.</Alert>;
  return (
    <div className="workspace-page homework-detail-page">
      <PageHeader title="Домашнее задание" />
      <Link className="workspace-back" to="/homework">
        ← Все задания
      </Link>{' '}
      <Button variant="secondary" disabled={query.isFetching} onClick={() => void query.refetch()}>
        Обновить
      </Button>
      {query.isPending && <p role="status">Загружаем задание…</p>}
      {query.isError && <Alert tone="error">{explainError(query.error)}</Alert>}
      {query.data && (
        <section className="workspace-panel homework-detail-panel">
          <h2>{lesson.data?.lesson.subject_name ?? 'Условие задания'}</h2>
          <p>
            {query.data.final_due_datetime
              ? `Сдать до ${schoolDatetime(query.data.final_due_datetime)}`
              : 'Урок срока отменён — ожидайте уточнения'}
          </p>
          <p style={{ whiteSpace: 'pre-wrap' }}>
            {displayHomeworkDescription(query.data.description)}
          </p>
          <p>
            <Link to={`/lessons/${query.data.issued_lesson_id}`}>
              Открыть урок, на котором задано
            </Link>
          </p>
          {lesson.isError && (
            <Alert>Не удалось уточнить название урока. Само задание доступно ниже.</Alert>
          )}
          <HomeworkFiles files={query.data.files} api={homework} />
          <HomeworkAnswerForm key={id} homeworkId={id} api={homework} />
        </section>
      )}
    </div>
  );
}
