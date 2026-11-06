/** 候选保存与回填共用服务端数据，刷新页面后仍可继续编辑。 */
import { request, type ModelSettings } from '@yingxu/api-client';

export type ModelCandidate = {
  id: string;
  digest: string;
  status: string;
  release_id: string | null;
  required_cases: string[];
  settings_json: Pick<ModelSettings, 'image' | 'llm' | 'vision'>;
};

export const modelCandidatesQuery = {
  queryKey: ['model-candidates'],
  queryFn: () => request<ModelCandidate[]>('/admin/model-candidates'),
};
