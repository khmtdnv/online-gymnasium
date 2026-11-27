import { zodResolver } from '@hookform/resolvers/zod';
import { useEffect, useRef, useState } from 'react';
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
import {
  type CreateLessonInput,
  type TeacherOption,
  type UpdateLessonInput,
  createLessonInputSchema,
} from './api';
import { textIdSchema } from './day-filters';
import { type SchoolPeriod, matchPeriod, periodToUtc } from './school-periods';
import { schoolDay, schoolTime } from './school-dates';

const schema = z.object({
  class_id: textIdSchema,
  teacher_id: z.uuid({ error: 'Введите UUID учителя из Gateway.' }),
  subject_id: textIdSchema,
  day: z.iso.date({ error: 'Введите корректную школьную дату урока.' }),
  period: z.string().regex(/^[1-7]$/, 'Выберите период урока.'),
});
type Fields = z.infer<typeof schema>;

export function LessonForm({
  lesson,
  classId,
  day,
  periods,
  presetPeriod,
  subjects,
  classes,
  searchTeachers,
  savingBlocked = false,
  onSubmit,
}: {
  lesson?: Lesson;
  classId: number | null;
  day: string;
  periods: SchoolPeriod[];
  presetPeriod?: SchoolPeriod;
  subjects?: { id: number; name: string | null }[];
  classes?: { id: number; name: string }[];
  searchTeachers?: (q: string, signal?: AbortSignal) => Promise<TeacherOption[]>;
  savingBlocked?: boolean;
  onSubmit: (
    input: CreateLessonInput | UpdateLessonInput,
    idempotencyKey?: string,
  ) => Promise<void>;
}) {
  const [failure, setFailure] = useState<unknown>(null);
  const [unknownResult, setUnknownResult] = useState(false);
  const [busy, setBusy] = useState(false);
  const [teacherQuery, setTeacherQuery] = useState('');
  const [teacherOptions, setTeacherOptions] = useState<TeacherOption[]>([]);
  const [teacherSearchError, setTeacherSearchError] = useState(false);
  const attempt = useRef<{ input: CreateLessonInput; key: string } | null>(null);

  // Урок редактируется по сетке: период подбирается по точному совпадению
  // сохранённого времени; вне сетки — период обязателен к выбору вручную.
  const storedPeriod = lesson ? matchPeriod(lesson.starts_at, lesson.ends_at, periods) : undefined;
  const offGrid = lesson !== undefined && storedPeriod === undefined;

  const {
    register,
    handleSubmit,
    watch,
    setValue,
    formState: { errors },
  } = useForm<Fields>({
    resolver: zodResolver(schema),
    defaultValues: {
      class_id: String(lesson?.class_id ?? classId ?? ''),
      teacher_id: String(lesson?.teacher_id ?? ''),
      subject_id: String(lesson?.subject_id ?? ''),
      day: lesson ? schoolDay(new Date(lesson.starts_at)) : day,
      period: lesson
        ? storedPeriod
          ? String(storedPeriod.number)
          : ''
        : presetPeriod
          ? String(presetPeriod.number)
          : '',
    },
  });

  // Поиск преподавателя по ФИО с задержкой; молча падает — ручной UUID остаётся запасным путём.
  const teacherValue = watch('teacher_id');
  const watchSubject = watch('subject_id');
  useEffect(() => {
    if (!searchTeachers || teacherQuery.trim().length < 2) {
      setTeacherOptions([]);
      return;
    }
    const controller = new AbortController();
    const timer = setTimeout(() => {
      searchTeachers(teacherQuery.trim(), controller.signal)
        .then((rows) => {
          setTeacherOptions(rows);
          setTeacherSearchError(false);
        })
        .catch(() => {
          if (!controller.signal.aborted) setTeacherSearchError(true);
        });
    }, 300);
    return () => {
      controller.abort();
      clearTimeout(timer);
    };
  }, [teacherQuery, searchTeachers]);
  const selectedTeacher = teacherOptions.find((row) => row.id === teacherValue);
  const selectedSubjectName = subjects?.find((row) => String(row.id) === watchSubject)?.name;
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
    const period = periods.find((item) => String(item.number) === values.period);
    if (!period) return;
    const interval = periodToUtc(values.day, period);
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
        {!lesson && (
          <>
            <div className="field">
              <label htmlFor="lesson-class_id">Класс</label>
              {classes && classes.length > 0 ? (
                <select id="lesson-class_id" className="input" {...register('class_id')}>
                  <option value="">Выберите класс</option>
                  {classes.map((item) => (
                    <option key={item.id} value={item.id}>
                      {item.name}
                    </option>
                  ))}
                </select>
              ) : (
                <Input id="lesson-class_id" inputMode="numeric" {...register('class_id')} />
              )}
              {errors.class_id && (
                <p className="field-error" id="lesson-class_id-error">
                  {errors.class_id.message}
                </p>
              )}
            </div>
            <div className="field">
              <label htmlFor="lesson-subject_id">Предмет</label>
              {subjects && subjects.length > 0 ? (
                <select id="lesson-subject_id" className="input" {...register('subject_id')}>
                  <option value="">Выберите предмет</option>
                  {subjects.map((item) => (
                    <option key={item.id} value={item.id}>
                      {item.name ?? `Предмет ${item.id}`}
                    </option>
                  ))}
                </select>
              ) : (
                <Input id="lesson-subject_id" inputMode="numeric" {...register('subject_id')} />
              )}
              {selectedSubjectName && <p className="field-hint">Выбрано: {selectedSubjectName}</p>}
              {errors.subject_id && (
                <p className="field-error" id="lesson-subject_id-error">
                  {errors.subject_id.message}
                </p>
              )}
            </div>
            <div className="field full-width">
              <label htmlFor={searchTeachers ? 'lesson-teacher-search' : 'lesson-teacher_id'}>
                Преподаватель
              </label>
              {searchTeachers ? (
                <>
                  <Input
                    id="lesson-teacher-search"
                    placeholder="Введите фамилию или имя (минимум 2 буквы)"
                    value={teacherQuery}
                    onChange={(event) => setTeacherQuery(event.target.value)}
                  />
                  {selectedTeacher ? (
                    <p className="field-hint">
                      Выбран: {selectedTeacher.full_name} ({selectedTeacher.email})
                    </p>
                  ) : (
                    <p className="field-hint">ID преподавателя: {teacherValue || 'не выбран'}</p>
                  )}
                  {teacherOptions.length > 0 && !selectedTeacher && (
                    <ul
                      className="teacher-options"
                      role="listbox"
                      aria-label="Найденные преподаватели"
                    >
                      {teacherOptions.map((row) => (
                        <li key={row.id}>
                          <button
                            type="button"
                            role="option"
                            aria-selected={false}
                            onClick={() => {
                              setValue('teacher_id', row.id, { shouldValidate: true });
                            }}
                          >
                            <strong>{row.full_name}</strong>
                            <span>{row.email}</span>
                          </button>
                        </li>
                      ))}
                    </ul>
                  )}
                  {teacherSearchError && (
                    <p className="field-hint">Поиск недоступен — введите UUID вручную ниже.</p>
                  )}
                  <details className="teacher-uuid-fallback">
                    <summary>Указать UUID вручную</summary>
                    <Input
                      id="lesson-teacher_id"
                      {...register('teacher_id')}
                      aria-invalid={!!errors.teacher_id}
                    />
                  </details>
                </>
              ) : (
                <Input
                  id="lesson-teacher_id"
                  placeholder="UUID преподавателя"
                  {...register('teacher_id')}
                  aria-invalid={!!errors.teacher_id}
                />
              )}
              {errors.teacher_id && (
                <p className="field-error" id="lesson-teacher_id-error">
                  {errors.teacher_id.message}
                </p>
              )}
            </div>
          </>
        )}
        <div className="field">
          <label htmlFor="lesson-day">Дата · школа</label>
          <Input
            id="lesson-day"
            type="date"
            {...register('day')}
            aria-invalid={!!errors.day}
            aria-describedby={errors.day ? 'lesson-day-error' : undefined}
          />
          {errors.day && (
            <p className="field-error" id="lesson-day-error">
              {errors.day.message}
            </p>
          )}
        </div>
        <div className="field">
          <label htmlFor="lesson-period">Период</label>
          <select
            id="lesson-period"
            className="input"
            {...register('period')}
            aria-invalid={!!errors.period}
            aria-describedby={
              errors.period ? 'lesson-period-error' : offGrid ? 'lesson-period-offgrid' : undefined
            }
          >
            <option value="">{periods.length ? 'Выберите период' : 'Периоды недоступны'}</option>
            {periods.map((item) => (
              <option key={item.number} value={item.number}>
                {item.number} · {item.start_at}–{item.end_at}
              </option>
            ))}
          </select>
          {offGrid && (
            <p className="field-hint" id="lesson-period-offgrid">
              Урок вне сетки (старое время {schoolTime(lesson.starts_at)}). Сохранить можно только
              выбрав период.
            </p>
          )}
          {errors.period && (
            <p className="field-error" id="lesson-period-error">
              {errors.period.message}
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
