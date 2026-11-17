import { describe, expect, it, vi } from 'vitest';
import { createScheduleApi } from '../app/features/schedule/api';
import { createDocumentsApi } from '../app/features/documents/api';
import { createWorkloadApi } from '../app/features/workload/api';

function setup() {
  const client = {
    json: vi.fn().mockResolvedValue({}),
    pdf: vi.fn().mockResolvedValue(new Blob()),
    downloadHomeworkFile: vi.fn().mockResolvedValue(new Blob()),
  };
  return {
    client,
    schedule: createScheduleApi(client),
    documents: createDocumentsApi(client),
    workload: createWorkloadApi(client),
  };
}

describe('адаптеры функций', () => {
  it('строит query расписания по настоящим числовым ID', async () => {
    const { client, schedule } = setup();
    await schedule.listLessons(9021, '2026-10-05');
    expect(client.json.mock.calls[0][0]).toBe(
      '/api/v1/schedule/lessons?class_id=9021&date=2026-10-05',
    );
    expect(() => schedule.listLessons(9007199254740992, '2026-10-05')).toThrow();
    expect(client.json).toHaveBeenCalledOnce();
  });

  it('передаёт тот же idempotency key и ожидаемую версию', async () => {
    const { client, schedule } = setup();
    const input = {
      class_id: 9021,
      teacher_id: '8df96b7a-7d30-44e7-b577-f6581300e101',
      subject_id: 1000,
      starts_at: '2026-10-05T09:00:00Z',
      ends_at: '2026-10-05T09:45:00Z',
    };
    await schedule.createLesson(input, 'fixed-attempt');
    expect(JSON.parse(client.json.mock.calls[0][1].body).teacher_id).toBe(input.teacher_id);
    expect(new Headers(client.json.mock.calls[0][1].headers).get('Idempotency-Key')).toBe(
      'fixed-attempt',
    );
    await schedule.cancelLesson(501, 4);
    expect(client.json.mock.calls[1].slice(0, 2)).toEqual([
      '/api/v1/schedule/lessons/501/cancel',
      { method: 'POST', body: JSON.stringify({ expected_version: 4 }) },
    ]);
  });

  it('использует day для Analytics и UUID для PDF', async () => {
    const { client, documents, workload } = setup();
    await workload.getWorkload(9021, '2026-10-05');
    expect(client.json.mock.calls[0][0]).toBe(
      '/api/v1/analytics/workload?class_id=9021&day=2026-10-05',
    );
    const id = '6c6f3434-e4cc-4619-8c2a-8d733913ecda';
    await documents.getDocumentPdf(id);
    expect(client.pdf).toHaveBeenCalledWith(`/api/v1/documents/${id}/content`, undefined);
    expect(() => documents.getDocumentPdf('https://evil.test/file')).toThrow();
    expect(client.pdf).toHaveBeenCalledOnce();
  });
});
