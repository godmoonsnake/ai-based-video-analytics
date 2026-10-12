import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { IconCheck, IconAlert, IconInfo, IconX } from "../icons";

export type ToastKind = "success" | "error" | "info";
interface Toast {
  id: number;
  kind: ToastKind;
  title: string;
  msg?: string;
}

const ToastCtx = createContext<(kind: ToastKind, title: string, msg?: string) => void>(() => {});

/** push(kind, title, msg?) — show a transient operator toast. */
export function useToast() {
  return useContext(ToastCtx);
}

const ICONS: Record<ToastKind, ReactNode> = {
  success: <IconCheck />,
  error: <IconAlert />,
  info: <IconInfo />,
};

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const nextId = useRef(1);

  const push = useCallback((kind: ToastKind, title: string, msg?: string) => {
    const id = nextId.current++;
    setToasts((t) => [...t.slice(-3), { id, kind, title, msg }]);
    window.setTimeout(() => {
      setToasts((t) => t.filter((x) => x.id !== id));
    }, 4200);
  }, []);

  const dismiss = useCallback((id: number) => {
    setToasts((t) => t.filter((x) => x.id !== id));
  }, []);

  const value = useMemo(() => push, [push]);

  return (
    <ToastCtx.Provider value={value}>
      {children}
      <div className="toasts" aria-live="polite">
        {toasts.map((t) => (
          <div key={t.id} className={`toast ${t.kind}`} role="status">
            <span className="ticon">{ICONS[t.kind]}</span>
            <span className="tmsg">
              <b>{t.title}</b>
              {t.msg && <span>{t.msg}</span>}
            </span>
            <button className="x" onClick={() => dismiss(t.id)} aria-label="Dismiss notification">
              <IconX />
            </button>
          </div>
        ))}
      </div>
    </ToastCtx.Provider>
  );
}
