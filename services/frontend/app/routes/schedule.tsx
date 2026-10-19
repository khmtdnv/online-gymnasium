import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Plus, RefreshCw } from 'lucide-react';
import { useState } from 'react';
import { Link } from 'react-router';
import { PageHeader } from '../components/page-header';
import { AsyncState } from '../components/async-state';
import { Alert } from '../components/ui/alert';
import { Button } from '../components/ui/button';
import { Dialog } from '../components/ui/dialog';
import { DayFilters, useDaySelection } from '../features/schedule/day-filters';
import { LessonForm } from '../features/schedule/lesson-form';
import { LessonList } from '../features/schedule/lesson-list';
import { scheduleKeys, workloadKeys } from '../features/schedule/query-keys';
import { utcDateTime } from '../features/schedule/utc';
import type { Lesson } from '../lib/api/contracts';
import { useFeatures } from '../lib/api/context';
import { ApiError, errorRequestId, explainError } from '../lib/api/errors';

export default function Schedule() {
  const selection = useDaySelection();
  const { schedule } = useFeatures();
  const queryClient = useQueryClient();
  const [editor, setEditor] = useState<Lesson | 'create' | null>(null);
  const [canceling, setCanceling] = useState<Lesson | null>(null);
  const [cancelBusy, setCancelBusy] = useState(false);
  const [cancelFailure, setCancelFailure] = useState<unknown>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [editorConflict, setEditorConflict] = useState<Lesson | 'missing' | null>(null);
  const [cancelConflict, setCancelConflict] = useState<Lesson | 'missing' | null>(null);
  const query = useQuery({
    queryKey: scheduleKeys.day(selection.classId ?? 0, selection.day),
    enabled: selection.classId !== null,
    queryFn: ({ signal }) => schedule.listLessons(selection.classId!, selection.day, signal),
  });

  function refreshDays(updated: Lesson, previous?: Lesson) {
    const affected = [updated, ...(previous ? [previous] : [])];
    for (const lesson of affected) {
      const day = new Date(lesson.starts_at).toISOString().slice(0, 10);
      void queryClient.invalidateQueries({ queryKey: scheduleKeys.day(lesson.class_id, day) });
      void queryClient.invalidateQueries({ queryKey: workloadKeys.day(lesson.class_id, day) });
    }
  }
  async function cancel() {
    if (!canceling) return;
    setCancelBusy(true);
    setCancelFailure(null);
    try {
      const result = await schedule.cancelLesson(canceling.id, canceling.version);
      setNotice(
        `Урок ${result.id} отменён. Обновляем выборку; кеш может отражать изменение с задержкой.`,
      );
      refreshDays(result, canceling);
      setCanceling(null);
    } catch (error) {
      setCancelFailure(error);
      if (error instanceof ApiError && error.status === 409) {
        const fresh = await query.refetch();
        const current = fresh.data?.find((lesson) => lesson.id === canceling.id);
        setCancelConflict(current && current.version > canceling.version ? current : 'missing');
      }
    } finally {
      setCancelBusy(false);
    }
  }
  return (
    <>
      <PageHeader
        title="Расписание"
        eyebrow="Школьный ритм"
        description="Уроки выбранного класса на один день. Время показано в UTC, а не в часовом поясе устройства."
        action={
          <Button
            onClick={() => {
              setEditorConflict(null);
              setEditor('create');
            }}
          >
            <Plus size={19} aria-hidden="true" />
            Новый урок
          </Button>
        }
      />
      <DayFilters
        classIdText={selection.classIdText}
        day={selection.day}
        onChange={selection.change}
      />
      {notice && <Alert tone="success">{notice}</Alert>}
      {selection.classId === null ? (
        <AsyncState
          state="empty"
          title="Выберите класс и день"
          message="Используйте числовой ID класса из сервиса расписания."
        />
      ) : (
        <>
          <div className="page-header">
            <h2>Класс · ID {selection.classId}</h2>
            <div className="form-actions">
              <Link
                className="button button-secondary"
                to={`/workload?class_id=${selection.classId}&day=${selection.day}`}
              >
                Нагрузка дня
              </Link>
              <Button
                variant="ghost"
                onClick={() => {
                  void query.refetch();
                }}
                disabled={query.isFetching}
              >
                <RefreshCw size={18} aria-hidden="true" />
                Обновить
              </Button>
            </div>
          </div>
          {query.isPending ? (
            <AsyncState state="loading" title="Читаем расписание" />
          ) : query.isError ? (
            <AsyncState
              state="error"
              title="Расписание недоступно"
              message={explainError(query.error)}
              requestId={errorRequestId(query.error)}
              onRetry={() => {
                void query.refetch();
              }}
            />
          ) : query.data.length === 0 ? (
            <AsyncState
              state="empty"
              title="На этот день уроков нет"
              message="Здесь появятся плановые уроки выбранного класса."
            />
          ) : (
            <LessonList
              lessons={query.data}
              onEdit={(lesson) => {
                setEditorConflict(null);
                setEditor(lesson);
              }}
              onCancel={(lesson) => {
                setCanceling(lesson);
                setCancelFailure(null);
                setCancelConflict(null);
              }}
            />
          )}
        </>
      )}
      <Dialog
        open={editor !== null}
        onOpenChange={(open) => {
          if (!open) setEditor(null);
        }}
        title={editor === 'create' ? 'Новый урок' : 'Перенос урока'}
        description="Проверяем время и числовые ID. Изменение урока использует прочитанную версию."
      >
        {editorConflict && (
          <Alert>
            {editorConflict === 'missing' ? (
              'Урок не найден с более новой версией на этом дне. Сохранение остановлено: найдите актуальный урок и сверьте его состояние.'
            ) : (
              <>
                Текущее состояние: версия {editorConflict.version},{' '}
                {utcDateTime(editorConflict.starts_at)} — {utcDateTime(editorConflict.ends_at)}.
                Введённый перенос сохранён. Сверьте его перед повторным сохранением.
                <Button
                  variant="secondary"
                  onClick={() => {
                    setEditor(editorConflict);
                    setEditorConflict(null);
                  }}
                >
                  Использовать версию {editorConflict.version} после сверки
                </Button>
              </>
            )}
          </Alert>
        )}
        {editor !== null && (
          <LessonForm
            key={editor === 'create' ? 'create' : editor.id}
            lesson={editor === 'create' ? undefined : editor}
            classId={selection.classId}
            day={selection.day}
            savingBlocked={editorConflict !== null}
            onSubmit={async (input, key) => {
              try {
                const result =
                  'class_id' in input
                    ? await schedule.createLesson(input, key!)
                    : await schedule.updateLesson((editor as Lesson).id, input);
                setNotice(
                  `Урок ${result.id} ${'class_id' in input ? 'создан' : 'перенесён'}. Перечитываем затронутые дни.`,
                );
                refreshDays(result, editor === 'create' ? undefined : editor);
                setEditor(null);
              } catch (error) {
                if (error instanceof ApiError && error.status === 409 && editor !== 'create') {
                  const fresh = await query.refetch();
                  const current = fresh.data?.find((lesson) => lesson.id === editor.id);
                  setEditorConflict(
                    current && current.version > editor.version ? current : 'missing',
                  );
                }
                throw error;
              }
            }}
          />
        )}
      </Dialog>
      <Dialog
        open={canceling !== null}
        onOpenChange={(open) => {
          if (!open && !cancelBusy) setCanceling(null);
        }}
        title="Отменить урок?"
        description={`Урок ${canceling?.id ?? ''} исчезнет из планового расписания. Подтверждение использует версию ${canceling?.version ?? ''}.`}
      >
        {cancelFailure !== null && (
          <Alert tone="error" requestId={errorRequestId(cancelFailure)}>
            {explainError(cancelFailure)}
          </Alert>
        )}
        {cancelConflict && (
          <Alert>
            {cancelConflict === 'missing' ? (
              'Урок не найден с более новой версией на этом дне. Найдите актуальный урок перед отменой.'
            ) : (
              <>
                Текущая версия {cancelConflict.version}: {utcDateTime(cancelConflict.starts_at)} —{' '}
                {utcDateTime(cancelConflict.ends_at)}. Отмена не выполнена автоматически.
                <Button
                  variant="secondary"
                  onClick={() => {
                    setCanceling(cancelConflict);
                    setCancelConflict(null);
                    setCancelFailure(null);
                  }}
                >
                  Использовать версию {cancelConflict.version} после сверки
                </Button>
              </>
            )}
          </Alert>
        )}
        <div className="form-actions">
          <Button
            variant="danger"
            disabled={cancelBusy || cancelConflict !== null}
            onClick={() => {
              void cancel();
            }}
          >
            Подтвердить отмену
          </Button>
          <Button variant="secondary" disabled={cancelBusy} onClick={() => setCanceling(null)}>
            Оставить урок
          </Button>
        </div>
      </Dialog>
    </>
  );
}
