import { useState } from 'react';
import { useNavigate } from 'react-router';
import { PageHeader } from '../components/page-header';
import { Input } from '../components/ui/input';
import { Button } from '../components/ui/button';
import { CertificateForm } from '../features/documents/certificate-form';
import { useFeatures } from '../lib/api/context';
import { uuidSchema } from '../lib/api/contracts';

export default function Documents() {
  const { documents } = useFeatures();
  const navigate = useNavigate();
  const [jobId, setJobId] = useState('');
  const [invalidId, setInvalidId] = useState(false);
  return (
    <>
      <PageHeader
        title="Справки об обучении"
        eyebrow="Школьные документы"
        description="Создайте справку и получите готовый PDF. Общая история заданий пока не подключена."
      />
      <div className="document-grid">
        <section className="card">
          <h2>Новая справка</h2>
          <p>Укажите данные, которые должны попасть в документ.</p>
          <CertificateForm
            onCreate={async (input) => {
              const job = await documents.createCertificate(input);
              navigate(`/documents/${uuidSchema.parse(job.id)}`);
            }}
          />
        </section>
        <section className="card">
          <span className="feature-icon peach" aria-hidden="true">
            PDF
          </span>
          <h2>Уже есть задание?</h2>
          <p>Откройте сохранённую ссылку или введите его UUID.</p>
          <form
            className="form-stack"
            noValidate
            onSubmit={(event) => {
              event.preventDefault();
              const parsed = uuidSchema.safeParse(jobId.trim());
              setInvalidId(!parsed.success);
              if (parsed.success) navigate(`/documents/${parsed.data}`);
            }}
          >
            <div className="field">
              <label htmlFor="known-job">ID задания</label>
              <Input
                id="known-job"
                value={jobId}
                onChange={(event) => setJobId(event.target.value)}
                autoComplete="off"
                placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
                aria-invalid={invalidId}
                aria-describedby={invalidId ? 'known-job-error' : undefined}
              />
              {invalidId && (
                <p className="field-error" id="known-job-error">
                  Введите корректный UUID.
                </p>
              )}
            </div>
            <Button type="submit" variant="secondary">
              Открыть задание
            </Button>
          </form>
          <p className="field-hint" style={{ marginTop: 20 }}>
            ФИО и документы не сохраняются в локальном хранилище браузера.
          </p>
        </section>
      </div>
    </>
  );
}
