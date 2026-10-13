'use client';

import { useEffect, useRef } from 'react';

/** Accessible modal built on the native <dialog> element (focus trap and Esc handled by the browser). */
export function Dialog({
  open,
  title,
  onClose,
  children,
  footer,
}: {
  open: boolean;
  title: string;
  onClose: () => void;
  children: React.ReactNode;
  footer: React.ReactNode;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const d = ref.current;
    if (!d) return;
    if (open && !d.open) {
      if (typeof d.showModal === 'function') d.showModal();
      else d.setAttribute('open', '');
    } else if (!open && d.open) {
      if (typeof d.close === 'function') d.close();
      else d.removeAttribute('open');
    }
  }, [open]);
  return (
    <dialog ref={ref} className="dialog" onClose={onClose} onCancel={onClose} aria-label={title}>
      <div className="dialog-head">{title}</div>
      <div className="dialog-body">{children}</div>
      <div className="dialog-foot">{footer}</div>
    </dialog>
  );
}
