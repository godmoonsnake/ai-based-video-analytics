import { useEffect } from "react";

export interface Hotkey {
  /** Key as KeyboardEvent.key, lowercase. */
  key: string;
  handler: (e: KeyboardEvent) => void;
  /** Allow while typing in an input/textarea (default: false). */
  allowInInput?: boolean;
}

function isTypingTarget(t: EventTarget | null): boolean {
  const el = t as HTMLElement | null;
  if (!el) return false;
  const tag = el.tagName;
  return (
    tag === "INPUT" ||
    tag === "TEXTAREA" ||
    tag === "SELECT" ||
    el.isContentEditable === true
  );
}

/**
 * Global keyboard map. Handlers run on keydown (no repeat) in document order.
 * Typing in form fields suppresses hotkeys unless `allowInInput` is set.
 */
export function useHotkeys(hotkeys: Hotkey[]): void {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.repeat || e.metaKey || e.ctrlKey || e.altKey) return;
      const typing = isTypingTarget(e.target);
      const key = e.key.toLowerCase();
      for (const hk of hotkeys) {
        if (hk.key !== key) continue;
        if (typing && !hk.allowInInput) continue;
        hk.handler(e);
        if (e.defaultPrevented) return;
        return;
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [hotkeys]);
}
