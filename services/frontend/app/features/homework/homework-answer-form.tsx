import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useRef, useState, type FormEvent } from 'react';
import { Alert } from '../../components/ui/alert';
import { Button } from '../../components/ui/button';
import { ApiError, ApiNetworkError, ApiProtocolError, explainError } from '../../lib/api/errors';
import { schoolDatetime } from '../schedule/school-dates';
import type {
  HomeworkAnswer,
  HomeworkAnswerFile,
  HomeworkApi,
  HomeworkFile,
  SubmitHomeworkAnswerInput,
} from './api';
import { prepareFile, uploadFilesWithRetry } from './file-upload';
import { HomeworkFiles } from './homework-files';

/** Те же безопасные скачивания, но отдельный путь приватной попытки. */
export function HomeworkAnswerFiles({
  answer,
  api,
  busy = false,
  onRetry,
}: {
  answer: HomeworkAnswer;
  api: HomeworkApi;
  busy?: boolean;
  onRetry?: (file: HomeworkAnswerFile, selected: File) => Promise<void>;
}) {
  const files = answer.files.map((file) => ({ ...file, homework_id: answer.homework_id }));
  const actual = (file: HomeworkFile) => answer.files.find((row) => row.id === file.id)!;
  return (
    <HomeworkFiles
      files={files}
      busy={busy}
      api={{
        ...api,
        downloadHomeworkFile: (file, signal) =>
          api.downloadAnswerFile(answer.homework_id, actual(file), signal),
      }}
      onRetry={onRetry ? (file, selected) => onRetry(actual(file), selected) : undefined}
    />
  );
}

/** Неизменяемая попытка и решение преподавателя, без внутреннего ключа отправки. */
export function HomeworkAnswerCard({
  answer,
  api,
  children,
}: {
  answer: HomeworkAnswer;
  api: HomeworkApi;
  children?: React.ReactNode;
}) {
  return (
    <article className="card homework-answer-card">
      <h3>
        Попытка №{answer.attempt_number} · {answer.student_name}
      </h3>
      <p className="homework-answer-meta">
        <span>Сдано {schoolDatetime(answer.submitted_at)}</span>
        <span className={`homework-answer-chip is-${answer.status}`}>
          {
            { submitted: 'На проверке', returned: 'Нужно исправить', graded: 'Проверено' }[
              answer.status
            ]
          }
        </span>
      </p>
      {answer.answer_text && (
        <blockquote className="homework-answer-text">
          <p style={{ whiteSpace: 'pre-wrap' }}>{answer.answer_text}</p>
        </blockquote>
      )}
      {answer.grade !== null && (
        <p className="homework-answer-grade">
          <strong>Оценка: {answer.grade}</strong>
        </p>
      )}
      {answer.teacher_comment && (
        <p className="homework-answer-comment" style={{ whiteSpace: 'pre-wrap' }}>
          Комментарий преподавателя: {answer.teacher_comment}
        </p>
      )}
      <HomeworkAnswerFiles answer={answer} api={api} />
      {children}
    </article>
  );
}

/** Сохраняет один payload/key до подтверждения; файлы загружает отдельно. */
export function HomeworkAnswerForm({ homeworkId, api }: { homeworkId: number; api: HomeworkApi }) {
  const cache = useQueryClient();
  const [offset, setOffset] = useState(0);
  const query = useQuery({
    queryKey: ['homework', 'answers', homeworkId, 'student', offset],
    queryFn: ({ signal }) => api.listAnswers(homeworkId, { offset }, signal),
  });
  // Последняя попытка определяет право сдачи, даже при просмотре старой страницы.
  const latest = useQuery({
    queryKey: ['homework', 'answers', homeworkId, 'latest'],
    queryFn: ({ signal }) => api.listAnswers(homeworkId, {}, signal),
  });
  const [text, setText] = useState('');
  const [files, setFiles] = useState<File[]>([]);
  const [saved, setSaved] = useState<HomeworkAnswer | null>(null);
  const [busy, setBusy] = useState(false);
  const [uncertain, setUncertain] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const active = useRef<AbortController | null>(null);
  const pending = useRef<{ key: string; body: SubmitHomeworkAnswerInput; files: File[] } | null>(
    null,
  );
  useEffect(() => () => active.current?.abort(), []);
  const refresh = () => cache.invalidateQueries({ queryKey: ['homework', 'answers', homeworkId] });
  const current = latest.data?.[0];
  const visibleCurrent =
    saved && saved.id === current?.id && current.status === 'submitted' ? saved : current;
  const canSubmit = latest.isSuccess && (!current || current.status === 'returned');

  async function sendFiles(answer: HomeworkAnswer, selected: File[], signal: AbortSignal) {
    const rows = await uploadFilesWithRetry(
      answer.files.map((file, index) => ({
        ...file,
        homework_id: homeworkId,
        file: selected[index],
      })),
      async (task, file, abort) => {
        const original = answer.files.find((row) => row.id === task.id)!;
        return {
          ...(await api.uploadAnswerFile(homeworkId, original, file, abort)),
          homework_id: homeworkId,
        };
      },
      signal,
      (file, failure) => {
        setSaved((previous) => ({
          ...(previous ?? answer),
          files: (previous ?? answer).files.map((row) =>
            row.id === file.id ? { ...row, upload_status: file.upload_status } : row,
          ),
        }));
        if (failure)
          setError(
            `Ответ сохранён, но файл ${file.file_name} не загружен. ${explainError(failure)} Выберите исходный файл и повторите загрузку.`,
          );
      },
    );
    setSaved((previous) => ({
      ...(previous ?? answer),
      files: (previous ?? answer).files.map((file) => ({
        ...file,
        upload_status: rows.find((row) => row.id === file.id)?.upload_status ?? file.upload_status,
      })),
    }));
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (active.current || (!canSubmit && !uncertain)) return;
    const controller = new AbortController();
    active.current = controller;
    setBusy(true);
    setError(null);
    let sent = false;
    try {
      if (!pending.current) {
        if (files.length > 5) throw new Error('Можно прикрепить не более 5 файлов.');
        const metadata = [];
        for (const file of files) {
          metadata.push(await prepareFile(file));
          controller.signal.throwIfAborted();
        }
        if (!text.trim() && !metadata.length)
          throw new Error('Напишите ответ или прикрепите файл.');
        pending.current = {
          key: crypto.randomUUID(),
          body: { answer_text: text.trim(), files: metadata },
          files,
        };
      }
      sent = true;
      const result = await api.submitAnswer(
        homeworkId,
        pending.current.key,
        pending.current.body,
        controller.signal,
      );
      controller.signal.throwIfAborted();
      setSaved(result);
      setUncertain(false);
      await sendFiles(result, pending.current.files, controller.signal);
      pending.current = null;
      await refresh();
    } catch (error) {
      if (!controller.signal.aborted) {
        const unknown =
          sent &&
          (error instanceof ApiNetworkError ||
            error instanceof ApiProtocolError ||
            (error instanceof ApiError && error.status >= 500));
        setUncertain(unknown);
        if (!unknown) pending.current = null;
        setError(
          unknown
            ? 'Результат отправки не подтверждён. Повторите отправку: ключ и содержимое сохранены, второй попытки не появится.'
            : error instanceof Error && !(error instanceof ApiError)
              ? error.message
              : explainError(error),
        );
        if (error instanceof ApiError && error.status === 409) await refresh();
      }
    } finally {
      active.current = null;
      if (!controller.signal.aborted) setBusy(false);
    }
  }

  async function retry(file: HomeworkAnswerFile, selected: File) {
    if (active.current || !current || current.status !== 'submitted') return;
    const controller = new AbortController();
    active.current = controller;
    setBusy(true);
    setError(null);
    try {
      const metadata = await prepareFile(selected);
      controller.signal.throwIfAborted();
      if (
        metadata.file_name !== file.file_name ||
        metadata.size_bytes !== file.size_bytes ||
        metadata.content_type !== file.content_type
      )
        throw new Error('Выберите тот же исходный файл.');
      const result = await api.uploadAnswerFile(homeworkId, file, selected, controller.signal);
      if (saved)
        setSaved({
          ...saved,
          files: saved.files.map((row) => (row.id === result.id ? result : row)),
        });
      await refresh();
    } catch (error) {
      if (!controller.signal.aborted) setError(explainError(error));
    } finally {
      active.current = null;
      if (!controller.signal.aborted) setBusy(false);
    }
  }

  return (
    <section className="card">
      <h2>Моя работа</h2>
      <Button
        variant="secondary"
        disabled={busy || query.isFetching}
        onClick={() => void refresh()}
      >
        Обновить ответы
      </Button>
      {(query.isPending || latest.isPending) && <p role="status">Загружаем ответы…</p>}
      {(query.isError || latest.isError) && (
        <Alert tone="error">{explainError(query.error ?? latest.error)}</Alert>
      )}
      {error && <Alert tone="error">{error}</Alert>}
      {query.isSuccess && !query.data.length && <p>Вы ещё не сдавали работу.</p>}
      {(canSubmit || uncertain) && (
        <form
          className="homework-form homework-answer-form"
          onSubmit={(event) => void submit(event)}
        >
          <label>
            Ваш ответ
            <textarea
              className="input"
              maxLength={10000}
              value={text}
              disabled={busy || uncertain}
              onChange={(event) => setText(event.target.value)}
            />
          </label>
          <span className="review-form-counter" aria-hidden="true">
            {text.length} / 10000 симв.
          </span>
          <label>
            Файлы ответа
            <input
              type="file"
              multiple
              accept=".pdf,.docx,.xlsx,.pptx,.jpg,.jpeg,.png,.txt"
              disabled={busy || uncertain}
              onChange={(event) => setFiles(Array.from(event.target.files ?? []))}
            />
          </label>
          <p>До 5 файлов по 10 МиБ. Сдать можно и после срока.</p>
          <Button type="submit" disabled={busy}>
            {busy ? 'Отправляем…' : uncertain ? 'Повторить отправку' : 'Сдать работу'}
          </Button>
        </form>
      )}
      {saved && (
        <Alert tone="success">
          Ответ сохранён. {busy ? 'Загружаем файлы — не закрывайте страницу.' : ''}
        </Alert>
      )}
      {current?.status === 'submitted' && (
        <p>Работа ожидает проверки. Новая попытка доступна после возврата.</p>
      )}
      {current?.status === 'graded' && <p>Работа проверена. Повторная сдача не требуется.</p>}
      {visibleCurrent?.status === 'submitted' &&
        visibleCurrent.files.some((file) => file.upload_status === 'pending') && (
          <HomeworkAnswerFiles answer={visibleCurrent} api={api} busy={busy} onRetry={retry} />
        )}
      {(query.data ?? []).map((answer) => (
        <HomeworkAnswerCard
          key={answer.id}
          answer={saved?.id === answer.id && answer.status === 'submitted' ? saved : answer}
          api={api}
        />
      ))}
      {query.isSuccess && (
        <div>
          <Button
            variant="secondary"
            disabled={offset === 0 || busy}
            onClick={() => setOffset(Math.max(0, offset - 50))}
          >
            Предыдущие
          </Button>{' '}
          <Button
            variant="secondary"
            disabled={query.data.length < 50 || busy}
            onClick={() => setOffset(offset + 50)}
          >
            Следующие
          </Button>
        </div>
      )}
    </section>
  );
}
