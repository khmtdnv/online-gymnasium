import { useEffect, useRef, useState, type ReactNode } from 'react';
import { FileImage, FileSpreadsheet, FileText, File as FileIcon, Presentation } from 'lucide-react';
import { Alert } from '../../components/ui/alert';
import { Button } from '../../components/ui/button';
import { explainError } from '../../lib/api/errors';
import type { HomeworkApi, HomeworkFile } from './api';

function fileIcon(file: HomeworkFile): ReactNode {
  const type = file.content_type;
  if (type.startsWith('image/')) return <FileImage size={20} aria-hidden="true" />;
  if (type.includes('spreadsheet')) return <FileSpreadsheet size={20} aria-hidden="true" />;
  if (type.includes('presentation')) return <Presentation size={20} aria-hidden="true" />;
  if (type === 'application/pdf' || type.startsWith('text/'))
    return <FileText size={20} aria-hidden="true" />;
  return <FileIcon size={20} aria-hidden="true" />;
}

function fileSize(bytes: number): string {
  return bytes >= 1048576
    ? `${(bytes / 1048576).toFixed(1)} МиБ`
    : `${Math.max(1, Math.ceil(bytes / 1024))} КиБ`;
}

/** Метаданные не дают права на скачивание: API заново проверяет пользователя. */
export function HomeworkFiles({
  files,
  api,
  onRetry,
  busy = false,
}: {
  files: HomeworkFile[];
  api: HomeworkApi;
  busy?: boolean;
  onRetry?: (file: HomeworkFile, selected: File) => Promise<void>;
}) {
  const [selected, setSelected] = useState<Record<number, File>>({});
  const [downloading, setDownloading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const controller = useRef<AbortController | null>(null);
  useEffect(() => () => controller.current?.abort(), []);

  async function download(file: HomeworkFile) {
    if (downloading) return;
    const current = new AbortController();
    controller.current = current;
    setDownloading(true);
    setError(null);
    try {
      const blob = await api.downloadHomeworkFile(file, current.signal);
      current.signal.throwIfAborted();
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement('a');
      anchor.href = url;
      anchor.download = file.file_name;
      document.body.append(anchor);
      anchor.click();
      anchor.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (error) {
      if (!current.signal.aborted) setError(explainError(error));
    } finally {
      if (!current.signal.aborted) setDownloading(false);
    }
  }

  return (
    <div className="homework-files" aria-label="Файлы задания">
      {error && <Alert tone="error">{error}</Alert>}
      {files.map((file) => (
        <div
          className={`homework-file-row${file.upload_status === 'pending' ? ' is-pending' : ''}`}
          key={file.id}
        >
          <span className="homework-file-icon" aria-hidden="true">
            {fileIcon(file)}
          </span>
          <div className="homework-file-info">
            <strong>{file.file_name}</strong>
            <p>
              {fileSize(file.size_bytes)} ·{' '}
              {file.upload_status === 'ready' ? 'Готов к скачиванию' : 'Ещё не загружен'}
            </p>
          </div>
          {file.upload_status === 'ready' ? (
            <Button variant="secondary" disabled={downloading} onClick={() => void download(file)}>
              Скачать {file.file_name}
            </Button>
          ) : (
            <div className="homework-file-retry">
              <p>Текст задания доступен. Вложение пока недоступно.</p>
              {onRetry && (
                <>
                  <label>
                    Выбрать файл заново: {file.file_name}
                    <input
                      type="file"
                      disabled={busy}
                      accept=".pdf,.docx,.xlsx,.pptx,.jpg,.jpeg,.png,.txt"
                      onChange={(event) => {
                        const value = event.target.files?.[0];
                        setSelected((previous) => {
                          const next = { ...previous };
                          if (value) next[file.id] = value;
                          else delete next[file.id];
                          return next;
                        });
                      }}
                    />
                  </label>
                  <Button
                    disabled={busy || !selected[file.id]}
                    onClick={() => void onRetry(file, selected[file.id])}
                  >
                    Повторить загрузку {file.file_name}
                  </Button>
                </>
              )}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
