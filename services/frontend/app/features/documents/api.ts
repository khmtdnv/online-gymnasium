import { z } from 'zod';
import type { ApiClient } from '../../lib/api/client';
import { createdDocumentSchema, documentJobSchema, uuidSchema } from '../../lib/api/contracts';

export const certificateInputSchema = z.object({
  student_full_name: z.string().trim().min(1, 'Укажите ФИО ученика.'),
  class_name: z.string().trim().min(1, 'Укажите класс.'),
  academic_year: z.string().trim().min(1, 'Укажите учебный год.'),
});
export type CertificateInput = z.infer<typeof certificateInputSchema>;

export function createDocumentsApi(client: ApiClient) {
  return {
    createCertificate(input: CertificateInput) {
      return client.json(
        '/api/v1/documents/certificates',
        { method: 'POST', body: JSON.stringify(certificateInputSchema.parse(input)) },
        createdDocumentSchema,
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
