import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

type Identity = { subject: string; display_name: string; tenant_id: string; site_id: string; role: string };
type AuthValue = { token: string | null; identity: Identity | null; enabled: boolean; login: () => Promise<void>; logout: () => Promise<void> };
const AuthContext = createContext<AuthValue | null>(null);
const issuer = (import.meta.env.VITE_OIDC_ISSUER ?? "").replace(/\/$/, "");
const clientId = import.meta.env.VITE_OIDC_CLIENT_ID ?? "";
const enabled = Boolean(issuer && clientId);
let accessToken: string | null = null;
let idToken: string | null = null;
let callbackCodeInFlight: string | null = null;
const callbackEvent = new Event("darson-auth-expired");
export function currentAccessToken() { return accessToken; }
export function expireAuth() { accessToken = null; idToken = null; window.dispatchEvent(callbackEvent); }

const b64 = (bytes: Uint8Array) => btoa(String.fromCharCode(...bytes)).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
const randomString = (size = 48) => b64(crypto.getRandomValues(new Uint8Array(size)));
async function discovery() {
  const response = await fetch(`${issuer}/.well-known/openid-configuration`);
  if (!response.ok) throw new Error("Identity provider discovery failed");
  const value = await response.json();
  if (String(value.issuer).replace(/\/$/, "") !== issuer || !value.authorization_endpoint || !value.token_endpoint)
    throw new Error("Identity provider metadata does not match configured issuer");
  return value;
}
function decode64url(value: string) {
  const padded = value.replace(/-/g, "+").replace(/_/g, "/");
  return atob(padded + "=".repeat((4 - padded.length % 4) % 4));
}
async function verifyIdToken(jwt: string, nonce: string, metadata: any) {
  const parts = jwt.split(".");
  if (parts.length !== 3) throw new Error("Malformed ID token.");
  const header = JSON.parse(decode64url(parts[0]));
  const claims = JSON.parse(decode64url(parts[1]));
  if (header.alg !== "RS256" || claims.nonce !== nonce || claims.iss !== issuer ||
      !(claims.aud === clientId || Array.isArray(claims.aud) && claims.aud.includes(clientId)) ||
      !Number.isFinite(claims.exp) || claims.exp <= Date.now() / 1000 || !metadata.jwks_uri)
    throw new Error("ID token claims failed validation.");
  const response = await fetch(metadata.jwks_uri, { cache: "no-store" });
  if (!response.ok) throw new Error("Could not load identity-provider signing keys.");
  const jwks = await response.json();
  const jwk = jwks.keys?.find((key: JsonWebKey & { kid?: string; alg?: string }) => key.kid === header.kid && key.alg !== "HS256");
  if (!jwk) throw new Error("Identity-provider signing key was not found.");
  const key = await crypto.subtle.importKey("jwk", jwk, { name: "RSASSA-PKCS1-v1_5", hash: "SHA-256" }, false, ["verify"]);
  const signature = Uint8Array.from(decode64url(parts[2]), (c) => c.charCodeAt(0));
  const valid = await crypto.subtle.verify("RSASSA-PKCS1-v1_5", key, signature,
    new TextEncoder().encode(`${parts[0]}.${parts[1]}`));
  if (!valid) throw new Error("ID token signature is invalid.");
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setToken] = useState<string | null>(accessToken);
  const [identity, setIdentity] = useState<Identity | null>(null);
  const [error, setError] = useState("");
  const [ready, setReady] = useState(!enabled);
  const applyToken = useCallback(async (value: string, expiresIn: number) => {
    accessToken = value; setToken(value); setReady(true); setError("");
    window.setTimeout(() => { if (accessToken === value) expireAuth(); }, Math.max(1, expiresIn - 30) * 1000);
    const me = await fetch("/api/v1/auth/me", { headers: { Authorization: `Bearer ${value}` }, cache: "no-store" });
    if (!me.ok) { expireAuth(); throw new Error(me.status === 401 || me.status === 403 ? "This account has no active DARSON site grant." : "Unable to load account scope."); }
    setIdentity(await me.json());
  }, []);

  useEffect(() => {
    if (!enabled) return;
    const onExpired = () => { setToken(null); setIdentity(null); };
    window.addEventListener("darson-auth-expired", onExpired);
    (async () => {
      try {
        const params = new URLSearchParams(window.location.search);
        const code = params.get("code");
        if (!code) { setReady(true); return; }
        if (callbackCodeInFlight === code) return;
        callbackCodeInFlight = code;
        const state = sessionStorage.getItem("darson_oidc_state");
        const verifier = sessionStorage.getItem("darson_oidc_verifier");
        const nonce = sessionStorage.getItem("darson_oidc_nonce");
        if (!state || params.get("state") !== state || !verifier || !nonce) throw new Error("Sign-in state validation failed.");
        const metadata = await discovery();
        const response = await fetch(metadata.token_endpoint, { method: "POST", headers: { "Content-Type": "application/x-www-form-urlencoded" },
          body: new URLSearchParams({ grant_type: "authorization_code", client_id: clientId, code,
            redirect_uri: window.location.origin, code_verifier: verifier }) });
        if (!response.ok) throw new Error("Identity provider rejected the sign-in code.");
        const result = await response.json();
        if (!result.access_token || result.token_type?.toLowerCase() !== "bearer" || !result.id_token) throw new Error("Identity provider returned an incomplete session.");
        await verifyIdToken(result.id_token, nonce, metadata);
        idToken = result.id_token;
        sessionStorage.removeItem("darson_oidc_state"); sessionStorage.removeItem("darson_oidc_verifier"); sessionStorage.removeItem("darson_oidc_nonce");
        history.replaceState({}, "", window.location.pathname);
        await applyToken(result.access_token, Number(result.expires_in ?? 300));
      } catch (e) { setError(e instanceof Error ? e.message : String(e)); setReady(true); }
    })();
    return () => window.removeEventListener("darson-auth-expired", onExpired);
  }, [applyToken]);

  const login = useCallback(async () => {
    const metadata = await discovery();
    const verifier = randomString(64);
    const challenge = b64(new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(verifier))));
    const state = randomString(32), nonce = randomString(32);
    sessionStorage.setItem("darson_oidc_state", state); sessionStorage.setItem("darson_oidc_verifier", verifier); sessionStorage.setItem("darson_oidc_nonce", nonce);
    const url = new URL(metadata.authorization_endpoint);
    url.search = new URLSearchParams({ client_id: clientId, response_type: "code", scope: "openid profile",
      redirect_uri: window.location.origin, state, nonce, code_challenge: challenge, code_challenge_method: "S256" }).toString();
    window.location.assign(url);
  }, []);

  const logout = useCallback(async () => {
    const hint = idToken;
    if (accessToken) {
      try { await fetch("/api/v1/auth/logout", { method: "POST", headers: { Authorization: `Bearer ${accessToken}` }, cache: "no-store" }); }
      catch { /* the local credential is cleared even if the network is unavailable */ }
    }
    expireAuth(); setIdentity(null);
    if (enabled) {
      try { const metadata = await discovery(); if (metadata.end_session_endpoint) {
        const url = new URL(metadata.end_session_endpoint); url.searchParams.set("id_token_hint", hint ?? "");
        url.searchParams.set("post_logout_redirect_uri", window.location.origin); window.location.assign(url);
      } } catch { /* local session is still cleared */ }
    }
  }, []);

  const value = useMemo(() => ({ token, identity, enabled, login, logout }), [token, identity, login, logout]);
  if (enabled && (!ready || !token)) return <main className="auth-gate"><h1>DARSON sign in</h1>
    <p>Access is scoped to the tenant and site bound to your identity-provider token.</p>
    {error && <p role="alert">{error}</p>}<button disabled={!ready} onClick={() => void login()}>Sign in with organization</button></main>;
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const value = useContext(AuthContext);
  if (!value) throw new Error("AuthProvider is missing");
  return value;
}
