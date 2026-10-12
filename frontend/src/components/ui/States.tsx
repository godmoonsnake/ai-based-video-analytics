import type { ReactNode } from "react";
import { ApiError } from "../../services/api";
import { IconAlert } from "../icons";

/** Radar-sweep loading block. */
export function LoadingBlock({ label = "Acquiring" }: { label?: string }) {
  return (
    <div className="state-block" data-testid="loading-block">
      <div className="radar" aria-hidden>
        <span className="sweep" />
        <span className="blip" style={{ top: "26%", left: "62%" }} />
        <span className="blip" style={{ top: "60%", left: "30%", opacity: 0.5 }} />
      </div>
      <div className="state-sub">{label.toUpperCase()} …</div>
    </div>
  );
}

/**
 * Structured error panel. Keeps the operator-facing contract:
 * role="alert", heading "Backend error", Retry control.
 */
export function ErrorPanel({ error, onRetry }: { error: Error | null; onRetry: () => void }) {
  const detail =
    error instanceof ApiError
      ? `${error.message}${error.detail ? ` — ${error.detail}` : ""}`
      : (error?.message ?? "Unknown failure");
  const network = error instanceof ApiError && error.isNetwork;
  return (
    <div className="error-panel" role="alert" data-testid="error-panel">
      <span className="t">{network ? "Connection lost" : "Backend error"}</span>
      <span className="d">{detail}</span>
      <button className="btn" onClick={onRetry}>
        Retry
      </button>
    </div>
  );
}

/** Centered empty state with radar motif. */
export function EmptyBlock({
  title,
  sub,
  children,
}: {
  title: string;
  sub?: ReactNode;
  children?: ReactNode;
}) {
  return (
    <div className="state-block">
      <div className="radar" aria-hidden>
        <span className="sweep" style={{ animationDuration: "4s", opacity: 0.5 }} />
      </div>
      <div className="state-title">{title}</div>
      {sub && <div className="state-sub">{sub}</div>}
      {children}
    </div>
  );
}

/** Inline warning used for rejected transitions (409 etc.). */
export function InlineAlert({ children }: { children: ReactNode }) {
  return (
    <span className="inline-alert transition-error" role="alert">
      <IconAlert />
      {children}
    </span>
  );
}

/** Panel with a signature "// LABEL" header. */
export function Panel({
  label,
  hint,
  actions,
  children,
  className,
}: {
  label: string;
  hint?: string;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={`panel ${className ?? ""}`}>
      <header className="panel-h">
        <span className="micro">{label}</span>
        {hint && <span className="hint">{hint}</span>}
        <span className="spacer" />
        {actions}
      </header>
      {children}
    </section>
  );
}
