import { ApiError } from "../../services/api";

export function Loading({ label = "Loading…" }: { label?: string }) {
  return (
    <div className="state state-loading" role="status" aria-live="polite">
      <span className="spinner" aria-hidden="true" />
      {label}
    </div>
  );
}

export function Empty({ label = "Nothing to show." }: { label?: string }) {
  return (
    <div className="state state-empty" role="status">
      {label}
    </div>
  );
}

export function ErrorState({
  error,
  onRetry,
}: {
  error: Error | ApiError;
  onRetry?: () => void;
}) {
  const api = error instanceof ApiError ? error : null;
  let heading = "Something went wrong";
  if (api?.isNetwork) heading = "Cannot reach the backend";
  else if (api?.isClient) heading = "Request rejected";
  else if (api?.isServer) heading = "Backend error";

  return (
    <div className="state state-error" role="alert">
      <strong>{heading}</strong>
      <div className="state-error-detail">
        {api ? `${api.message}${api.detail ? ` — ${api.detail}` : ""}` : error.message}
      </div>
      {onRetry && (
        <button className="btn-secondary" onClick={onRetry}>
          Retry
        </button>
      )}
    </div>
  );
}
