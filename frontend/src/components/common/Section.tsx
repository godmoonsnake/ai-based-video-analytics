import { useState, type ReactNode } from "react";

interface Props {
  title: string;
  count?: number;
  defaultOpen?: boolean;
  children: ReactNode;
}

/** A titled, collapsible detail section with an optional item count. */
export function Section({ title, count, defaultOpen = true, children }: Props) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <section className="detail-section">
      <button
        className="section-head"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
      >
        <span className="section-caret">{open ? "▾" : "▸"}</span>
        <span className="section-title">{title}</span>
        {count != null && <span className="section-count">{count}</span>}
      </button>
      {open && <div className="section-body">{children}</div>}
    </section>
  );
}
