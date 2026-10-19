import { zodResolver } from '@hookform/resolvers/zod';
import { useRef, useState } from 'react';
import { useForm } from 'react-hook-form';
import { z } from 'zod';
import { Alert } from '../../components/ui/alert';
import { Button } from '../../components/ui/button';
import { Input } from '../../components/ui/input';
import type { Lesson } from '../../lib/api/contracts';
import {
  ApiError,
  ApiNetworkError,
  ApiProtocolError,
  errorRequestId,
  explainError,
} from '../../lib/api/errors';
import { type CreateLessonInput, type UpdateLessonInput, createLessonInputSchema } from './api';
import { textIdSchema } from './day-filters';
import { isoToUtcInput, utcInputToIso } from './utc';

const schema = z
  .object({
    class_id: textIdSchema,
    teacher_id: z.uuid({ error: 'Введите UUID учителя из Gateway.' }),
    subject_id: textIdSchema,
    starts_at: z.string(),
    ends_at: z.string(),
  })
  .superRefine((values, context) => {
    try {
      const start = utcInputToIso(values.starts_at);
      const end = utcInputToIso(values.ends_at);
      if (start >= end || start.slice(0, 10) !== end.slice(0, 10))
        context.addIssue({
          code: 'custom',
          path: ['ends_at'],
          message: 'Конец должен быть позже начала в тот же день UTC.',
        });
    } catch {
      context.addIssue({
        code: 'custom',
        path: ['starts_at'],
        message: 'Введите корректную дату и время UTC.',
      });
    }
  });
type Fields = z.infer<typeof schema>;

export function LessonForm({
  lesson,
  classId,
  day,
  savingBlocked = false,
  onSubmit,
}: {
  lesson?: Lesson;
  classId: number | null;
  day: string;
  savingBlocked?: boolean;
  onSubmit: (
    input: CreateLessonInput | UpdateLessonInput,
    idempotencyKey?: string,
  ) => Promise<void>;
}) {
  const [failure, setFailure] = useState<unknown>(null);
  const [unknownResult, setUnknownResult] = useState(false);
  const [busy, setBusy] = useState(false);
  const attempt = useRef<{ input: CreateLessonInput; key: string } | null>(null);
  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<Fields>({
    resolver: zodResolver(schema),
    defaultValues: {
      class_id: String(lesson?.class_id ?? classId ?? ''),
      teacher_id: String(lesson?.teacher_id ?? ''),
      subject_id: String(lesson?.subject_id ?? ''),
      starts_at: lesson ? isoToUtcInput(lesson.starts_at) : `${day}T09:00`,
      ends_at: lesson ? isoToUtcInput(lesson.ends_at) : `${day}T09:45`,
    },
  });
  async function run(input: CreateLessonInput | UpdateLessonInput, key?: string) {
    setBusy(true);
    setFailure(null);
    try {
      await onSubmit(input, key);
      setUnknownResult(false);
    } catch (error) {
      setFailure(error);
      setUnknownResult(
        !lesson &&
          (error instanceof ApiNetworkError ||
            error instanceof ApiProtocolError ||
            (error instanceof ApiError && error.status >= 500)),
      );
    } finally {
      setBusy(false);
    }
  }
  async function submit(values: Fields) {
    const interval = {
      starts_at: utcInputToIso(values.starts_at),
      ends_at: utcInputToIso(values.ends_at),
    };
    if (lesson) return run({ ...interval, expected_version: lesson.version });
    const input = createLessonInputSchema.parse({
      ...interval,
      class_id: Number(values.class_id),
      teacher_id: values.teacher_id,
      subject_id: Number(values.subject_id),
    });
    attempt.current = { input, key: crypto.randomUUID() };
    await run(input, attempt.current.key);
  }
  return (
    <form className="form-stack" noValidate onSubmit={handleSubmit(submit)}>
      {failure !== null && (
        <Alert tone="error" requestId={errorRequestId(failure)}>
          {unknownResult
            ? 'Результат отправки неизвестен. Повтор той же попытки сохранит ключ и прежние данные.'
            : explainError(failure)}
        </Alert>
      )}
      <fieldset
        disabled={busy || unknownResult}
        className="form-grid"
        style={{ border: 0, padding: 0, margin: 0 }}
      >
        {!lesson &&
          (['class_id', 'teacher_id', 'subject_id'] as const).map((name) => (
            <div className="field" key={name}>
              <label htmlFor={`lesson-${name}`}>
                {name === 'class_id'
                  ? 'ID класса'
                  : name === 'teacher_id'
                    ? 'ID учителя'
                    : 'ID предмета'}
              </label>
              <Input
                id={`lesson-${name}`}
                inputMode={name === 'teacher_id' ? 'text' : 'numeric'}
                {...register(name)}
                aria-invalid={!!errors[name]}
                aria-describedby={errors[name] ? `lesson-${name}-error` : undefined}
              />
              {errors[name] && (
                <p className="field-error" id={`lesson-${name}-error`}>
                  {errors[name]?.message}
                </p>
              )}
            </div>
          ))}
        <div className="field full-width">
          <label htmlFor="lesson-start">Начало · UTC</label>
          <Input
            id="lesson-start"
            type="datetime-local"
            {...register('starts_at')}
            aria-invalid={!!errors.starts_at}
            aria-describedby={errors.starts_at ? 'lesson-start-error' : undefined}
          />
          {errors.starts_at && (
            <p className="field-error" id="lesson-start-error">
              {errors.starts_at.message}
            </p>
          )}
        </div>
        <div className="field full-width">
          <label htmlFor="lesson-end">Окончание · UTC</label>
          <Input
            id="lesson-end"
            type="datetime-local"
            {...register('ends_at')}
            aria-invalid={!!errors.ends_at}
            aria-describedby={errors.ends_at ? 'lesson-end-error' : undefined}
          />
          {errors.ends_at && (
            <p className="field-error" id="lesson-end-error">
              {errors.ends_at.message}
            </p>
          )}
        </div>
      </fieldset>
      <div className="form-actions">
        {unknownResult ? (
          <>
            <Button
              disabled={busy}
              onClick={() => {
                if (attempt.current) void run(attempt.current.input, attempt.current.key);
              }}
            >
              Повторить ту же попытку
            </Button>
            <Button
              variant="secondary"
              disabled={busy}
              onClick={() => {
                attempt.current = null;
                setUnknownResult(false);
                setFailure(null);
              }}
            >
              Новая попытка с изменением данных
            </Button>
          </>
        ) : (
          <Button type="submit" disabled={busy || savingBlocked}>
            {busy ? 'Сохраняем…' : lesson ? 'Сохранить перенос' : 'Создать урок'}
          </Button>
        )}
      </div>
    </form>
  );
}
