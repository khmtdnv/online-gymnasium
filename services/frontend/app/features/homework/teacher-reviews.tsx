import { useInfiniteQuery, useQuery } from '@tanstack/react-query';
import { useMemo, useState } from 'react';
import { Link, useSearchParams } from 'react-router';
import { PageHeader } from '../../components/page-header';
import { useFeatures } from '../../lib/api/context';
import { schoolDatetime } from '../schedule/school-dates';
import { displayHomeworkDescription } from './display-description';
import { HomeworkAnswerCard } from './homework-answer-form';
import { ReviewForm } from './homework-answer-review';

type QueueSort = 'new' | 'old';

function SelectedAnswer({ homeworkId, answerId }: { homeworkId: number; answerId: number }) {
  const { homework } = useFeatures();
  const query = useQuery({
    queryKey: ['homework', 'answers', homeworkId, 'selected', answerId],
    queryFn: ({ signal }) => homework.getAnswer(homeworkId, answerId, signal),
  });
  return (
    <section className="workspace-panel homework-review-panel">
      <Link className="workspace-back" to="/homework">
        ← Все работы
      </Link>
      {query.isPending && <p role="status">Загружаем работу…</p>}
      {query.isError && <p role="alert">Не удалось открыть работу.</p>}
      {query.data && (
        <div className="homework-review-layout">
          <HomeworkAnswerCard answer={query.data} api={homework} />
          <div className="homework-review-side">
            {query.data.status === 'submitted' ? (
              <ReviewForm answer={query.data} api={homework} />
            ) : (
              <p className="homework-review-note">
                Работа уже проверена. Повторное решение невозможно.
              </p>
            )}
          </div>
        </div>
      )}
    </section>
  );
}

export function TeacherReviews() {
  const { homework } = useFeatures();
  const [params] = useSearchParams();
  const answerId = Number(params.get('answer'));
  const homeworkId = Number(params.get('homework'));
  const [filter, setFilter] = useState<'submitted' | 'graded' | 'returned' | 'all'>('submitted');
  const [classId, setClassId] = useState('');
  const [subjectId, setSubjectId] = useState('');
  const [sort, setSort] = useState<QueueSort>('new');
  const [search, setSearch] = useState('');
  const query = useInfiniteQuery({
    queryKey: ['teacher-reviews'],
    initialPageParam: 0,
    queryFn: ({ pageParam, signal }) => homework.listTeacherReviews(pageParam, signal),
    getNextPageParam: (page) => page.next_cursor ?? undefined,
  });
  const allItems = query.data?.pages.flatMap((page) => page.items) ?? [];
  const classes = [...new Map(allItems.map((item) => [item.class_id, item.class_name])).entries()];
  const subjects = [
    ...new Map(allItems.map((item) => [item.subject_id, item.subject_name])).entries(),
  ];
  const counts = useMemo(
    () => ({
      submitted: allItems.filter((item) => item.status === 'submitted').length,
      graded: allItems.filter((item) => item.status === 'graded').length,
      returned: allItems.filter((item) => item.status === 'returned').length,
      all: allItems.length,
    }),
    [allItems],
  );
  const needle = search.trim().toLowerCase();
  const items = allItems
    .filter(
      (item) =>
        (filter === 'all' || item.status === filter) &&
        (!classId || item.class_id === Number(classId)) &&
        (!subjectId || item.subject_id === Number(subjectId)) &&
        (!needle ||
          item.student_name.toLowerCase().includes(needle) ||
          item.description.toLowerCase().includes(needle)),
    )
    .sort((a, b) =>
      sort === 'new'
        ? Date.parse(b.submitted_at) - Date.parse(a.submitted_at)
        : Date.parse(a.submitted_at) - Date.parse(b.submitted_at),
    );
  const labels = { submitted: 'На проверке', graded: 'Проверено', returned: 'Возвращено' };
  return (
    <div className="workspace-page teacher-reviews-page">
      <PageHeader
        title="Очередь проверки домашних заданий"
        description="Работы учеников по вашим заданиям."
        action={
          <span className="homework-queue-chip" aria-hidden="true">
            Работ на проверке: {counts.submitted}
          </span>
        }
      />
      {Number.isSafeInteger(answerId) &&
        answerId > 0 &&
        Number.isSafeInteger(homeworkId) &&
        homeworkId > 0 && <SelectedAnswer answerId={answerId} homeworkId={homeworkId} />}
      <div className="teacher-reviews-tabs" aria-label="Состояние работ">
        {(['submitted', 'graded', 'returned', 'all'] as const).map((value) => (
          <button
            key={value}
            className={`teacher-reviews-tab${filter === value ? ' is-active' : ''}`}
            type="button"
            aria-pressed={filter === value}
            onClick={() => setFilter(value)}
          >
            {value === 'all' ? 'Все работы' : labels[value]}
            <span className="teacher-reviews-tab-count" aria-hidden="true">
              {counts[value]}
            </span>
          </button>
        ))}
      </div>
      <div className="teacher-reviews-filters">
        <label>
          Класс{' '}
          <select value={classId} onChange={(event) => setClassId(event.target.value)}>
            <option value="">Все классы</option>
            {classes.map(([id, name]) => (
              <option key={id} value={id}>
                {name}
              </option>
            ))}
          </select>
        </label>
        <label>
          Предмет{' '}
          <select value={subjectId} onChange={(event) => setSubjectId(event.target.value)}>
            <option value="">Все предметы</option>
            {subjects.map(([id, name]) => (
              <option key={id} value={id}>
                {name}
              </option>
            ))}
          </select>
        </label>
        <label>
          Сортировка{' '}
          <select
            value={sort}
            onChange={(event) => setSort(event.target.value as QueueSort)}
            aria-label="Сортировка работ"
          >
            <option value="new">Сначала новые</option>
            <option value="old">Сначала старые</option>
          </select>
        </label>
        <label>
          Поиск ученика{' '}
          <input
            className="input"
            type="search"
            placeholder="Фамилия или тема задания…"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
          />
        </label>
        {query.hasNextPage && <small>Показаны загруженные работы</small>}
      </div>
      {query.isPending && <p role="status">Загружаем работы…</p>}
      {query.isError && (
        <p role="alert">
          Не удалось загрузить работы.{' '}
          <button type="button" onClick={() => void query.refetch()}>
            Повторить
          </button>
        </p>
      )}
      {query.isSuccess && !items.length && <p>В загруженных работах ничего не найдено.</p>}
      <div className="teacher-reviews-list">
        {items.map((item) => (
          <article className={`teacher-review-card is-${item.status}`} key={item.answer_id}>
            <div className="teacher-review-content">
              <div className="teacher-review-course">
                <span>{item.subject_name}</span>
                <span>{item.class_name}</span>
              </div>
              <h2>{item.student_name}</h2>
              <p className="teacher-review-description">
                {displayHomeworkDescription(item.description)}
              </p>
              <p className="teacher-review-date">Сдано {schoolDatetime(item.submitted_at)}</p>
            </div>
            <div className="teacher-review-side">
              <span className={`teacher-review-status is-${item.status}`}>
                {labels[item.status]}
              </span>
              <Link to={`/homework?answer=${item.answer_id}&homework=${item.homework_id}`}>
                Открыть работу <span aria-hidden="true">→</span>
              </Link>
            </div>
          </article>
        ))}
      </div>
      {query.hasNextPage && (
        <button
          className="button button-secondary"
          disabled={query.isFetchingNextPage}
          onClick={() => void query.fetchNextPage()}
        >
          {query.isFetchingNextPage ? 'Загружаем…' : 'Загрузить ещё'}
        </button>
      )}
    </div>
  );
}
