import { useEffect, useRef, useState, type FormEvent } from 'react';
import { Alert } from '../../components/ui/alert';
import { Button } from '../../components/ui/button';
import { Input } from '../../components/ui/input';
import type { Lesson } from '../../lib/api/contracts';
import { ApiError, ApiNetworkError, ApiProtocolError, explainError } from '../../lib/api/errors';
import type { Homework, HomeworkApi, HomeworkFile, HomeworkFileInput } from './api';
import { prepareFile, uploadFilesWithRetry, type UploadTask } from './file-upload';
import { HomeworkFiles } from './homework-files';

/** Одна кнопка создаёт текст и резервации один раз, затем отдельно догружает байты. */
export function HomeworkForm({
  lessonId,
  nextLesson,
  homework,
  api,
  onCreated,
}: {
  lessonId: number;
  nextLesson: Lesson | null;
  homework?: Homework;
  api: HomeworkApi;
  onCreated?: () => void;
}) {
  const [description, setDescription] = useState('');
  const [mode, setMode] = useState<'lesson' | 'manual'>(nextLesson ? 'lesson' : 'manual');
  const [manual, setManual] = useState('');
  const [files, setFiles] = useState<File[]>([]);
  const [created, setCreated] = useState<Homework | undefined>();
  const [busy, setBusy] = useState(false);
  const [uncertain, setUncertain] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const active = useRef<AbortController | null>(null);
  const expected = useRef<Record<number, HomeworkFileInput>>({});
  const saved = created ?? homework;
  useEffect(() => () => active.current?.abort(), []);

  async function sendFiles(tasks: UploadTask[], parent: Homework, signal: AbortSignal) {
    const results = await uploadFilesWithRetry(
      tasks,
      api.uploadHomeworkFile,
      signal,
      (result, failure) => {
        setCreated((previous) => ({
          ...(previous ?? parent),
          files: (previous ?? parent).files.map((file) => (file.id === result.id ? result : file)),
        }));
        if (failure)
          setError(
            `Не удалось загрузить ${result.file_name}. ${explainError(failure)} Можно выбрать исходный файл и повторить.`,
          );
      },
    );
    setCreated((previous) => ({
      ...(previous ?? parent),
      files: (previous ?? parent).files.map(
        (file) => results.find((row) => row.id === file.id) ?? file,
      ),
    }));
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (active.current || saved || uncertain) return;
    const controller = new AbortController();
    active.current = controller;
    setBusy(true);
    setError(null);
    let submitted = false;
    try {
      if (files.length > 5) throw new Error('Можно прикрепить не более 5 файлов.');
      const metadata: HomeworkFileInput[] = [];
      for (const file of files) {
        metadata.push(await prepareFile(file));
        controller.signal.throwIfAborted();
      }
      const deadline =
        mode === 'lesson' && nextLesson
          ? { due_lesson_id: nextLesson.id }
          : { manual_due_datetime: new Date(manual).toISOString() };
      submitted = true;
      const result = await api.createHomework(
        lessonId,
        { description: description.trim(), ...deadline, files: metadata },
        controller.signal,
      );
      controller.signal.throwIfAborted();
      setCreated(result);
      result.files.forEach((file, index) => {
        expected.current[file.id] = metadata[index];
      });
      await sendFiles(
        result.files.map((file, index) => ({ ...file, file: files[index] })),
        result,
        controller.signal,
      );
      onCreated?.();
    } catch (error) {
      if (!controller.signal.aborted) {
        const unknown =
          submitted &&
          (error instanceof ApiNetworkError ||
            error instanceof ApiProtocolError ||
            (error instanceof ApiError && (error.status >= 500 || error.status === 409)));
        if (unknown && !saved) {
          setUncertain(true);
          setError(
            'Результат создания не подтверждён. Обновите карточку урока перед новой попыткой: задание могло сохраниться.',
          );
        } else
          setError(
            error instanceof Error && !(error instanceof ApiError)
              ? error.message
              : explainError(error),
          );
      }
    } finally {
      active.current = null;
      if (!controller.signal.aborted) setBusy(false);
    }
  }

  async function retry(file: HomeworkFile, selected: File) {
    if (active.current || !saved) return;
    const controller = new AbortController();
    active.current = controller;
    setBusy(true);
    setError(null);
    try {
      const metadata = await prepareFile(selected);
      controller.signal.throwIfAborted();
      const original = expected.current[file.id];
      if (
        metadata.file_name !== file.file_name ||
        metadata.size_bytes !== file.size_bytes ||
        metadata.content_type !== file.content_type ||
        (original && metadata.content_sha256 !== original.content_sha256)
      )
        throw new Error(
          'Выберите тот же исходный файл. Имя, размер и содержимое должны совпадать.',
        );
      // После reload digest не публикуется: исходные байты дополнительно сверяет Homework.
      await sendFiles([{ ...file, file: selected }], saved, controller.signal);
      onCreated?.();
    } catch (error) {
      if (!controller.signal.aborted)
        setError(error instanceof Error ? error.message : explainError(error));
    } finally {
      active.current = null;
      if (!controller.signal.aborted) setBusy(false);
    }
  }

  return (
    <section className="card">
      <h2>{saved ? 'Задано на этом уроке' : 'Задать домашнее задание'}</h2>
      {error && <Alert tone="error">{error}</Alert>}
      {saved ? (
        <>
          {created && <Alert tone="success">Задание создано и доступно ученикам.</Alert>}
          <p style={{ whiteSpace: 'pre-wrap' }}>{saved.description}</p>
          {busy && (
            <p role="status">
              Загружаем файлы. Не закрывайте страницу; текст задания уже доступен.
            </p>
          )}
          <HomeworkFiles files={saved.files} api={api} onRetry={retry} busy={busy} />
        </>
      ) : (
        <form className="homework-form" onSubmit={(event) => void submit(event)}>
          <label>
            Что нужно выполнить
            <textarea
              className="input"
              required
              maxLength={10000}
              value={description}
              disabled={busy || uncertain}
              onChange={(event) => setDescription(event.target.value)}
            />
          </label>
          <label>
            Срок сдачи
            <select
              className="input"
              value={mode}
              disabled={busy || uncertain}
              onChange={(event) => setMode(event.target.value as 'lesson' | 'manual')}
            >
              {nextLesson && (
                <option value="lesson">
                  К следующему уроку · {new Date(nextLesson.starts_at).toLocaleString('ru-RU')}
                </option>
              )}
              <option value="manual">Указать дату и время вручную</option>
            </select>
          </label>
          {mode === 'manual' && (
            <label>
              Дата и время сдачи (ваш часовой пояс)
              <Input
                type="datetime-local"
                required
                value={manual}
                disabled={busy || uncertain}
                onChange={(event) => setManual(event.target.value)}
              />
            </label>
          )}
          <label>
            Файлы задания
            <Input
              type="file"
              multiple
              accept=".pdf,.docx,.xlsx,.pptx,.jpg,.jpeg,.png,.txt"
              disabled={busy || uncertain}
              onChange={(event) => setFiles(Array.from(event.target.files ?? []))}
            />
          </label>
          <p>До 5 файлов по 10 МиБ. При сбое загрузки текст задания останется доступен ученикам.</p>
          <Button type="submit" disabled={busy || uncertain}>
            {busy ? 'Сохраняем…' : 'Задать ДЗ'}
          </Button>
        </form>
      )}
    </section>
  );
}
