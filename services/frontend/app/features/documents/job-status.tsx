import { CircleCheck, LoaderCircle, TriangleAlert } from 'lucide-react';
import { Link } from 'react-router';
import { Alert } from '../../components/ui/alert';
import { Button } from '../../components/ui/button';
import type { DocumentJob } from '../../lib/api/contracts';
import { utcDateTime } from '../schedule/utc';

const labels = {
  pending: 'В очереди',
  processing: 'Готовим PDF',
  completed: 'Готово',
  failed: 'Не удалось создать',
} as const;
export function JobStatus({
  job,
  paused,
  onContinue,
}: {
  job: DocumentJob;
  paused: boolean;
  onContinue: () => void;
}) {
  const Icon =
    job.status === 'completed'
      ? CircleCheck
      : job.status === 'failed'
        ? TriangleAlert
        : LoaderCircle;
  return (
    <section className="card" style={{ marginBottom: 24 }}>
      <span className={`badge${job.status === 'failed' ? ' badge-error' : ''}`}>
        <Icon
          size={16}
          className={
            job.status === 'pending' || job.status === 'processing' ? 'spinner' : undefined
          }
          aria-hidden="true"
        />
        {labels[job.status]}
      </span>
      <h2 className="section-title">Задание генерации</h2>
      <p className="job-id">ID: {job.id}</p>
      <p>Принято: {utcDateTime(job.created_at)}</p>
      {job.status === 'failed' ? (
        <>
          <Alert tone="error">
            Документ не удалось подготовить. Можно создать новое задание; это не повтор текущей
            задачи.
          </Alert>
          <Link to="/documents" className="button button-secondary">
            К новому документу
          </Link>
        </>
      ) : (
        job.status !== 'completed' &&
        (paused ? (
          <>
            <Alert>
              Автоматическая проверка приостановлена через две минуты. Задание продолжает
              выполняться на сервере.
            </Alert>
            <Button onClick={onContinue}>Продолжить проверку</Button>
          </>
        ) : (
          <p className="field-hint" role="status">
            Проверяем статус автоматически. Можно оставить страницу открытой или сохранить её адрес.
          </p>
        ))
      )}
    </section>
  );
}
