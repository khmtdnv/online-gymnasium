import { useQuery } from '@tanstack/react-query';
import { Download, ExternalLink } from 'lucide-react';
import { useEffect, useState } from 'react';
import { AsyncState } from '../../components/async-state';
import { useFeatures } from '../../lib/api/context';
import { errorRequestId, explainError } from '../../lib/api/errors';

/** Blob URL живёт только пока показан этот PDF, не хранится в браузерном storage. */
export function PdfPreview({ jobId }: { jobId: string }) {
  const { documents } = useFeatures();
  const query = useQuery({
    queryKey: ['document-pdf', jobId],
    queryFn: ({ signal }) => documents.getDocumentPdf(jobId, signal),
    staleTime: Infinity,
    gcTime: 0,
  });
  const [preview, setPreview] = useState<{ jobId: string; url: string } | null>(null);
  useEffect(() => {
    if (!query.data) {
      setPreview(null);
      return;
    }
    const url = URL.createObjectURL(query.data);
    setPreview({ jobId, url });
    return () => {
      URL.revokeObjectURL(url);
    };
  }, [jobId, query.data]);
  if (query.isError)
    return (
      <AsyncState
        state="error"
        title="PDF недоступен"
        message={explainError(query.error)}
        requestId={errorRequestId(query.error)}
        onRetry={() => {
          void query.refetch();
        }}
      />
    );
  if (query.isPending || !preview || preview.jobId !== jobId)
    return <AsyncState state="loading" title="Загружаем PDF" />;
  return (
    <section className="card">
      <div className="page-header">
        <div>
          <span className="eyebrow">Документ готов</span>
          <h2>Учебный документ</h2>
        </div>
        <div className="form-actions">
          <a
            className="button button-primary"
            href={preview.url}
            download={`document-${jobId}.pdf`}
          >
            <Download size={18} aria-hidden="true" />
            Скачать PDF
          </a>
          <a
            className="button button-secondary"
            href={preview.url}
            target="_blank"
            rel="noopener noreferrer"
          >
            <ExternalLink size={18} aria-hidden="true" />
            Открыть отдельно
          </a>
        </div>
      </div>
      <iframe className="pdf-frame" title="Учебный документ — PDF" src={preview.url} />
      <p className="field-hint">
        Если встроенный просмотр не поддерживается браузером, скачайте файл или откройте отдельно.
      </p>
    </section>
  );
}
