import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';
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
import { StudentDay, dayTitle, rubles, studyPeriodLabel } from '../features/dashboard/student-day';
import { TeacherDay } from '../features/dashboard/teacher-day';
import {
  formatNotificationTime,
  notificationCategory,
} from '../features/notifications/notification-row';
import { schoolDay } from '../features/schedule/school-dates';
import { useFeatures } from '../lib/api/context';
import type { CurrentUser } from '../lib/api/contracts';

/** Экран администратора: макета в архиве нет — действующий вид в общем стиле. */
export function HomeContent({ user }: { user: CurrentUser }) {
  const adminName = [user.first_name, user.last_name].filter(Boolean).join(' ');
  const cards = [
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
            {adminName && <>Здравствуйте, {adminName}. </>}
            Выберите школьную задачу. За расписание, расчёты и документы отвечают ваши работающие
            сервисы.
          </p>
          <Link to="/schedule" className="button button-primary">
            Перейти к урокам
            <ArrowUpRight size={18} aria-hidden="true" />
          </Link>
        </div>
        <div className="hero-art" aria-hidden="true">
          <GraduationCap size={90} strokeWidth={1.2} />
        </div>
      </section>
      <h2 className="section-title">Что сделаем сегодня?</h2>
      <div className="card-grid">
        {cards.map(({ to, title, description, action, icon: Icon }) => (
          <Link className="card feature-card" to={to} key={to}>
            <span className="feature-icon">
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

/**
 * Экран родителя по макету p01: выбор ребёнка, оплата и уведомления.
 * Куратор, справки, расписание и ДЗ ребёнка опущены — для них нет контракта API.
 */
function ParentDay() {
  const { billing, notifications } = useFeatures();
  const today = schoolDay();
  const students = useQuery({
    queryKey: ['parent-day-students'],
    queryFn: ({ signal }) => billing.students(signal),
  });
  const [selection, setSelection] = useState('');
  const studentId = selection || students.data?.[0]?.id || '';
  const orders = useQuery({
    queryKey: ['parent-day-orders', studentId],
    enabled: studentId !== '',
    queryFn: ({ signal }) => billing.orders(studentId, 0, signal),
  });
  const unpaid = orders.data?.find((order) => order.status === 'unpaid');
  const notifs = useQuery({
    queryKey: ['parent-day-notifications'],
    queryFn: ({ signal }) => notifications.list(0, signal),
  });

  return (
    <div className="day-sheet day-sheet--parent">
      <header className="day-heading">
        <div className="day-heading-main">
          <span className="day-kicker">Родительский контроль</span>
          <h1>Личный кабинет родителя</h1>
          <p className="day-date">{dayTitle(today)}</p>
        </div>
        {(students.data?.length ?? 0) > 1 && (
          <div className="day-child-switch" role="group" aria-label="Выбор ребёнка">
            {students.data?.map((child) => (
              <button
                type="button"
                key={child.id}
                aria-pressed={child.id === studentId}
                className={`day-child-tab${child.id === studentId ? ' is-active' : ''}`}
                onClick={() => setSelection(child.id)}
              >
                <span className="day-child-dot" aria-hidden="true" />
                {child.name}
              </button>
            ))}
          </div>
        )}
      </header>
      {students.isError && (
        <Alert tone="error">
          Не удалось загрузить список детей. Раздел оплаты открывается напрямую.
        </Alert>
      )}
      {students.data?.length === 0 && <Alert>Нет связанных учеников для оплаты.</Alert>}
      {orders.isError && (
        <Alert tone="error">
          Не удалось загрузить счета. <Link to="/billing">Открыть раздел оплаты</Link>
        </Alert>
      )}
      {orders.data &&
        (unpaid ? (
          <section className="day-invoice" aria-labelledby="day-invoice-heading">
            <div className="day-invoice-main">
              <div className="day-invoice-head">
                <span className="badge badge-peach">Счёт выставлен к оплате</span>
                <span className="day-invoice-period">
                  {studyPeriodLabel(unpaid.study_month, unpaid.period_type)}
                </span>
              </div>
              <h2 className="day-invoice-amount" id="day-invoice-heading">
                {rubles(unpaid.amount_kopecks)}
              </h2>
              <p>
                Оплата обучения проходит через защищённый шлюз ЮKassa. Статус платежа, чек и
                история — в разделе «Оплата и биллинг».
              </p>
            </div>
            <div className="day-invoice-actions">
              {unpaid.payment?.status === 'pending' && unpaid.payment.confirmation_url ? (
                <a
                  className="button button-primary"
                  href={unpaid.payment.confirmation_url}
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  Продолжить оплату в ЮKassa
                </a>
              ) : (
                <Link className="button button-primary" to="/billing">
                  Перейти к оплате
                </Link>
              )}
              <Link className="day-panel-more" to="/billing">
                История платежей
              </Link>
            </div>
          </section>
        ) : (
          <section className="day-invoice is-paid" aria-labelledby="day-invoice-heading">
            <div className="day-invoice-main">
              <span className="day-kicker">Оплата обучения</span>
              <h2 className="day-invoice-amount" id="day-invoice-heading">
                Счетов к оплате нет
              </h2>
              <p>Новых счетов нет. История платежей и квитанции — в разделе оплаты.</p>
            </div>
            <div className="day-invoice-actions">
              <Link className="button button-secondary" to="/billing">
                История платежей
              </Link>
            </div>
          </section>
        ))}
      <section className="day-panel day-diary" aria-labelledby="day-diary-heading">
        <div className="day-panel-head">
          <h2 id="day-diary-heading">Дневник ребёнка</h2>
          <Link to="/diary">Открыть</Link>
        </div>
        <p>Оценки за уроки, посещаемость и сводка по четвертям.</p>
      </section>
      <section className="day-panel day-notifications">
        <div className="day-panel-head">
          <h2>Уведомления</h2>
          <Link to="/notifications">Все уведомления</Link>
        </div>
        {notifs.isPending && <p role="status">Загружаем уведомления…</p>}
        {notifs.isError && <p role="alert">Не удалось загрузить уведомления.</p>}
        {notifs.data && !notifs.data.length && <p>Новых уведомлений нет.</p>}
        <div className="day-notif-list">
          {notifs.data?.slice(0, 3).map((item) => (
            <article className="day-notif" key={item.id}>
              <div className="day-notif-meta">
                <span className="day-hw-chip">{notificationCategory(item.link)}</span>
                <time dateTime={item.created_at}>{formatNotificationTime(item.created_at)}</time>
              </div>
              <strong>{item.title}</strong>
              <p>{item.body}</p>
              <Link className="day-panel-more" to={item.link}>
                Открыть
              </Link>
            </article>
          ))}
        </div>
      </section>
    </div>
  );
}

export default function Home() {
  const { state } = useSession();
  if (state.status !== 'authenticated') return null;
  if (state.user.role === 'student') return <StudentDay />;
  if (state.user.role === 'teacher') return <TeacherDay />;
  if (state.user.role === 'parent') return <ParentDay />;
  return <HomeContent user={state.user} />;
}
