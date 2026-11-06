/** 用户作品列表与私有下载；开发卡片明确标注，不混用首页样片。 */
import { useParams, Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { request, assetUrl, type Asset } from '@yingxu/api-client';
import { Download, ArrowUpRight } from 'lucide-react';
import { RequireUser, useApp } from '../app/context';
import { Heading, Status, Empty } from '../shared/ui';
/** 已撤销授权的作品不会出现在列表，直接下载也重新鉴权。 */
export default function WorksPage() {
  const { projectId = '' } = useParams();
  const { user } = useApp();
  const works = useQuery({
    queryKey: ['works', projectId],
    queryFn: () => request<Asset[]>(`/web/projects/${projectId}/works`),
    enabled: !!user,
  });
  return (
    <RequireUser>
      <div className="page-content">
        <Heading
          eyebrow="THE MOMENTS YOU KEEP"
          title="把喜欢，留在这里。"
          description="每一张，都是你的独家故事。"
          action={
            <Link className="button" to={`/projects/${projectId}/studio`}>
              回到创作室
              <ArrowUpRight size={16} />
            </Link>
          }
        />
        <Status loading={works.isLoading} error={works.error} retry={() => works.refetch()}>
          {works.data?.length ? (
            <div className="works-grid">
              {works.data.map((asset, index) => (
                <article className="work-card" key={asset.id}>
                  <a target="_blank" rel="noreferrer" href={assetUrl(asset.id)}>
                    <img
                      src={assetUrl(asset.id)}
                      alt={asset.development_sample ? '开发测试卡片' : '创作作品 ' + (index + 1)}
                      loading="lazy"
                    />
                  </a>
                  <div>
                    <span>
                      {asset.development_sample ? '开发测试卡片' : '我的作品'} /{' '}
                      {String(index + 1).padStart(2, '0')}
                    </span>
                    <a
                      className="icon-button"
                      aria-label={'下载作品' + (index + 1)}
                      href={assetUrl(asset.id, true)}
                    >
                      <Download size={17} />
                    </a>
                  </div>
                  {asset.development_sample && (
                    <p className="muted">用于验证流程，未生成真人照片。</p>
                  )}
                </article>
              ))}
            </div>
          ) : (
            <Empty
              title="这里，等待第一束光。"
              description="回到创作室确认方案，作品完成后会出现在这里。"
              action={
                <Link className="button primary" to={`/projects/${projectId}/studio`}>
                  继续创作
                  <ArrowUpRight size={16} />
                </Link>
              }
            />
          )}
        </Status>
      </div>
    </RequireUser>
  );
}
