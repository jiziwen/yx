/** 工作室按需打开素材和细节；原生弹框负责焦点、Esc及背景隔离。 */
import { useEffect, useRef, type ReactNode } from 'react';
import { X } from 'lucide-react';

export default function StudioDialog({
  title,
  children,
  onClose,
  className = '',
  showFooter = true,
}: {
  title: string;
  children: ReactNode;
  onClose: () => void;
  className?: string;
  showFooter?: boolean;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const dialog = ref.current!;
    const previous = document.activeElement;
    const overflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    dialog.showModal();
    return () => {
      dialog.close();
      document.body.style.overflow = overflow;
      if (previous instanceof HTMLElement && previous.isConnected) previous.focus();
    };
  }, []);
  return (
    <dialog
      ref={ref}
      className={`sx-dialog ${className}`.trim()}
      aria-label={title}
      onCancel={(event) => {
        event.preventDefault();
        onClose();
      }}
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div className="sx-dialog-content">
        <header>
          <h2>{title}</h2>
          <button type="button" aria-label="关闭弹框" onClick={onClose}>
            <X size={18} />
          </button>
        </header>
        <div className="sx-dialog-body">{children}</div>
        {showFooter && (
          <footer>
            <button type="button" className="sx-button sx-primary" onClick={onClose}>
              完成
            </button>
          </footer>
        )}
      </div>
    </dialog>
  );
}
