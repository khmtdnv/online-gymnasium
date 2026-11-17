import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi, type Mock } from 'vitest';
import { FeaturesContext, type Features } from '../app/lib/api/context';
import { PdfPreview } from '../app/features/documents/pdf-preview';
import { ApiProtocolError } from '../app/lib/api/errors';

const id = '6c6f3434-e4cc-4619-8c2a-8d733913ecda';
let createUrl: Mock<(obj: Blob | MediaSource) => string>;
let revokeUrl: Mock<(url: string) => void>;
beforeEach(() => {
  createUrl = vi.fn<(obj: Blob | MediaSource) => string>(() => 'blob:pdf-preview');
  revokeUrl = vi.fn<(url: string) => void>();
  const OriginalURL = URL;
  vi.stubGlobal(
    'URL',
    class extends OriginalURL {
      static createObjectURL = createUrl;
      static revokeObjectURL = revokeUrl;
    },
  );
});
afterEach(() => vi.unstubAllGlobals());
function setup(getDocumentPdf: Features['documents']['getDocumentPdf']) {
  const features = { documents: { getDocumentPdf } } as Features;
  return render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <FeaturesContext.Provider value={features}>
        <PdfPreview jobId={id} />
      </FeaturesContext.Provider>
    </QueryClientProvider>,
  );
}
it('создаёт доступную ссылку на PDF и освобождает blob при unmount', async () => {
  const blob = await new Response('%PDF-actual').blob();
  const view = setup(vi.fn().mockResolvedValue(blob));
  expect(await screen.findByRole('link', { name: 'Скачать PDF' })).toHaveAttribute(
    'download',
    `document-${id}.pdf`,
  );
  expect(screen.getByTitle('Учебный документ — PDF')).toHaveAttribute('src', 'blob:pdf-preview');
  view.unmount();
  expect(revokeUrl).toHaveBeenCalledWith('blob:pdf-preview');
});
it('не создаёт blob URL для нарушенного PDF-контракта', async () => {
  setup(vi.fn().mockRejectedValue(new ApiProtocolError('pdf-r1')));
  await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('формату'));
  expect(createUrl).not.toHaveBeenCalled();
});
