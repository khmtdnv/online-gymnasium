import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useRef, useState, type FormEvent } from 'react';
import { Alert } from '../../components/ui/alert';
import { Button } from '../../components/ui/button';
import { explainError } from '../../lib/api/errors';
import type { HomeworkAnswer, HomeworkApi } from './api';
import { HomeworkAnswerCard } from './homework-answer-form';

/** Последние работы класса и полная история выбранного ученика. */
export function HomeworkAnswerReview({
  homeworkId,
  api,
}: {
  homeworkId: number;
  api: HomeworkApi;
}) {
  const [studentId, setStudentId] = useState<string | undefined>();
  const [offset, setOffset] = useState(0);
  const query = useQuery({
    queryKey: ['homework', 'answers', homeworkId, 'teacher', studentId, offset],
    queryFn: ({ signal }) => api.listAnswers(homeworkId, { studentId, offset }, signal),
  });
  return (
    <section className="card">
      <h2>Работы учеников</h2>
      <Button variant="secondary" disabled={query.isFetching} onClick={() => void query.refetch()}>
        Обновить работы
      </Button>{' '}
      {studentId && (
        <Button
          variant="secondary"
          onClick={() => {
            setStudentId(undefined);
            setOffset(0);
          }}
        >
          Все ученики
        </Button>
      )}
      {query.isPending && <p role="status">Загружаем работы…</p>}
      {query.isError && <Alert tone="error">{explainError(query.error)}</Alert>}
      {query.isSuccess && !query.data.length && <p>Сданных работ пока нет.</p>}
      {(query.data ?? []).map((answer) => (
        <HomeworkAnswerCard key={answer.id} answer={answer} api={api}>
          {!studentId && (
            <Button
              variant="secondary"
              onClick={() => {
                setStudentId(answer.student_id);
                setOffset(0);
              }}
            >
              История: {answer.student_name}
            </Button>
          )}
          {answer.status === 'submitted' && <ReviewForm answer={answer} api={api} />}
        </HomeworkAnswerCard>
      ))}
      {query.isSuccess && (
        <div>
          <Button
            variant="secondary"
            disabled={!offset}
            onClick={() => setOffset(Math.max(0, offset - 50))}
          >
            Предыдущие
          </Button>{' '}
          <Button
            variant="secondary"
            disabled={query.data.length < 50}
            onClick={() => setOffset(offset + 50)}
          >
            Следующие
          </Button>
        </div>
      )}
    </section>
  );
}

export function ReviewForm({ answer, api }: { answer: HomeworkAnswer; api: HomeworkApi }) {
  const cache = useQueryClient();
  const [grade, setGrade] = useState('5');
  const [comment, setComment] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const active = useRef<AbortController | null>(null);
  useEffect(() => () => active.current?.abort(), []);
  async function review(event: FormEvent, status: 'graded' | 'returned') {
    event.preventDefault();
    if (active.current) return;
    if (status === 'returned' && !comment.trim()) {
      setError('При возврате напишите, что нужно исправить.');
      return;
    }
    const controller = new AbortController();
    active.current = controller;
    setBusy(true);
    setError(null);
    try {
      await api.reviewAnswer(
        answer.homework_id,
        answer.id,
        {
          status,
          grade: status === 'graded' ? Number(grade) : null,
          teacher_comment: comment.trim(),
        },
        controller.signal,
      );
      await cache.invalidateQueries({ queryKey: ['homework', 'answers', answer.homework_id] });
      await cache.invalidateQueries({ queryKey: ['teacher-reviews'] });
      await cache.invalidateQueries({ queryKey: ['teacher-reviews-preview'] });
    } catch (error) {
      if (!controller.signal.aborted) {
        setError(explainError(error));
        await cache.invalidateQueries({ queryKey: ['homework', 'answers', answer.homework_id] });
      }
    } finally {
      active.current = null;
      if (!controller.signal.aborted) setBusy(false);
    }
  }
  const pending = answer.files.some((file) => file.upload_status === 'pending');
  return (
    <form className="homework-form" onSubmit={(event) => void review(event, 'graded')}>
      {error && <Alert tone="error">{error}</Alert>}
      <label>
        Оценка
        <select
          className="input"
          value={grade}
          disabled={busy}
          onChange={(event) => setGrade(event.target.value)}
        >
          {[2, 3, 4, 5].map((value) => (
            <option key={value}>{value}</option>
          ))}
        </select>
      </label>
      <label>
        Комментарий преподавателя
        <textarea
          className="input"
          maxLength={10000}
          value={comment}
          disabled={busy}
          onChange={(event) => setComment(event.target.value)}
        />
      </label>
      {pending && (
        <p>Не все файлы загружены. Оценить пока нельзя; можно вернуть работу с комментарием.</p>
      )}
      <Button type="submit" disabled={busy || pending}>
        Поставить оценку
      </Button>{' '}
      <Button
        type="button"
        variant="secondary"
        disabled={busy}
        onClick={(event) => void review(event, 'returned')}
      >
        Вернуть на исправление
      </Button>
    </form>
  );
}
