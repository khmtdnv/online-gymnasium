import { afterEach, describe, expect, it, vi } from 'vitest';
import { uploadFilesWithRetry } from '../app/features/homework/file-upload';
import { prepareFile } from '../app/features/homework/file-upload';
import { File as NodeFile } from 'node:buffer';
import { webcrypto } from 'node:crypto';
import { ApiError, ApiNetworkError } from '../app/lib/api/errors';

afterEach(() => vi.useRealTimers());

const file = new File(['answer'], 'Задачи.txt', { type: 'text/plain' });
const task = {
  id: 8,
  homework_id: 1,
  file_name: file.name,
  size_bytes: 6,
  content_type: 'text/plain',
  upload_status: 'pending' as const,
  file,
};

describe('загрузка ожидаемых файлов', () => {
  it('повторяет временный сбой через2/5/10секунд, всего4попытки', async () => {
    vi.useFakeTimers();
    const upload = vi.fn().mockRejectedValue(new ApiNetworkError());
    const result = uploadFilesWithRetry([task], upload, new AbortController().signal);
    await vi.advanceTimersByTimeAsync(0);
    expect(upload).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(1999);
    expect(upload).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(1);
    expect(upload).toHaveBeenCalledTimes(2);
    await vi.advanceTimersByTimeAsync(5000);
    expect(upload).toHaveBeenCalledTimes(3);
    await vi.advanceTimersByTimeAsync(10000);
    expect(upload).toHaveBeenCalledTimes(4);
    expect((await result)[0].upload_status).toBe('pending');
  });

  it.each([401, 403, 404, 409, 413, 415, 422])('не повторяет отказ%i', async (status) => {
    const upload = vi.fn().mockRejectedValue(new ApiError(status, 'error', 'failed'));
    const result = await uploadFilesWithRetry([task], upload, new AbortController().signal);
    expect(upload).toHaveBeenCalledTimes(1);
    expect(result[0].upload_status).toBe('pending');
  });

  it('пропускает готовый файл и возвращает успех после временного сбоя', async () => {
    vi.useFakeTimers();
    const ready = { ...task, upload_status: 'ready' as const };
    const upload = vi.fn().mockRejectedValueOnce(new ApiNetworkError()).mockResolvedValue(ready);
    const result = uploadFilesWithRetry(
      [ready, { ...task, id: 9 }],
      upload,
      new AbortController().signal,
    );
    await vi.advanceTimersByTimeAsync(2000);
    expect((await result).map((row) => row.upload_status)).toEqual(['ready', 'ready']);
    expect(upload).toHaveBeenCalledTimes(2);
  });

  it.each([429, 503])(
    'учитывает Retry-After при%i и прекращает ожидание при уходе со страницы',
    async (status) => {
      vi.useFakeTimers();
      const controller = new AbortController();
      const upload = vi
        .fn()
        .mockRejectedValue(new ApiError(status, 'unavailable', 'failed', undefined, 12000));
      const result = uploadFilesWithRetry([task], upload, controller.signal);
      const rejected = expect(result).rejects.toMatchObject({ name: 'AbortError' });
      await vi.advanceTimersByTimeAsync(11000);
      expect(upload).toHaveBeenCalledTimes(1);
      controller.abort();
      await rejected;
      await vi.advanceTimersByTimeAsync(20000);
      expect(upload).toHaveBeenCalledTimes(1);
    },
  );
  it('различает содержимое одинаковых по имени и размеру файлов', async () => {
    vi.stubGlobal('crypto', webcrypto);
    try {
      const first = await prepareFile(new NodeFile(['answer'], 'x.txt') as unknown as File);
      const second = await prepareFile(new NodeFile(['other!'], 'x.txt') as unknown as File);
      expect(first.size_bytes).toBe(second.size_bytes);
      expect(first.content_sha256).not.toBe(second.content_sha256);
      expect(first.content_sha256).toMatch(/^[a-f0-9]{64}$/);
    } finally {
      vi.unstubAllGlobals();
    }
  });
});
