import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { ArrowLeft, Users } from 'lucide-react';
import { Link, useParams } from 'react-router';
import { Alert } from '../components/ui/alert';
import { PageHeader } from '../components/page-header';
import { useSession } from '../features/auth/session-context';
import { PenCanvas } from '../features/pen/pen-canvas';
import { useFeatures } from '../lib/api/context';
import { explainError } from '../lib/api/errors';
import { schoolDatetime } from '../features/schedule/school-dates';

function studentsLabel(count: number) {
  const mod10 = count % 10;
  const mod100 = count % 100;
  const word =
    mod10 === 1 && mod100 !== 11
      ? 'ученик'
      : mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)
        ? 'ученика'
        : 'учеников';
  return `${count} ${word}`;
}

export default function PenPage() {
  const { state } = useSession();
  const { pen, schedule } = useFeatures();
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
  // Строка «предмет · класс · дата» в шапке — витрина: сбой чтения урока
  // не должен прятать само полотно, поэтому ошибки здесь не показываем.
  const lesson = useQuery({
    queryKey: ['pen-lesson', lessonId],
    enabled: valid && (teacher || student),
    queryFn: ({ signal }) => schedule.getLessonView(lessonId, signal),
    retry: false,
  });
  if (!valid) return <Alert tone="error">Некорректный урок.</Alert>;
  if (!teacher && !student) return <Alert>Ручка доступна ученику и преподавателю.</Alert>;
  const studentId =
    student && state.status === 'authenticated'
      ? state.user.id
      : (students.data?.find((row) => row.id === selected)?.id ?? students.data?.[0]?.id);
  const description = lesson.data
    ? `${lesson.data.lesson.subject_name} · ${lesson.data.lesson.class_name} · ${schoolDatetime(lesson.data.lesson.starts_at)}`
    : teacher
      ? 'Выберите ученика и читайте его записи во время урока.'
      : 'Пишите мышью, пальцем или стилусом — преподаватель увидит ваши записи.';
  return (
    <div className="workspace-page pen-page">
      <Link className="workspace-back" to={`/lessons/${lessonId}`}>
        <ArrowLeft size={16} /> Вернуться в урок
      </Link>
      <PageHeader title="Умная ручка" description={description} />
      {teacher && (
        <section className="workspace-panel pen-student-picker">
          <div className="workspace-panel-head">
            <div>
              <h2>Состав класса</h2>
              <p>
                {students.data
                  ? students.data.length
                    ? `Выберите ученика · ${studentsLabel(students.data.length)}`
                    : 'В классе нет учеников'
                  : 'Кто пишет на этом уроке'}
              </p>
            </div>
            <span className="workspace-icon">
              <Users size={20} />
            </span>
          </div>
          <label className="pen-picker-label">
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
          {students.isPending && <p role="status">Загружаем состав класса…</p>}
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
