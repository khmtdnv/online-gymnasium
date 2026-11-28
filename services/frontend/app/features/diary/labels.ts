import type { AttendanceStatus, GradeKind } from './api';

/** Подписи статусов посещаемости формы записи урока. */
export const attendanceStatusLabel: Record<AttendanceStatus, string> = {
  present: 'Был',
  absent_sick: 'Не был (болезнь)',
  absent_excused: 'Не был (уважительная)',
  absent_unexcused: 'Не был (без причины)',
};

/** Короткие причины пропуска для сетки недели и сводки. */
export const absenceReasonLabel: Record<'sick' | 'excused' | 'unexcused', string> = {
  sick: 'болезнь',
  excused: 'уважительная',
  unexcused: 'без причины',
};

/** Подписи статусов домашнего задания в сетке недели. */
export const homeworkStatusLabel: Record<
  'submitted' | 'returned' | 'graded' | 'not_submitted',
  string
> = {
  submitted: 'сдано',
  returned: 'на доработке',
  graded: 'проверено',
  not_submitted: 'не сдано',
};

/** Подписи типов оценки. */
export const gradeKindLabel: Record<GradeKind, string> = {
  oral: 'устный',
  written: 'письменный',
  control: 'контрольная',
};
