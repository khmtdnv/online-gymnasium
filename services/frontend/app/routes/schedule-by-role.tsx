import { useSession } from '../features/auth/session-context';
import { Alert } from '../components/ui/alert';
import MySchedulePage from './my-schedule';
import Schedule from './schedule';

export default function ScheduleByRole() {
  const { state } = useSession();
  if (state.status !== 'authenticated') return null;
  if (state.user.role === 'admin') return <Schedule />;
  if (state.user.role === 'student' || state.user.role === 'teacher') return <MySchedulePage />;
  return <Alert>Расписание недоступно для этой роли.</Alert>;
}
