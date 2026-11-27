import { zodResolver } from '@hookform/resolvers/zod';
import { useState } from 'react';
import { useForm } from 'react-hook-form';
import { z } from 'zod';
import { AtSign, Eye, EyeOff, Lock } from 'lucide-react';
import { Button } from '../../components/ui/button';
import { Input } from '../../components/ui/input';
import { Alert } from '../../components/ui/alert';
import { ApiError, errorRequestId, explainError } from '../../lib/api/errors';
import { DEMO_LOGIN_PASSWORD, demoAccounts } from './demo-accounts';

const schema = z.object({
  email: z.email('Введите корректный email.'),
  password: z.string().min(1, 'Введите пароль.'),
});

/** Кнопочному демо-входу не подходят упрёки ручной формы: посетитель ничего не вводил. */
function failureText(error: unknown, demo: boolean): string {
  if (error instanceof ApiError && demo) {
    if (error.status === 401)
      return 'Демо-вход недоступен: сервер не принял демо-учётку. Попробуйте позже.';
    if (error.status === 429) {
      const minutes = error.retryAfterMs
        ? Math.max(1, Math.round(error.retryAfterMs / 60_000))
        : null;
      return minutes === null
        ? 'Демо-вход временно ограничен. Повторите позже.'
        : `Демо-вход временно ограничен. Повторите через ${minutes} мин.`;
    }
  }
  if (error instanceof ApiError && error.status === 401)
    return 'Email или пароль не подошли. Проверьте данные.';
  return explainError(error);
}

export function LoginForm({
  onLogin,
}: {
  onLogin: (email: string, password: string) => Promise<void>;
}) {
  const [failure, setFailure] = useState<{ error: unknown; demo: boolean } | null>(null);
  const [passwordVisible, setPasswordVisible] = useState(false);
  const {
    register,
    handleSubmit,
    setValue,
    formState: { errors, isSubmitting },
  } = useForm<z.infer<typeof schema>>({
    resolver: zodResolver(schema),
    defaultValues: { email: '', password: '' },
  });
  async function submit({ email, password }: z.infer<typeof schema>, demo: boolean) {
    setFailure(null);
    try {
      await onLogin(email, password);
    } catch (error) {
      setFailure({ error, demo });
    } finally {
      setValue('password', '');
    }
  }
  /** Демо-кнопка идёт тем же путём, что и ручной сабмит: валидация, ошибки, блокировка. */
  function loginAsDemo(email: string) {
    setValue('email', email, { shouldValidate: true });
    setValue('password', DEMO_LOGIN_PASSWORD, { shouldValidate: true });
    void handleSubmit((values) => submit(values, true))();
  }
  return (
    <form
      className="form-stack"
      noValidate
      onSubmit={handleSubmit((values) => submit(values, false))}
    >
      {failure !== null && (
        <Alert tone="error" requestId={errorRequestId(failure.error)}>
          {failureText(failure.error, failure.demo)}
        </Alert>
      )}
      <div className="field">
        <label htmlFor="login-email">Email</label>
        <div className="field-with-icon">
          <AtSign size={18} aria-hidden="true" />
          <Input
            id="login-email"
            type="email"
            autoComplete="username"
            autoCapitalize="none"
            placeholder="имя@gymnasium.online"
            {...register('email')}
            aria-invalid={!!errors.email}
            aria-describedby={errors.email ? 'login-email-error' : undefined}
          />
        </div>
        {errors.email && (
          <p className="field-error" id="login-email-error">
            {errors.email.message}
          </p>
        )}
      </div>
      <div className="field">
        <label htmlFor="login-password">Пароль</label>
        <div className="field-with-icon has-trailing">
          <Lock size={18} aria-hidden="true" />
          <Input
            id="login-password"
            type={passwordVisible ? 'text' : 'password'}
            autoComplete="current-password"
            placeholder="Введите пароль"
            {...register('password')}
            aria-invalid={!!errors.password}
            aria-describedby={errors.password ? 'login-password-error' : undefined}
          />
          <button
            type="button"
            className="password-toggle"
            aria-label="Показать/скрыть пароль"
            aria-pressed={passwordVisible}
            disabled={isSubmitting}
            onClick={() => {
              setPasswordVisible((visible) => !visible);
            }}
          >
            {passwordVisible ? (
              <EyeOff size={18} aria-hidden="true" />
            ) : (
              <Eye size={18} aria-hidden="true" />
            )}
          </button>
        </div>
        {errors.password && (
          <p className="field-error" id="login-password-error">
            {errors.password.message}
          </p>
        )}
      </div>
      <Button type="submit" disabled={isSubmitting}>
        {isSubmitting ? 'Входим…' : 'Войти'}
      </Button>
      <p className="login-recovery">
        Забыли пароль? Обратитесь к куратору или администратору школы
      </p>
      <div className="login-demo" role="group" aria-label="Демо-доступ">
        <p className="login-demo-title">Или осмотреть демо-школу без учётки</p>
        <div className="login-demo-actions">
          {demoAccounts.map((account) => (
            <Button
              key={account.email}
              type="button"
              variant="secondary"
              disabled={isSubmitting}
              onClick={() => {
                loginAsDemo(account.email);
              }}
            >
              {account.label}
            </Button>
          ))}
        </div>
      </div>
    </form>
  );
}
