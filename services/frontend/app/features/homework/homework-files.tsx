import { useEffect, useRef, useState } from 'react';
import { Alert } from '../../components/ui/alert';
import { Button } from '../../components/ui/button';
import { explainError } from '../../lib/api/errors';
import type { HomeworkApi, HomeworkFile } from './api';

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
        <div className="card" key={file.id}>
          <strong>{file.file_name}</strong>
          <p>
            {Math.ceil(file.size_bytes / 1024)}КиБ ·{' '}
            {file.upload_status === 'ready' ? 'Готов к скачиванию' : 'Ещё не загружен'}
          </p>
          {file.upload_status === 'ready' ? (
            <Button variant="secondary" disabled={downloading} onClick={() => void download(file)}>
              Скачать {file.file_name}
            </Button>
          ) : (
            <>
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
            </>
          )}
        </div>
      ))}
    </div>
  );
}
