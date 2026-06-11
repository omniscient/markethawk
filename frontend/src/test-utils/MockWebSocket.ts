/** Minimal WebSocket mock. Assign to global.WebSocket before each test that opens a WS. */
export class MockWebSocket {
  static lastInstance: MockWebSocket | null = null;

  url: string;
  readyState: number = WebSocket.CONNECTING;

  onopen: ((e: Event) => void) | null = null;
  onmessage: ((e: MessageEvent) => void) | null = null;
  onerror: ((e: Event) => void) | null = null;
  onclose: ((e: CloseEvent) => void) | null = null;

  constructor(url: string) {
    this.url = url;
    MockWebSocket.lastInstance = this;
  }

  /** Call from tests to simulate the connection opening. */
  simulateOpen() {
    this.readyState = WebSocket.OPEN;
    this.onopen?.(new Event('open'));
  }

  /** Call from tests to push a server message. */
  simulateMessage(data: unknown) {
    const ev = new MessageEvent('message', { data: JSON.stringify(data) });
    this.onmessage?.(ev);
  }

  /** Call from tests to simulate a WS error. */
  simulateError() {
    this.onerror?.(new Event('error'));
  }

  /** Call from tests to simulate the connection closing. */
  simulateClose(wasClean = false) {
    this.readyState = WebSocket.CLOSED;
    const ev = new CloseEvent('close', { wasClean });
    this.onclose?.(ev);
  }

  close() {
    this.readyState = WebSocket.CLOSED;
  }

  send(_data: string) {}
}

type GlobalWithWebSocket = typeof globalThis & { WebSocket: typeof WebSocket };

/** Install MockWebSocket as the global WebSocket implementation. Returns a cleanup fn. */
export function installMockWebSocket(): () => void {
  const g = globalThis as GlobalWithWebSocket;
  const original = g.WebSocket;
  g.WebSocket = MockWebSocket as unknown as typeof WebSocket;
  MockWebSocket.lastInstance = null;
  return () => {
    g.WebSocket = original;
  };
}
