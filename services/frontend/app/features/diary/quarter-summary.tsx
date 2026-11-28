import { formatSchoolDay } from '../schedule/school-dates';
import type { DiarySummary } from './api';
import { absenceReasonLabel } from './labels';

const QUARTERS = [1, 2, 3, 4] as const;

/**
 * Сводка четверти дневника: средние по предметам, четвертная оценка
 * («предварительно» для текущей четверти — среднее вместо округления),
 * динамика средних по всем четвертям и список пропусков с причинами.
 * Прочерк вместо данных, нулей нет.
 */
export function QuarterSummary({
  summary,
  isCurrentQuarter,
  dynamics,
}: {
  summary: DiarySummary;
  isCurrentQuarter: boolean;
  /** Средние четырёх четвертей подряд; отсутствующие данные — прочерк. */
  dynamics?: DiarySummary[];
}) {
  return (
    <div className="diary-summary" data-testid="diary-summary">
      <h3>
        Четверть {summary.quarter} (
        {formatSchoolDay(summary.quarter_from, { day: 'numeric', month: 'short' })} —{' '}
        {formatSchoolDay(summary.quarter_to, { day: 'numeric', month: 'short' })})
        {isCurrentQuarter && ' — текущая'}
      </h3>
      {summary.subject_averages.length > 0 ? (
        <div className="diary-table-wrap">
          <table className="diary-summary-table">
            <thead>
              <tr>
                <th scope="col">Предмет</th>
                <th scope="col">Средняя</th>
                <th scope="col">Четвертная</th>
                <th scope="col">Оценок</th>
              </tr>
            </thead>
            <tbody>
              {summary.subject_averages.map((subject) => (
                <tr key={subject.subject_id}>
                  <th scope="row">Предмет {subject.subject_id}</th>
                  <td>{subject.average.toFixed(2)}</td>
                  <td className={`quarter-grade-${subject.quarter_grade}`}>
                    {isCurrentQuarter ? (
                      <>
                        {subject.average.toFixed(2)} <small>(предварительно)</small>
                      </>
                    ) : (
                      subject.quarter_grade
                    )}
                  </td>
                  <td>{subject.grade_count}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p>Нет оценок за эту четверть. Это не нулевая успеваемость.</p>
      )}
      {dynamics && <DynamicsTable dynamics={dynamics} />}
      {summary.absences.length > 0 && (
        <div className="diary-absences">
          <h4>Пропуски с причинами</h4>
          <ul>
            {summary.absences.map((absence, index) => (
              <li key={index}>
                {formatSchoolDay(absence.lesson_date, { day: 'numeric', month: 'short' })} —{' '}
                {absenceReasonLabel[absence.reason] ?? absence.reason}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

/** «Динамика»: средние всех четвертей рядом, по одной строке на предмет. */
function DynamicsTable({ dynamics }: { dynamics: DiarySummary[] }) {
  const subjects = new Set<number>();
  for (const quarter of dynamics) {
    for (const subject of quarter.subject_averages) subjects.add(subject.subject_id);
  }
  const rows = [...subjects].map((subjectId) => ({
    subjectId,
    cells: QUARTERS.map((_, index) => {
      const subject = dynamics[index]?.subject_averages.find(
        (row) => row.subject_id === subjectId,
      );
      return subject ? subject.average.toFixed(2) : '—';
    }),
  }));
  return (
    <div className="diary-dynamics" data-testid="diary-dynamics">
      <h4>Динамика средних по четвертям</h4>
      {rows.length > 0 ? (
        <div className="diary-table-wrap">
          <table className="diary-summary-table diary-dynamics-table">
            <thead>
              <tr>
                <th scope="col">Предмет</th>
                {QUARTERS.map((quarter) => (
                  <th key={quarter} scope="col">
                    {quarter} четв.
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.subjectId}>
                  <th scope="row">Предмет {row.subjectId}</th>
                  {row.cells.map((cell, index) => (
                    <td key={index}>{cell}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p>Оценок за учебный год пока нет.</p>
      )}
    </div>
  );
}
