import type { ProgressRow } from './api';

/* Технический JSON аудита: экранированный текст в <pre>, без HTML-интерпретации
   (инъекция разметки запрещена; React экранирует текст сам). Значения
   длиннее 2000 символов усекаются с индикатором. */
export const TECHNICAL_JSON_LIMIT = 2000;

export function formatTechnicalJson(value: unknown): { text: string; truncated: boolean } {
  const full = JSON.stringify(value, null, 2) ?? 'null';
  if (full.length <= TECHNICAL_JSON_LIMIT) return { text: full, truncated: false };
  return { text: full.slice(0, TECHNICAL_JSON_LIMIT), truncated: true };
}

export function AuditPayload({ payload }: { payload: unknown }) {
  const { text, truncated } = formatTechnicalJson(payload);
  return (
    <div className="technical-json">
      <pre>{text}</pre>
      {truncated && (
        <p className="technical-json-note" role="note">
          Показаны первые {TECHNICAL_JSON_LIMIT.toLocaleString('ru-RU')} символов — данные события
          длиннее и усечены.
        </p>
      )}
    </div>
  );
}

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
