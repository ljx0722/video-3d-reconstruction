import { useEffect, useRef } from 'react';

export function useWebSocket(jobId: string | undefined, onMessage: (data: any) => void) {
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    if (!jobId) return;
    const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
    const ws = new WebSocket(`${protocol}//${location.host}/ws/${jobId}`);
    wsRef.current = ws;
    ws.onmessage = (e) => onMessage(JSON.parse(e.data));
    ws.onerror = () => {}; // Fallback to polling
    return () => ws.close();
  }, [jobId, onMessage]);
}
