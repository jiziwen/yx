/** 历史按 seq 稳定翻页，实时快照不覆盖已载入旧页；隐私变化和迟到响应隔离。 */
import { useEffect, useMemo, useRef, useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import {
  api,
  ApiError,
  expectData,
  type AgentConversation,
  type AgentMessagePage,
} from '@yingxu/api-client';

export type ConversationArchive = Pick<
  AgentConversation,
  'project_id' | 'privacy_epoch' | 'messages' | 'runs' | 'older_cursor'
>;

/** 新窗口完全跳过已知末尾时重新建立连续窗口，避免留下用户无法翻页填补的洞。 */
export function mergeSnapshot(
  old: ConversationArchive | null,
  latest: AgentConversation,
): ConversationArchive {
  if (
    !old ||
    old.project_id !== latest.project_id ||
    old.privacy_epoch !== latest.privacy_epoch ||
    (old.messages.length &&
      latest.messages.length &&
      latest.messages[0].seq > old.messages.at(-1)!.seq + 1)
  )
    return latest;
  return {
    ...latest,
    older_cursor: old.older_cursor,
    messages: [
      ...new Map([...old.messages, ...latest.messages].map((item) => [item.id, item])).values(),
    ].sort((a, b) => a.seq - b.seq),
    runs: [...new Map([...old.runs, ...latest.runs].map((run) => [run.id, run])).values()].sort(
      (a, b) => a.created_at.localeCompare(b.created_at),
    ),
  };
}

export default function useConversationHistory(
  projectId: string,
  epoch: number,
  latest: AgentConversation | undefined,
  active: boolean,
) {
  const client = useQueryClient();
  const [archive, setArchive] = useState<ConversationArchive | null>(null);
  const scope = `${projectId}:${epoch}:${active}`;
  const current = useRef({ scope, latest });
  current.current = { scope, latest };
  const merged = useMemo(() => (latest ? mergeSnapshot(archive, latest) : null), [archive, latest]);
  useEffect(() => {
    setArchive((old) => (latest && active ? mergeSnapshot(old, latest) : null));
  }, [latest, active, projectId, epoch]);
  const load = useMutation({
    mutationFn: async ({ cursor }: { cursor: string; scope: string }) =>
      expectData(
        await api.GET('/api/v1/web/projects/{project_id}/conversation/history', {
          params: { path: { project_id: projectId }, query: { cursor, limit: 20 } },
        }),
      ),
    onSuccess: (page: AgentMessagePage, variables) => {
      if (
        current.current.scope !== variables.scope ||
        !current.current.latest ||
        page.privacy_epoch !== epoch
      )
        return;
      setArchive((old) => {
        const value = mergeSnapshot(old, current.current.latest!);
        if (
          page.items.length &&
          value.messages.length &&
          page.items.at(-1)!.seq < value.messages[0].seq - 1
        )
          return value;
        return {
          ...value,
          older_cursor: page.next_cursor,
          messages: [
            ...new Map([...page.items, ...value.messages].map((item) => [item.id, item])).values(),
          ].sort((a, b) => a.seq - b.seq),
          runs: [
            ...new Map([...page.runs, ...value.runs].map((item) => [item.id, item])).values(),
          ].sort((a, b) => a.created_at.localeCompare(b.created_at)),
        };
      });
    },
    onError: (error, variables) => {
      if (current.current.scope !== variables.scope) return;
      if (error instanceof ApiError && error.code === 'HISTORY_CURSOR_INVALID') {
        setArchive(null);
        client.invalidateQueries({ queryKey: ['conversation', projectId] });
      }
    },
  });
  const conversation = latest && merged && active ? { ...latest, ...merged } : undefined;
  return {
    conversation,
    isPending: load.isPending,
    error: load.error,
    loadOlder: () =>
      merged?.older_cursor && !load.isPending
        ? load.mutateAsync({ cursor: merged.older_cursor, scope })
        : Promise.resolve(null),
  };
}
