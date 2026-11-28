import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useState, type FormEvent } from 'react';
import { Alert } from '../../components/ui/alert';
import { Button } from '../../components/ui/button';
import { explainError } from '../../lib/api/errors';
import type { AttendanceStatus, DiaryApi, GradeKind, LessonRecordResult } from './api';
import { attendanceStatusLabel, gradeKindLabel } from './labels';

const ATTENDANCE_OPTIONS: Array<AttendanceStatus | 'unmarked'> = [
  'present',
  'absent_sick',
  'absent_excused',
  'absent_unexcused',
  'unmarked',
];
const GRADE_KINDS: GradeKind[] = ['oral', 'written', 'control'];
const GRADE_VALUES = [5, 4, 3, 2] as const;

interface GradeSlot {
  kind: GradeKind | '';
  grade: number;
}

interface StudentRow {
  studentId: string;
  name: string;
  attendance: AttendanceStatus | 'unmarked';
  slots: [GradeSlot, GradeSlot];
}

/** Собирает строки формы из ростера и сохранённых записей урока. */
function buildRows(
  roster: Array<{ id: string; name: string }>,
  entries: LessonRecordResult,
): StudentRow[] {
  const attendance = new Map(
    entries.attendance.map((row) => [row.student_id, row.status]),
  );
  const grades = new Map<string, GradeSlot[]>();
  for (const row of entries.grades) {
    const list = grades.get(row.student_id) ?? [];
    list.push({ kind: row.kind, grade: row.grade });
    grades.set(row.student_id, list);
  }
  return roster.map((student) => {
    const saved = grades.get(student.id) ?? [];
    return {
      studentId: student.id,
      name: student.name,
      attendance: attendance.get(student.id) ?? 'unmarked',
      slots: [
        saved[0] ?? { kind: '', grade: 5 },
        saved[1] ?? { kind: '', grade: 5 },
      ],
    };
  });
}

/**
 * Форма записи урока: посещаемость с причиной и не более двух оценок
 * с типом на ученика. Одна кнопка сохранения отправляет пакет-замену;
 * повтор сети не создаёт дублей — сервер заменяет записи урока.
 */
export function LessonRecordForm({
  lessonId,
  teacherId,
  lesson,
  roster,
  api,
}: {
  lessonId: number;
  teacherId: string;
  lesson: { class_id: number; subject_id: number; lesson_date: string };
  roster: Array<{ id: string; name: string }>;
  api: Pick<DiaryApi, 'getLessonEntries' | 'recordLessonEntries'>;
}) {
  const queryClient = useQueryClient();
  const entries = useQuery({
    queryKey: ['lesson-entries', lessonId],
    queryFn: ({ signal }) => api.getLessonEntries(lessonId, signal),
  });
  const [rows, setRows] = useState<StudentRow[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Первичная инициализация строк из сохранённых записей; ростер — каркас.
  useEffect(() => {
    if (rows !== null || !entries.data) return;
    setRows(buildRows(roster, entries.data));
  }, [entries.data, roster, rows]);

  function updateRow(studentId: string, patch: Partial<StudentRow>) {
    setRows((previous) =>
      (previous ?? []).map((row) =>
        row.studentId === studentId ? { ...row, ...patch } : row,
      ),
    );
  }

  function updateSlot(studentId: string, slotIndex: number, patch: Partial<GradeSlot>) {
    setRows((previous) =>
      (previous ?? []).map((row) => {
        if (row.studentId !== studentId) return row;
        const slots: [GradeSlot, GradeSlot] = [row.slots[0], row.slots[1]];
        slots[slotIndex] = { ...slots[slotIndex], ...patch };
        return { ...row, slots };
      }),
    );
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy || !rows) return;
    setError(null);
    setSaved(false);
    const attendance: Array<{ student_id: string; status: AttendanceStatus }> = [];
    const grades: Array<{ student_id: string; kind: GradeKind; grade: number }> = [];
    for (const row of rows) {
      const marked = row.slots.filter(
        (slot): slot is GradeSlot & { kind: GradeKind } => slot.kind !== '',
      );
      if (marked.length === 2 && marked[0].kind === marked[1].kind) {
        setError(`«${row.name}»: типы двух оценок должны различаться.`);
        return;
      }
      if (row.attendance !== 'present' && marked.length > 0) {
        setError(`«${row.name}»: оценка ставится только присутствовавшему ученику.`);
        return;
      }
      if (row.attendance !== 'unmarked') {
        attendance.push({ student_id: row.studentId, status: row.attendance });
      }
      for (const slot of marked) {
        grades.push({ student_id: row.studentId, kind: slot.kind, grade: slot.grade });
      }
    }
    setBusy(true);
    try {
      const result = await api.recordLessonEntries({
        lesson_id: lessonId,
        context: {
          class_id: lesson.class_id,
          subject_id: lesson.subject_id,
          lesson_date: lesson.lesson_date,
          status: 'planned',
          teacher_id: teacherId,
        },
        attendance,
        grades,
      });
      setRows(buildRows(roster, result));
      setSaved(true);
      void queryClient.invalidateQueries({ queryKey: ['lesson-entries', lessonId] });
    } catch (failure) {
      // Замена на сервере делает повтор безопасным: дублей не будет.
      setError(
        `Не удалось сохранить записи. ${explainError(failure)} Повторная отправка заменит записи урока и дублей не создаст.`,
      );
    } finally {
      setBusy(false);
    }
  }

  if (entries.isPending) return <p role="status">Загружаем записи урока…</p>;
  if (entries.isError)
    return (
      <Alert tone="error">
        Не удалось загрузить записи урока.{' '}
        <Button
          variant="secondary"
          disabled={entries.isFetching}
          onClick={() => void entries.refetch()}
        >
          Повторить
        </Button>
      </Alert>
    );
  if (!rows) return <p role="status">Загружаем записи урока…</p>;
  if (rows.length === 0) return <p>В классе нет учеников для записи.</p>;

  return (
    <form className="lesson-record-form" onSubmit={submit} data-testid="lesson-record-form">
      {error && (
        <Alert tone="error">{error}</Alert>
      )}
      {saved && (
        <p role="status" className="lesson-record-saved">
          Записи урока сохранены.
        </p>
      )}
      <div className="lesson-record-wrap">
        <table className="lesson-record-table">
          <thead>
            <tr>
              <th scope="col">Ученик</th>
              <th scope="col">Посещаемость</th>
              <th scope="col">Оценка 1</th>
              <th scope="col">Оценка 2</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.studentId}>
                <th scope="row">{row.name}</th>
                <td>
                  <div
                    className="lesson-record-radios"
                    role="radiogroup"
                    aria-label={`Посещаемость: ${row.name}`}
                  >
                    {ATTENDANCE_OPTIONS.map((option) => (
                      <label key={option} className="lesson-record-option">
                        <input
                          type="radio"
                          name={`attendance-${row.studentId}`}
                          value={option}
                          checked={row.attendance === option}
                          onChange={() => updateRow(row.studentId, { attendance: option })}
                        />
                        <span>{option === 'unmarked' ? 'не отмечено' : attendanceStatusLabel[option]}</span>
                      </label>
                    ))}
                  </div>
                </td>
                {([0, 1] as const).map((slotIndex) => {
                  const slot = row.slots[slotIndex];
                  return (
                    <td key={slotIndex} className="lesson-record-grade">
                      <select
                        aria-label={`Оценка ${slotIndex + 1}: тип — ${row.name}`}
                        value={slot.kind}
                        onChange={(event) =>
                          updateSlot(row.studentId, slotIndex, {
                            kind: event.target.value as GradeKind | '',
                          })
                        }
                      >
                        <option value="">—</option>
                        {GRADE_KINDS.map((kind) => (
                          <option key={kind} value={kind}>
                            {gradeKindLabel[kind]}
                          </option>
                        ))}
                      </select>
                      <select
                        aria-label={`Оценка ${slotIndex + 1}: балл — ${row.name}`}
                        value={slot.kind ? String(slot.grade) : ''}
                        disabled={!slot.kind}
                        onChange={(event) =>
                          updateSlot(row.studentId, slotIndex, {
                            grade: Number(event.target.value),
                          })
                        }
                      >
                        <option value="">—</option>
                        {GRADE_VALUES.map((value) => (
                          <option key={value} value={value}>
                            {value}
                          </option>
                        ))}
                      </select>
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <Button type="submit" disabled={busy}>
        {busy ? 'Сохраняем…' : 'Сохранить записи урока'}
      </Button>
    </form>
  );
}
