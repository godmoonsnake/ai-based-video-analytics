import { useCallback, useEffect, useState, type FormEvent } from "react";
import { api, ApiError, type GuardRosterEntry, type GuardShift, type SecurityPost } from "../../services/api";

const localDate = () => {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
};

export function GuardSchedule({ role, simulated, siteTimezone }: { role: string; simulated: boolean; siteTimezone: string }) {
  const canEdit = role === "supervisor" || role === "configuration_admin";
  const [posts, setPosts] = useState<SecurityPost[]>([]);
  const [guards, setGuards] = useState<GuardRosterEntry[]>([]);
  const [shifts, setShifts] = useState<GuardShift[]>([]);
  const [postName, setPostName] = useState("");
  const [block, setBlock] = useState("");
  const [floor, setFloor] = useState("");
  const [instructions, setInstructions] = useState("");
  const [demoGuard, setDemoGuard] = useState("");
  const [postId, setPostId] = useState("");
  const [subject, setSubject] = useState("");
  const [date, setDate] = useState(localDate);
  const [label, setLabel] = useState<"day" | "night" | "custom">("day");
  const [start, setStart] = useState("08:00");
  const [end, setEnd] = useState("20:00");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const reload = useCallback(async () => {
    try {
      const [newPosts, newGuards, newShifts] = await Promise.all([api.listSecurityPosts(), api.listGuards(), api.listGuardShifts()]);
      setPosts(newPosts); setGuards(newGuards); setShifts(newShifts);
      setPostId(old => old || newPosts[0]?.id || "");
      setSubject(old => old || newGuards[0]?.subject || "");
      setError("");
    } catch { setError("Could not load the guard roster and shifts."); }
  }, []);
  useEffect(() => { void reload(); }, [reload]);
  const report = (failure: unknown) => setError(failure instanceof ApiError ? failure.detail || failure.message : "Could not save the schedule.");
  const submitPost = async (event: FormEvent) => {
    event.preventDefault(); setBusy(true); setError(""); setMessage("");
    try {
      const result = await api.createSecurityPost({ name: postName.trim(), block: block.trim(), floor: floor.trim(), instructions: instructions.trim() });
      await reload(); setPostId(result.id); setPostName(""); setBlock(""); setFloor(""); setInstructions("");
      setMessage("Post created. Assign a guard below.");
    } catch (failure) { report(failure); } finally { setBusy(false); }
  };
  const submitDemoGuard = async (event: FormEvent) => {
    event.preventDefault(); setBusy(true); setError(""); setMessage("");
    const id = `demo-${demoGuard.trim().toLowerCase().replace(/[^a-z0-9-]+/g, "-").replace(/^-|-$/g, "")}`;
    try { await api.createDemoGuard(id); await reload(); setSubject(id); setDemoGuard(""); setMessage("Demo guard added. This is not a real login account."); }
    catch (failure) { report(failure); } finally { setBusy(false); }
  };
  const chooseLabel = (value: "day" | "night" | "custom") => {
    setLabel(value);
    if (value === "day") { setStart("08:00"); setEnd("20:00"); }
    if (value === "night") { setStart("20:00"); setEnd("08:00"); }
  };
  const submitShift = async (event: FormEvent) => {
    event.preventDefault(); setError(""); setMessage("");
    const begins = new Date(`${date}T${start}:00`);
    const finishes = new Date(`${date}T${end}:00`);
    if (!Number.isFinite(begins.getTime()) || !Number.isFinite(finishes.getTime())) { setError("Choose a valid date and time."); return; }
    if (finishes <= begins) finishes.setDate(finishes.getDate() + 1);
    setBusy(true);
    try {
      await api.createGuardShift({ post_id: postId, subject, label,
        starts_at: begins.getTime() / 1000, ends_at: finishes.getTime() / 1000 });
      await reload(); setMessage("Guard shift saved. Tasks will route to this guard when an active camera rule is linked to this post.");
    } catch (failure) { report(failure); } finally { setBusy(false); }
  };
  const cancel = async (id: string) => {
    if (!window.confirm("Cancel this guard shift? It will no longer route new tasks.")) return;
    setBusy(true); setError(""); setMessage("");
    try { await api.cancelGuardShift(id); await reload(); setMessage("Shift cancelled; its record is kept for audit."); }
    catch (failure) { report(failure); } finally { setBusy(false); }
  };
  const postById = new Map(posts.map(post => [post.id, post]));
  const format = (value: number) => new Date(value * 1000).toLocaleString([], { dateStyle: "medium", timeStyle: "short" });
  return <main className="guard-workspace" aria-label="Guard schedule">
    <div className="guard-workspace-heading"><div><small>DAILY COVERAGE</small><h1>Guard posts & shifts</h1></div><span>{guards.length} guards · {posts.length} posts</span></div>
    <p className="guard-workspace-note">Assign a guard to a floor and block for a day or night shift. The alert engine uses the active post shift; it does not guess who is physically nearest.</p>
    {error && <p role="alert" className="guard-action-error">{error}</p>}
    {message && <p role="status" className="guard-recorded">{message}</p>}
    {simulated && canEdit && <form className="guard-schedule-card" onSubmit={event => void submitDemoGuard(event)}><h2>Demo guard</h2><p>For today’s rehearsal only. Real guards need organization accounts and site grants.</p>
      <div className="guard-form-row"><label>Demo guard name<input value={demoGuard} onChange={event => setDemoGuard(event.target.value)} placeholder="guard-one" required minLength={3} /></label><button disabled={busy} type="submit">Add demo guard</button></div></form>}
    {canEdit && <form className="guard-schedule-card" onSubmit={event => void submitPost(event)}><h2>1. Add a security post</h2>
      <div className="guard-form-grid"><label>Block<input value={block} onChange={event => setBlock(event.target.value)} placeholder="A" required maxLength={80} /></label><label>Floor<input value={floor} onChange={event => setFloor(event.target.value)} placeholder="2" required maxLength={80} /></label><label>Post name<input value={postName} onChange={event => setPostName(event.target.value)} placeholder="North gate" required maxLength={120} /></label><label>Response instructions<input value={instructions} onChange={event => setInstructions(event.target.value)} placeholder="Check the entrance" required maxLength={2000} /></label></div>
      <button type="submit" disabled={busy}>Save post</button></form>}
    {canEdit && <form className="guard-schedule-card" onSubmit={event => void submitShift(event)}><h2>2. Assign a shift</h2>
      <div className="guard-form-grid"><label>Guard<select value={subject} onChange={event => setSubject(event.target.value)} required><option value="">Choose guard</option>{guards.map(guard => <option key={guard.subject} value={guard.subject}>{guard.subject}{guard.demo ? " · demo" : ""}</option>)}</select></label>
        <label>Floor / block / post<select value={postId} onChange={event => setPostId(event.target.value)} required><option value="">Choose post</option>{posts.map(post => <option key={post.id} value={post.id}>{post.block || "Block ?"} · Floor {post.floor || "?"} · {post.name}</option>)}</select></label>
        <label>Date<input type="date" value={date} onChange={event => setDate(event.target.value)} required /></label><label>Shift<select value={label} onChange={event => chooseLabel(event.target.value as "day" | "night" | "custom")}><option value="day">Day</option><option value="night">Night</option><option value="custom">Custom</option></select></label>
        <label>Start<input type="time" value={start} onChange={event => setStart(event.target.value)} required /></label><label>End<input type="time" value={end} onChange={event => setEnd(event.target.value)} required /></label></div>
      <p>End time before start time means the shift ends the next day. Times use this computer’s zone ({Intl.DateTimeFormat().resolvedOptions().timeZone}); site zone is {siteTimezone || "not loaded"}.</p>
      <button type="submit" disabled={busy || !postId || !subject}>Assign guard</button></form>}
    <section className="guard-schedule-card"><h2>Scheduled coverage</h2>{!shifts.length ? <p>No shifts assigned yet.</p> : <div className="guard-shift-list">{shifts.map(shift => {
      const post = postById.get(shift.post_id);
      return <div key={shift.id} className={shift.cancelled_at ? "cancelled" : ""}><div><strong>{shift.subject}</strong><span>{shift.label.toUpperCase()} · {post ? `${post.block || "Block ?"} / Floor ${post.floor || "?"} / ${post.name}` : shift.post_id}</span><small>{format(shift.starts_at)} → {format(shift.ends_at)}{shift.cancelled_at ? " · CANCELLED" : ""}</small></div>
        {canEdit && !shift.cancelled_at && <button type="button" disabled={busy} onClick={() => void cancel(shift.id)}>Cancel</button>}</div>;
    })}</div>}</section>
  </main>;
}
