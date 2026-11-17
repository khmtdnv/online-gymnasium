import { describe, expect, it } from 'vitest';
import { getDocumentPollInterval } from '../app/features/documents/polling';

describe('опрос генерации', () => {
  it('замедляется через минуту и останавливается через две', () => {
    expect(getDocumentPollInterval(0, 'pending')).toBe(2000);
    expect(getDocumentPollInterval(59999, 'processing')).toBe(2000);
    expect(getDocumentPollInterval(60000, 'processing')).toBe(5000);
    expect(getDocumentPollInterval(119999, 'processing')).toBe(5000);
    expect(getDocumentPollInterval(120000, 'processing')).toBe(false);
  });

  it('не опрашивает конечные состояния', () => {
    expect(getDocumentPollInterval(0, 'completed')).toBe(false);
    expect(getDocumentPollInterval(0, 'failed')).toBe(false);
  });
});
