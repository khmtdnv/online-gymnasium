import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { Link, useParams } from 'react-router';
import { Alert } from '../components/ui/alert';
import { PageHeader } from '../components/page-header';
import { useSession } from '../features/auth/session-context';
import { PenCanvas } from '../features/pen/pen-canvas';
import { useFeatures } from '../lib/api/context';
import { explainError } from '../lib/api/errors';

export default function PenPage() {
  const { state } = useSession();
  const { pen } = useFeatures();
  const lessonId = Number(useParams().lessonId);
  const valid = Number.isInteger(lessonId) && lessonId > 0 && lessonId <= 2147483647;
  const teacher = state.status === 'authenticated' && state.user.role === 'teacher';
  const student = state.status === 'authenticated' && state.user.role === 'student';
  const [selected, setSelected] = useState('');
  const students = useQuery({
    queryKey: ['pen-students', lessonId],
    enabled: valid && teacher,
    queryFn: ({ signal }) => pen.listStudents(lessonId, signal),
  });
  if (!valid) return <Alert tone="error">Некорректный урок.</Alert>;
  if (!teacher && !student) return <Alert>Ручка доступна ученику и преподавателю.</Alert>;
  const studentId =
    student && state.status === 'authenticated'
      ? state.user.id
      : (students.data?.find((row) => row.id === selected)?.id ?? students.data?.[0]?.id);
  return (
    <div className="workspace-page pen-page">
      <Link className="workspace-back" to={`/lessons/${lessonId}`}>
        ← К уроку
      </Link>
      <PageHeader
        title="Умная ручка"
        description={
          teacher
            ? 'Смотрите записи ученика во время урока.'
            : 'Пишите мышью, пальцем или стилусом — преподаватель увидит ваши записи.'
        }
      />
      {teacher && (
        <section className="workspace-panel pen-student-picker">
          <label>
            Ученик{' '}
            <select
              className="input"
              value={studentId ?? ''}
              onChange={(event) => setSelected(event.target.value)}
              disabled={!students.data?.length}
            >
              {!students.data?.length && <option value="">Нет доступных учеников</option>}
              {students.data?.map((row) => (
                <option key={row.id} value={row.id}>
                  {row.name}
                </option>
              ))}
            </select>
          </label>
          {students.isPending && <p>Загружаем состав класса…</p>}
          {students.isError && <Alert tone="error">{explainError(students.error)}</Alert>}
        </section>
      )}
      {studentId && (
        <PenCanvas
          key={`${lessonId}:${studentId}`}
          lessonId={lessonId}
          studentId={studentId}
          readonly={teacher}
        />
      )}
    </div>
  );
}
