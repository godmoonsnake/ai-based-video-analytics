import type { BehaviourSignal } from "../../types/incident";

export function WhyCreated({ reasons }: { reasons: string[] }) {
  if (reasons.length === 0) {
    return <p className="muted">No explanation recorded.</p>;
  }
  return (
    <ul className="why-list">
      {reasons.map((r, i) => (
        <li key={i} data-testid="why-reason">
          {r}
        </li>
      ))}
    </ul>
  );
}

export function SupportingTracks({ tracks }: { tracks: string[] }) {
  if (tracks.length === 0) return <p className="muted">No supporting tracks.</p>;
  return (
    <ul className="chip-list">
      {tracks.map((t) => (
        <li key={t} className="chip chip-track" data-testid="supporting-track">
          track {t}
        </li>
      ))}
    </ul>
  );
}

export function SupportingEvents({ events }: { events: string[] }) {
  if (events.length === 0) return <p className="muted">No supporting events.</p>;
  return (
    <ul className="chip-list">
      {events.map((e) => (
        <li key={e} className="chip chip-event" data-testid="supporting-event">
          {e}
        </li>
      ))}
    </ul>
  );
}

export function BehaviourSignals({ signals }: { signals: BehaviourSignal[] }) {
  if (signals.length === 0) return <p className="muted">No behaviour signals.</p>;
  return (
    <table className="signals-table">
      <thead>
        <tr>
          <th>Event</th>
          <th>Type</th>
          <th>Risk contribution</th>
        </tr>
      </thead>
      <tbody>
        {signals.map((s, i) => (
          <tr key={i} data-testid="behaviour-signal">
            <td>{s.event_id ?? "—"}</td>
            <td>{s.event_type ?? "—"}</td>
            <td>{s.risk_contribution != null ? s.risk_contribution.toFixed(2) : "—"}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
