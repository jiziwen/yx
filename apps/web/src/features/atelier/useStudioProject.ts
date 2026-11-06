/** 工作室数据边界：所有人物、权益、方案、任务和作品继续来自受权业务 API。 */
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useRef } from 'react';
import {
  request,
  type Project,
  type Subject,
  type Asset,
  type Plan,
  type Job,
  type Account,
} from '@yingxu/api-client';
import { useApp } from '../../app/context';
export const activeJobs = new Set([
  'queued',
  'running',
  'cancel_requested',
  'reconciliation_required',
]);
export const jobLabels: Record<string, string> = {
  queued: '等待创作',
  running: '创作中',
  succeeded: '已完成',
  failed: '未完成 · 不消耗次数',
  cancelled: '已取消 · 不消耗次数',
  cancel_requested: '取消处理中',
  reconciliation_required: '正在核对生成结果',
};
/** 同一项目共用查询键；切主题保持实例，任务阶段改变才刷新权益和作品。 */
export function useStudioProject(projectId: string) {
  const { user } = useApp();
  const client = useQueryClient();
  const deliveryDeadlines = useRef(new Map<string, number>());
  const project = useQuery({
    queryKey: ['project', projectId],
    queryFn: () => request<Project>(`/web/projects/${projectId}`),
    enabled: !!user,
  });
  const subjects = useQuery({
    queryKey: ['subjects', projectId],
    queryFn: () => request<Subject[]>(`/web/projects/${projectId}/subjects`),
    enabled: !!user,
  });
  const assets = useQuery({
    queryKey: ['assets', projectId],
    queryFn: () => request<Asset[]>(`/web/projects/${projectId}/assets`),
    enabled: !!user,
  });
  const plans = useQuery({
    queryKey: ['plans', projectId],
    queryFn: () => request<Plan[]>(`/web/projects/${projectId}/plans`),
    enabled: !!user,
  });
  const jobs = useQuery({
    queryKey: ['jobs', projectId],
    queryFn: () => request<Job[]>(`/web/projects/${projectId}/jobs`),
    enabled: !!user,
    refetchInterval: (query) =>
      query.state.data?.some((job) => activeJobs.has(job.status)) ? 2000 : 5000,
  });
  const statuses = jobs.data?.map((job) => job.id + ':' + job.status).join(',');
  const account = useQuery({
    queryKey: ['entitlements', projectId],
    queryFn: () => request<Account>(`/web/projects/${projectId}/entitlements`),
    enabled: !!user,
  });
  const works = useQuery({
    queryKey: ['works', projectId],
    queryFn: () => request<Asset[]>(`/web/projects/${projectId}/works`),
    enabled: !!user,
    refetchInterval: (query) => {
      const delivered = new Set(query.state.data?.map((asset) => asset.source_job_id));
      const missing =
        jobs.data?.filter((job) => job.status === 'succeeded' && !delivered.has(job.id)) ?? [];
      for (const job of missing) {
        if (!deliveryDeadlines.current.has(job.id))
          deliveryDeadlines.current.set(job.id, Date.now() + 30000);
      }
      return missing.some((job) => Date.now() < deliveryDeadlines.current.get(job.id)!)
        ? 2000
        : false;
    },
  });
  // 使用稳定查询键保留现有缩略图，任务变化时主动同步作品、素材与余额。
  useEffect(() => {
    if (!jobs.data) return;
    for (const key of ['works', 'assets', 'entitlements'])
      void client.invalidateQueries({ queryKey: [key, projectId] });
  }, [statuses, projectId, client]);
  const refresh = () => {
    void client.invalidateQueries({ predicate: (query) => query.queryKey.includes(projectId) });
  };
  return { project, subjects, assets, plans, jobs, account, works, refresh };
}
export type StudioData = ReturnType<typeof useStudioProject>;
