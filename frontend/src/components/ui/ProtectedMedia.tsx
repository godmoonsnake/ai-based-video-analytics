import { useEffect, useState, type ReactNode } from "react";
import { API_BASE } from "../../services/api";
import { currentAccessToken } from "../../services/auth";

function useMediaObjectUrl(path?: string | null) {
  const [result, setResult] = useState<{ url: string | null; failed: boolean }>({ url: null, failed: false });
  useEffect(() => {
    if (!path) { setResult({ url: null, failed: false }); return; }
    setResult({ url: null, failed: false });
    let active = true;
    let objectUrl: string | null = null;
    const token = currentAccessToken();
    fetch(`${API_BASE}${path}`, { headers: token ? { Authorization: `Bearer ${token}` } : {}, cache: "no-store" })
      .then((response) => { if (!response.ok) throw new Error("Evidence unavailable"); return response.blob(); })
      .then((blob) => { if (active) { objectUrl = URL.createObjectURL(blob); setResult({ url: objectUrl, failed: false }); } })
      .catch(() => { if (active) setResult({ url: null, failed: true }); });
    return () => { active = false; if (objectUrl) URL.revokeObjectURL(objectUrl); };
  }, [path]);
  return result;
}

export function ProtectedImage({ src, alt, fallback }: { src?: string | null; alt: string; fallback: ReactNode }) {
  const media = useMediaObjectUrl(src);
  return media.url ? <img src={media.url} alt={alt} /> : <>{fallback}</>;
}

export function ProtectedVideo({ src, onError, fallback }: { src?: string | null; onError?: () => void; fallback: ReactNode }) {
  const media = useMediaObjectUrl(src);
  useEffect(() => { if (media.failed) onError?.(); }, [media.failed, onError]);
  return media.url ? <video src={media.url} controls autoPlay loop /> : <>{fallback}</>;
}

export function ProtectedOpenLink({ src, children }: { src?: string | null; children: ReactNode }) {
  const media = useMediaObjectUrl(src);
  return <a className="btn btn-sm" href={media.url ?? undefined} target="_blank" rel="noreferrer" aria-disabled={!media.url}>{children}</a>;
}
