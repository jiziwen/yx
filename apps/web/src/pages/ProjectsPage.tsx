/** 我的项目：从真实 API 建立和继续项目，空状态不混入演示项目。 */
import { useRef, useState } from 'react';
import { useNavigate, useSearchParams, Link } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { request, newKey, type Project } from '@yingxu/api-client';
import { Plus, ArrowUpRight, Archive } from 'lucide-react';
import { useApp, RequireUser } from '../app/context';
import { Heading, Modal, Action, Status, Empty } from '../shared/ui';
import { themes } from '../themes/registry';

/** 项目 CRUD 与状态刷新；版本冲突交给后端拒绝。 */
export default function ProjectsPage() {
  const { user, catalog, notify, creativeEntry, setCreativeEntry } = useApp();
  const [search, setSearch] = useSearchParams();
  const navigate = useNavigate();
  const client = useQueryClient();
  const [open, setOpen] = useState(search.get('new') === '1');
  const [title, setTitle] = useState('');
  const initialStyle =
    catalog.styles.find((s) => s.id === search.get('style')) ??
    catalog.styles.find((s) => s.theme_id === search.get('theme'));
  const [kind, setKind] = useState(
    initialStyle?.kind ??
      (creativeEntry && !/情侣|婚纱|两个人|我们|双人/.test(creativeEntry.brief)
        ? 'portrait'
        : 'wedding'),
  );
  const pendingCreation = useRef<{ body: string; key: string } | null>(null);
  const projects = useQuery({
    queryKey: ['projects'],
    queryFn: () => request<Project[]>('/web/projects'),
    enabled: !!user,
  });
  const create = useMutation({
    mutationFn: () => {
      const body = JSON.stringify({ title, kind });
      // 响应丢失后保留同一个动作键；内容改变才视为新建意图。
      if (pendingCreation.current?.body !== body) {
        pendingCreation.current = { body, key: newKey() };
      }
      return request<Project>('/web/projects', {
        method: 'POST',
        headers: { 'Idempotency-Key': pendingCreation.current.key },
        body,
      });
    },
    onSuccess: (project) => {
      client.invalidateQueries({ queryKey: ['projects'] });
      const style = initialStyle?.kind === project.kind ? initialStyle : undefined;
      setCreativeEntry({
        ...creativeEntry,
        brief: creativeEntry?.brief ?? '',
        styleId: style?.id,
        shotIds: style ? creativeEntry?.shotIds : [],
        styleShotIds: style ? creativeEntry?.styleShotIds : [],
        mode: creativeEntry?.mode,
        projectId: project.id,
      });
      navigate(`/projects/${project.id}/studio${style ? '?style=' + style.id : ''}`);
    },
  });
  const archive = useMutation({
    mutationFn: (project: Project) =>
      request('/web/projects/' + project.id, {
        method: 'PATCH',
        body: JSON.stringify({
          title: project.title,
          lifecycle: project.lifecycle === 'active' ? 'archived' : 'active',
          expected_revision: project.brief_revision,
        }),
      }),
    onSuccess: () => client.invalidateQueries({ queryKey: ['projects'] }),
    onError: (error) => notify(error.message),
  });
  const remove = useMutation({
    mutationFn: (id: string) =>
      request(`/web/projects/${id}`, {
        method: 'DELETE',
        body: JSON.stringify({ confirmed: true }),
      }),
    onSuccess: () => client.invalidateQueries({ queryKey: ['projects'] }),
    onError: (error) => notify(error.message),
  });
  const close = () => {
    setOpen(false);
    setSearch({});
    setCreativeEntry(null);
  };
  return (
    <RequireUser>
      <div className="page-content">
        <Heading
          eyebrow="A SPACE FOR EVERY STORY"
          title="把故事，慢慢写成光。"
          description="每一次心动，都有一个专属的创作空间。"
          action={
            <Action onClick={() => setOpen(true)}>
              <Plus size={16} />
              新建项目
            </Action>
          }
        />
        <Status
          loading={projects.isLoading}
          error={projects.error}
          retry={() => projects.refetch()}
        >
          {projects.data?.length ? (
            <div className="project-grid">
              {projects.data.map((project, index) => (
                <article
                  className={'project-card ' + (project.lifecycle === 'archived' ? 'archived' : '')}
                  key={project.id}
                >
                  <div className="project-art">
                    <img src={themes[index % themes.length].image} alt="" />
                    <span>PROJECT / {String(index + 1).padStart(2, '0')}</span>
                    <small>封面为风格样片</small>
                  </div>
                  <div className="project-card-content">
                    <span className="eyebrow">
                      {project.kind === 'wedding' ? 'TWO OF US' : 'IN YOUR OWN LIGHT'}
                    </span>
                    <h2>{project.title}</h2>
                    <p>
                      {project.kind === 'wedding' ? '双人婚纱 / 情侣影像' : '个人写真'} ·{' '}
                      {project.lifecycle === 'archived' ? '已归档' : '创作中'}
                    </p>
                    <div className="project-card-actions">
                      <Link to={`/projects/${project.id}/studio`}>
                        继续这段故事
                        <ArrowUpRight size={16} />
                      </Link>
                      <button
                        aria-label={
                          project.lifecycle === 'active'
                            ? '归档' + project.title
                            : '恢复' + project.title
                        }
                        className="icon-button"
                        onClick={() => archive.mutate(project)}
                      >
                        <Archive size={16} />
                      </button>
                      <button
                        disabled={remove.isPending}
                        onClick={() => {
                          if (
                            window.confirm(
                              '删除整个项目的照片、作品、分析、聊天和全部偏好？此操作不可恢复。',
                            )
                          )
                            remove.mutate(project.id);
                        }}
                      >
                        删除项目
                      </button>
                    </div>
                  </div>
                </article>
              ))}
            </div>
          ) : (
            <Empty
              title="第一段故事，从这里开始。"
              description="新建项目，上传参考照片，再把你的灵感整理成一份方案。"
              action={<Action onClick={() => setOpen(true)}>创建我的第一个项目</Action>}
            />
          )}
        </Status>
      </div>
      {open && (
        <Modal title="为故事，写一个名字。" onClose={close}>
          <form
            onSubmit={(event) => {
              event.preventDefault();
              create.mutate();
            }}
          >
            <label>
              项目名称
              <input
                aria-label="项目名称"
                value={title}
                onChange={(event) => setTitle(event.target.value)}
                placeholder="例如：我们的海边来信"
                maxLength={120}
                disabled={create.isPending}
                required
              />
            </label>
            <label>
              创作类型
              <select
                aria-label="创作类型"
                value={kind}
                disabled={create.isPending}
                onChange={(event) => setKind(event.target.value)}
              >
                <option value="wedding">双人婚纱 / 情侣照</option>
                <option value="portrait">个人写真</option>
              </select>
            </label>
            <p className="muted">主题外观可以随时切换。方案中的风格由你另行确认。</p>
            {create.error && (
              <p className="error-text" role="alert">
                {create.error.message}
              </p>
            )}
            <Action type="submit" disabled={create.isPending}>
              {create.isPending ? '正在创建…' : '开启这段故事'}
            </Action>
          </form>
        </Modal>
      )}
    </RequireUser>
  );
}
