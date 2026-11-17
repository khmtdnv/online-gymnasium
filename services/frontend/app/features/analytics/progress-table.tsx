import type { ProgressRow } from './api';

export function ProgressTable({ rows }: { rows: ProgressRow[] }) {
  if (!rows.length)
    return <p>Проверенных работ за этот период нет. Это не нулевая успеваемость.</p>;
  return (
    <div style={{ overflowX: 'auto' }}>
      <table className="data-table">
        <caption>Оценки проверенных работ за выбранный период</caption>
        <thead>
          <tr>
            <th scope="col">Ученик</th>
            <th scope="col">Предмет</th>
            <th scope="col">Проверено работ</th>
            <th scope="col">Средняя оценка</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={`${row.student_id}-${row.subject_id}`}>
              <th scope="row">{row.student_name}</th>
              <td>{row.subject_name}</td>
              <td>{row.graded_count}</td>
              <td>
                {row.average_grade.toLocaleString('ru-RU', {
                  minimumFractionDigits: 2,
                  maximumFractionDigits: 2,
                })}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
