import { useQuery } from '@tanstack/react-query';
import { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router';
import { AsyncState } from '../components/async-state';
import { PageHeader } from '../components/page-header';
import { JobStatus } from '../features/documents/job-status';
import { PdfPreview } from '../features/documents/pdf-preview';
import { getDocumentPollInterval } from '../features/documents/polling';
import { uuidSchema } from '../lib/api/contracts';
import { useFeatures } from '../lib/api/context';
import { ApiError, errorRequestId, explainError } from '../lib/api/errors';

function JobPage({ jobId }: { jobId: string }) {
  const { documents } = useFeatures();
  const valid = uuidSchema.safeParse(jobId).success;
  const [startedAt, setStartedAt] = useState(Date.now);
  const [paused, setPaused] = useState(false);
  const [visible, setVisible] = useState(
    () => typeof document === 'undefined' || document.visibilityState !== 'hidden',
  );
  const query = useQuery({
    queryKey: ['document-job', jobId],
    enabled: valid && visible,
    queryFn: ({ signal }) => documents.getDocument(jobId, signal),
    refetchInterval: (query) =>
      !visible || paused || query.state.error
        ? false
        : getDocumentPollInterval(Date.now() - startedAt, query.state.data?.status ?? 'pending'),
    refetchIntervalInBackground: false,
  });
  const terminal = query.data?.status === 'completed' || query.data?.status === 'failed';
  useEffect(() => {
    if (!valid || terminal) return;
    const timer = window.setTimeout(
      () => setPaused(true),
      Math.max(0, 120_000 - (Date.now() - startedAt)),
    );
    return () => window.clearTimeout(timer);
  }, [startedAt, terminal, valid]);
  useEffect(() => {
    function changed() {
      const next = document.visibilityState !== 'hidden';
      setVisible(next);
      if (next && valid) void query.refetch();
    }
    document.addEventListener('visibilitychange', changed);
    return () => document.removeEventListener('visibilitychange', changed);
  }, [valid, query.refetch]);
  return (
    <>
      <PageHeader
        title="Ваша справка"
        eyebrow="Задание генерации"
        description="Сохраните адрес этой страницы, чтобы вернуться к результату."
        action={
          <Link to="/documents" className="button button-secondary">
            К справкам
          </Link>
        }
      />
      {!valid ? (
        <AsyncState
          state="error"
          title="Неверный ID задания"
          message="В адресе должен быть UUID полученного задания."
        />
      ) : query.isPending ? (
        <AsyncState state="loading" title="Проверяем статус справки" />
      ) : query.isError ? (
        <AsyncState
          state="error"
          title={
            query.error instanceof ApiError && query.error.status === 404
              ? 'Задание не найдено'
              : 'Статус недоступен'
          }
          message={explainError(query.error)}
          requestId={errorRequestId(query.error)}
          onRetry={() => {
            void query.refetch();
          }}
        />
      ) : (
        <>
          <JobStatus
            job={query.data}
            paused={paused}
            onContinue={() => {
              setStartedAt(Date.now());
              setPaused(false);
              void query.refetch();
            }}
          />
          {query.data.status === 'completed' && <PdfPreview jobId={jobId} />}
        </>
      )}
    </>
  );
}
export default function DocumentJobPage() {
  const { jobId = '' } = useParams();
  return <JobPage key={jobId} jobId={jobId} />;
}
