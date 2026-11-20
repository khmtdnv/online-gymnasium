import {
  ArrowUpRight,
  CalendarDays,
  ChartNoAxesCombined,
  Files,
  GraduationCap,
  UserRound,
} from 'lucide-react';
import { Link } from 'react-router';
import { PageHeader } from '../components/page-header';
import { Alert } from '../components/ui/alert';
import { useSession } from '../features/auth/session-context';
import { StudentDay } from '../features/dashboard/student-day';
import { TeacherDay } from '../features/dashboard/teacher-day';
import type { CurrentUser } from '../lib/api/contracts';

export function HomeContent({ user }: { user: CurrentUser }) {
  const admin = user.role === 'admin';
  const cards = admin
    ? [
        {
          to: '/schedule',
          title: 'Расписание',
          description: 'Планируйте уроки, переносите время и отменяйте занятия.',
          action: 'Открыть день',
          icon: CalendarDays,
        },
        {
          to: '/workload',
          title: 'Нагрузка класса',
          description: 'Плановые уроки и минуты за выбранный день.',
          action: 'Посмотреть расчёт',
          icon: ChartNoAxesCombined,
        },
        {
          to: '/documents',
          title: 'Справки об обучении',
          description: 'Подготовьте справку и скачайте готовый PDF.',
          action: 'Создать справку',
          icon: Files,
        },
        {
          to: '/profile',
          title: 'Ваш профиль',
          description: 'Учётная запись, текущая роль и ID пользователя.',
          action: 'Открыть профиль',
          icon: UserRound,
        },
      ]
    : [
        {
          to: '/profile',
          title: 'Ваш профиль',
          description: 'Ваш email, текущая роль и ID учётной записи.',
          action: 'Открыть профиль',
          icon: UserRound,
        },
      ];
  return (
    <>
      <PageHeader
        title="Онлайн-гимназия"
        eyebrow="Хороший день начинается здесь"
        description="Ваше рабочее пространство для школьных дел."
      />
      <section className="card hero">
        <div>
          <span className="badge badge-peach">Спокойно. Понятно. По порядку.</span>
          <h2 className="section-title">
            Всё нужное —<br />в одном пространстве.
          </h2>
          <p>
            {admin
              ? 'Выберите школьную задачу. За расписание, расчёты и документы отвечают ваши работающие сервисы.'
              : 'Откройте своё расписание или домашние задания. Здесь находятся ваши школьные дела.'}
          </p>
          <Link to={admin ? '/schedule' : '/profile'} className="button button-primary">
            {admin ? 'Перейти к урокам' : 'Посмотреть профиль'}
            <ArrowUpRight size={18} aria-hidden="true" />
          </Link>
        </div>
        <div className="hero-art" aria-hidden="true">
          <GraduationCap size={90} strokeWidth={1.2} />
        </div>
      </section>
      {['teacher', 'student'].includes(user.role) && (
        <Link to="/homework" className="button button-primary">
          {user.role === 'teacher' ? 'Мои уроки и ДЗ' : 'Домашние задания'}
        </Link>
      )}
      {user.role === 'parent' && (
        <Alert>
          Сейчас доступен профиль. Мы не показываем чужие классы и документы, пока нет настройки
          личного доступа.
        </Alert>
      )}
      <h2 className="section-title">{admin ? 'Что сделаем сегодня?' : 'Ваши возможности'}</h2>
      <div className="card-grid">
        {cards.map(({ to, title, description, action, icon: Icon }, index) => (
          <Link className="card feature-card" to={to} key={to}>
            <span className={`feature-icon${index % 2 ? ' peach' : ''}`}>
              <Icon size={25} aria-hidden="true" />
            </span>
            <h3>{title}</h3>
            <p>{description}</p>
            <span className="link-label">
              {action}
              <ArrowUpRight size={17} aria-hidden="true" />
            </span>
          </Link>
        ))}
      </div>
    </>
  );
}

export default function Home() {
  const { state } = useSession();
  if (state.status === 'authenticated' && state.user.role === 'student') return <StudentDay />;
  if (state.status === 'authenticated' && state.user.role === 'teacher') return <TeacherDay />;
  return state.status === 'authenticated' ? <HomeContent user={state.user} /> : null;
}
