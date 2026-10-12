import '@testing-library/jest-dom';

class MockWebSocket {
  url: string;
  readyState: number = 1;
  onopen: any = null;
  onclose: any = null;
  onmessage: any = null;
  onerror: any = null;

  constructor(url: string) {
    this.url = url;
  }

  send() {}
  close() {}
}

(globalThis as any).WebSocket = MockWebSocket;
