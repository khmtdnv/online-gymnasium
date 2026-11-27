import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { ClipboardList } from 'lucide-react';
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

const STATES: { value: HomeworkState; label: string }[] = [
  { value: 'all', label: 'Все задания' },
  { value: 'needs_action', label: 'Нужно выполнить' },
  { value: 'submitted', label: 'На проверке' },
  { value: 'returned', label: 'Вернули' },
  { value: 'graded', label: 'Проверено' },
];

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
  const shown =
    query.data && query.data.items.length
      ? `Показано ${offset + 1}–${offset + query.data.items.length} из ${query.data.total}`
      : null;
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
        <Button
          variant="secondary"
          disabled={!valid || query.isFetching}
          onClick={() => void query.refetch()}
        >
          Обновить
        </Button>
      </div>
      <div className="homework-state-tabs" aria-label="Статус заданий">
        {STATES.map(({ value, label }) => (
          <button
            key={value}
            type="button"
            className={`homework-state-tab${state === value ? ' is-active' : ''}`}
            aria-pressed={state === value}
            onClick={() => {
              setState(value);
              setOffset(0);
            }}
          >
            {label}
          </button>
        ))}
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
        <div className="homework-layout">
          <div className="homework-list-column">
            <div className="homework-results-heading">
              <h2>Задания</h2>
              <span className="homework-results-count" aria-label={`Найдено: ${query.data.total}`}>
                Найдено: {query.data.total}
              </span>
            </div>
            {!query.data.items.length && (
              <section className="card">
                <h2>Подходящих заданий нет</h2>
                <p>Попробуйте другой период или выберите «Все задания».</p>
              </section>
            )}
            <HomeworkList items={query.data.items} />
            <div className="homework-list-footer card">
              {shown && <span>{shown}</span>}
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
                  disabled={
                    offset + query.data.items.length >= query.data.total || query.isFetching
                  }
                  onClick={() => setOffset((value) => value + 50)}
                >
                  Следующие
                </Button>
              </div>
            </div>
          </div>
          <aside className="homework-aside">
            <section className="workspace-panel homework-aside-panel">
              <div className="workspace-panel-head">
                <div>
                  <h2>Регламент сдачи</h2>
                  <p>Как устроена сдача работ.</p>
                </div>
                <span className="workspace-icon">
                  <ClipboardList size={20} />
                </span>
              </div>
              <ul className="homework-rules">
                <li>Сдать работу можно и после срока — отсчёт статусов не останавливается.</li>
                <li>
                  До 5 файлов по 10 МиБ: PDF, DOCX, XLSX, PPTX, JPG, PNG, TXT. Неудачный файл
                  загружается повторно отдельно.
                </li>
                <li>Новая попытка открывается после возврата работы преподавателем.</li>
                <li>Проверенная работа повторной сдачи не требует.</li>
              </ul>
            </section>
          </aside>
        </div>
      )}
    </div>
  );
}
