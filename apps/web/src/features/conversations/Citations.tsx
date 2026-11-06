/** 引用按可读消息+序号读取，打开前重新检查发布资格；不接受任意chunk URL。 */
import { useState, type CSSProperties } from 'react';
import { createPortal } from 'react-dom';
import { useTheme } from '../../themes/ThemeProvider';
import { useMutation } from '@tanstack/react-query';
import { api, expectData, type KnowledgeCitation } from '@yingxu/api-client';
import { Modal } from '../../shared/ui';

export default function Citations({
  messageId,
  references,
}: {
  messageId: string;
  references: KnowledgeCitation[] | null | undefined;
}) {
  const { theme } = useTheme();
  const [selected, setSelected] = useState<KnowledgeCitation | null>(null);
  const source = useMutation({
    mutationFn: async (index: number) =>
      expectData(
        await api.GET('/api/v1/web/messages/{message_id}/citations/{index}', {
          params: { path: { message_id: messageId, index } },
        }),
      ),
    onSuccess: setSelected,
  });
  if (!references?.length) return null;
  return (
    <div className="m2-citations" aria-label="知识引用来源">
      {references.map((item, index) => (
        <button
          key={item.chunk_id}
          disabled={source.isPending}
          onClick={() => source.mutate(index + 1)}
        >
          [{index + 1}] {item.title} · v{item.version_no}
        </button>
      ))}
      {source.error && <p role="alert">{source.error.message}</p>}
      {selected &&
        createPortal(
          <div className="m2-source-dialog" style={theme.tokens as CSSProperties}>
            <Modal title={selected.title} onClose={() => setSelected(null)}>
              <p>
                版本 {selected.version_no} · {selected.locator}
              </p>
              <p className="m2-source-text">{selected.text}</p>
            </Modal>
          </div>,
          document.body,
        )}
    </div>
  );
}
