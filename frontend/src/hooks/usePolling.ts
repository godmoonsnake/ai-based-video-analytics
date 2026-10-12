import { useEffect, useRef } from "react";

/**
 * Calls `fn` every `intervalMs` while `enabled` and the tab is visible.
 * Pauses when the document is hidden and resumes (with an immediate tick)
 * when it becomes visible again. `fn` should be a stable callback.
 */
export function usePolling(fn: () => void, intervalMs: number, enabled: boolean): void {
  const ref = useRef(fn);
  ref.current = fn;

  useEffect(() => {
    if (!enabled) return;
    let timer: number | undefined;

    const tick = () => {
      if (document.hidden) return;
      ref.current();
    };

    const onVisible = () => {
      if (document.hidden) return;
      ref.current();
      schedule();
    };

    const schedule = () => {
      window.clearInterval(timer);
      timer = window.setInterval(tick, intervalMs);
    };

    schedule();
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [enabled, intervalMs]);
}
