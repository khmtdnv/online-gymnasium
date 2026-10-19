import { useSearchParams } from 'react-router';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { daySchema, positiveIdSchema } from '../../lib/api/contracts';
import { Button } from '../../components/ui/button';
import { Input } from '../../components/ui/input';

export const textIdSchema = z
  .string()
  .trim()
  .regex(/^[1-9]\d*$/, 'Введите положительный целый ID.')
  .refine(
    (value) => positiveIdSchema.safeParse(Number(value)).success,
    'ID слишком большой для точного отображения.',
  );
const filterSchema = z.object({ class_id: textIdSchema, day: daySchema });

export function useDaySelection() {
  const [params, setParams] = useSearchParams();
  const classId = params.get('class_id') ?? '';
  const day = params.get('day') ?? new Date().toISOString().slice(0, 10);
  const valid = filterSchema.safeParse({ class_id: classId, day });
  return {
    classIdText: classId,
    day,
    classId: valid.success ? Number(valid.data.class_id) : null,
    change: (values: z.infer<typeof filterSchema>) => setParams(values),
  };
}

export function DayFilters({
  classIdText,
  day,
  onChange,
}: {
  classIdText: string;
  day: string;
  onChange: (values: z.infer<typeof filterSchema>) => void;
}) {
  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<z.infer<typeof filterSchema>>({
    resolver: zodResolver(filterSchema),
    values: { class_id: classIdText, day },
  });
  return (
    <form className="filters card" noValidate onSubmit={handleSubmit(onChange)}>
      <div className="field">
        <label htmlFor="filter-class">ID класса</label>
        <Input
          id="filter-class"
          inputMode="numeric"
          placeholder="Например, 9021"
          {...register('class_id')}
          aria-invalid={!!errors.class_id}
          aria-describedby={errors.class_id ? 'filter-class-error' : undefined}
        />
        {errors.class_id && (
          <p id="filter-class-error" className="field-error">
            {errors.class_id.message}
          </p>
        )}
      </div>
      <div className="field">
        <label htmlFor="filter-day">День · UTC</label>
        <Input
          id="filter-day"
          type="date"
          {...register('day')}
          aria-invalid={!!errors.day}
          aria-describedby={errors.day ? 'filter-day-error' : undefined}
        />
        {errors.day && (
          <p id="filter-day-error" className="field-error">
            Введите корректную дату.
          </p>
        )}
      </div>
      <Button type="submit">Показать</Button>
    </form>
  );
}
