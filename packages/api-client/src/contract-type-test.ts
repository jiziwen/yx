/** 只参与编译的接口契约断言；错误路径、方法、字段和缺少参数必须被 TypeScript 拒绝。 */
import { api } from './index';
import type { components } from './generated';
/** 不在运行时调用，不发起请求；@ts-expect-error 失效会让类型检查失败。 */
export function assertContractTypes() {
  void api.GET('/api/v1/web/me');
  void api.POST('/api/v1/web/auth/login', { body: { phone: '13900000000', code: '000000' } });
  // @ts-expect-error 登录不是 GET，禁止调用不存在的 HTTP 方法。
  void api.GET('/api/v1/web/auth/login');
  // @ts-expect-error 不存在的接口路径必须拒绝。
  void api.GET('/api/v1/web/nonexistent');
  const invalidBody: components['schemas']['LoginInput'] = {
    phone: '13900000000',
    code: '000000',
    // @ts-expect-error 普通登录 DTO 不接受客户端角色字段。
    role: 'admin',
  };
  void invalidBody;
  // @ts-expect-error 路径参数不可缺失。
  void api.GET('/api/v1/web/projects/{project_id}');
}
