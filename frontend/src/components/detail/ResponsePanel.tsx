import { useCallback, useEffect, useState } from "react";
import { api, ApiError } from "../../services/api";

type ResponseState = { version: number; response_state: string; owner: string | null;
  policy: { steps?: { id: string; instruction: string; required: boolean }[] } | null; steps_done: string[];
  acknowledged_at?: number | null; responded_at?: number | null; resolved_at?: number | null };

export function ResponsePanel({ incidentId, role, actor }: { incidentId: number; role: string; actor: string }) {
  const [state, setState] = useState<ResponseState | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [reason, setReason] = useState("");
  const [handoverTo, setHandoverTo] = useState("");
  const [sla, setSla] = useState<Awaited<ReturnType<typeof api.getSla>> | null>(null);
  const reload = useCallback(() => api.getResponse(incidentId).then(setState).catch((e) => setError(String(e))), [incidentId]);
  useEffect(() => { void reload(); }, [reload]);
  useEffect(() => {
    if (role === "responder") return;
    api.getSla(incidentId).then(setSla).catch(() => setSla(null));
  }, [incidentId, role]);
  async function act(action: string, extra: Record<string, unknown> = {}) {
    if (!state) return;
    setError(null);
    try { await api.responseAction(incidentId, action, state.version, extra); await reload(); }
    catch (e) {
      if (e instanceof ApiError && e.status === 409) { await reload(); setError("This case changed elsewhere. Current state refreshed; review it before retrying."); }
      else setError(e instanceof Error ? e.message : String(e));
    }
  }
  if (!state) return <section className="case-file"><h3>Response workflow</h3><p>{error ?? "Loading response state…"}</p></section>;
  const stages = ["assigned", "acknowledged", "responding", "resolved"];
  const current = stages.indexOf(state.response_state);
  return <section className="response-card" aria-label="Response workflow">
    <div className="response-heading"><div><span className="micro">OPERATOR RESPONSE</span><h3>From assignment to resolution</h3></div><span className="response-state">{state.response_state.replace(/_/g, " ")}</span></div>
    <div className="response-stages" aria-label="Response progress">{stages.map((stage, index) =>
      <span key={stage} className={index <= current ? "reached" : ""}><i>{index + 1}</i>{stage}</span>)}</div>
    <div className="response-owner"><span>Case owner</span><strong>{state.owner ?? "Unassigned"}</strong><span>Case version {state.version}</span></div>
    <div className="response-timestamps"><span>Acknowledged: {state.acknowledged_at ? new Date(state.acknowledged_at * 1000).toLocaleString() : "—"}</span><span>Response: {state.responded_at ? new Date(state.responded_at * 1000).toLocaleString() : "—"}</span><span>Resolved: {state.resolved_at ? new Date(state.resolved_at * 1000).toLocaleString() : "—"}</span></div>
    {sla && <div className="response-sla"><strong>SLA</strong>{sla.length ? sla.map((item, index) => <span key={`${item.stage}-${index}`}>{item.stage}: {item.status} · deadline {new Date(item.deadline_at * 1000).toLocaleString()}</span>) : <span>No SLA deadline recorded for this incident.</span>}</div>}
    <div className="response-actions">
    {state.response_state === "unassigned" && ["operator", "supervisor"].includes(role) && <button className="btn btn-accent" onClick={() => void act("assign")}>Assign to me</button>}
    {state.owner === actor && state.response_state === "assigned" && <button className="btn btn-accent" onClick={() => void act("acknowledge")}>Acknowledge assignment</button>}
    {state.owner === actor && state.response_state === "acknowledged" && <button className="btn btn-accent" onClick={() => void act("respond", { reason: "Responder reports arrival and begins site procedure" })}>Start response</button>}
    </div>
    {state.policy?.steps?.length ? <div className="response-steps"><span className="micro">SITE PROCEDURE</span>{state.policy.steps.map((step) => <label key={step.id}>
      <input type="checkbox" disabled={state.steps_done.includes(step.id) || state.owner !== actor || !["acknowledged", "responding"].includes(state.response_state)}
        checked={state.steps_done.includes(step.id)} onChange={() => void act("complete_step", { step_id: step.id })} /> {step.instruction}
    </label>)}</div> : null}
    {role !== "responder" && state.owner && state.response_state !== "resolved" && <div className="response-form">
      <input aria-label="Handover assignee" value={handoverTo} onChange={(e) => setHandoverTo(e.target.value)} placeholder="Responder subject" />
      <input aria-label="Handover reason" value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Handover reason" />
      <button className="btn" disabled={!handoverTo || reason.trim().length < 3} onClick={() => void act("handover", { assignee: handoverTo, reason })}>Handover</button>
    </div>}
    {role === "supervisor" && state.response_state === "responding" && <div className="response-form">
      <input aria-label="Resolution reason" value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Resolution reason" />
      <button className="btn btn-accent" disabled={reason.trim().length < 3} onClick={() => void act("resolve", { reason })}>Resolve response</button>
    </div>}
    {error && <p className="response-error" role="alert">{error}</p>}
  </section>;
}
