import { zodResolver } from '@hookform/resolvers/zod';
import { useState } from 'react';
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
}: {
  onCreate: (input: CertificateInput) => Promise<void>;
}) {
  const [failure, setFailure] = useState<unknown>(null);
  const [unknownResult, setUnknownResult] = useState(false);
  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<CertificateInput>({
    resolver: zodResolver(certificateInputSchema),
    defaultValues: { student_full_name: '', class_name: '', academic_year: '' },
  });
  async function submit(input: CertificateInput) {
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
            ? 'Результат отправки неизвестен: повтор может создать второе задание. Автоматически запрос не повторяем.'
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
            disabled={isSubmitting || unknownResult}
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
      {unknownResult ? (
        <Button
          variant="secondary"
          onClick={() => {
            setUnknownResult(false);
            setFailure(null);
          }}
        >
          Понимаю риск, начать новую попытку
        </Button>
      ) : (
        <Button type="submit" disabled={isSubmitting}>
          {isSubmitting ? 'Отправляем…' : 'Создать справку'}
        </Button>
      )}
      <p className="field-hint">
        Справка об обучении будет подготовлена в PDF. После отправки вы получите отдельную ссылку на
        задание.
      </p>
    </form>
  );
}
