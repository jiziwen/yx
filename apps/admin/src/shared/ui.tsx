/** 管理端独立功能文件；后端 API 始终校验管理员角色。 */
import type { ReactNode } from 'react';
import { RefreshCw } from 'lucide-react';
/** 通用状态视图；读取失败时保留明确重试。 */
export function State({
  children,
  error,
  retry,
}: {
  children?: ReactNode;
  error?: Error | null;
  retry?: () => void;
}) {
  return (
    <div className="state" role={error ? 'alert' : 'status'}>
      {error ? (
        <>
          <h3>读取失败</h3>
          <p>{error.message}</p>
          <button onClick={retry}>重试</button>
        </>
      ) : (
        children
      )}
    </div>
  );
}
/** 页面标题与刷新动作。 */
export function Title({
  title,
  description,
  onRefresh,
}: {
  title: string;
  description: string;
  onRefresh: () => void;
}) {
  return (
    <div className="title">
      <div>
        <span className="eyebrow">LUMIÈRE / WORKSPACE</span>
        <h1>{title}</h1>
        <p>{description}</p>
      </div>
      <button className="outline" onClick={onRefresh}>
        <RefreshCw size={14} />
        刷新
      </button>
    </div>
  );
}
