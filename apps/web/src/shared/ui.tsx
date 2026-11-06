/** 共用无障碍交互与请求状态；不包含主题或业务策略。 */
import { useEffect, useRef, type ReactNode } from 'react';
import { X, ArrowUpRight, LoaderCircle, TriangleAlert } from 'lucide-react';

/** 页面统一加载、错误和重试状态。 */
export function Status({
  loading,
  error,
  retry,
  children,
}: {
  loading?: boolean;
  error?: Error | null;
  retry?: () => void;
  children?: ReactNode;
}) {
  if (loading)
    return (
      <div className="status-state" role="status">
        <LoaderCircle className="spin" />
        <p>正在为你准备…</p>
      </div>
    );
  if (error)
    return (
      <div className="status-state" role="alert">
        <TriangleAlert />
        <h2>暂时没有连接上</h2>
        <p>{error.message}</p>
        <button className="button" onClick={retry}>
          重新加载
        </button>
      </div>
    );
  return <>{children}</>;
}
/** 弹窗封装焦点锁定、Escape 和滚动恢复。 */
export function Modal({
  title,
  children,
  onClose,
}: {
  title: string;
  children: ReactNode;
  onClose: () => void;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const close = useRef(onClose);
  close.current = onClose;
  useEffect(() => {
    const old = document.activeElement as HTMLElement | null;
    const overflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    ref.current?.focus();
    const handler = (event: KeyboardEvent) => {
      if (event.key === 'Escape') close.current();
      if (event.key === 'Tab') {
        const nodes = Array.from(
          ref.current?.querySelectorAll<HTMLElement>(
            'button:not([disabled]),input,select,textarea,a[href],[tabindex="0"]',
          ) ?? [],
        );
        const first = nodes[0],
          last = nodes.at(-1);
        if (
          event.shiftKey &&
          (document.activeElement === first || document.activeElement === ref.current)
        ) {
          event.preventDefault();
          last?.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault();
          first?.focus();
        }
      }
    };
    document.addEventListener('keydown', handler);
    return () => {
      document.body.style.overflow = overflow;
      document.removeEventListener('keydown', handler);
      old?.focus();
    };
  }, []);
  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div
        className="modal"
        role="dialog"
        aria-modal="true"
        aria-label={title}
        tabIndex={-1}
        ref={ref}
        onClick={(event) => event.stopPropagation()}
      >
        <button className="icon-button modal-close" aria-label="关闭弹窗" onClick={onClose}>
          <X size={20} />
        </button>
        <span className="eyebrow">YOUR STORY, IN LIGHT</span>
        <h2>{title}</h2>
        {children}
      </div>
    </div>
  );
}
/** 页面段落标题保留参考 UI 的衬线节奏。 */
export function Heading({
  eyebrow,
  title,
  description,
  action,
}: {
  eyebrow: string;
  title: string;
  description: string;
  action?: ReactNode;
}) {
  return (
    <div className="page-heading">
      <div>
        <span className="eyebrow">{eyebrow}</span>
        <h1>{title}</h1>
        <p>{description}</p>
      </div>
      {action}
    </div>
  );
}
/** 统一空状态，不用样例作品伪装用户的历史记录。 */
export function Empty({
  title,
  description,
  action,
}: {
  title: string;
  description: string;
  action?: ReactNode;
}) {
  return (
    <div className="empty-state">
      <span className="empty-art">✧</span>
      <h2>{title}</h2>
      <p>{description}</p>
      {action}
    </div>
  );
}
/** 带统一图标的主动作按钮。 */
export function Action({
  children,
  onClick,
  disabled = false,
  type = 'button',
}: {
  children: ReactNode;
  onClick?: () => void;
  disabled?: boolean;
  type?: 'button' | 'submit';
}) {
  return (
    <button className="button primary" onClick={onClick} disabled={disabled} type={type}>
      {children}
      <ArrowUpRight size={16} />
    </button>
  );
}
