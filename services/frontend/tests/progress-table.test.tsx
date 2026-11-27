import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import {
  AuditPayload,
  ProgressTable,
  TECHNICAL_JSON_LIMIT,
  formatTechnicalJson,
} from '../app/features/analytics/progress-table';

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

describe('technical audit JSON', () => {
  const analyticsSources = [
    readFileSync(join(process.cwd(), 'app/features/analytics/progress-table.tsx'), 'utf-8'),
    readFileSync(join(process.cwd(), 'app/routes/analytics.tsx'), 'utf-8'),
  ];

  it('не использует dangerouslySetInnerHTML в аналитике', () => {
    for (const source of analyticsSources) expect(source).not.toContain('dangerouslySetInnerHTML');
  });

  it('renders JSON as escaped text inside pre, never as HTML', () => {
    render(
      <AuditPayload
        payload={{ note: '<script>alert(1)</script>', grade: 4, tag: '<img src=x onerror=1>' }}
      />,
    );
    const pre = document.querySelector('.technical-json pre');
    expect(pre).not.toBeNull();
    // Текст, а не разметка: тег виден пользователю как текст.
    expect(pre?.textContent).toContain('"grade": 4');
    expect(pre?.textContent).toContain('<script>alert(1)</script>');
    expect(pre?.innerHTML).not.toContain('<script>alert');
    expect(document.querySelector('.technical-json script')).toBeNull();
    expect(document.querySelector('.technical-json img')).toBeNull();
  });

  it('truncates values longer than 2000 characters with an indicator', () => {
    const long = { blob: 'x'.repeat(5000) };
    const formatted = formatTechnicalJson(long);
    expect(formatted.truncated).toBe(true);
    expect(formatted.text.length).toBe(TECHNICAL_JSON_LIMIT);
    render(<AuditPayload payload={long} />);
    const limit = TECHNICAL_JSON_LIMIT.toLocaleString('ru-RU');
    expect(
      screen.getByText(
        (_, el) =>
          el?.classList.contains('technical-json-note') === true &&
          (el.textContent ?? '').includes(limit) &&
          (el.textContent ?? '').includes('усечены'),
      ),
    ).toBeInTheDocument();
  });

  it('keeps short payloads whole without an indicator', () => {
    render(<AuditPayload payload={{ grade: 4, status: 'graded' }} />);
    expect(screen.queryByText(/усечены/)).not.toBeInTheDocument();
    expect(screen.getByText(/"status": "graded"/)).toBeInTheDocument();
  });
});
