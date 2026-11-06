/** 指南仅展示当前有效发布版本；正文以纯文本渲染，不执行Markdown中的HTML或脚本。 */
import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api, expectData } from '@yingxu/api-client';
import { Heading, Empty, Status, Modal } from '../shared/ui';
export default function GuidesPage() {
  const [id, setId] = useState<string | null>(null);
  const list = useQuery({
    queryKey: ['guides'],
    queryFn: () => api.GET('/api/v1/web/guides').then(expectData),
  });
  const detail = useQuery({
    queryKey: ['guide', id],
    enabled: !!id,
    queryFn: () =>
      api
        .GET('/api/v1/web/guides/{document_id}', { params: { path: { document_id: id! } } })
        .then(expectData),
    staleTime: 0,
  });
  return (
    <div className="page-content">
      <Heading
        eyebrow="A FEW WORDS BEFORE WE BEGIN"
        title="慢慢读，自在地成为自己。"
        description="关于参考照、影像氛围，以及如何留住心动。"
      />
      <Status loading={list.isLoading} error={list.error} retry={() => void list.refetch()}>
        {list.data?.length ? (
          <div className="m2-guide-grid">
            {list.data.map((guide) => (
              <button
                className="m2-guide"
                key={guide.document_id}
                onClick={() => setId(guide.document_id)}
              >
                <small>
                  {guide.category === 'photography'
                    ? '摄影准备'
                    : guide.category === 'wedding'
                      ? '婚礼指南'
                      : '使用指南'}
                </small>
                <h2>{guide.title}</h2>
                <p>{guide.summary}</p>
                <span>慢慢读一读 ↗</span>
              </button>
            ))}
          </div>
        ) : (
          <Empty
            title="一些温柔的建议，正在整理。"
            description="发布后的摄影与使用指南，会出现在这里。"
          />
        )}
      </Status>
      {id && (
        <Modal title={detail.data?.title ?? '正在翻开指南'} onClose={() => setId(null)}>
          <Status
            loading={detail.isLoading}
            error={detail.error}
            retry={() => void detail.refetch()}
          >
            <p className="m2-source-text">{detail.data?.content}</p>
          </Status>
        </Modal>
      )}
    </div>
  );
}
