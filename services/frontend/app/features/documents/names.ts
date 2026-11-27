import type { DocumentType } from './api';

/** Названия типов документов — единый источник для форм, реестра и страницы задания. */
export const documentNames: Record<DocumentType, string> = {
  certificate: 'Справка об обучении',
  contract: 'Договор об обучении',
  act: 'Акт об оказании услуг',
  receipt: 'Квитанция тестовой оплаты',
};

/** Короткие подписи статусов задания генерации для реестра. */
export const jobStatusLabels = {
  pending: 'В очереди',
  processing: 'Готовим PDF',
  completed: 'Готово',
  failed: 'Ошибка генерации',
} as const;
