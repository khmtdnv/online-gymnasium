import { act, renderHook, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { usePen } from '../app/features/pen/use-pen';

vi.mock('../app/features/auth/session-context', () => ({
  useSession: () => ({ session }),
}));
const session = { getAccessToken: () => 'test-token' };

afterEach(() => vi.unstubAllGlobals());

it('снимает предупреждение заполненной очереди после ACK без переподключения', async () => {
  const sent: string[] = [];
  const sockets: FakeSocket[] = [];
  class FakeSocket {
    static OPEN = 1;
    readyState = 1;
    onmessage?: (event: { data: string }) => void;
    constructor() {
      sockets.push(this);
    }
    send(data: string) {
      sent.push(data);
    }
    close() {}
  }
  vi.stubGlobal('WebSocket', FakeSocket);
  const { result, unmount } = renderHook(() => usePen(1, 'student', false));
  await waitFor(() => expect(sockets).toHaveLength(1));
  const socket = sockets[0];
  act(() => socket.onmessage?.({ data: JSON.stringify({ type: 'ready', after: 0 }) }));
  const point = { x: 0.1, y: 0.2 };
  act(() => {
    for (let i = 0; i < 49; i++) {
      result.current.start(point);
      result.current.end();
    }
    result.current.start(point);
    for (let i = 0; i < 63; i++) result.current.move(point);
    result.current.end();
  });
  expect(result.current.message).toContain('Очередь заполнена');
  act(() =>
    socket.onmessage?.({
      data: JSON.stringify({
        type: 'ack',
        batch: { ...JSON.parse(sent[0]), id: 1 },
      }),
    }),
  );
  expect(result.current.message).toBe('Сохраняем штрихи… Не закрывайте вкладку.');
  act(() => {
    for (let i = 1; i < 50; i++) {
      socket.onmessage?.({
        data: JSON.stringify({ type: 'ack', batch: { ...JSON.parse(sent[i]), id: i + 1 } }),
      });
    }
  });
  expect(result.current.message).toBe('Подключено. Все штрихи сохранены.');
  expect(sockets).toHaveLength(1);
  act(() => socket.onmessage?.({ data: 'invalid JSON' }));
  expect(result.current.message).toContain('неподходящие данные');
  unmount();
});
