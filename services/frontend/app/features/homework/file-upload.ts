import { ApiError, ApiNetworkError } from '../../lib/api/errors';
import type { HomeworkFile, HomeworkFileInput } from './api';

const contentTypes: Record<string, string> = {
  pdf: 'application/pdf',
  docx: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  xlsx: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  pptx: 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
  jpg: 'image/jpeg',
  jpeg: 'image/jpeg',
  png: 'image/png',
  txt: 'text/plain',
};

/** Один выбранный файл — одна временная копия для SHA-256, без хранения байтов между страницами. */
export async function prepareFile(file: File): Promise<HomeworkFileInput> {
  const content_type = contentTypes[file.name.split('.').at(-1)?.toLowerCase() ?? ''];
  if (
    !content_type ||
    file.size < 1 ||
    file.size > 10485760 ||
    file.name.length > 255 ||
    /\p{Cc}/u.test(file.name) ||
    /[/\\]/.test(file.name)
  )
    throw new Error('Допустимы PDF, DOCX, XLSX, PPTX, JPG, PNG и TXT от 1 байта до 10 МиБ.');
  const hash = await crypto.subtle.digest('SHA-256', await file.arrayBuffer());
  return {
    file_name: file.name,
    size_bytes: file.size,
    content_type,
    content_sha256: Array.from(new Uint8Array(hash), (byte) =>
      byte.toString(16).padStart(2, '0'),
    ).join(''),
  };
}

export type UploadTask = HomeworkFile & { file?: File };

/** Последовательные попытки; исключения прав/контракта не превращаются в слепой retry. */
export async function uploadFilesWithRetry(
  tasks: UploadTask[],
  upload: (task: HomeworkFile, file: File, signal: AbortSignal) => Promise<HomeworkFile>,
  signal: AbortSignal,
  onResult?: (file: HomeworkFile, error?: unknown) => void,
): Promise<HomeworkFile[]> {
  const results: HomeworkFile[] = [];
  for (const task of tasks) {
    signal.throwIfAborted();
    let result: HomeworkFile = task;
    if (task.upload_status === 'pending' && task.file) {
      for (let attempt = 0; attempt < 4; attempt++) {
        signal.throwIfAborted();
        try {
          result = await upload(task, task.file, signal);
          signal.throwIfAborted();
          onResult?.(result);
          break;
        } catch (error) {
          signal.throwIfAborted();
          const temporary =
            error instanceof ApiNetworkError ||
            (error instanceof ApiError && [408, 429, 500, 502, 503, 504].includes(error.status));
          if (!temporary || attempt === 3) {
            onResult?.(task, error);
            break;
          }
          const retryAfter = error instanceof ApiError ? (error.retryAfterMs ?? 0) : 0;
          const delay = Math.max([2000, 5000, 10000][attempt], retryAfter);
          // Не переполняем browser timer и не повторяем раньше огромного Retry-After.
          if (!Number.isFinite(delay) || delay > 2147483647) {
            onResult?.(task, error);
            break;
          }
          await new Promise<void>((resolve, reject) => {
            const abort = () => {
              clearTimeout(timer);
              reject(signal.reason ?? new DOMException('Отменено', 'AbortError'));
            };
            const timer = setTimeout(() => {
              signal.removeEventListener('abort', abort);
              resolve();
            }, delay);
            signal.addEventListener('abort', abort, { once: true });
            if (signal.aborted) abort();
          });
        }
      }
    }
    results.push(result);
  }
  return results;
}
