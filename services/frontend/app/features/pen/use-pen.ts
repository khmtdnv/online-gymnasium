import { useEffect, useRef, useState } from 'react';
import { useSession } from '../auth/session-context';
import {
  penBatchSchema,
  penMessageSchema,
  type PenBatch,
  type PenPoint,
  type SavedPenBatch,
} from './contracts';

/** Одна очередь в памяти: неизвестный результат повторяется с прежним batch_id. */
export type PenConnectionStatus = 'connecting' | 'online' | 'offline' | 'failure';

export function usePen(lessonId: number, studentId: string, readonly: boolean) {
  const { session } = useSession();
  const [version, setVersion] = useState(0);
  const [view, setView] = useState({
    batches: [] as PenBatch[],
    ready: false,
    message: 'Подключаем ручку…',
    status: 'connecting' as PenConnectionStatus,
    queue: 0,
  });
  const pending = useRef<PenBatch[]>([]);
  const saved = useRef(new Map<string, SavedPenBatch>());
  const buffer = useRef<PenPoint[]>([]);
  const stroke = useRef<string | null>(null);
  const lastPoint = useRef<PenPoint | null>(null);
  const cursor = useRef(0);
  const socket = useRef<WebSocket | null>(null);
  const ready = useRef(false);
  const opened = useRef(false);
  const inFlight = useRef<string | null>(null);
  const error = useRef<string | null>(null);
  const identity = useRef(`${lessonId}:${studentId}`);

  function publish() {
    const drawing: PenBatch[] =
      buffer.current.length && stroke.current
        ? [
            {
              batch_id: 'buffer',
              sequence: 4097,
              stroke_id: stroke.current,
              points: [...buffer.current],
              finished: false,
            },
          ]
        : [];
    const batches = [...saved.current.values(), ...pending.current, ...drawing];
    setView({
      batches,
      ready: ready.current,
      status: error.current
        ? 'failure'
        : ready.current
          ? 'online'
          : opened.current
            ? 'offline'
            : 'connecting',
      queue: pending.current.length + (drawing.length ? 1 : 0),
      message:
        error.current ??
        (!ready.current
          ? 'Соединение прервано. Несохранённые штрихи пока в этой вкладке.'
          : pending.current.length >= 50
            ? 'Очередь заполнена. Дождитесь сохранения и начните новый штрих.'
            : pending.current.length || buffer.current.length
              ? 'Сохраняем штрихи… Не закрывайте вкладку.'
              : 'Подключено. Все штрихи сохранены.'),
    });
  }

  function sendNext() {
    if (
      !ready.current ||
      inFlight.current ||
      !pending.current.length ||
      socket.current?.readyState !== WebSocket.OPEN
    )
      return;
    inFlight.current = pending.current[0].batch_id;
    socket.current.send(JSON.stringify(pending.current[0]));
  }

  function flush(finished: boolean) {
    if (!stroke.current || readonly || !ready.current) return;
    if (!buffer.current.length && (!finished || !lastPoint.current)) return;
    if (pending.current.length >= 50) {
      publish();
      return;
    }
    const sequence = Math.max(cursor.current, pending.current.at(-1)?.sequence ?? 0) + 1;
    if (sequence > 4096) {
      error.current = 'Достигнут предел страницы. Сохранённый рисунок доступен для просмотра.';
      publish();
      return;
    }
    pending.current.push(
      penBatchSchema.parse({
        batch_id: crypto.randomUUID(),
        sequence,
        stroke_id: stroke.current,
        points: buffer.current.length ? buffer.current : [lastPoint.current],
        finished,
      }),
    );
    buffer.current = [];
    if (finished) stroke.current = null;
    sendNext();
    publish();
  }

  useEffect(() => {
    if (!session) return;
    let disposed = false;
    let retryTimer: ReturnType<typeof setTimeout> | undefined;
    let retries = 0;
    const key = `${lessonId}:${studentId}`;
    if (identity.current !== key) {
      identity.current = key;
      pending.current = [];
      buffer.current = [];
      stroke.current = null;
    }
    async function connect() {
      ready.current = false;
      opened.current = false;
      inFlight.current = null;
      error.current = null;
      saved.current.clear();
      cursor.current = 0;
      publish();
      try {
        const token = session!.getAccessToken() ?? (await session!.refresh());
        if (disposed) return;
        const url = new URL(
          `/api/v1/pen/lessons/${lessonId}/students/${studentId}`,
          window.location.href,
        );
        url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:';
        const ws = new WebSocket(url);
        socket.current = ws;
        ws.onopen = () => ws.send(JSON.stringify({ access_token: token, after: 0 }));
        ws.onmessage = (event) => {
          if (disposed) return;
          try {
            const message = penMessageSchema.parse(JSON.parse(String(event.data)));
            if (message.type === 'ready') {
              if (message.after !== cursor.current) throw new Error('history gap');
              pending.current = pending.current.filter(
                (batch) => !saved.current.has(batch.batch_id),
              );
              if (pending.current.length && pending.current[0].sequence !== cursor.current + 1) {
                error.current =
                  'Рисунок изменён в другой вкладке. Перезагрузите страницу; несохранённые штрихи будут потеряны.';
                ws.close(1000);
              } else {
                ready.current = true;
                opened.current = true;
                retries = 0;
                sendNext();
              }
            } else {
              const batch = message.batch;
              if (message.type === 'ack') {
                const first = pending.current[0];
                const confirmed = penBatchSchema.strip().parse(batch);
                if (!first || JSON.stringify(first) !== JSON.stringify(confirmed))
                  throw new Error('ack mismatch');
                pending.current.shift();
                inFlight.current = null;
              }
              const existing = saved.current.get(batch.batch_id);
              if (
                (!existing && batch.sequence !== cursor.current + 1) ||
                (existing && JSON.stringify(existing) !== JSON.stringify(batch))
              )
                throw new Error('sequence mismatch');
              saved.current.set(batch.batch_id, batch);
              cursor.current = Math.max(cursor.current, batch.sequence);
              sendNext();
            }
            publish();
          } catch {
            error.current = 'Сервер вернул неподходящие данные ручки. Переподключитесь.';
            ws.close(1000);
            publish();
          }
        };
        ws.onclose = async (event) => {
          if (disposed) return;
          flush(true);
          ready.current = false;
          if (event.code === 4403 || event.code === 4404)
            error.current = 'Доступ к этой странице закрыт. Возможно, изменился класс или урок.';
          if (event.code === 4409)
            error.current =
              'Конфликт с другой вкладкой. Перезагрузите страницу; несохранённые штрихи будут потеряны.';
          if (event.code === 4413)
            error.current = 'Страница заполнена. Сохранённые штрихи доступны для просмотра.';
          if (event.code === 4429)
            error.current = 'Слишком много сообщений или подключений. Закройте лишние вкладки.';
          publish();
          if (error.current || event.code === 1000 || retries >= 3) return;
          if (event.code === 4401) {
            try {
              await session!.refresh();
            } catch {
              return;
            }
          }
          if (!disposed) retryTimer = setTimeout(() => void connect(), 1000 * 2 ** retries++);
        };
      } catch {
        error.current = 'Не удалось открыть ручку. Проверьте вход и подключение.';
        publish();
      }
    }
    void connect();
    const timer = setInterval(() => flush(false), 200);
    return () => {
      disposed = true;
      ready.current = false;
      clearInterval(timer);
      clearTimeout(retryTimer);
      socket.current?.close(1000);
    };
    // Изменение снимка холста не должно пересоздавать соединение.
  }, [lessonId, studentId, session, version]);

  return {
    ...view,
    reconnect: () => setVersion((value) => value + 1),
    start(point: PenPoint) {
      if (readonly || !ready.current || pending.current.length >= 50) return;
      stroke.current = crypto.randomUUID();
      buffer.current = [point];
      lastPoint.current = point;
      publish();
    },
    move(point: PenPoint) {
      if (!stroke.current || !ready.current || readonly || buffer.current.length >= 64) return;
      buffer.current.push(point);
      lastPoint.current = point;
      if (buffer.current.length >= 64) flush(false);
      publish();
    },
    end: () => flush(true),
  };
}
