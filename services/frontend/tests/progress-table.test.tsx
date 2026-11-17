import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { ProgressTable } from '../app/features/analytics/progress-table';

describe('progress report', () => {
  it('shows names and checked work count, not technical student IDs', () => {
    render(
      <ProgressTable
        rows={[
          {
            student_id: '00000000-0000-0000-0000-000000000001',
            subject_id: 3,
            student_name: 'Петров Иван',
            subject_name: 'Математика',
            graded_count: 2,
            average_grade: 4.5,
          },
        ]}
      />,
    );
    expect(screen.getByText('Петров Иван')).toBeVisible();
    expect(screen.getByText('Математика')).toBeVisible();
    expect(screen.getByText('4,50')).toBeVisible();
    expect(screen.queryByText('00000000-0000-0000-0000-000000000001')).not.toBeInTheDocument();
  });
  it('does not represent absent grades as a zero average', () => {
    render(<ProgressTable rows={[]} />);
    expect(screen.getByText(/Проверенных работ за этот период нет/)).toBeVisible();
    expect(screen.queryByRole('table')).not.toBeInTheDocument();
  });
});
