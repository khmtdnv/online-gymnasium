import { useQuery } from '@tanstack/react-query';
import { RefreshCw } from 'lucide-react';
import { PageHeader } from '../components/page-header';
import { AsyncState } from '../components/async-state';
import { Button } from '../components/ui/button';
import { DayFilters, useDaySelection } from '../features/schedule/day-filters';
import { workloadKeys } from '../features/schedule/query-keys';
import { WorkloadCard } from '../features/workload/workload-card';
import { useFeatures } from '../lib/api/context';
import { ApiError, errorRequestId, explainError } from '../lib/api/errors';

export default function Workload() {
  const selection = useDaySelection();
  const { workload } = useFeatures();
  const query = useQuery({
    queryKey: workloadKeys.day(selection.classId ?? 0, selection.day),
    enabled: selection.classId !== null,
    queryFn: ({ signal }) => workload.getWorkload(selection.classId!, selection.day, signal),
  });
  return (
    <>
      <PageHeader
        title="Нагрузка расписания"
        eyebrow="Один день в цифрах"
        description="Плановые уроки и минуты выбранного класса — из готового расчёта Analytics."
        action={
          <Button
            variant="secondary"
            onClick={() => {
              void query.refetch();
            }}
            disabled={selection.classId === null || query.isFetching}
          >
            <RefreshCw size={18} aria-hidden="true" />
            Обновить
          </Button>
        }
      />
      <DayFilters
        classIdText={selection.classIdText}
        day={selection.day}
        onChange={selection.change}
      />
      {selection.classId === null ? (
        <AsyncState state="empty" title="Выберите класс и день" />
      ) : query.isPending ? (
        <AsyncState state="loading" title="Читаем готовый расчёт" />
      ) : query.isError ? (
        query.error instanceof ApiError && query.error.status === 404 ? (
          <AsyncState
            state="empty"
            title="Расчёт пока отсутствует"
            message="Для этого класса и дня ещё нет результата. Это не означает нулевую нагрузку."
            onRetry={() => {
              void query.refetch();
            }}
          />
        ) : (
          <AsyncState
            state="error"
            title="Расчёт недоступен"
            message={explainError(query.error)}
            requestId={errorRequestId(query.error)}
            onRetry={() => {
              void query.refetch();
            }}
          />
        )
      ) : (
        <WorkloadCard workload={query.data} />
      )}
    </>
  );
}
