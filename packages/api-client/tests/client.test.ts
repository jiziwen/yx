/** M0 共享客户端运行时契约；仅 stub fetch，不连接真实账号或远程供应商。 */
import { afterEach, describe, expect, it, vi } from 'vitest';
import { api, expectData, ApiError } from '../src/index';

afterEach(() => vi.unstubAllGlobals());
describe('generated API client', () => {
  it('serializes typed path parameters and includes the cookie audience', async () => {
    const fetch = vi.fn(async (_input: Request) =>
      Response.json({
        id: 'project/id',
        title: 'Story',
        kind: 'portrait',
        lifecycle: 'active',
        brief_revision: 1,
        created_at: '2026-10-21T00:00:00Z',
      }),
    );
    vi.stubGlobal('fetch', fetch);
    const project = await api
      .GET('/api/v1/web/projects/{project_id}', {
        baseUrl: 'http://local.test',
        params: { path: { project_id: 'project/id' } },
      })
      .then(expectData);
    expect(project.title).toBe('Story');
    const input = fetch.mock.calls[0][0] as Request;
    expect(input.url).toContain('project%2Fid');
    expect(input.credentials).toBe('include');
  });
  it('sends only the declared login fields as JSON', async () => {
    const fetch = vi.fn(async (_input: Request) =>
      Response.json({ id: 'u', display_name: 'Test', role: 'customer' }),
    );
    vi.stubGlobal('fetch', fetch);
    await api
      .POST('/api/v1/web/auth/login', {
        baseUrl: 'http://local.test',
        body: { phone: '13900000000', code: '000000' },
      })
      .then(expectData);
    const input = fetch.mock.calls[0][0] as Request;
    expect(input.method).toBe('POST');
    expect(await input.json()).toEqual({ phone: '13900000000', code: '000000' });
  });
  it('converts the shared error envelope without losing request correlation', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        Response.json(
          { error: { code: 'UNAUTHENTICATED', message: '请先登录', request_id: 'request-123' } },
          { status: 401 },
        ),
      ),
    );
    await expect(api.GET('/api/v1/web/me', { baseUrl: 'http://local.test' })).rejects.toMatchObject(
      { code: 'UNAUTHENTICATED', status: 401, requestId: 'request-123' },
    );
  });
  it('maps network failures and invalid error bodies to stable errors', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => {
        throw new TypeError('sensitive connection details');
      }),
    );
    await expect(api.GET('/api/v1/web/me', { baseUrl: 'http://local.test' })).rejects.toMatchObject(
      { code: 'NETWORK_ERROR', status: 0 },
    );
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        Response.json(null, { status: 503, headers: { 'X-Request-ID': 'request-fallback' } }),
      ),
    );
    await expect(api.GET('/api/v1/web/me', { baseUrl: 'http://local.test' })).rejects.toMatchObject(
      { code: 'REQUEST_FAILED', status: 503, requestId: 'request-fallback' },
    );
  });
  it('does not turn an empty success payload into a valid DTO', () => {
    expect(() => expectData({ data: undefined })).toThrow(ApiError);
  });
});
