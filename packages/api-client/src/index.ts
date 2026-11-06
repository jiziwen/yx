/** 共享请求与后端生成类型；Cookie 仅由浏览器管理，不复制到本地存储。 */
import type { components, paths } from './generated';
import createClient from 'openapi-fetch';
export type User = components['schemas']['UserView'];
export type Project = components['schemas']['ProjectView'];
export type Subject = components['schemas']['SubjectView'];
export type Asset = components['schemas']['AssetView'];
export type Plan = components['schemas']['PlanView'];
export type Job = components['schemas']['JobView'];
export type Account = components['schemas']['AccountView'];
export type Catalog = components['schemas']['CatalogView'];
export type PlanInput = components['schemas']['PlanInput'];
/** 稳定错误码供页面显示可操作的错误与重试入口。 */
export class ApiError extends Error {
  constructor(
    public code: string,
    message: string,
    public status: number,
    public requestId?: string,
  ) {
    super(message);
  }
}
/** 变更操作由调用点决定幂等键生命周期，失败重试必须复用同一键。 */
export async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers);
  if (options.body && !(options.body instanceof FormData))
    headers.set('Content-Type', 'application/json');
  let response: Response;
  try {
    response = await fetch('/api/v1' + path, { ...options, headers, credentials: 'include' });
  } catch {
    throw new ApiError('NETWORK_ERROR', '连接失败，请检查网络后重试', 0);
  }
  if (!response.ok) throw await responseError(response);
  return response.json() as Promise<T>;
}
/** 每个用户动作独立生成请求键；不得在自动重试中重新生成。 */
export function newKey() {
  return crypto.randomUUID();
}
/** 返回私有认证代理地址；请求期间服务端持续验证权限。 */
export function assetUrl(id: string, download = false) {
  return `/api/v1/web/assets/${encodeURIComponent(id)}/content${download ? '?download=true' : ''}`;
}

/** 编译期同时校验路径、HTTP 方法、路径参数和请求体；默认包含独立 HttpOnly Cookie。 */
export const api = createClient<paths>({
  credentials: 'include',
  fetch: async (input) => {
    try {
      return await fetch(input);
    } catch {
      throw new ApiError('NETWORK_ERROR', '连接失败，请检查网络后重试', 0);
    }
  },
});
api.use({
  /** 所有生成接口共用一个错误协议，业务页面不用解析未受控的供应商正文。 */
  async onResponse({ response }) {
    if (!response.ok) throw await responseError(response);
    return response;
  },
});
/** 错误中间件已经拒绝非成功响应；成功但没有 JSON 载荷也不能伪装成有效 DTO。 */
export function expectData<T>({ data }: { data?: T }): T {
  if (data === undefined) throw new ApiError('INVALID_RESPONSE', '服务返回了无法使用的结果', 502);
  return data;
}
export type Inventory = components['schemas']['InventoryView'];
export type Overview = components['schemas']['OverviewView'];
export type AdminJob = components['schemas']['AdminJobView'];
export type AdminUser = components['schemas']['AdminUserView'];
export type GrantInput = components['schemas']['GrantInput'];
export type GrantRecord = components['schemas']['GrantRecord'];
export type ThemeCatalog = components['schemas']['ThemeCatalogView'];
export type ThemeStyle = components['schemas']['ThemeStyleView'];
export type ThemeShot = components['schemas']['ThemeShotView'];
export type ThemeSave = components['schemas']['ThemeSaveInput'];
export type Audit = components['schemas']['AuditView'];
export type ModelSettings = components['schemas']['ModelSettingsView'];
export type ModelSettingsInput = components['schemas']['ModelSettingsInput'];
export type ImageModelSettings = components['schemas']['ImageModelSettings'];
export type AgentConversation = components['schemas']['ConversationView'];
export type AgentRun = components['schemas']['RunView'];
export type AgentMessageInput = components['schemas']['SendMessage'];
export type AgentDraftPatch = components['schemas']['DraftPatch'];
export type ProjectMemory = components['schemas']['MemoryView'];
export type AgentObservation = components['schemas']['ToolObservation'];
export type AgentReplyPreview = components['schemas']['ReplyPreview'];
export type AgentMessagePage = components['schemas']['MessagePage'];

export type SupportConversation = components['schemas']['SupportView'];
export type SupportMessageInput = components['schemas']['SupportSend'];
export type AgentStep = components['schemas']['StepView'];
export type KnowledgeDocument = components['schemas']['DocumentView'];
export type KnowledgeVersion = components['schemas']['VersionView'];
export type KnowledgeCitation = components['schemas']['CitationView'];
export type KnowledgeImport = components['schemas']['ImportVersion'];

/** 运行时不信任错误体的形状，HTML/null/非字符串字段不能破坏 UI 的错误处理。 */
async function responseError(response: Response): Promise<ApiError> {
  const payload: unknown = await response
    .clone()
    .json()
    .catch(() => undefined);
  const error =
    typeof payload === 'object' && payload !== null && 'error' in payload
      ? payload.error
      : undefined;
  const fields =
    typeof error === 'object' && error !== null ? (error as Record<string, unknown>) : {};
  return new ApiError(
    typeof fields.code === 'string' ? fields.code : 'REQUEST_FAILED',
    typeof fields.message === 'string' ? fields.message : '请求失败，请稍后重试',
    response.status,
    typeof fields.request_id === 'string'
      ? fields.request_id
      : (response.headers.get('X-Request-ID') ?? undefined),
  );
}
