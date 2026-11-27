import { useQuery } from '@tanstack/react-query';
import { ArrowLeft, CalendarDays, Clock3, FileText, Info, UserRound } from 'lucide-react';
import { Link, useParams } from 'react-router';
import { PageHeader } from '../components/page-header';
import { Alert } from '../components/ui/alert';
import { Button } from '../components/ui/button';
import { useSession } from '../features/auth/session-context';
import { HomeworkFiles } from '../features/homework/homework-files';
import { displayHomeworkDescription } from '../features/homework/display-description';
import { HomeworkAnswerForm } from '../features/homework/homework-answer-form';
import { useFeatures } from '../lib/api/context';
import { explainError } from '../lib/api/errors';
import {
  formatSchoolDay,
  schoolDay,
  schoolDatetime,
  schoolTime,
} from '../features/schedule/school-dates';

export default function HomeworkDetailPage() {
  const { state } = useSession();
  if (state.status !== 'authenticated' || state.user.role !== 'student')
    return <Alert>Раздел доступен ученику.</Alert>;
  return <StudentHomeworkDetail />;
}

function StudentHomeworkDetail() {
  const { homeworkId } = useParams();
  const id = Number(homeworkId);
  const valid = Number.isInteger(id) && id > 0 && id <= 2147483647;
  const { homework, schedule } = useFeatures();
  const query = useQuery({
    queryKey: ['homework', 'student-detail', id],
    enabled: valid,
    queryFn: ({ signal }) => homework.getHomework(id, signal),
  });
  const lesson = useQuery({
    queryKey: ['student-lesson', query.data?.issued_lesson_id],
    enabled: !!query.data,
    queryFn: ({ signal }) => schedule.getLessonView(query.data!.issued_lesson_id, signal),
  });
  if (!valid) return <Alert tone="error">Некорректный номер задания.</Alert>;
  const task = query.data;
  const overdue = !!task?.final_due_datetime && Date.parse(task.final_due_datetime) < Date.now();
  return (
    <div className="workspace-page homework-detail-page">
      <PageHeader title="Домашнее задание" />
      <div className="homework-detail-toolbar">
        <Link className="workspace-back" to="/homework">
          <ArrowLeft size={16} /> Все задания
        </Link>
        <Button
          variant="secondary"
          disabled={query.isFetching}
          onClick={() => void query.refetch()}
        >
          Обновить
        </Button>
      </div>
      {query.isPending && <p role="status">Загружаем задание…</p>}
      {query.isError && <Alert tone="error">{explainError(query.error)}</Alert>}
      {task && (
        <div className="homework-layout">
          <div className="homework-detail-main">
            <section className="workspace-panel homework-detail-panel">
              <div className="homework-detail-head">
                <div>
                  <span className="workspace-kicker">
                    {lesson.data?.lesson.subject_name ?? 'Условие задания'}
                  </span>
                  <h2>Условие задания</h2>
                </div>
                {task.final_due_datetime && (
                  <span className={`homework-due-chip${overdue ? ' is-overdue' : ''}`}>
                    <Clock3 size={15} aria-hidden="true" />
                    Сдать до {schoolDatetime(task.final_due_datetime)}
                  </span>
                )}
              </div>
              {!task.final_due_datetime && (
                <p className="homework-due-note">Урок срока отменён — ожидайте уточнения</p>
              )}
              <dl className="homework-detail-meta">
                <div>
                  <dt>
                    <UserRound size={15} aria-hidden="true" /> Преподаватель
                  </dt>
                  <dd>{lesson.data?.lesson.teacher_name ?? '—'}</dd>
                </div>
                <div>
                  <dt>
                    <CalendarDays size={15} aria-hidden="true" /> Выдано
                  </dt>
                  <dd>{schoolDatetime(task.created_at)}</dd>
                </div>
                <div>
                  <dt>
                    <Clock3 size={15} aria-hidden="true" /> Крайний срок
                  </dt>
                  <dd className={overdue ? 'is-overdue' : undefined}>
                    {task.final_due_datetime
                      ? schoolDatetime(task.final_due_datetime)
                      : 'уточняется'}
                  </dd>
                </div>
              </dl>
              <div className="homework-task-text">
                <p style={{ whiteSpace: 'pre-wrap' }}>
                  {displayHomeworkDescription(task.description)}
                </p>
              </div>
              {lesson.isError && (
                <Alert>Не удалось уточнить название урока. Само задание доступно ниже.</Alert>
              )}
              {!!task.files.length && (
                <div className="homework-materials">
                  <h3>
                    <FileText size={16} aria-hidden="true" /> Материалы к заданию
                  </h3>
                  <HomeworkFiles files={task.files} api={homework} />
                </div>
              )}
              <HomeworkAnswerForm key={id} homeworkId={id} api={homework} />
            </section>
          </div>
          <aside className="homework-aside">
            {lesson.data && (
              <section className="workspace-panel homework-aside-panel">
                <div className="workspace-panel-head">
                  <div>
                    <h2>Урок, на котором задано</h2>
                    <p>Привязка к расписанию.</p>
                  </div>
                  <span className="workspace-icon">
                    <CalendarDays size={20} />
                  </span>
                </div>
                <div className="lesson-info-row">
                  <CalendarDays size={18} />
                  <div>
                    <span>Дата</span>
                    <strong>
                      {formatSchoolDay(schoolDay(new Date(lesson.data.lesson.starts_at)), {
                        weekday: 'long',
                        year: 'numeric',
                      })}
                    </strong>
                  </div>
                </div>
                <div className="lesson-info-row">
                  <Clock3 size={18} />
                  <div>
                    <span>Время школы</span>
                    <strong>
                      {schoolTime(lesson.data.lesson.starts_at)}–
                      {schoolTime(lesson.data.lesson.ends_at)}
                    </strong>
                  </div>
                </div>
                <Link to={`/lessons/${task.issued_lesson_id}`} className="lesson-info-link">
                  Открыть урок, на котором задано
                </Link>
              </section>
            )}
            <section className="workspace-panel homework-aside-panel">
              <div className="workspace-panel-head">
                <div>
                  <h2>Памятка по файлам</h2>
                  <p>Что можно прикрепить к ответу.</p>
                </div>
                <span className="workspace-icon">
                  <Info size={20} />
                </span>
              </div>
              <ul className="homework-rules">
                <li>PDF, DOCX, XLSX, PPTX, JPG, PNG, TXT.</li>
                <li>До 5 файлов, каждый от 1 байта до 10 МиБ.</li>
                <li>Сбитую загрузку можно повторить тем же файлом.</li>
              </ul>
            </section>
          </aside>
        </div>
      )}
    </div>
  );
}
