import { zodResolver } from '@hookform/resolvers/zod';
import { useRef, useState } from 'react';
import { useForm } from 'react-hook-form';
import { Alert } from '../../components/ui/alert';
import { Button } from '../../components/ui/button';
import { Input } from '../../components/ui/input';
import {
  ApiError,
  ApiNetworkError,
  ApiProtocolError,
  errorRequestId,
  explainError,
} from '../../lib/api/errors';
import { certificateInputSchema, type CertificateInput } from './api';

export function CertificateForm({
  onCreate,
  kind = 'certificate',
}: {
  onCreate: (input: CertificateInput) => Promise<void>;
  kind?: 'certificate' | 'contract' | 'act';
}) {
  const [failure, setFailure] = useState<unknown>(null);
  const [unknownResult, setUnknownResult] = useState(false);
  const [sending, setSending] = useState(false);
  const lastInput = useRef<CertificateInput | null>(null);
  const label =
    kind === 'contract' ? 'Создать договор' : kind === 'act' ? 'Создать акт' : 'Создать справку';
  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<CertificateInput>({
    resolver: zodResolver(certificateInputSchema),
    defaultValues: { student_full_name: '', class_name: '', academic_year: '' },
  });
  async function submit(input: CertificateInput) {
    if (sending) return;
    lastInput.current = input;
    setSending(true);
    setFailure(null);
    try {
      await onCreate(input);
    } catch (error) {
      setFailure(error);
      setUnknownResult(
        error instanceof ApiNetworkError ||
          error instanceof ApiProtocolError ||
          (error instanceof ApiError && error.status >= 500),
      );
    } finally {
      setSending(false);
    }
  }
  const fields = [
    { name: 'student_full_name', label: 'ФИО ученика', placeholder: 'Иван Петров' },
    { name: 'class_name', label: 'Класс', placeholder: '7А' },
    { name: 'academic_year', label: 'Учебный год', placeholder: '2026/2027' },
  ] as const;
  return (
    <form className="form-stack" noValidate onSubmit={handleSubmit(submit)}>
      {failure !== null && (
        <Alert tone="error" requestId={errorRequestId(failure)}>
          {unknownResult
            ? 'Результат отправки неизвестен. Повторите с тем же ключом: сервер вернёт уже принятое задание, если оно создано.'
            : explainError(failure)}
        </Alert>
      )}
      {fields.map(({ name, label, placeholder }) => (
        <div className="field" key={name}>
          <label htmlFor={`certificate-${name}`}>{label}</label>
          <Input
            id={`certificate-${name}`}
            placeholder={placeholder}
            {...register(name)}
            disabled={isSubmitting || sending || unknownResult}
            aria-invalid={!!errors[name]}
            aria-describedby={errors[name] ? `certificate-${name}-error` : undefined}
          />
          {errors[name] && (
            <p className="field-error" id={`certificate-${name}-error`}>
              {errors[name]?.message}
            </p>
          )}
        </div>
      ))}
      {kind === 'act' && (
        <>
          <div className="field">
            <label htmlFor="act-from">Начало периода</label>
            <Input
              id="act-from"
              type="date"
              required
              disabled={sending || unknownResult}
              {...register('period_from')}
            />
          </div>
          <div className="field">
            <label htmlFor="act-to">Конец периода</label>
            <Input
              id="act-to"
              type="date"
              required
              disabled={sending || unknownResult}
              {...register('period_to')}
            />
          </div>
          <p className="field-hint">
            Период до 366 дней. Конец не раньше начала; окончательно проверит сервер.
          </p>
        </>
      )}
      {unknownResult ? (
        <Button
          variant="secondary"
          disabled={sending}
          onClick={() => {
            if (lastInput.current) void submit(lastInput.current);
          }}
        >
          Повторить с тем же ключом
        </Button>
      ) : (
        <Button type="submit" disabled={isSubmitting || sending}>
          {isSubmitting || sending ? 'Отправляем…' : label}
        </Button>
      )}
      <p className="field-hint">
        Учебный документ будет подготовлен в PDF. После отправки вы получите отдельную ссылку на
        задание.
      </p>
    </form>
  );
}
