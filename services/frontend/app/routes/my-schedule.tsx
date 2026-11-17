import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { PageHeader } from '../components/page-header';
import { Alert } from '../components/ui/alert';
import { Button } from '../components/ui/button';
import { useSession } from '../features/auth/session-context';
import { WeeklySchedule } from '../features/schedule/weekly-schedule';
import { addSchoolDays, schoolWeek, schoolTimezone } from '../features/schedule/school-dates';
import { useFeatures } from '../lib/api/context';
import { explainError } from '../lib/api/errors';
export default function MySchedulePage() {
  const { state } = useSession();
  if (state.status !== 'authenticated' || !['student', 'teacher'].includes(state.user.role))
    return <Alert>Личное расписание доступно ученикам и преподавателям.</Alert>;
  return <MySchedule />;
}
function MySchedule() {
  const { schedule } = useFeatures();
  const [week, setWeek] = useState(() => schoolWeek());
  const query = useQuery({
    queryKey: ['my-schedule', week],
    queryFn: ({ signal }) => schedule.getMySchedule(week, signal),
  });
  return (
    <>
      <PageHeader
        title="Моё расписание"
        description="Выберите день и откройте предмет, чтобы посмотреть урок и домашние задания."
      />
      {query.isPending && <p role="status">Загружаем расписание…</p>}
      {query.isError && (
        <Alert tone="error">
          {explainError(query.error)}{' '}
          <Button variant="secondary" onClick={() => void query.refetch()}>
            Повторить
          </Button>
        </Alert>
      )}
      {query.data && !query.data.has_class && (
        <Alert>Вы пока не зачислены в класс. Обратитесь к сотруднику школы.</Alert>
      )}
      <WeeklySchedule
        weekStart={week}
        days={
          query.data?.days ??
          Array.from({ length: 6 }, (_, i) => ({ date: addSchoolDays(week, i), lessons: [] }))
        }
        timezone={schoolTimezone}
        loading={query.isPending}
        failed={query.isError}
        onWeekChange={setWeek}
      />
    </>
  );
}
