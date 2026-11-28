import { useQuery } from '@tanstack/react-query';
import { useEffect, useState } from 'react';
import { PageHeader } from '../components/page-header';
import { Alert } from '../components/ui/alert';
import { Button } from '../components/ui/button';
import { useSession } from '../features/auth/session-context';
import { addSchoolDays, formatSchoolDay } from '../features/schedule/school-dates';
import type { DiarySummary } from '../features/diary/api';
import { QuarterSummary } from '../features/diary/quarter-summary';
import { WeekGrid } from '../features/diary/week-grid';
import { useFeatures } from '../lib/api/context';
import { explainError } from '../lib/api/errors';

const QUARTERS = [1, 2, 3, 4] as const;

export default function DiaryPage() {
  const { state } = useSession();
  if (state.status !== 'authenticated') return null;
  const { role } = state.user;
  if (role !== 'student' && role !== 'parent')
    return <Alert>Дневник доступен ученикам и родителям.</Alert>;
  return <Diary role={role} />;
}

/** Режимы: ученик читает свои данные, родитель — выбранного ребёнка. */
function Diary({ role }: { role: 'student' | 'parent' }) {
  const { diary, billing } = useFeatures();
  const [week, setWeek] = useState<string | undefined>(undefined);
  const [quarterOverride, setQuarterOverride] = useState<number | null>(null);
  const [childSelection, setChildSelection] = useState('');

  const children = useQuery({
    queryKey: ['diary-children'],
    enabled: role === 'parent',
    queryFn: ({ signal }) => billing.students(signal),
  });
  const studentId =
    role === 'parent' ? childSelection || children.data?.[0]?.id || '' : undefined;

  const weekQuery = useQuery({
    queryKey: ['diary', week, studentId],
    // Родителю нужен student_id: ждём список детей, чтобы не слать запрос без него.
    enabled: role !== 'parent' || studentId !== '',
    queryFn: ({ signal }) => diary.getDiaryWeek(week, studentId || undefined, signal),
  });

  // Четверть дефолтной (якорной) недели — опорная «текущая» четверть страницы:
  // «предварительно» помечается только она, навигация по неделям метку не сдвигает.
  const [currentQuarter, setCurrentQuarter] = useState<number | null>(null);
  useEffect(() => {
    if (week === undefined && weekQuery.data) setCurrentQuarter(weekQuery.data.quarter);
  }, [week, weekQuery.data]);

  // Динамика: средние всех четвертей учебного года рядом (спецификация дневника).
  const summaries = useQuery({
    queryKey: ['diary-summaries', studentId],
    enabled: currentQuarter !== null,
    queryFn: async ({ signal }) => {
      const list = await Promise.all(
        QUARTERS.map((quarter) =>
          diary.getDiarySummary(quarter, studentId || undefined, signal),
        ),
      );
      return Object.fromEntries(QUARTERS.map((quarter, index) => [quarter, list[index]])) as Record<
        number,
        DiarySummary
      >;
    },
  });

  const data = weekQuery.data;
  const selectedQuarter = quarterOverride ?? data?.quarter ?? null;
  const summary =
    selectedQuarter === data?.quarter
      ? data?.summary
      : selectedQuarter !== null
        ? summaries.data?.[selectedQuarter]
        : undefined;

  function switchChild(childId: string) {
    setChildSelection(childId);
    setWeek(undefined);
    setQuarterOverride(null);
  }

  return (
    <div className="workspace-page diary-page">
      <PageHeader
        title="Дневник"
        description="Учебные дни с оценками за урок, посещаемостью и домашними заданиями."
      />
      {role === 'parent' && (
        <div className="diary-parent-bar">
          {children.isPending && <p role="status">Загружаем список детей…</p>}
          {children.isError && (
            <Alert tone="error">
              Не удалось загрузить список детей.{' '}
              <Button
                variant="secondary"
                disabled={children.isFetching}
                onClick={() => void children.refetch()}
              >
                Повторить
              </Button>
            </Alert>
          )}
          {children.data?.length === 0 && <Alert>Нет связанных учеников.</Alert>}
          {(children.data?.length ?? 0) > 1 && (
            <div className="day-child-switch" role="group" aria-label="Выбор ребёнка">
              {children.data?.map((child) => (
                <button
                  type="button"
                  key={child.id}
                  aria-pressed={child.id === studentId}
                  className={`day-child-tab${child.id === studentId ? ' is-active' : ''}`}
                  onClick={() => switchChild(child.id)}
                >
                  <span className="day-child-dot" aria-hidden="true" />
                  {child.name}
                </button>
              ))}
            </div>
          )}
        </div>
      )}
      {weekQuery.isPending && <p role="status">Загружаем дневник…</p>}
      {weekQuery.isError && (
        <Alert tone="error">
          {explainError(weekQuery.error)}{' '}
          <Button
            variant="secondary"
            disabled={weekQuery.isFetching}
            onClick={() => void weekQuery.refetch()}
          >
            Повторить
          </Button>
        </Alert>
      )}
      {data && (
        <>
          <WeekNavigation weekStart={data.week_start} onChange={setWeek} />
          {data.demo_cutoff && (
            <p className="diary-cutoff" role="note">
              Демо-срез на дату {formatSchoolDay(data.demo_cutoff)}
            </p>
          )}
          <WeekGrid week={data} />
          <div className="diary-summary-bar">
            <label className="diary-quarter-select">
              Четверть сводки
              <select
                value={selectedQuarter ?? data.quarter}
                onChange={(event) => setQuarterOverride(Number(event.target.value))}
              >
                {QUARTERS.map((quarter) => (
                  <option key={quarter} value={quarter}>
                    {quarter}
                    {quarter === currentQuarter ? ' (текущая)' : ''}
                  </option>
                ))}
              </select>
            </label>
          </div>
          {summary ? (
            <QuarterSummary
              summary={summary}
              isCurrentQuarter={selectedQuarter === currentQuarter}
              dynamics={summaries.data ? QUARTERS.map((q) => summaries.data![q]) : undefined}
            />
          ) : summaries.isError ? (
            <Alert tone="error">
              Не удалось загрузить сводку четверти.{' '}
              <Button
                variant="secondary"
                disabled={summaries.isFetching}
                onClick={() => void summaries.refetch()}
              >
                Повторить
              </Button>
            </Alert>
          ) : (
            <p role="status">Загружаем сводку…</p>
          )}
        </>
      )}
    </div>
  );
}

function WeekNavigation({
  weekStart,
  onChange,
}: {
  weekStart: string;
  onChange: (week: string | undefined) => void;
}) {
  return (
    <div className="diary-nav">
      <Button variant="secondary" onClick={() => onChange(addSchoolDays(weekStart, -7))}>
        ← Предыдущая
      </Button>
      <span className="diary-week-label">
        Неделя {formatSchoolDay(weekStart, { day: 'numeric', month: 'long' })}
      </span>
      <Button variant="secondary" onClick={() => onChange(addSchoolDays(weekStart, 7))}>
        Следующая →
      </Button>
      <Button variant="secondary" onClick={() => onChange(undefined)}>
        Последняя заполненная
      </Button>
    </div>
  );
}
