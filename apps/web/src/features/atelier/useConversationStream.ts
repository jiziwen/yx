/** 正式消息靠快照恢复；临时回复使用带 Run/尝试/序号的整段前缀替换。 */
import { useEffect, useRef, useState } from 'react';
import { applyReplyEvent, type PreviewMap } from './replyStream';

export type ConnectionState = 'connecting' | 'live' | 'recovering' | 'paused' | 'revoked';

export default function useConversationStream({
  projectId,
  conversationId,
  privacyEpoch,
  enabled,
  onSync,
  onReset,
  onRevoked,
}: {
  projectId: string;
  conversationId?: string;
  privacyEpoch: number;
  enabled: boolean;
  onSync: () => Promise<unknown>;
  onReset: () => void;
  onRevoked: () => void;
}) {
  const [state, setState] = useState<ConnectionState>('connecting');
  const [failures, setFailures] = useState(0);
  const [previews, setPreviews] = useState<PreviewMap>({});
  const callbacks = useRef({ onSync, onReset, onRevoked });
  callbacks.current = { onSync, onReset, onRevoked };
  useEffect(() => {
    setPreviews({});
    if (!enabled) return;
    let disposed = false;
    let revoked = false;
    let source: EventSource | null = null;
    let retry: ReturnType<typeof setTimeout> | undefined;
    let attempts = 0;
    let seenAt = Date.now();
    let syncing = false;
    let dirty = false;
    const sync = async () => {
      dirty = true;
      if (syncing) return;
      syncing = true;
      try {
        do {
          dirty = false;
          await callbacks.current.onSync();
        } while (dirty && !disposed && !revoked);
      } catch {
        // 权威读取的错误由 Query 展示；通知本身不合成成功回复。
      } finally {
        syncing = false;
      }
    };
    const close = () => {
      source?.close();
      source = null;
      clearTimeout(retry);
      setPreviews({});
    };
    const reconnect = () => {
      close();
      if (disposed || revoked || document.hidden) return;
      attempts += 1;
      setFailures(attempts);
      setState('recovering');
      retry = setTimeout(connect, Math.min(30000, 1000 * 2 ** Math.min(attempts - 1, 5)));
    };
    const connect = () => {
      if (disposed || revoked || document.hidden || source) return;
      seenAt = Date.now();
      setState(attempts ? 'recovering' : 'connecting');
      const current = new EventSource(
        conversationId
          ? `/api/v1/web/conversations/${encodeURIComponent(conversationId)}/events`
          : `/api/v1/web/projects/${encodeURIComponent(projectId)}/conversation/events`,
        { withCredentials: true },
      );
      source = current;
      const listen = (name: string, callback: (event: MessageEvent<string>) => void) =>
        current.addEventListener(name, (event) => {
          if (disposed || source !== current || revoked) return;
          seenAt = Date.now();
          callback(event as MessageEvent<string>);
        });
      listen('stream.ready', (event) => {
        try {
          if (JSON.parse(event.data).payload.privacy_epoch !== privacyEpoch) {
            callbacks.current.onReset();
            reconnect();
            return;
          }
        } catch {
          reconnect();
          return;
        }
        attempts = 0;
        setFailures(0);
        setState('live');
        void sync();
      });
      for (const name of ['run.updated', 'message.committed', 'stream.sync'])
        listen(name, () => void sync());
      listen('message.delta', (event) => {
        try {
          const value: unknown = JSON.parse(event.data);
          setPreviews((current) => applyReplyEvent(current, value, privacyEpoch));
        } catch {
          void sync();
        }
      });
      listen('stream.heartbeat', () => {});
      listen('stream.reconnect', reconnect);
      listen('stream.reset', () => {
        callbacks.current.onReset();
        reconnect();
      });
      listen('stream.revoked', () => {
        revoked = true;
        close();
        setState('revoked');
        callbacks.current.onRevoked();
      });
      current.onerror = () => {
        if (source === current) reconnect();
      };
    };
    const foreground = () => {
      if (document.hidden) {
        close();
        setState('paused');
      } else if (!revoked) {
        void sync();
        connect();
      }
    };
    const watchdog = setInterval(() => {
      if (source && Date.now() - seenAt > 35000) reconnect();
    }, 1000);
    document.addEventListener('visibilitychange', foreground);
    window.addEventListener('online', foreground);
    window.addEventListener('focus', foreground);
    foreground();
    return () => {
      disposed = true;
      close();
      clearInterval(watchdog);
      document.removeEventListener('visibilitychange', foreground);
      window.removeEventListener('online', foreground);
      window.removeEventListener('focus', foreground);
    };
  }, [projectId, conversationId, privacyEpoch, enabled]);
  return { state, failures, previews };
}
