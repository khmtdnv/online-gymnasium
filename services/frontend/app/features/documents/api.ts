import { z } from 'zod';
import type { ApiClient } from '../../lib/api/client';
import {
  createdDocumentSchema,
  documentJobSchema,
  uuidSchema,
  positiveIdSchema,
} from '../../lib/api/contracts';

export const certificateInputSchema = z.object({
  student_full_name: z.string().trim().min(1, 'Укажите ФИО ученика.').max(300),
  class_name: z.string().trim().min(1, 'Укажите класс.').max(64),
  academic_year: z
    .string()
    .trim()
    .min(1, 'Укажите учебный год.')
    .regex(/^\d{4}\/\d{4}$/, 'Формат: 2026/2027.')
    .refine(
      (year) => Number(year.slice(5)) === Number(year.slice(0, 4)) + 1,
      'Укажите два последовательных года.',
    ),
  period_from: z.string().optional(),
  period_to: z.string().optional(),
});
export type CertificateInput = z.infer<typeof certificateInputSchema>;
export type DocumentType = 'certificate' | 'contract' | 'act' | 'receipt';

export function createDocumentsApi(client: ApiClient) {
  return {
    createCertificate(input: CertificateInput, key: string = crypto.randomUUID()) {
      return client.json(
        '/api/v1/documents',
        {
          method: 'POST',
          body: JSON.stringify({
            document_type: 'certificate',
            request_key: uuidSchema.parse(key),
            payload: certificateInputSchema.parse(input),
          }),
        },
        createdDocumentSchema,
      );
    },
    createTemplate(
      type: DocumentType,
      input: CertificateInput | { payment_id: number },
      key: string,
    ) {
      const payload =
        type === 'receipt'
          ? z.strictObject({ payment_id: positiveIdSchema.max(2147483647) }).parse(input)
          : certificateInputSchema.parse(input);
      return client.json(
        '/api/v1/documents',
        {
          method: 'POST',
          body: JSON.stringify({
            document_type: type,
            request_key: uuidSchema.parse(key),
            payload,
          }),
        },
        createdDocumentSchema,
      );
    },
    listJobs(offset: number, signal?: AbortSignal) {
      return client.json(
        `/api/v1/documents?offset=${offset}`,
        { signal },
        z.array(documentJobSchema).max(50),
      );
    },
    getDocument(jobId: string, signal?: AbortSignal) {
      return client.json(
        `/api/v1/documents/${uuidSchema.parse(jobId)}`,
        { signal },
        documentJobSchema,
      );
    },
    // Ссылку из ответа сервера не используем: токен не должен уйти на чужой URL.
    getDocumentPdf(jobId: string, signal?: AbortSignal) {
      return client.pdf(`/api/v1/documents/${uuidSchema.parse(jobId)}/content`, signal);
    },
  };
}
