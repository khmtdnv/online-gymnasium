import { zodResolver } from '@hookform/resolvers/zod';
import { useState } from 'react';
import { useForm } from 'react-hook-form';
import { z } from 'zod';
import { AtSign, Eye, EyeOff, Lock } from 'lucide-react';
import { Button } from '../../components/ui/button';
import { Input } from '../../components/ui/input';
import { Alert } from '../../components/ui/alert';
import { ApiError, errorRequestId, explainError } from '../../lib/api/errors';

const schema = z.object({
  email: z.email('Введите корректный email.'),
  password: z.string().min(1, 'Введите пароль.'),
});

export function LoginForm({
  onLogin,
}: {
  onLogin: (email: string, password: string) => Promise<void>;
}) {
  const [failure, setFailure] = useState<unknown>(null);
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
  async function submit({ email, password }: z.infer<typeof schema>) {
    setFailure(null);
    try {
      await onLogin(email, password);
    } catch (error) {
      setFailure(error);
    } finally {
      setValue('password', '');
    }
  }
  return (
    <form className="form-stack" noValidate onSubmit={handleSubmit(submit)}>
      {failure !== null && (
        <Alert tone="error" requestId={errorRequestId(failure)}>
          {failure instanceof ApiError && failure.status === 401
            ? 'Email или пароль не подошли. Проверьте данные.'
            : explainError(failure)}
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
    </form>
  );
}
