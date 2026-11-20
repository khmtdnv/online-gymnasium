import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { PageHeader } from '../components/page-header';
import { Alert } from '../components/ui/alert';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { useSession } from '../features/auth/session-context';
import { HomeworkList } from '../features/homework/homework-list';
import { TeacherReviews } from '../features/homework/teacher-reviews';
import type { HomeworkState } from '../features/homework/api';
import { addSchoolDays, formatSchoolDay, schoolWeek } from '../features/schedule/school-dates';
import { useFeatures } from '../lib/api/context';
import { explainError } from '../lib/api/errors';

export default function HomeworkPage() {
  const { state } = useSession();
  if (state.status !== 'authenticated') return null;
  if (state.user.role === 'teacher') return <TeacherReviews />;
  if (state.user.role !== 'student') return <Alert>Домашние задания доступны ученикам.</Alert>;
  return <StudentHomework />;
}

function StudentHomework() {
  const { homework } = useFeatures();
  const [from, setFrom] = useState(() => addSchoolDays(schoolWeek(), -7));
  const [until, setUntil] = useState(() => addSchoolDays(schoolWeek(), 20));
  const [state, setState] = useState<HomeworkState>('all');
  const [offset, setOffset] = useState(0);
  const distance = (Date.parse(until) - Date.parse(from)) / 86400000;
  const valid = Number.isFinite(distance) && distance >= 0 && distance < 31;
  const query = useQuery({
    queryKey: ['my-homework', from, until, state, offset],
    enabled: valid,
    queryFn: ({ signal }) => homework.listMyHomework(from, until, state, offset, signal),
  });
  return (
    <div className="workspace-page homework-page">
      <PageHeader
        title="Домашние задания"
        description="По срокам сдачи. Откройте задание, чтобы ответить, прикрепить файл или посмотреть проверку."
      />
      <div className="homework-filters card">
        <label>
          Срок с
          <Input
            type="date"
            value={from}
            onChange={(e) => {
              setFrom(e.target.value);
              setOffset(0);
            }}
          />
        </label>
        <label>
          Срок по
          <Input
            type="date"
            value={until}
            onChange={(e) => {
              setUntil(e.target.value);
              setOffset(0);
            }}
          />
        </label>
        <label>
          Показать
          <select
            className="input"
            value={state}
            onChange={(e) => {
              setState(e.target.value as HomeworkState);
              setOffset(0);
            }}
          >
            <option value="all">Все задания</option>
            <option value="needs_action">Нужно выполнить</option>
            <option value="submitted">На проверке</option>
            <option value="returned">Вернули</option>
            <option value="graded">Проверено</option>
          </select>
        </label>
        <Button
          variant="secondary"
          disabled={!valid || query.isFetching}
          onClick={() => void query.refetch()}
        >
          Обновить
        </Button>
      </div>
      {!valid && <Alert tone="error">Выберите период от 1 до 31 дня.</Alert>}
      {valid && (
        <p className="calendar-timezone">
          Сроки с {formatSchoolDay(from)} по {formatSchoolDay(until)} · время школы UTC+5
        </p>
      )}
      {query.isPending && valid && <p role="status">Загружаем задания…</p>}
      {query.isError && <Alert tone="error">{explainError(query.error)}</Alert>}
      {valid && query.data && (
        <>
          <div className="homework-results-heading">
            <h2>Задания</h2>
            <span>Найдено: {query.data.total}</span>
          </div>
          {!query.data.items.length && (
            <section className="card">
              <h2>Подходящих заданий нет</h2>
              <p>Попробуйте другой период или выберите «Все задания».</p>
            </section>
          )}
          <HomeworkList items={query.data.items} />
          <div className="calendar-toolbar">
            <Button
              variant="secondary"
              disabled={offset === 0 || query.isFetching}
              onClick={() => setOffset((value) => Math.max(0, value - 50))}
            >
              Предыдущие
            </Button>
            <Button
              variant="secondary"
              disabled={offset + query.data.items.length >= query.data.total || query.isFetching}
              onClick={() => setOffset((value) => value + 50)}
            >
              Следующие
            </Button>
          </div>
        </>
      )}
    </div>
  );
}
