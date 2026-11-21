import { Link } from 'react-router';
import type { HomeworkListItem } from './api';
import { formatSchoolDay, schoolDay, schoolDatetime } from '../schedule/school-dates';
import { displayHomeworkDescription } from './display-description';
export function homeworkStatus(row: HomeworkListItem): string {
  if (row.latest_answer_status === 'graded') return `Проверено · оценка ${row.grade}`;
  if (row.latest_answer_status === 'submitted') return 'На проверке';
  if (row.latest_answer_status === 'returned') return 'Вернули — нужно исправить';
  return 'Нужно выполнить';
}
export function HomeworkList({
  items,
  now = new Date(),
}: {
  items: HomeworkListItem[];
  now?: Date;
}) {
  const groups = new Map<string, { label: string; rows: HomeworkListItem[] }>();
  for (const row of items) {
    const needsAction =
      row.latest_answer_status === null || row.latest_answer_status === 'returned';
    const overdue =
      needsAction && row.final_due_datetime && Date.parse(row.final_due_datetime) < now.getTime();
    const day = row.final_due_datetime ? schoolDay(new Date(row.final_due_datetime)) : null;
    const key = overdue ? 'overdue' : (day ?? 'unknown');
    const weekday = day
      ? ['воскресенью', 'понедельнику', 'вторнику', 'среде', 'четвергу', 'пятнице', 'субботе'][
          new Date(day + 'T12:00:00Z').getUTCDay()
        ]
      : '';
    const label = overdue
      ? 'Просрочено — нужно выполнить'
      : day
        ? `${weekday === 'вторнику' ? 'Ко' : 'К'} ${weekday}, ${formatSchoolDay(day)}`
        : 'Срок уточняется';
    const group = groups.get(key) ?? { label, rows: [] };
    group.rows.push(row);
    groups.set(key, group);
  }
  return (
    <div className="homework-groups">
      {[...groups.entries()].map(([key, group]) => (
        <section key={key} className="homework-date-group">
          <div className="homework-group-heading">
            <h2>{group.label}</h2>
            <span className="homework-group-rule" aria-hidden="true" />
            <span className="homework-group-count" aria-label={`Заданий: ${group.rows.length}`}>
              {group.rows.length}
            </span>
          </div>
          <div className="homework-rows">
            {group.rows.map((row) => (
              <Link
                to={`/homework/${row.id}`}
                key={row.id}
                data-subject={row.subject_name}
                className={`homework-row${key === 'overdue' ? ' is-overdue' : ''}`}
              >
                <div className="homework-row-content">
                  <h3>{row.subject_name}</h3>
                  <p className="homework-description">
                    {displayHomeworkDescription(row.description)}
                  </p>
                  <div className="homework-row-meta">
                    <span className="homework-deadline">
                      {row.final_due_datetime
                        ? `Сдать до ${schoolDatetime(row.final_due_datetime)}`
                        : 'Урок срока отменён — ожидайте уточнения'}
                    </span>
                    <span>{row.teacher_name}</span>
                    {!!row.files.length && (
                      <span>
                        Файлов: {row.files.length}
                        {row.files.some((f) => f.upload_status === 'pending')
                          ? ' · не все загружены'
                          : ''}
                      </span>
                    )}
                  </div>
                </div>
                <div className="homework-row-status">
                  {key === 'overdue' && (
                    <span className="badge homework-status homework-status--overdue">
                      Просрочено
                    </span>
                  )}
                  <span
                    className={`badge homework-status homework-status--${row.latest_answer_status ?? 'assigned'}`}
                  >
                    {homeworkStatus(row)}
                  </span>
                  <span>Открыть задание →</span>
                </div>
              </Link>
            ))}
          </div>
        </section>
      ))}
    </div>
  );
}
